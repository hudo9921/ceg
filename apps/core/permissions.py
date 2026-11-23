"""
Controle de acesso único do projeto.

Toda view exclusiva da GOM/organização deve herdar `StaffRequiredMixin` (ou usar
`staff_required`). O teste `apps/core/tests.py` percorre todas as rotas e falha se
uma rota não pública responder 200 para visitantes anônimos ou joiners.
"""
import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

security_logger = logging.getLogger('security')

STAFF_LOGIN_URL = '/entrar/'
DENIED_MESSAGE = 'Acesso restrito ao organizador.'


def _wants_json(request) -> bool:
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or request.content_type == 'application/json'
        or 'application/json' in request.headers.get('accept', '')
    )


def is_staff_user(request) -> bool:
    """
    Equipe do GOM ativo (dono/admin ou plataforma) com 2FA verificado — ver apps.goms.access.
    Recebe a requisição: o acesso depende do GOM em que a pessoa está atuando.
    """
    if getattr(request, 'is_gom_staff', None) is not None:
        return request.is_gom_staff
    from apps.goms.access import has_backoffice_access
    return has_backoffice_access(request)


def deny_staff_access(request):
    """
    Resposta padrão para acesso negado:
    - AJAX/JSON: 401 (não autenticado) ou 403 (autenticado sem staff);
    - página: 403 para usuário autenticado sem staff, redirect para o login para anônimos.
    """
    if _wants_json(request):
        status = 403 if request.user.is_authenticated else 401
        return JsonResponse(
            {'success': False, 'message': DENIED_MESSAGE, 'error': DENIED_MESSAGE},
            status=status,
        )
    if request.user.is_authenticated:
        security_logger.warning("Acesso staff negado (usuário=%s, rota=%s)",
                                request.user.get_username(), request.path)
        raise PermissionDenied(DENIED_MESSAGE)
    messages.error(request, "Acesso restrito: Você precisa estar autenticado como Administrador/Organizador.")
    return redirect_to_login(request.get_full_path(), STAFF_LOGIN_URL)


def _active_gom(request):
    from apps.goms.access import get_active_gom
    return get_active_gom(request)


class StaffRequiredMixin:
    """Equipe do GOM ativo. A view deve filtrar tudo por `request.active_gom` (for_gom)."""

    def dispatch(self, request, *args, **kwargs):
        if not is_staff_user(request):
            return deny_staff_access(request)
        request.active_gom = getattr(request, 'active_gom', None) or _active_gom(request)
        return super().dispatch(request, *args, **kwargs)


def staff_required(view_func):
    """Equivalente de `StaffRequiredMixin` para views em função."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_staff_user(request):
            return deny_staff_access(request)
        request.active_gom = getattr(request, 'active_gom', None) or _active_gom(request)
        return view_func(request, *args, **kwargs)
    return _wrapped


def is_platform_admin_request(request) -> bool:
    """Administrador da plataforma (superusuário) com 2FA verificado."""
    from apps.core.two_factor import is_two_factor_verified, requires_two_factor
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated and user.is_active and user.is_superuser):
        return False
    return not requires_two_factor(user) or is_two_factor_verified(user)


class PlatformAdminRequiredMixin:
    """Ações da plataforma (banner da home, bot de WhatsApp, catálogo compartilhado)."""

    def dispatch(self, request, *args, **kwargs):
        if not is_platform_admin_request(request):
            return deny_staff_access(request)
        return super().dispatch(request, *args, **kwargs)
