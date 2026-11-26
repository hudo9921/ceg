from django.conf import settings
from django.urls import reverse

# Seções do joiner (DESIGN_SYSTEM §7.4): CEGs, Vitrine e Caixinhas abertas separados; Pagar, Meus itens e Envios.
# Pagar, Meus itens e Envios são abas do /me/ (P3); o painel mantém ?tab= e o destaque do menu em sincronia.
JOINER_SECTIONS = (
    ('cegs', 'CEGs', 'sparkles'),
    ('vitrine', 'Vitrine', 'store'),
    ('caixinhas', 'Caixinhas', 'package-open'),
    ('pagar', 'Pagar', 'wallet'),
    ('itens', 'Meus itens', 'package'),
    ('envios', 'Envios', 'truck'),
)
# Só aparecem para o joiner logado (sem login, o menu mostra CEGs, Vitrine e Caixinhas).
SECOES_COM_LOGIN = {'pagar', 'itens', 'envios'}


def _active_section(request):
    match = getattr(request, 'resolver_match', None)
    name = match.url_name if match else ''
    if name in ('home', 'ceg_detail'):
        return 'cegs'
    if name and name.startswith('vitrine'):
        return 'vitrine'
    if name == 'caixinhas_abertas':
        return 'caixinhas'
    if name == 'my_claims':
        tab = request.GET.get('tab', '')
        return {'pagar': 'pagar', 'caixinha': 'envios', 'envios': 'envios', 'itens': 'itens',
                'reservas': 'itens'}.get(tab, 'pagar')
    return ''


def _ui_css_version():
    from django.contrib.staticfiles import finders

    path = finders.find('css/ui.css')
    import os
    return int(os.path.getmtime(path)) if path else ''


def frontend(request):
    """Modo dos assets e a navegação principal do joiner (barra lateral e barra de abas)."""
    me = reverse('my_claims')
    urls = {
        'cegs': reverse('home'),
        'vitrine': reverse('vitrine_list'),
        'caixinhas': reverse('caixinhas_abertas'),
        'pagar': f'{me}?tab=pagar',
        'itens': f'{me}?tab=itens',
        'envios': f'{me}?tab=envios',
    }
    active = _active_section(request)
    logado = bool(request.session.get('participant_id')) if hasattr(request, 'session') else False
    return {
        'frontend_build': settings.FRONTEND_MODE == 'build',
        # Desenvolvimento: ?v=<data do arquivo> no ui.css para o navegador não usar cópia antiga.
        # Em produção o ManifestStaticFilesStorage já põe o hash no nome do arquivo.
        'ui_css_version': _ui_css_version() if settings.FRONTEND_MODE != 'build' else '',
        'nav_section': active,
        'nav_repasses': getattr(getattr(request, 'resolver_match', None), 'url_name', '') == 'repasses_disponiveis',
        'nav_goms': getattr(getattr(request, 'resolver_match', None), 'url_name', '') in ('gom_directory', 'gom_public'),
        'joiner_nav': [
            {'key': key, 'label': label, 'icon': icon, 'url': urls[key], 'active': key == active}
            for key, label, icon in JOINER_SECTIONS
            if logado or key not in SECOES_COM_LOGIN
        ],
    }
