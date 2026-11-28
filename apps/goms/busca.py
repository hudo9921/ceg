"""
Busca rápida do painel (Ctrl+K): joiners, CEGs, caixas e pacotes do GOM ativo, cada grupo só para quem tem a
permissão daquela área. As páginas do menu são filtradas no navegador (components/_busca_rapida.html).
"""
import re

from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.core.permissions import has_gom_permission, staff_required

from .permissions import ANY

LIMITE = 6


def _joiners(gom, q, digitos):
    from apps.participants.models import Participant
    filtro = Q(name__icontains=q) | Q(username__icontains=q) | Q(social_handle__icontains=q.lstrip('@'))
    if len(digitos) >= 4:
        filtro |= Q(whatsapp__endswith=digitos)
    return [{'tipo': 'joiner', 'id': p.id, 'titulo': p.display_name,
             'sub': ' · '.join(x for x in (p.social_handle, f'•••• {p.whatsapp[-4:]}' if p.whatsapp else '') if x),
             'url': f"{reverse('consulta_joiner')}?participant_id={p.id}"}
            for p in Participant.objects.for_gom(gom).filter(filtro).order_by('name')[:LIMITE]]


def _cegs(gom, q):
    from apps.cegs.models import CEG
    qs = (CEG.objects.for_gom(gom).filter(Q(title__icontains=q) | Q(era__name__icontains=q) | Q(era__group__name__icontains=q))
          .select_related('era__group').order_by('-created_at')[:LIMITE])
    return [{'tipo': 'ceg', 'titulo': c.title, 'sub': f'{c.era.group.name} · {c.get_status_display()}' if c.era_id else c.get_status_display(),
             'url': reverse('ceg_detail', args=[c.slug])} for c in qs]


def _caixas(gom, q):
    from apps.cegs.models import Caixa
    qs = Caixa.objects.for_gom(gom).filter(Q(nome__icontains=q) | Q(codigo_rastreio__iexact=q)).order_by('-id')[:LIMITE]
    return [{'tipo': 'caixa', 'titulo': c.nome, 'sub': c.get_status_display(), 'url': reverse('caixa_detail', args=[c.slug])}
            for c in qs]


def _pacotes(gom, q):
    from apps.cegs.models import PacoteNacional
    qs = (PacoteNacional.objects.for_gom(gom).filter(Q(identificador__icontains=q) | Q(codigo_rastreio__iexact=q))
          .select_related('participant').order_by('-id')[:LIMITE])
    return [{'tipo': 'pacote', 'titulo': f'Pacote {p.identificador}', 'sub': f'{p.participant.display_name} · {p.get_status_display()}',
             'url': f"{reverse('envios_nacionais')}?view=lista&q={p.identificador}"} for p in qs]


@never_cache
@staff_required(ANY)
def busca(request):
    q = (request.GET.get('q') or '').strip()[:80]
    if len(q) < 2:
        return JsonResponse({'grupos': []})
    gom = request.active_gom
    digitos = re.sub(r'\D', '', q)
    grupos = []
    if has_gom_permission(request, 'pedidos.ver'):
        grupos.append(('Joiners', _joiners(gom, q, digitos)))
    grupos.append(('CEGs', _cegs(gom, q)))
    if has_gom_permission(request, ('caixas.editar', 'caixas.valores', 'caixas.etapa')):
        grupos.append(('Caixas', _caixas(gom, q)))
    if has_gom_permission(request, ('envios.pacotes', 'gom.envio')):
        grupos.append(('Pacotes', _pacotes(gom, q)))
    return JsonResponse({'grupos': [{'titulo': t, 'itens': itens} for t, itens in grupos if itens]})
