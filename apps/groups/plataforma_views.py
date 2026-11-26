"""
Catálogo para o administrador da plataforma (/plataforma/catalogo/): números, busca e filtros dos grupos/solistas
e uma página por grupo com integrantes, eras (capas) e CEGs. Editar continua no Django Admin (links em cada linha).
"""
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, render
from django.utils.http import urlencode
from django.views.decorators.cache import never_cache

from apps.goms.access import platform_admin_required

from .models import Era, GroupMember, KpopGroup, Source, normalize_name

POR_PAGINA = 50
ORDENS = {
    'ranking': ('Ranking', ('popularity_rank', 'name')),
    'nome': ('Nome', ('name',)),
    'cegs': ('Mais CEGs', ('-n_cegs', 'name')),
    'recentes': ('Adicionados por último', ('-created_at',)),
}
PROBLEMAS = {
    'sem_foto': ('Sem foto', Q(image_url='')),
    'sem_eras': ('Sem eras', Q(n_eras=0)),
    'sem_integrantes': ('Sem integrantes (grupos)', Q(n_membros=0) & ~Q(kind=KpopGroup.Kind.SOLISTA)),
    'eras_sem_capa': ('Com eras sem capa', Q(n_eras_sem_capa__gt=0)),
}


def _numeros():
    return [
        ('Grupos e solistas', KpopGroup.objects.count()),
        ('Eras', Era.objects.count()),
        ('Integrantes', GroupMember.objects.count()),
        ('Grupos sem foto', KpopGroup.objects.filter(image_url='').count()),
        ('Eras sem capa', Era.objects.filter(banner_url='').count()),
        ('Vindos do catálogo', KpopGroup.objects.exclude(source=Source.MANUAL).count()),
    ]


@never_cache
@platform_admin_required
def catalogo(request):
    q = request.GET.get('q', '').strip()
    tipo = request.GET.get('tipo', '')
    problema = request.GET.get('problema', '')
    ordem = request.GET.get('ordem', 'ranking')
    if ordem not in ORDENS:
        ordem = 'ranking'

    grupos = KpopGroup.objects.annotate(
        n_eras=Count('eras', distinct=True),
        n_membros=Count('members', distinct=True),
        n_cegs=Count('eras__cegs', distinct=True),
        n_eras_sem_capa=Count('eras', filter=Q(eras__banner_url=''), distinct=True),
    )
    if q:
        chave = normalize_name(q)
        grupos = grupos.filter(Q(name__icontains=q) | Q(search_key__contains=chave) | Q(agency__icontains=q))
    if tipo in KpopGroup.Kind.values:
        grupos = grupos.filter(kind=tipo)
    else:
        tipo = ''
    if problema in PROBLEMAS:
        grupos = grupos.filter(PROBLEMAS[problema][1])
    else:
        problema = ''
    ordenacao = ORDENS[ordem][1]
    if ordem == 'ranking':  # sem posição vai para o fim
        ordenacao = (F('popularity_rank').asc(nulls_last=True), 'name')
    pagina = Paginator(grupos.order_by(*ordenacao), POR_PAGINA).get_page(request.GET.get('pagina'))

    filtros = {k: v for k, v in (('q', q), ('tipo', tipo), ('problema', problema), ('ordem', ordem if ordem != 'ranking' else '')) if v}
    return render(request, 'groups/plataforma_catalogo.html', {
        'pagina': pagina, 'numeros': _numeros(), 'q': q, 'tipo': tipo, 'problema': problema, 'ordem': ordem,
        'tipos': KpopGroup.Kind.choices, 'problemas': [(k, v[0]) for k, v in PROBLEMAS.items()],
        'ordens': [(k, v[0]) for k, v in ORDENS.items()],
        'filtros_qs': urlencode(filtros),
        'tem_filtro': bool(q or tipo or problema),
    })


@never_cache
@platform_admin_required
def catalogo_grupo(request, pk):
    grupo = get_object_or_404(KpopGroup, pk=pk)
    eras = list(grupo.eras.annotate(n_cegs=Count('cegs')).order_by('-release_date', 'name'))
    membros = list(grupo.members.select_related('solo').order_by('is_former', 'order', 'name'))
    from apps.cegs.models import CEG
    cegs_por_gom = (CEG.objects.filter(era__group=grupo).values('gom__name')
                    .annotate(n=Count('id')).order_by('-n'))
    return render(request, 'groups/plataforma_grupo.html', {
        'grupo': grupo, 'eras': eras, 'membros': membros, 'cegs_por_gom': list(cegs_por_gom),
        'eras_sem_capa': sum(1 for e in eras if not e.banner_url),
    })
