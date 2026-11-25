"""
Carga do catálogo (docs/CATALOG_IMPORT_PLAN.md §4.3): lê o seed gerado por `build_catalog_seed` e cria/completa
grupos, solistas, subunidades, integrantes e eras.

- Idempotente: casa por wikidata_id → musicbrainz_id → nome normalizado (nome, Hangul e apelidos). Rodar 2x não duplica.
- Nunca sobrescreve edição manual: só preenche campos vazios. A posição no ranking é sempre atualizada.
- Imagens são copiadas para o nosso storage (com miniatura), via `fetch_public_url` (anti-SSRF). Sem hotlink.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction

from .models import Era, GroupMember, KpopGroup, Source, normalize_name

logger = logging.getLogger(__name__)

GROUP_FIELDS = ('name_native', 'aliases', 'debut_date', 'agency', 'image_credit', 'wikidata_id', 'musicbrainz_id')
ERA_FIELDS = ('release_date', 'musicbrainz_id')


@dataclass
class Report:
    grupos_criados: int = 0
    grupos_completados: int = 0
    integrantes_criados: int = 0
    eras_criadas: int = 0
    imagens_copiadas: int = 0
    imagens_falharam: int = 0
    avisos: list = field(default_factory=list)

    def resumo(self):
        return (f'{self.grupos_criados} grupos criados, {self.grupos_completados} completados, '
                f'{self.integrantes_criados} integrantes e {self.eras_criadas} eras criados, '
                f'{self.imagens_copiadas} imagens copiadas ({self.imagens_falharam} falharam)')


def _date(value):
    if not value:
        return None
    try:
        parts = [int(p) for p in str(value).split('-')]
        return date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
    except (ValueError, IndexError):
        return None


class Loader:
    def __init__(self, copy_images=True, report=None):
        self.copy_images = copy_images
        self.report = report or Report()
        self._copiadas = {}
        self._cores = {}
        self._proximo_wm = 0.0
        self.cor = ''

    # --- imagens -------------------------------------------------------------------------------
    def imagem(self, url, folder):
        """Copia a imagem para o storage; devolve a URL nossa ('' se não deu). A cor dela fica em `self.cor`."""
        self.cor = self._cores.get(url, '')
        if not url or not self.copy_images:
            return ''
        if url in self._copiadas:
            return self._copiadas[url]
        from apps.cegs.image_utils import _optimize_image_bytes, _saved_with_thumbnail
        from apps.core.net import fetch_public_url
        try:
            raw = self._baixar(url, fetch_public_url)
            data, ext = _optimize_image_bytes(raw, max_dimension=1000)
            name = f'catalogo/{folder}/{uuid.uuid4().hex[:12]}{ext}'
            saved = default_storage.save(name, ContentFile(data))
            nossa = _saved_with_thumbnail(saved, data)
            self.report.imagens_copiadas += 1
            from .color_utils import extract_dominant_color
            self.cor = self._cores[url] = extract_dominant_color(data, default_color='')
        except Exception as exc:  # imagem é opcional: segue sem ela
            logger.warning('Catálogo: imagem não copiada (%s): %s', url, exc)
            self.report.imagens_falharam += 1
            nossa = ''
        self._copiadas[url] = nossa
        return nossa

    def _baixar(self, url, fetch):
        """Wikimedia limita robôs: 1 download por segundo e, se vier 429, espera e tenta de novo (até 4 vezes)."""
        import time
        import urllib.error
        from urllib.parse import urlparse

        wikimedia = urlparse(url).hostname or ''
        wikimedia = wikimedia.endswith('wikimedia.org') or wikimedia.endswith('wikipedia.org')
        for tentativa in range(5):
            if wikimedia:
                time.sleep(max(0.0, self._proximo_wm - time.monotonic()))
                self._proximo_wm = time.monotonic() + 1.0
            try:
                return fetch(url, timeout=20, max_bytes=8 * 1024 * 1024)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 503) or tentativa == 4:
                    raise
                espera = exc.headers.get('Retry-After', '') if exc.headers else ''
                time.sleep(min(120, int(espera)) if espera.isdigit() else 15 * (tentativa + 1))

    # --- grupos ------------------------------------------------------------------------------
    def encontrar(self, a):
        if a.get('wikidata_id'):
            g = KpopGroup.objects.filter(wikidata_id=a['wikidata_id']).first()
            if g:
                return g
        if a.get('musicbrainz_id'):
            g = KpopGroup.objects.filter(musicbrainz_id=a['musicbrainz_id']).first()
            if g:
                return g
        for nome in [a['name'], a.get('name_native'), *(a.get('aliases') or [])]:
            g = KpopGroup.objects.matching(nome).filter(wikidata_id__isnull=True).first() if nome else None
            if g:
                return g
        return None

    @staticmethod
    def _nome_livre(a):
        """Dois artistas com o mesmo nome (ex.: solistas homônimos): o segundo ganha a agência ou a estreia."""
        nome = a['name'][:150]
        if not KpopGroup.objects.filter(name__iexact=nome).exists():
            return nome
        extra = a.get('agency') or (a.get('debut_date') or '')[:4] or a.get('wikidata_id') or 'novo'
        return f'{nome} ({extra})'[:150]

    def grupo(self, a):
        valores = {
            'name_native': a.get('name_native') or '',
            'aliases': ', '.join(a.get('aliases') or [])[:300],
            'debut_date': _date(a.get('debut_date')),
            'agency': (a.get('agency') or '')[:150],
            'image_credit': (a.get('image_credit') or '')[:300],
            'wikidata_id': a.get('wikidata_id') or None,
            'musicbrainz_id': a.get('musicbrainz_id') or None,
        }
        g = self.encontrar(a)
        if g is None:
            g = KpopGroup(name=self._nome_livre(a), source=Source.IMPORTADO, kind=a.get('kind') or KpopGroup.Kind.GRUPO,
                          status=a.get('status') or KpopGroup.Status.ATIVO, color_hex=a.get('color_hex') or '',
                          popularity_rank=a.get('rank'), **valores)
            g.image_url = self.imagem(a.get('image_url'), 'grupos')
            g.color_hex = g.color_hex or self.cor
            g.save()
            self.report.grupos_criados += 1
            return g
        mudou = [k for k, v in valores.items() if v and not getattr(g, k)]
        for k in mudou:
            setattr(g, k, valores[k])
        if a.get('rank') and g.popularity_rank != a['rank']:
            g.popularity_rank = a['rank']
            mudou.append('popularity_rank')
        if a.get('kind') and a['kind'] != KpopGroup.Kind.GRUPO and g.kind == KpopGroup.Kind.GRUPO:
            g.kind = a['kind']  # GRUPO é só o padrão do cadastro manual
            mudou.append('kind')
        if not g.image_url and a.get('image_url'):
            g.image_url = self.imagem(a['image_url'], 'grupos')
            if g.image_url:
                mudou.append('image_url')
        if mudou:
            g.save()
            self.report.grupos_completados += 1
        return g

    def integrantes(self, g, membros):
        atuais = list(g.members.all())
        ordem = max((m.order for m in atuais), default=-1) + 1
        for m in membros:
            achado = next((x for x in atuais if m.get('wikidata_id') and x.wikidata_id == m['wikidata_id']), None) \
                or next((x for x in atuais if normalize_name(x.name) == normalize_name(m['name'])), None)
            if achado is None:
                achado = GroupMember.objects.create(group=g, name=m['name'][:100], order=ordem,
                                                    name_native=m.get('name_native') or '',
                                                    is_former=bool(m.get('is_former')), wikidata_id=m.get('wikidata_id') or '')
                atuais.append(achado)
                ordem += 1
                self.report.integrantes_criados += 1
                continue
            mudou = []
            for k in ('name_native', 'wikidata_id'):
                if m.get(k) and not getattr(achado, k):
                    setattr(achado, k, m[k])
                    mudou.append(k)
            if mudou:
                achado.save(update_fields=mudou)

    def eras(self, g, eras):
        atuais = list(g.eras.all())
        for e in eras:
            achada = next((x for x in atuais if e.get('musicbrainz_id') and x.musicbrainz_id == e['musicbrainz_id']), None) \
                or next((x for x in atuais if normalize_name(x.name) == normalize_name(e['name'])), None)
            if achada is None:
                if e.get('musicbrainz_id') and Era.objects.filter(musicbrainz_id=e['musicbrainz_id']).exists():
                    self.report.avisos.append(f"Era {e['name']} ({g.name}) já existe em outro grupo; ignorada.")
                    continue
                achada = Era(group=g, name=e['name'][:150], kind=e.get('kind') or Era.Kind.OUTRO,
                             release_date=_date(e.get('release_date')), musicbrainz_id=e.get('musicbrainz_id') or None,
                             color_hex=g.color_hex or '', source=Source.IMPORTADO)
                achada.banner_url = self.imagem(e.get('cover_url'), 'eras')
                achada.color_hex = e.get('color_hex') or self.cor or achada.color_hex
                achada.save()
                atuais.append(achada)
                self.report.eras_criadas += 1
                continue
            mudou = []
            if e.get('release_date') and not achada.release_date:
                achada.release_date = _date(e['release_date'])
                mudou.append('release_date')
            if e.get('musicbrainz_id') and not achada.musicbrainz_id \
                    and not Era.objects.filter(musicbrainz_id=e['musicbrainz_id']).exists():
                achada.musicbrainz_id = e['musicbrainz_id']
                mudou.append('musicbrainz_id')
            if e.get('cover_url') and not achada.banner_url:  # capa que falhou numa carga anterior
                achada.banner_url = self.imagem(e['cover_url'], 'eras')
                if achada.banner_url:
                    mudou.append('banner_url')
            if e.get('kind') and achada.kind == Era.Kind.OUTRO:
                achada.kind = e['kind']
                mudou.append('kind')
            if mudou:
                achada.save(update_fields=mudou)

    # --- tudo --------------------------------------------------------------------------------
    def carregar(self, artistas):
        por_wd = {}
        for a in artistas:
            try:
                with transaction.atomic():
                    g = self.grupo(a)
                    self.integrantes(g, a.get('members') or [])
                    self.eras(g, a.get('eras') or [])
                if a.get('wikidata_id'):
                    por_wd[a['wikidata_id']] = g
            except Exception as exc:
                logger.exception('Catálogo: falha em %s', a.get('name'))
                self.report.avisos.append(f"{a.get('name')}: {exc}")
        # Ligações: subunidade → grupo principal; integrante → carreira solo.
        for a in artistas:
            g = por_wd.get(a.get('wikidata_id'))
            pai = por_wd.get(a.get('parent_wikidata_id'))
            if g and pai and not g.parent_id and pai.pk != g.pk:
                g.parent = pai
                g.save(update_fields=['parent'])
            for m in a.get('members') or []:
                solo = por_wd.get(m.get('solo_wikidata_id'))
                if g and solo and m.get('wikidata_id'):
                    g.members.filter(wikidata_id=m['wikidata_id'], solo__isnull=True).update(solo=solo)
        return self.report


def load_seed(seed, copy_images=True, dry_run=False):
    """Carrega o seed (dict com `artists`). Em `dry_run`, faz tudo e desfaz no fim (sem copiar imagens)."""
    loader = Loader(copy_images=copy_images and not dry_run)
    if not dry_run:
        return loader.carregar(seed.get('artists') or [])
    with transaction.atomic():
        report = loader.carregar(seed.get('artists') or [])
        transaction.set_rollback(True)
    return report
