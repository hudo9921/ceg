"""
2FA (TOTP) obrigatório para quem acessa o backoffice.

Ponto único de política: `requires_two_factor(user)`. Hoje cobre todo usuário `is_staff`
ou `is_superuser`. Quando a plataforma tiver vários GOMs (GOM principal + admins de GOM),
os novos papéis devem passar por esta função — nunca espalhe a regra pelas views.

Camadas:
1. `StaffTwoFactorMiddleware`: um usuário que exige 2FA e ainda não verificou nesta
   sessão só consegue abrir as telas de 2FA, o logout e arquivos estáticos.
2. `apps.core.permissions.is_staff_user` também exige a sessão verificada (defesa em
   profundidade caso alguma rota escape do middleware).
"""
import logging

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode
from django_otp import devices_for_user
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

security_logger = logging.getLogger('security')

BACKUP_CODE_COUNT = 10
SETUP_URL_NAME = 'staff_2fa_setup'
VERIFY_URL_NAME = 'staff_2fa_verify'


def requires_two_factor(user) -> bool:
    if not getattr(settings, 'STAFF_2FA_REQUIRED', True):
        return False
    return bool(user and user.is_authenticated and user.is_active
                and (user.is_staff or user.is_superuser))


def is_two_factor_verified(user) -> bool:
    is_verified = getattr(user, 'is_verified', None)
    return bool(callable(is_verified) and is_verified())


def has_confirmed_device(user) -> bool:
    return any(True for _ in devices_for_user(user, confirmed=True))


def get_or_create_pending_totp(user) -> TOTPDevice:
    """Dispositivo ainda não confirmado: o QR code fica estável entre recarregamentos."""
    device = TOTPDevice.objects.filter(user=user, confirmed=False).order_by('-id').first()
    return device or TOTPDevice.objects.create(user=user, name='Autenticador', confirmed=False)


def regenerate_backup_codes(user) -> list[str]:
    """Substitui todos os códigos de recuperação do usuário e devolve os novos (exibidos uma vez)."""
    device, _ = StaticDevice.objects.get_or_create(
        user=user, name='Códigos de recuperação', defaults={'confirmed': True})
    device.token_set.all().delete()
    codes = [StaticToken.random_token() for _ in range(BACKUP_CODE_COUNT)]
    StaticToken.objects.bulk_create(StaticToken(device=device, token=c) for c in codes)
    security_logger.info("2FA: códigos de recuperação gerados (usuário=%s)", user.get_username())
    return codes


def remaining_backup_codes(user) -> int:
    return StaticToken.objects.filter(device__user=user, device__confirmed=True).count()


def reset_two_factor(user) -> int:
    """Remove todos os dispositivos (perda do celular). O próximo login refaz o cadastro."""
    deleted = 0
    for model in (TOTPDevice, StaticDevice):
        deleted += model.objects.filter(user=user).delete()[0]
    security_logger.warning("2FA: dispositivos removidos (usuário=%s)", user.get_username())
    return deleted


class StaffTwoFactorMiddleware:
    """Exige 2FA verificado antes de qualquer rota para usuários do backoffice."""

    def __init__(self, get_response):
        self.get_response = get_response

    def _is_exempt(self, path: str) -> bool:
        exempt = (
            reverse(SETUP_URL_NAME), reverse(VERIFY_URL_NAME),
            reverse('admin:logout'), reverse('health_check'),
        )
        static_prefix = settings.STATIC_URL if settings.STATIC_URL.startswith('/') else '/' + settings.STATIC_URL
        return path in exempt or path.startswith(static_prefix)

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (requires_two_factor(user) and not is_two_factor_verified(user)
                and not self._is_exempt(request.path)):
            target = VERIFY_URL_NAME if has_confirmed_device(user) else SETUP_URL_NAME
            url = f"{reverse(target)}?{urlencode({'next': request.get_full_path()})}"
            wants_json = (request.headers.get('x-requested-with') == 'XMLHttpRequest'
                          or 'application/json' in request.headers.get('accept', ''))
            if wants_json:
                return JsonResponse({'success': False, 'requires_2fa': True, 'redirect': url,
                                     'message': 'Confirme a verificação em duas etapas.'}, status=403)
            return redirect(url)
        return self.get_response(request)
