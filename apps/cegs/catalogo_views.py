"""
Catálogo compartilhado no Hub de Criações.

`era_fotos`: fotos já usadas em CEGs publicadas da mesma era, de qualquer GOM (capas e fotos dos itens),
para a Nova CEG reaproveitar em vez de subir de novo. Rascunhos ficam de fora: só entra o que já é público.
As imagens nunca são apagadas do storage quando uma CEG é excluída, então o link reaproveitado continua válido.
"""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from apps.core.permissions import staff_required
from apps.core.thumbnails import thumbnail_url
from apps.groups.models import Era

from .models import CEG, CEGItemDefinition

LIMITE_CAPAS = 24
LIMITE_ITENS = 300


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
