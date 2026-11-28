"""
Procurar integrante (página pública /procurar/): "onde tem Wonyoung?" em todos os GOMs — vagas livres nas CEGs
abertas ou agendadas, itens da Vitrine e repasses públicos com item dela. `?q=` acha integrantes pelo nome
(ou em hangul); `?m=<id>` mostra os resultados daquele integrante.
"""
from collections import OrderedDict
from urllib.parse import urlencode

from django.db.models import Count, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.groups.models import GroupMember, KpopGroup

from .models import CEG, CEGItemDefinition, ItemSlot, ItemVitrine

LIMITE_CANDIDATOS = 12


def _nomes(m):
    return [n for n in (m.name, m.name_native) if n]


def _filtro_nome(campo, nomes):
    q = Q()
    for n in nomes:
        q |= Q(**{f'{campo}__iexact': n})
    return q


def resultados(membro):
    """CEGs com vagas livres do integrante, itens da Vitrine e repasses públicos (todos os GOMs ativos)."""
    from apps.repasses.models import Repasse

    nomes = _nomes(membro)
    grupos = [membro.group_id, *KpopGroup.objects.filter(parent_id=membro.group_id).values_list('id', flat=True)]
    now = timezone.now()
    cegs_visiveis = (Q(ceg__status=CEG.Status.OPEN) | Q(ceg__status=CEG.Status.SCHEDULED)) & Q(ceg__gom__is_active=True)

    defs = (CEGItemDefinition.objects.filter(cegs_visiveis, _filtro_nome('member_name', nomes), ceg__era__group_id__in=grupos)
            .select_related('ceg__era__group', 'ceg__gom')
            .annotate(livres=Count('slots', filter=Q(slots__status=ItemSlot.Status.AVAILABLE, slots__set__is_active=True)))
            .order_by('ceg__opens_at', '-ceg__created_at'))
    cegs = OrderedDict()
    for d in defs:
        agendada = d.ceg.status == CEG.Status.SCHEDULED and d.ceg.opens_at and d.ceg.opens_at > now
        if d.livres <= 0 and not agendada:
            continue
        bloco = cegs.setdefault(d.ceg_id, {'ceg': d.ceg, 'agendada': agendada, 'itens': []})
        bloco['itens'].append(d)

    vitrine = list(ItemVitrine.objects.filter(_filtro_nome('integrante', nomes), status=ItemVitrine.Status.DISPONIVEL,
                                              group_id__in=grupos, gom__is_active=True)
                   .select_related('gom').order_by('-created_at')[:24])
    repasses = list(Repasse.objects.filter(_filtro_nome('slot__item_definition__member_name', nomes),
                                           status=Repasse.Status.DISPONIVEL, publico=True,
                                           slot__set__ceg__era__group_id__in=grupos)
                    .select_related('gom', 'slot__item_definition', 'slot__set__ceg').order_by('-id')[:24])
    cartoes_repasse = [{'img': r.slot.item_definition.image_url or r.slot.set.ceg.display_image_url,
                        'titulo': r.slot.item_definition.name, 'sub': r.slot.set.ceg.title, 'gom': r.gom, 'selo': 'Repasse',
                        'url': f"{reverse('ceg_detail', args=[r.slot.set.ceg.slug])}#repasse-{r.slot_id}"} for r in repasses]
    cartoes_vitrine = [{'img': v.display_image_url, 'titulo': v.titulo, 'sub': f'R$ {v.preco:.2f}'.replace('.', ','),
                        'gom': v.gom, 'selo': 'Pronta entrega',
                        'url': f"{reverse('vitrine_list')}?{urlencode({'q': v.titulo})}"} for v in vitrine]
    return {'cegs': list(cegs.values()), 'vitrine': cartoes_vitrine, 'repasses': cartoes_repasse}


def procurar(request):
    q = (request.GET.get('q') or '').strip()[:60]
    membro = None
    if (request.GET.get('m') or '').isdigit():
        membro = GroupMember.objects.select_related('group').filter(pk=request.GET['m']).first()
    candidatos = []
    if q and membro is None:
        candidatos = list(GroupMember.objects.filter(Q(name__icontains=q) | Q(name_native__icontains=q))
                          .select_related('group').order_by('is_former', 'name')[:LIMITE_CANDIDATOS])
        candidatos.sort(key=lambda m: (q.lower() not in (m.name.lower(), (m.name_native or '').lower()), m.is_former))
        if len(candidatos) == 1:
            membro = candidatos[0]
    contexto = {'q': q or (membro.name if membro else ''), 'membro': membro, 'candidatos': candidatos,
                'nav_procurar': True}
    if membro:
        contexto.update(resultados(membro))
        contexto['total'] = len(contexto['cegs']) + len(contexto['vitrine']) + len(contexto['repasses'])
    return render(request, 'cegs/procurar.html', contexto)
