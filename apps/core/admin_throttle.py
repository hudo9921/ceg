"""
Proteção contra força bruta no login do admin (/admin/login/).

Contadores de falha por IP e por username ficam no cache compartilhado (Redis em
produção), valendo entre todos os workers do Gunicorn. Após MAX_FAILURES falhas em
WINDOW_SECONDS, novos POSTs de login recebem HTTP 429 até a janela expirar.
"""
import logging

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.dispatch import receiver
from django.http import HttpResponse

from apps.participants.session_auth import get_client_ip

logger = logging.getLogger('security')

MAX_FAILURES = 10
WINDOW_SECONDS = 15 * 60
ADMIN_LOGIN_PATH = '/admin/login/'


def _keys(ip, username):
    keys = []
    if ip:
        keys.append(f'admin-login-fail:ip:{ip}')
    if username:
        keys.append(f'admin-login-fail:user:{username.strip().lower()}')
    return keys


def _increment(key):
    if cache.add(key, 1, WINDOW_SECONDS):
        return 1
    try:
        return cache.incr(key)
    except ValueError:  # expirou entre o add e o incr
        cache.set(key, 1, WINDOW_SECONDS)
        return 1


def is_locked(ip, username) -> bool:
    return any((cache.get(k) or 0) >= MAX_FAILURES for k in _keys(ip, username))


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    if request is None:
        return
    ip = get_client_ip(request)
    username = (credentials or {}).get('username', '')
    for key in _keys(ip, username):
        _increment(key)
    logger.warning("Falha de login staff (usuário=%s, ip=%s)", username or '-', ip or '-')


@receiver(user_logged_in)
def _on_login_success(sender, request, user, **kwargs):
    ip = get_client_ip(request) if request else None
    cache.delete_many(_keys(ip, user.get_username()))
    logger.info("Login staff OK (usuário=%s, ip=%s)", user.get_username(), ip or '-')


class AdminLoginThrottleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == 'POST' and request.path == ADMIN_LOGIN_PATH:
            ip = get_client_ip(request)
            username = request.POST.get('username', '')
            if is_locked(ip, username):
                logger.warning("Login staff bloqueado por excesso de falhas (usuário=%s, ip=%s)",
                               username or '-', ip or '-')
                return HttpResponse(
                    "Muitas tentativas de login. Aguarde 15 minutos e tente novamente.",
                    status=429, content_type='text/plain; charset=utf-8',
                )
        return self.get_response(request)
