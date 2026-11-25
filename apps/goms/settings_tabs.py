"""
Configurações do GOM (docs/GOM_CUSTOMIZATION_PLAN.md, C0): uma tela com abas, cada aba com a sua permissão
(apps.goms.permissions). Novas abas entram em TABS e ganham um handler em apps/goms/settings_views.py.
"""
from django.urls import reverse

# (slug, rótulo, ícone lucide, permissão, resumo)
TABS = [
    ('perfil', 'Perfil', 'store', 'gom.perfil', 'Nome, logo, banner, bio e contatos da sua página.'),
    ('pix', 'Pix', 'qr-code', 'pix.alterar', 'Chaves Pix usadas quando a CEG ou a caixa não tem chave própria.'),
    ('envio', 'Envio', 'truck', 'gom.envio', 'Formulário de endereço e instruções do envio nacional.'),
]
PERMISSIONS = tuple(perm for _slug, _label, _icon, perm, _help in TABS)


def visible_tabs(request, current=None):
    """Abas que a pessoa pode abrir, com a atual marcada."""
    from .access import has_gom_perm

    return [{'slug': slug, 'label': label, 'icon': icon, 'help': help_text, 'active': slug == current,
             'url': reverse('gom_settings_tab', args=[slug])}
            for slug, label, icon, perm, help_text in TABS if has_gom_perm(request, perm)]


def tab_permission(slug):
    return next((perm for s, _l, _i, perm, _h in TABS if s == slug), None)
