"""Telas de 2FA do backoffice: cadastro (QR code), verificação e códigos de recuperação."""
import base64
import logging
from functools import wraps
from io import BytesIO

import qrcode
import qrcode.image.svg
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django_otp import login as otp_login, match_token
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.participants.session_auth import safe_next_url

from .permissions import STAFF_LOGIN_URL
from .two_factor import (
    get_or_create_pending_totp, has_confirmed_device, is_two_factor_verified,
    regenerate_backup_codes, remaining_backup_codes, requires_two_factor,
)

security_logger = logging.getLogger('security')
DEFAULT_NEXT = '/painel/'


def backoffice_user_required(view):
    """Somente usuários que precisam de 2FA (anônimo -> login; demais -> 403)."""
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), STAFF_LOGIN_URL)
        if not requires_two_factor(request.user):
            raise PermissionDenied('Verificação em duas etapas é exclusiva da organização.')
        return view(request, *args, **kwargs)
    return _wrapped


def _qr_data_uri(config_url: str) -> str:
    image = qrcode.make(config_url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buffer = BytesIO()
    image.save(buffer)
    return 'data:image/svg+xml;base64,' + base64.b64encode(buffer.getvalue()).decode()


def _complete_login(request, device):
    otp_login(request, device)
    request.session.cycle_key()
    request.session.set_expiry(settings.STAFF_SESSION_AGE)


def _token(request) -> str:
    return ''.join(request.POST.get('token', '').split()).lower()


@never_cache
@backoffice_user_required
@require_http_methods(['GET', 'POST'])
def setup_view(request):
    next_url = safe_next_url(request, request.GET.get('next') or request.POST.get('next'), DEFAULT_NEXT)
    if has_confirmed_device(request.user):
        return redirect(next_url if is_two_factor_verified(request.user) else 'staff_2fa_verify')

    device = get_or_create_pending_totp(request.user)
    if request.method == 'POST':
        if device.verify_token(_token(request)):
            device.confirmed = True
            device.save(update_fields=['confirmed'])
            _complete_login(request, device)
            codes = regenerate_backup_codes(request.user)
            security_logger.info("2FA: autenticador cadastrado (usuário=%s)", request.user.get_username())
            return render(request, 'core/two_factor/backup_codes.html',
                          {'codes': codes, 'next_url': next_url, 'first_time': True})
        messages.error(request, 'Código inválido. Aguarde alguns segundos, confira o horário do celular e tente de novo.')

    return render(request, 'core/two_factor/setup.html', {
        'qr_data_uri': _qr_data_uri(device.config_url),
        'secret': base64.b32encode(device.bin_key).decode().rstrip('='),
        'next_url': next_url,
    })


@never_cache
@backoffice_user_required
@require_http_methods(['GET', 'POST'])
def verify_view(request):
    next_url = safe_next_url(request, request.GET.get('next') or request.POST.get('next'), DEFAULT_NEXT)
    if not has_confirmed_device(request.user):
        return redirect('staff_2fa_setup')
    if is_two_factor_verified(request.user):
        return redirect(next_url)

    if request.method == 'POST':
        device = match_token(request.user, _token(request))
        if device is not None:
            _complete_login(request, device)
            if not isinstance(device, TOTPDevice):
                left = remaining_backup_codes(request.user)
                security_logger.warning("2FA: código de recuperação usado (usuário=%s, restantes=%s)",
                                        request.user.get_username(), left)
                messages.warning(request, f'Código de recuperação usado. Restam {left}; gere novos em "Segurança da conta".')
            return redirect(next_url)
        security_logger.warning("2FA: código inválido (usuário=%s)", request.user.get_username())
        messages.error(request, 'Código inválido ou tentativas demais. Aguarde alguns segundos e tente de novo.')

    return render(request, 'core/two_factor/verify.html', {'next_url': next_url})


@never_cache
@backoffice_user_required
@require_http_methods(['GET', 'POST'])
def manage_view(request):
    """Status do 2FA e geração de novos códigos de recuperação (sessão já verificada)."""
    if not is_two_factor_verified(request.user):
        return redirect('staff_2fa_verify')
    if request.method == 'POST':
        codes = regenerate_backup_codes(request.user)
        return render(request, 'core/two_factor/backup_codes.html',
                      {'codes': codes, 'next_url': reverse('staff_2fa_manage'), 'first_time': False})
    return render(request, 'core/two_factor/manage.html', {
        'remaining_codes': remaining_backup_codes(request.user),
        'devices': TOTPDevice.objects.filter(user=request.user, confirmed=True),
    })
