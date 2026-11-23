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

STAFF_LOGIN_URL = '/admin/login/'
DENIED_MESSAGE = 'Acesso restrito ao organizador.'


def _wants_json(request) -> bool:
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or request.content_type == 'application/json'
        or 'application/json' in request.headers.get('accept', '')
    )


def is_staff_user(user) -> bool:
    return bool(user and user.is_authenticated and user.is_staff)


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


class StaffRequiredMixin:
    """Garante que apenas usuários autenticados com `is_staff` acessem a view."""

    def dispatch(self, request, *args, **kwargs):
        if not is_staff_user(request.user):
            return deny_staff_access(request)
        return super().dispatch(request, *args, **kwargs)


def staff_required(view_func):
    """Equivalente de `StaffRequiredMixin` para views em função."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_staff_user(request.user):
            return deny_staff_access(request)
        return view_func(request, *args, **kwargs)
    return _wrapped
