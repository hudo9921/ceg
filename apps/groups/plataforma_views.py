"""
Catálogo para o administrador da plataforma (/plataforma/catalogo/): números, busca e filtros dos grupos/solistas
e uma página por grupo com integrantes, eras (capas) e CEGs. O lápis abre um modal (grupo ou era) que salva aqui
mesmo; o Django Admin fica para os campos raros (link no modal).
"""
from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.goms.access import platform_admin_required
from apps.participants.session_auth import safe_next_url

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


class GrupoForm(forms.ModelForm):
    class Meta:
        model = KpopGroup
        fields = ('name', 'name_native', 'aliases', 'kind', 'status', 'agency', 'debut_date', 'popularity_rank', 'image_url')


class EraForm(forms.ModelForm):
    class Meta:
        model = Era
        fields = ('name', 'kind', 'release_date', 'banner_url')


def dados_grupo(g):
    """O que o modal de edição precisa (vai para data-dados com |json_attr)."""
    return {
        'tipo': 'grupo', 'url': reverse('platform_catalogo_grupo_salvar', args=[g.pk]),
        'admin': reverse('admin:groups_kpopgroup_change', args=[g.pk]),
        'name': g.name, 'name_native': g.name_native, 'aliases': g.aliases, 'kind': g.kind, 'status': g.status,
        'agency': g.agency, 'debut_date': g.debut_date.isoformat() if g.debut_date else '',
        'popularity_rank': g.popularity_rank or '', 'image_url': g.image_url,
    }


def dados_era(e):
    return {
        'tipo': 'era', 'url': reverse('platform_catalogo_era_salvar', args=[e.pk]),
        'admin': reverse('admin:groups_era_change', args=[e.pk]),
        'name': e.name, 'kind': e.kind, 'release_date': e.release_date.isoformat() if e.release_date else '',
        'image_url': e.banner_url,
    }


def _escolhas():
    return {'kinds_grupo': KpopGroup.Kind.choices, 'status_grupo': KpopGroup.Status.choices, 'kinds_era': Era.Kind.choices}


def _salvar(request, form, rotulo):
    if form.is_valid():
        form.save()
        messages.success(request, f'{rotulo} salvo.')
    else:
        erros = '; '.join(f'{form.fields[c].label if c in form.fields else c}: {" ".join(e)}' for c, e in form.errors.items())
        messages.error(request, f'Não salvou {rotulo}. {erros}')
    return redirect(safe_next_url(request, request.POST.get('next', ''), default=reverse('platform_catalogo')))


@platform_admin_required
@require_POST
def catalogo_grupo_salvar(request, pk):
    grupo = get_object_or_404(KpopGroup, pk=pk)
    return _salvar(request, GrupoForm(request.POST, instance=grupo), grupo.name)


@platform_admin_required
@require_POST
def catalogo_era_salvar(request, pk):
    era = get_object_or_404(Era, pk=pk)
    dados = request.POST.copy()
    dados['banner_url'] = dados.get('image_url', '')  # o modal usa o mesmo campo de imagem para grupo e era
    return _salvar(request, EraForm(dados, instance=era), f'{era.group.name} · {era.name}')


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
    for g in pagina.object_list:
        g.dados = dados_grupo(g)

    filtros = {k: v for k, v in (('q', q), ('tipo', tipo), ('problema', problema), ('ordem', ordem if ordem != 'ranking' else '')) if v}
    return render(request, 'groups/plataforma_catalogo.html', {
        'pagina': pagina, 'numeros': _numeros(), 'q': q, 'tipo': tipo, 'problema': problema, 'ordem': ordem,
        'tipos': KpopGroup.Kind.choices, 'problemas': [(k, v[0]) for k, v in PROBLEMAS.items()],
        'ordens': [(k, v[0]) for k, v in ORDENS.items()],
        'filtros_qs': urlencode(filtros),
        'tem_filtro': bool(q or tipo or problema), **_escolhas(),
    })


@never_cache
@platform_admin_required
def catalogo_grupo(request, pk):
    grupo = get_object_or_404(KpopGroup, pk=pk)
    eras = list(grupo.eras.annotate(n_cegs=Count('cegs')).order_by('-release_date', 'name'))
    for e in eras:
        e.dados = dados_era(e)
    membros = list(grupo.members.select_related('solo').order_by('is_former', 'order', 'name'))
    from apps.cegs.models import CEG
    cegs_por_gom = (CEG.objects.filter(era__group=grupo).values('gom__name')
                    .annotate(n=Count('id')).order_by('-n'))
    return render(request, 'groups/plataforma_grupo.html', {
        'grupo': grupo, 'eras': eras, 'membros': membros, 'cegs_por_gom': list(cegs_por_gom),
        'eras_sem_capa': sum(1 for e in eras if not e.banner_url), 'dados_grupo': dados_grupo(grupo), **_escolhas(),
    })
