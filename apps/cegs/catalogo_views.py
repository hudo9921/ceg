"""
Catálogo compartilhado no Hub de Criações (docs/CATALOG_IMPORT_PLAN.md §9).

`catalogo_buscar`, `catalogo_grupo_novo` e `catalogo_era_nova`: o seletor "busca primeiro" da Nova CEG. Qualquer GOM
adiciona grupos e eras que faltam (sem duplicar); editar e excluir continua só com a plataforma.

`era_fotos`: fotos já usadas em CEGs publicadas da mesma era, de qualquer GOM (capas e fotos dos itens),
para a Nova CEG reaproveitar em vez de subir de novo. Rascunhos ficam de fora: só entra o que já é público.
As imagens nunca são apagadas do storage quando uma CEG é excluída, então o link reaproveitado continua válido.
"""
import logging

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.core.permissions import staff_required
from apps.core.thumbnails import thumbnail_url
from apps.groups.models import Era

from .models import CEG, CEGItemDefinition

logger = logging.getLogger(__name__)

LIMITE_CAPAS = 24
LIMITE_ITENS = 300
LIMITE_BUSCA = 12


def grupo_json(g):
    """Formato usado pelo creationsHubApp (`groups`): com integrantes e eras para a Nova CEG."""
    return {
        'id': g.id, 'name': g.name, 'slug': g.slug, 'image_url': g.image_url,
        'thumb': thumbnail_url(g.image_url) if g.image_url else '',
        'color_hex': g.color_hex or '', 'description': g.description or '',
        'kind': g.kind, 'kind_display': g.get_kind_display(), 'name_native': g.name_native,
        'parent_name': g.parent.name if g.parent_id else '',
        'members_count': len(g.members.all()),
        'members': [{'id': m.id, 'name': m.name, 'order': m.order}
                    for m in g.members.all() if not m.is_former],
        'eras': [{
            'id': e.id, 'name': e.name, 'slug': e.slug, 'kind': e.kind, 'kind_display': e.get_kind_display(),
            'release_date': e.release_date.strftime('%Y-%m-%d') if e.release_date else '',
            'banner_url': e.banner_url, 'color_hex': e.color_hex or '', 'description': e.description or '',
            'group_id': g.id, 'group_name': g.name, 'aliases': e.aliases,
        } for e in g.eras.all()],
    }


def buscar_grupos(q, limite=LIMITE_BUSCA):
    """Por nome, Hangul ou apelido (sem acento/maiúscula/espaço): igual > começa com > contém; depois popularidade."""
    from django.db.models import Case, IntegerField, Q, Value, When
    from django.db.models.functions import Coalesce

    from apps.groups.models import KpopGroup, normalize_name

    key = normalize_name(q)
    if not key:
        return []
    qs = (KpopGroup.objects.filter(search_key__contains=key)
          .annotate(peso=Case(
              When(Q(search_key=key) | Q(search_key__startswith=key + ' ') | Q(search_key__contains=' ' + key + ' ')
                   | Q(search_key__endswith=' ' + key), then=Value(0)),
              When(Q(search_key__startswith=key) | Q(search_key__contains=' ' + key), then=Value(1)),
              default=Value(2), output_field=IntegerField()),
              pos=Coalesce('popularity_rank', Value(10 ** 6)))
          .order_by('peso', 'pos', 'name')
          .select_related('parent').prefetch_related('members', 'eras'))
    return [grupo_json(g) for g in qs[:limite]]


@staff_required('ceg.editar')
def catalogo_buscar(request):
    return JsonResponse({'grupos': buscar_grupos(request.GET.get('q', ''))})


@staff_required('ceg.editar')
def era_fotos(request, era_id):
    era = get_object_or_404(Era, pk=era_id)
    cegs = (CEG.objects.filter(era=era).exclude(status=CEG.Status.DRAFT)
            .select_related('gom').order_by('-created_at'))

    capas, vistos = [], set()
    if era.banner_url:
        capas.append({'url': era.banner_url, 'thumb': thumbnail_url(era.banner_url), 'origem': 'Capa da era', 'gom': ''})
        vistos.add(era.banner_url)
    for ceg in cegs:
        url = (ceg.banner_url or '').strip()
        if url and url not in vistos and not url.startswith('data:'):
            vistos.add(url)
            capas.append({'url': url, 'thumb': thumbnail_url(url), 'origem': ceg.title, 'gom': ceg.gom.name if ceg.gom_id else ''})
        if len(capas) >= LIMITE_CAPAS:
            break

    itens, vistos = [], set()
    defs = (CEGItemDefinition.objects.filter(ceg__in=cegs).exclude(image_url='')
            .select_related('ceg__gom').order_by('-ceg__created_at', 'id'))
    for d in defs:
        if d.image_url in vistos or d.image_url.startswith('data:'):
            continue
        vistos.add(d.image_url)
        itens.append({
            'url': d.image_url,
            'thumb': thumbnail_url(d.image_url),
            'integrante': d.member_name or '',
            'nome': d.name,
            'sub': d.sub_category or '',
            'origem': d.ceg.title,
            'gom': d.ceg.gom.name if d.ceg.gom_id else '',
        })
        if len(itens) >= LIMITE_ITENS:
            break

    return JsonResponse({'capas': capas, 'itens': itens})


def _grupo_completo(pk):
    from apps.groups.models import KpopGroup
    return grupo_json(KpopGroup.objects.select_related('parent').prefetch_related('members', 'eras').get(pk=pk))


@require_POST
@staff_required('ceg.editar')
def catalogo_grupo_novo(request):
    """Adiciona ao catálogo um grupo/solista que não existe. Se já existe (mesmo nome, Hangul ou apelido), devolve o existente."""
    from apps.groups.models import GroupMember, KpopGroup

    nome = (request.POST.get('name') or '').strip()[:150]
    kind = request.POST.get('kind') or KpopGroup.Kind.GRUPO
    if not nome:
        return JsonResponse({'success': False, 'message': 'Digite o nome do grupo ou solista.'}, status=400)
    if kind not in KpopGroup.Kind.values:
        kind = KpopGroup.Kind.GRUPO
    existente = KpopGroup.objects.matching(nome).first()
    if existente:
        return JsonResponse({'success': True, 'existente': True, 'grupo': _grupo_completo(existente.pk)})
    membros = [m.strip()[:100] for m in (request.POST.get('members') or '').split(',') if m.strip()]
    with transaction.atomic():
        g = KpopGroup.objects.create(name=nome, kind=kind)
        for i, m in enumerate(dict.fromkeys(membros)):
            GroupMember.objects.create(group=g, name=m, order=i)
    logger.info('Catálogo: %s adicionou o grupo %s (GOM %s)', request.user.username, g.name, getattr(request.active_gom, 'slug', '-'))
    return JsonResponse({'success': True, 'existente': False, 'grupo': _grupo_completo(g.pk)})


@require_POST
@staff_required('ceg.editar')
def catalogo_era_nova(request):
    """Adiciona uma era a um grupo do catálogo (sem duplicar pelo nome)."""
    from apps.groups.eras import era_por_nome
    from apps.groups.models import Era, KpopGroup

    grupo = get_object_or_404(KpopGroup, pk=request.POST.get('group_id') or 0)
    nome = (request.POST.get('name') or '').strip()[:150]
    if not nome:
        return JsonResponse({'success': False, 'message': 'Digite o nome da era.'}, status=400)
    kind = request.POST.get('kind') if request.POST.get('kind') in Era.Kind.values else Era.Kind.OUTRO
    existente = era_por_nome(grupo, nome)  # pelo nome ou por um apelido: "SWIM" usa a era "ARIRANG"
    if existente is None:
        lancamento = parse_date(request.POST.get('release_date') or '') if request.POST.get('release_date') else None
        existente = Era.objects.create(group=grupo, name=nome, kind=kind, release_date=lancamento,
                                       color_hex=grupo.color_hex or '')
    return JsonResponse({'success': True, 'era_id': existente.id, 'grupo': _grupo_completo(grupo.pk)})
