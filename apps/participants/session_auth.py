"""
Helpers de sessão do participante (joiner).

Regra de ouro: a identidade do joiner vem SOMENTE da sessão, que só é criada por
`login_participant()` após verificação de OTP. Nenhuma view deve gravar
`participant_id` na sessão a partir de dados enviados no request.
"""
import ipaddress

from django.conf import settings
from django.utils.http import url_has_allowed_host_and_scheme

SESSION_KEY = 'participant_id'


def login_participant(request, participant) -> None:
    """Autentica o participante na sessão, rotacionando a chave (anti session fixation)."""
    request.session.cycle_key()
    request.session[SESSION_KEY] = participant.id
    # A partir do primeiro login o cadastro passa a ser do joiner (apps.goms.joiners).
    from django.utils import timezone
    type(participant).objects.filter(pk=participant.pk).update(last_login_at=timezone.now())
    participant.last_login_at = timezone.now()


def logout_participant(request) -> None:
    request.session.pop(SESSION_KEY, None)
    request.session.cycle_key()


def get_session_participant(request):
    """Retorna o Participant autenticado na sessão ou None (limpa ids órfãos)."""
    from .models import Participant
    participant_id = request.session.get(SESSION_KEY)
    if not participant_id:
        return None
    participant = Participant.objects.filter(id=participant_id).first()
    if participant is None:
        request.session.pop(SESSION_KEY, None)
    return participant


def safe_next_url(request, url: str, default: str = '/me/') -> str:
    """Aceita apenas redirecionamentos relativos para o próprio site (bloqueia //evil.com)."""
    url = (url or '').strip()
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return default


def get_client_ip(request) -> str | None:
    """
    IP do cliente atrás do Caddy. Usa o último valor de X-Forwarded-For (adicionado
    pelo proxy mais próximo), com fallback para REMOTE_ADDR.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    candidates = [forwarded.split(',')[-1].strip()] if forwarded else []
    candidates.append(request.META.get('REMOTE_ADDR', ''))
    for ip in candidates:
        try:
            return str(ipaddress.ip_address(ip))
        except ValueError:
            continue
    return None


def can_expose_dev_otp() -> bool:
    """O código OTP só pode aparecer na tela em desenvolvimento local com o provider console."""
    return bool(settings.DEBUG) and getattr(settings, 'WHATSAPP_PROVIDER', '') == 'console'
