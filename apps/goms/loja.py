"""
Loja da página pública do GOM (/gom/<slug>/): busca, filtros, ordenação e paginação no servidor.

Tudo é filtrado no banco e paginado (POR_PAGINA), então a página não cresce com o número de CEGs. Os filtros só
oferecem o que está à venda agora (grupos, integrantes e tipos com vaga livre), nunca o catálogo inteiro.
Vistas: "cegs" (cards de CEG) e "itens" (cada item com vaga livre vira um produto). Aba "pronta": Vitrine do GOM.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.db.models import Count, Exists, F, Min, OuterRef, Q
from django.utils import timezone

from apps.cegs.models import CEG, ItemSlot, ItemVitrine
from apps.groups.models import KpopGroup

POR_PAGINA = 24
TOPO_GRUPOS = 8
ORDENS = {
    'recentes': 'Mais recentes',
    'preco': 'Menor preço',
    'vagas': 'Mais vagas',
    'fechando': 'Fechando logo',
}


@dataclass
class Filtros:
    aba: str = 'cegs'          # cegs | pronta
    vista: str = 'cegs'        # cegs | itens
    q: str = ''
    grupo: int | None = None
    integrante: str = ''
    tipo: int | None = None
    preco_max: Decimal | None = None
    ordem: str = 'recentes'
    pagina: int = 1

    @property
    def ativos(self):
        return bool(self.q or self.grupo or self.integrante or self.tipo or self.preco_max)

    def url(self, **mudar):
        """Query string com os filtros atuais e as mudanças pedidas (None ou '' tira o filtro)."""
        dados = {'aba': self.aba, 'vista': self.vista, 'q': self.q, 'grupo': self.grupo, 'integrante': self.integrante,
                 'tipo': self.tipo, 'preco_max': self.preco_max, 'ordem': self.ordem}
        if 'grupo' in mudar and 'integrante' not in mudar:  # integrante depende do grupo
            dados['integrante'] = ''
        dados.update(mudar)
        padrao = {'aba': 'cegs', 'vista': 'cegs', 'ordem': 'recentes'}
        limpos = {k: v for k, v in dados.items() if v not in (None, '') and padrao.get(k) != v}
        return '?' + urlencode(limpos) if limpos else '?'


def _int(valor):
    try:
        return int(valor) if valor not in (None, '') else None
    except (TypeError, ValueError):
        return None


def ler_filtros(get):
    preco = None
    try:
        preco = Decimal(str(get.get('preco_max') or '').replace(',', '.')) if get.get('preco_max') else None
        preco = preco if preco and preco > 0 else None
    except (InvalidOperation, ValueError):
        preco = None
    return Filtros(
        aba='pronta' if get.get('aba') == 'pronta' else 'cegs',
        vista='itens' if get.get('vista') == 'itens' else 'cegs',
        q=(get.get('q') or '').strip()[:80],
        grupo=_int(get.get('grupo')),
        integrante=(get.get('integrante') or '').strip()[:100],
        tipo=_int(get.get('tipo')),
        preco_max=preco,
        ordem=get.get('ordem') if get.get('ordem') in ORDENS else 'recentes',
        pagina=max(1, _int(get.get('pagina')) or 1),
    )


def cegs_abertas(gom):
    now = timezone.now()
    return CEG.objects.for_gom(gom).filter(Q(status=CEG.Status.OPEN) | Q(status=CEG.Status.SCHEDULED, opens_at__lte=now))


def _vagas(gom, f, com_integrante=True):
    """Vagas livres (sets ativos) das CEGs abertas do GOM, já com busca, grupo, tipo, preço e integrante."""
    qs = ItemSlot.objects.filter(set__ceg__in=cegs_abertas(gom), set__is_active=True, status=ItemSlot.Status.AVAILABLE)
    if f.grupo:
        qs = qs.filter(set__ceg__era__group_id=f.grupo)
    if f.tipo:
        qs = qs.filter(item_definition__tipo_item_id=f.tipo)
    if f.preco_max:
        qs = qs.filter(price__lte=f.preco_max)
    if f.integrante and com_integrante:
        qs = qs.filter(Q(item_definition__member_name__iexact=f.integrante) | Q(item_definition__name__iexact=f.integrante))
    if f.q:
        qs = qs.filter(Q(set__ceg__title__icontains=f.q) | Q(set__ceg__era__name__icontains=f.q)
                       | Q(set__ceg__era__group__name__icontains=f.q) | Q(item_definition__name__icontains=f.q)
                       | Q(item_definition__member_name__icontains=f.q))
    return qs


def _pagina(qs_ou_lista, f, total):
    inicio = (f.pagina - 1) * POR_PAGINA
    return list(qs_ou_lista[inicio:inicio + POR_PAGINA]), inicio + POR_PAGINA < total


def _seguindo_cegs(qs, prefs):
    """Anota `_seg`: 2 = CEG com item de integrante seguido, 1 = de grupo seguido (apps/participants/seguindo.py)."""
    from django.db.models import Case, IntegerField, Value, When

    from apps.cegs.models import CEGItemDefinition
    from apps.participants.seguindo import anotar_seguindo

    casos = []
    if prefs and prefs.membros:
        itens = anotar_seguindo(CEGItemDefinition.objects.filter(ceg_id=OuterRef('pk')), prefs,
                                'ceg__era__group_id', 'member_name').filter(_seg=2)
        casos.append(When(Exists(itens), then=Value(2)))
    if prefs:
        casos.append(When(era__group_id__in=prefs.todos_grupos, then=Value(1)))
    return qs.annotate(_seg=Case(*casos, default=Value(0), output_field=IntegerField()) if casos
                       else Value(0, output_field=IntegerField()))


def listar_cegs(gom, f, prefs=None):
    """CEGs abertas com ao menos uma vaga que bate com os filtros (sem filtros: todas, inclusive as esgotadas).
    Ordem "recentes" (padrão) põe primeiro quem o joiner segue (`prefs`)."""
    qs = cegs_abertas(gom).select_related('era__group', 'gom')
    if f.ativos:
        qs = qs.filter(Exists(_vagas(gom, f).filter(set__ceg_id=OuterRef('pk'))))
    livres = ItemSlot.objects.filter(set__ceg_id=OuterRef('pk'), set__is_active=True, status=ItemSlot.Status.AVAILABLE)
    if f.ordem == 'preco':
        qs = qs.annotate(_min=Min('sets__slots__price', filter=Q(sets__is_active=True,
                                                                  sets__slots__status=ItemSlot.Status.AVAILABLE)))
        qs = qs.order_by(F('_min').asc(nulls_last=True), '-created_at')
    elif f.ordem == 'vagas':
        qs = qs.annotate(_livres=Count('sets__slots', filter=Q(sets__is_active=True,
                                                              sets__slots__status=ItemSlot.Status.AVAILABLE)))
        qs = qs.order_by('-_livres', '-created_at')
    elif f.ordem == 'fechando':
        qs = qs.order_by(F('closes_at').asc(nulls_last=True), '-created_at')
    else:  # recentes; esgotadas vão para o fim; quem o joiner segue primeiro
        qs = _seguindo_cegs(qs, prefs).annotate(_tem=Exists(livres)).order_by('-_tem', '-_seg', '-created_at')
    total = qs.count()
    itens, mais = _pagina(qs, f, total)
    return itens, total, mais


def listar_itens(gom, f, prefs=None):
    """Cada item (definição) com vaga livre vira um produto: menor preço, quantas vagas e em quais sets."""
    qs = (_vagas(gom, f)
          .values('item_definition_id', 'item_definition__name', 'item_definition__member_name',
                  'item_definition__image_url', 'set__ceg_id', 'set__ceg__title', 'set__ceg__slug',
                  'set__ceg__banner_url', 'set__ceg__era__name', 'set__ceg__era__banner_url',
                  'set__ceg__era__group__name', 'set__ceg__created_at', 'set__ceg__closes_at')
          .annotate(preco=Min('price'), vagas=Count('id')))
    ordem = {'preco': ['preco', '-set__ceg__created_at'], 'vagas': ['-vagas', 'preco'],
             'fechando': [F('set__ceg__closes_at').asc(nulls_last=True), 'preco']}
    if f.ordem not in ordem:  # padrão: integrante/grupo seguido primeiro
        from apps.participants.seguindo import anotar_seguindo
        qs = anotar_seguindo(qs, prefs, 'set__ceg__era__group_id', 'item_definition__member_name')
    qs = qs.order_by(*ordem.get(f.ordem, ['-_seg', '-set__ceg__created_at', 'item_definition__order_index',
                                          'item_definition__name']))
    total = qs.count()
    itens, mais = _pagina(qs, f, total)
    for it in itens:
        it['foto'] = (it['item_definition__image_url'] or it['set__ceg__banner_url'] or it['set__ceg__era__banner_url'] or '')
        it['titulo'] = it['item_definition__member_name'] or it['item_definition__name']
    return itens, total, mais


def listar_pronta(gom, f, prefs=None):
    qs = ItemVitrine.objects.for_gom(gom).filter(status=ItemVitrine.Status.DISPONIVEL).select_related('group', 'era')
    if f.grupo:
        qs = qs.filter(group_id=f.grupo)
    if f.integrante:
        qs = qs.filter(integrante__iexact=f.integrante)
    if f.tipo:
        qs = qs.filter(tipo_item_id=f.tipo)
    if f.preco_max:
        qs = qs.filter(preco__lte=f.preco_max)
    if f.q:
        qs = qs.filter(Q(titulo__icontains=f.q) | Q(integrante__icontains=f.q) | Q(group__name__icontains=f.q)
                       | Q(era__name__icontains=f.q))
    if f.ordem not in ('preco', 'fechando'):
        from apps.participants.seguindo import anotar_seguindo
        qs = anotar_seguindo(qs, prefs, 'group_id', 'integrante')
    qs = qs.order_by(*{'preco': ['preco'], 'fechando': ['-destaque', '-created_at']}.get(
        f.ordem, ['-destaque', '-_seg', '-created_at']))
    total = qs.count()
    itens, mais = _pagina(qs, f, total)
    return itens, total, mais


def facetas(gom, f):
    """Opções dos filtros, só com o que está à venda agora (com contagem). Grupos: os mais vendidos viram chips."""
    if f.aba == 'pronta':
        base = ItemVitrine.objects.for_gom(gom).filter(status=ItemVitrine.Status.DISPONIVEL)
        grupos = list(base.exclude(group=None).values('group_id', 'group__name').annotate(n=Count('id')).order_by('-n'))
        grupos = [{'id': g['group_id'], 'name': g['group__name'], 'n': g['n']} for g in grupos]
        integ = base.filter(group_id=f.grupo).exclude(integrante='').values('integrante').annotate(n=Count('id')) \
            if f.grupo else []
        integrantes = sorted(({'nome': i['integrante'], 'n': i['n']} for i in integ), key=lambda i: i['nome'].lower())
        tipos = list(base.exclude(tipo_item=None).values('tipo_item_id', 'tipo_item__nome').annotate(n=Count('id')))
    else:
        livres = ItemSlot.objects.filter(set__ceg__in=cegs_abertas(gom), set__is_active=True,
                                         status=ItemSlot.Status.AVAILABLE)
        grupos = list(livres.values('set__ceg__era__group_id', 'set__ceg__era__group__name')
                      .annotate(n=Count('set__ceg', distinct=True)).order_by('-n', 'set__ceg__era__group__name'))
        grupos = [{'id': g['set__ceg__era__group_id'], 'name': g['set__ceg__era__group__name'], 'n': g['n']} for g in grupos]
        integrantes = []
        if f.grupo:
            nomes = {}
            for member in _vagas(gom, f, com_integrante=False).values_list('item_definition__member_name', flat=True):
                nome = (member or '').strip()
                if nome:
                    nomes[nome] = nomes.get(nome, 0) + 1
            integrantes = sorted(({'nome': k, 'n': v} for k, v in nomes.items()), key=lambda i: i['nome'].lower())
        tipos = list(livres.exclude(item_definition__tipo_item=None)
                     .values('item_definition__tipo_item_id', 'item_definition__tipo_item__nome')
                     .annotate(n=Count('id')))
        tipos = [{'tipo_item_id': t['item_definition__tipo_item_id'], 'tipo_item__nome': t['item_definition__tipo_item__nome'],
                  'n': t['n']} for t in tipos]
    tipos = sorted(({'id': t['tipo_item_id'], 'nome': t['tipo_item__nome'], 'n': t['n']} for t in tipos),
                   key=lambda t: t['nome'].lower())
    topo = grupos[:TOPO_GRUPOS]
    if f.grupo and all(g['id'] != f.grupo for g in topo):
        escolhido = next((g for g in grupos if g['id'] == f.grupo), None) \
            or KpopGroup.objects.filter(pk=f.grupo).values('id', 'name').first()
        if escolhido:
            topo = [dict(escolhido, n=escolhido.get('n', 0))] + topo[:TOPO_GRUPOS - 1]
    return {'grupos_topo': topo, 'grupos_todos': sorted(grupos, key=lambda g: g['name'].lower()),
            'integrantes': integrantes, 'tipos': tipos}


def contexto_loja(gom, get, prefs=None):
    """`prefs`: o que o joiner logado segue (apps/participants/seguindo.preferencias); personaliza a ordem padrão."""
    f = ler_filtros(get)
    if not gom.pagina_mostrar_vitrine:  # GOM escondeu a pronta entrega da página
        f.aba = 'cegs'
    if f.aba == 'pronta':
        if f.vista != 'cegs':
            f.vista = 'cegs'
        resultados, total, mais = listar_pronta(gom, f, prefs)
    elif f.vista == 'itens':
        resultados, total, mais = listar_itens(gom, f, prefs)
    else:
        resultados, total, mais = listar_cegs(gom, f, prefs)
        from apps.cegs.services import enrich_cegs_with_availability
        enrich_cegs_with_availability(resultados)
    return {
        'f': f, 'resultados': resultados, 'total': total, 'tem_mais': mais,
        'proxima_url': f.url(pagina=f.pagina + 1) if mais else '',
        'ordens': ORDENS, **facetas(gom, f),
        'total_pronta': ItemVitrine.objects.for_gom(gom).filter(status=ItemVitrine.Status.DISPONIVEL).count()
        if gom.pagina_mostrar_vitrine else 0,
        'total_abertas': cegs_abertas(gom).count(),
    }
