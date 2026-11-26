"""Página pública /caixinhas/: caixas de todos os GOMs que aceitam pedidos agora (apps/cegs/caixinhas.py)."""
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import render

from apps.goms.models import Gom

from . import caixinhas
from .models import Caixa

POR_PAGINA = 24


def caixinhas_abertas(request):
    origem = request.GET.get('origem', '').strip().upper()
    if origem not in Caixa.Origem.values:
        origem = ''
    gom = None
    gom_slug = request.GET.get('gom', '').strip()
    if gom_slug:
        gom = Gom.objects.filter(slug=gom_slug, is_active=True).first()

    base = caixinhas.abertas(gom=gom)
    # Chips de origem só com as origens que têm caixa aberta (com contagem).
    por_origem = dict(base.order_by().values_list('origem').annotate(n=Count('id', distinct=True)))
    origens = [(valor, caixinhas.ORIGEM_CURTA[valor][1], por_origem[valor])
               for valor in Caixa.Origem.values if por_origem.get(valor)]

    lista = base.filter(origem=origem) if origem else base
    pagina = Paginator(lista, POR_PAGINA).get_page(request.GET.get('pagina'))
    return render(request, 'cegs/caixinhas.html', {
        'caixas': caixinhas.com_rotulos(pagina.object_list),
        'pagina': pagina,
        'origem': origem,
        'origens': origens,
        'total': sum(por_origem.values()),
        'filtro_gom': gom,
    })
