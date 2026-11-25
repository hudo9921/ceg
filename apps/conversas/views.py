"""
Conversas (S5): joiner em /me/mensagens/ (sessão do joiner) e equipe do GOM em /mensagens/ (mensagens.responder).
A tela da conversa envia por fetch e busca mensagens novas a cada poucos segundos (JSON).
"""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.core.permissions import staff_required
from apps.goms.models import Gom
from apps.participants.models import Participant
from apps.participants.session_auth import get_session_participant

from . import services
from .models import Conversa, Mensagem

PERM = 'mensagens.responder'


def _wants_json(request):
    return 'application/json' in request.headers.get('Accept', '')


def _alvo(gom, tipo, alvo_id):
    from apps.cegs.models import CEG, ItemVitrine, PacoteNacional
    model = {Conversa.Tipo.PACOTE: PacoteNacional, Conversa.Tipo.CEG: CEG, Conversa.Tipo.VITRINE: ItemVitrine}.get(tipo)
    return get_object_or_404(model.objects.for_gom(gom), pk=alvo_id) if model else None


def _page(request, conversas, cur, lado, template, extra=None):
    if cur is not None:
        services.marcar_lida(cur, lado)
    return render(request, template, {'conversas': conversas, 'cur': cur, 'lado': lado,
                                      'msgs': services.mensagens_json(cur, lado=lado) if cur else [], **(extra or {})})


# ----------------------------------------------------------------------------------------------- joiner
def _joiner(request):
    participant = get_session_participant(request)
    if participant is None:
        if _wants_json(request) or request.method == 'POST' and request.content_type == 'application/json':
            return None, JsonResponse({'success': False, 'requires_auth': True, 'redirect_url': '/me/login/'}, status=401)
        return None, redirect(f"{reverse('login_otp')}?next={request.get_full_path()}")
    return participant, None


@never_cache
@require_GET
def joiner_lista(request):
    participant, deny = _joiner(request)
    if deny:
        return deny
    conversas = list(Conversa.objects.filter(participant=participant).select_related('gom'))
    cur = next((c for c in conversas if str(c.id) == request.GET.get('c')), None)
    return _page(request, conversas, cur, 'joiner', 'conversas/joiner.html')


@require_POST
def joiner_nova(request):
    participant, deny = _joiner(request)
    if deny:
        return deny
    gom = get_object_or_404(Gom, pk=request.POST.get('gom_id'), is_active=True)
    tipo = request.POST.get('tipo', Conversa.Tipo.GERAL)
    if tipo not in Conversa.Tipo.values:
        tipo = Conversa.Tipo.GERAL
    alvo = _alvo(gom, tipo, request.POST.get('alvo_id'))
    if tipo == Conversa.Tipo.PACOTE and alvo.participant_id != participant.id:
        return redirect('joiner_mensagens')
    conversa = services.abrir(participant, gom, tipo, alvo)
    if request.POST.get('texto'):
        try:
            services.enviar(conversa, Mensagem.Autor.JOINER, request.POST['texto'])
        except services.ConversaError as exc:
            messages.error(request, str(exc))
    return redirect(f"{reverse('joiner_mensagens')}?c={conversa.id}")


def _send(request, conversa, autor, user=None):
    try:
        services.enviar(conversa, autor, request.POST.get('texto', ''), user)
    except services.ConversaError as exc:
        if _wants_json(request):
            return JsonResponse({'success': False, 'message': str(exc)}, status=400)
        messages.error(request, str(exc))
    if _wants_json(request):
        return JsonResponse({'success': True})
    return None


@require_POST
def joiner_enviar(request, conversa_id):
    participant, deny = _joiner(request)
    if deny:
        return deny
    conversa = get_object_or_404(Conversa, pk=conversa_id, participant=participant)
    return _send(request, conversa, Mensagem.Autor.JOINER) or redirect(f"{reverse('joiner_mensagens')}?c={conversa.id}")


@never_cache
@require_GET
def joiner_novas(request, conversa_id):
    participant, deny = _joiner(request)
    if deny:
        return deny
    conversa = get_object_or_404(Conversa, pk=conversa_id, participant=participant)
    services.marcar_lida(conversa, 'joiner')
    return JsonResponse({'mensagens': services.mensagens_json(conversa, int(request.GET.get('depois') or 0), 'joiner')})


# ----------------------------------------------------------------------------------------------- GOM
@never_cache
@staff_required(PERM)
@require_GET
def gom_lista(request):
    conversas = list(Conversa.objects.for_gom(request.active_gom).select_related('participant')[:200])
    cur = next((c for c in conversas if str(c.id) == request.GET.get('c')), None)
    return _page(request, conversas, cur, 'gom', 'conversas/gom.html')


@staff_required(PERM)
@require_POST
def gom_nova(request):
    """Equipe abre uma conversa com um joiner (Consulta 360°)."""
    participant = get_object_or_404(Participant.objects.for_gom(request.active_gom), pk=request.POST.get('participant_id'))
    conversa = services.abrir(participant, request.active_gom)
    return redirect(f"{reverse('gom_mensagens')}?c={conversa.id}")


@staff_required(PERM)
@require_POST
def gom_enviar(request, conversa_id):
    conversa = get_object_or_404(Conversa.objects.for_gom(request.active_gom), pk=conversa_id)
    return _send(request, conversa, Mensagem.Autor.GOM, request.user) or redirect(f"{reverse('gom_mensagens')}?c={conversa.id}")


@never_cache
@staff_required(PERM)
@require_GET
def gom_novas(request, conversa_id):
    conversa = get_object_or_404(Conversa.objects.for_gom(request.active_gom), pk=conversa_id)
    services.marcar_lida(conversa, 'gom')
    return JsonResponse({'mensagens': services.mensagens_json(conversa, int(request.GET.get('depois') or 0), 'gom')})
