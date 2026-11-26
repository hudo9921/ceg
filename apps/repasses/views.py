"""Repasse: ações do joiner (JSON), lista pública de vagas disponíveis e a fila do GOM (pedidos.editar)."""
import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.cegs.models import ItemSlot
from apps.core.permissions import staff_required
from apps.participants.session_auth import get_session_participant

from . import services
from .models import Repasse

PERM = 'pedidos.editar'  # "Trocar dono de item"


def _joiner(view):
    def _wrapped(request, *args, **kwargs):
        participant = get_session_participant(request)
        if participant is None:
            return JsonResponse({'success': False, 'requires_auth': True, 'redirect_url': '/me/login/?next=/me/',
                                 'message': 'Entre na sua conta para continuar.'}, status=401)
        request.participant = participant
        return view(request, *args, **kwargs)
    _wrapped.__name__ = view.__name__
    return _wrapped


def _corpo(request):
    try:
        return json.loads(request.body or '{}')
    except ValueError:
        return {}


def _resposta(fn, *args, msg):
    try:
        fn(*args)
    except services.RepasseError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    return JsonResponse({'success': True, 'message': msg})


@require_POST
@_joiner
def criar(request):
    body = _corpo(request)
    slot = get_object_or_404(ItemSlot.objects.select_related('set__ceg'), pk=body.get('slot_id') or 0)
    publico = body.get('modo') == 'publico'
    msg = ('Pronto: a vaga aparece como disponível para repasse. O GOM aprova quando alguém pedir.' if publico
           else 'Pedido enviado. Quando a pessoa aceitar, o GOM aprova.')
    return _resposta(services.criar, request.participant, slot, body.get('whatsapp', ''), publico, body.get('recado', ''),
                     msg=msg)


@require_POST
@_joiner
def responder(request, pk):
    aceitar = bool(_corpo(request).get('aceitar'))
    rep = get_object_or_404(Repasse, pk=pk)
    return _resposta(services.responder, rep, request.participant, aceitar,
                     msg='Aceito! Agora o GOM aprova o repasse.' if aceitar else 'Repasse recusado.')


@require_POST
@_joiner
def cancelar(request, pk):
    rep = get_object_or_404(Repasse, pk=pk, de=request.participant)
    return _resposta(services.cancelar, rep, request.participant, msg='Repasse cancelado.')


@require_POST
@_joiner
def pedir(request, pk):
    rep = get_object_or_404(Repasse, pk=pk, publico=True)
    return _resposta(services.pedir_publico, rep, request.participant, msg='Pedido enviado! O GOM vai aprovar ou recusar.')


def disponiveis(gom=None, ceg=None):
    qs = (Repasse.objects.filter(status=Repasse.Status.DISPONIVEL, gom__is_active=True)
          .select_related('gom', 'de', 'slot__set__ceg__era__group', 'slot__item_definition'))
    if gom is not None:
        qs = qs.filter(gom=gom)
    if ceg is not None:
        qs = qs.filter(slot__set__ceg=ceg)
    return qs.order_by('-criado_em')


def com_valores(repasses):
    """Põe .pendencias e .a_pagar (o que passa para quem receber) em cada repasse."""
    repasses = list(repasses)
    for r in repasses:
        r.pendencias = services.pendencias(r.slot)
        r.a_pagar = sum(v for _, v in r.pendencias)
    return repasses


def lista_publica(request):
    """/repasses/: vagas que joiners deixaram disponíveis (qualquer pessoa pede; o GOM aprova)."""
    pagina = Paginator(disponiveis(), 30).get_page(request.GET.get('pagina'))
    com_valores(pagina.object_list)
    return render(request, 'repasses/lista.html', {'pagina': pagina})


@never_cache
@staff_required(PERM)
@require_http_methods(['GET', 'POST'])
def gom_fila(request):
    gom = request.active_gom
    if request.method == 'POST':
        rep = get_object_or_404(Repasse.objects.for_gom(gom), pk=request.POST.get('repasse') or 0)
        try:
            if request.POST.get('acao') == 'aprovar':
                services.aprovar(rep, request.user)
                messages.success(request, 'Repasse aprovado. Os dois joiners foram avisados.')
            else:
                services.recusar(rep, request.user, request.POST.get('motivo', ''))
                messages.success(request, 'Repasse recusado.')
        except services.RepasseError as exc:
            messages.error(request, str(exc))
        return redirect('gom_repasses')
    base = Repasse.objects.for_gom(gom).select_related('de', 'para', 'slot__set__ceg', 'slot__item_definition', 'resolvido_por')
    pendentes = com_valores(base.filter(status=Repasse.Status.AGUARDANDO_GOM).order_by('aceito_em'))
    return render(request, 'repasses/gom_fila.html', {
        'pendentes': pendentes,
        'andamento': list(base.filter(status__in=[Repasse.Status.DISPONIVEL, Repasse.Status.AGUARDANDO_ACEITE])[:50]),
        'historico': list(base.exclude(status__in=Repasse.ATIVOS)[:30]),
    })
