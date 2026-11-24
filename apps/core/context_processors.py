from django.conf import settings
from django.urls import reverse

# Seções do joiner (DESIGN_SYSTEM §7.4): CEGs e Vitrine separados; Pagar, Meus itens e Envios.
# Pagar, Meus itens e Envios são abas do /me/ (P3); o painel mantém ?tab= e o destaque do menu em sincronia.
JOINER_SECTIONS = (
    ('cegs', 'CEGs', 'sparkles'),
    ('vitrine', 'Vitrine', 'store'),
    ('pagar', 'Pagar', 'wallet'),
    ('itens', 'Meus itens', 'package'),
    ('envios', 'Envios', 'truck'),
)


def _active_section(request):
    match = getattr(request, 'resolver_match', None)
    name = match.url_name if match else ''
    if name in ('home', 'ceg_detail', 'gom_public'):
        return 'cegs'
    if name and name.startswith('vitrine'):
        return 'vitrine'
    if name == 'my_claims':
        tab = request.GET.get('tab', '')
        return {'pagar': 'pagar', 'caixinha': 'envios', 'envios': 'envios', 'itens': 'itens',
                'reservas': 'itens'}.get(tab, 'pagar')
    return ''


def frontend(request):
    """Modo dos assets e a navegação principal do joiner (barra lateral e barra de abas)."""
    me = reverse('my_claims')
    urls = {
        'cegs': reverse('home'),
        'vitrine': reverse('vitrine_list'),
        'pagar': f'{me}?tab=pagar',
        'itens': f'{me}?tab=itens',
        'envios': f'{me}?tab=envios',
    }
    active = _active_section(request)
    return {
        'frontend_build': settings.FRONTEND_MODE == 'build',
        'nav_section': active,
        'joiner_nav': [
            {'key': key, 'label': label, 'icon': icon, 'url': urls[key], 'active': key == active}
            for key, label, icon in JOINER_SECTIONS
        ],
    }
