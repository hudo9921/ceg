"""
Content-Security-Policy e Permissions-Policy.

Todos os scripts e estilos são servidos pelo próprio site (static/vendor + Tailwind
compilado), inclusive as fontes (static/fonts). 'unsafe-inline' e 'unsafe-eval' continuam
necessários porque os templates usam <script> inline e o Alpine.js avalia expressões
(x-data, @click) com `new Function`. Mesmo assim a política impede carregar scripts de
qualquer outro domínio, enviar dados para fora (connect-src/form-action) e o site ser
emoldurado por terceiros.
"""
from django.conf import settings


def build_csp() -> str:
    script_src = ["'self'", "'unsafe-inline'", "'unsafe-eval'"]
    if settings.FRONTEND_MODE == 'dev':  # Play CDN do Tailwind, só desenvolvimento
        script_src.append('https://cdn.tailwindcss.com')
    directives = {
        'default-src': ["'self'"],
        'script-src': script_src,
        'style-src': ["'self'", "'unsafe-inline'"],
        'font-src': ["'self'", 'data:'],
        # Fotos de photocards podem vir de URLs externas e do R2 (https), além de uploads em blob/data.
        'img-src': ["'self'", 'data:', 'blob:', 'https:'],
        'media-src': ["'self'", 'blob:', 'https:'],
        'connect-src': ["'self'"],
        'object-src': ["'none'"],
        'base-uri': ["'self'"],
        'frame-ancestors': ["'none'"],
        'form-action': ["'self'"],
    }
    policy = '; '.join(f"{name} {' '.join(values)}" for name, values in directives.items())
    if not settings.DEBUG:
        policy += '; upgrade-insecure-requests'
    return policy


PERMISSIONS_POLICY = 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()'


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = build_csp()
        self.csp_header = ('Content-Security-Policy-Report-Only'
                           if settings.CSP_REPORT_ONLY else 'Content-Security-Policy')

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault(self.csp_header, self.csp)
        response.headers.setdefault('Permissions-Policy', PERMISSIONS_POLICY)
        return response
