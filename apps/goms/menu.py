"""
Menu do painel do GOM (P5): uma lista só, filtrada pelas permissões de quem está logado
(apps.goms.permissions). Usado pela barra lateral (components/_sidebar_gom_menu.html).
"""
from django.urls import reverse

from .permissions import ANY

# (chave, rótulo, ícone lucide, url_name, permissões (qualquer uma), url_names que marcam o item como ativo)
GOM_MENU = [
    ('inicio', 'Início', 'layout-dashboard', 'backoffice_home', (ANY,), ('backoffice_home',)),
    ('cegs', 'CEGs', 'sparkles', 'cegs_status', ('ceg.editar', 'analytics.ver', 'pag.confirmar'), ('cegs_status', 'cegs_status_tab')),
    ('criar', 'Criar', 'circle-plus', 'creations_hub', ('ceg.editar',), ('creations_hub', 'ceg_bulk_allocator', 'bulk_joiner_allocator_global', 'creations_bulk_participant')),
    ('caixas', 'Caixas', 'plane', 'caixas_dashboard', ('caixas.editar', 'caixas.valores', 'caixas.etapa'),
     ('caixas_dashboard', 'caixa_create', 'caixa_update', 'caixa_transfer_unclaimed_vitrine')),
    ('envios', 'Envios', 'truck', 'envios_nacionais', ('envios.pacotes', 'gom.envio'), ('envios_nacionais',)),
    ('joiners', 'Joiners', 'users', 'consulta_joiner', ('pedidos.ver',), ('consulta_joiner',)),
    ('relatorios', 'Relatórios', 'chart-column', 'sales_report', ('analytics.ver',), ('sales_report', 'sales_report_alias', 'analytics_dashboard')),
    ('avisos', 'Avisos', 'bell', 'gom_notifications', (ANY,), ('gom_notifications',)),
    ('auditoria', 'Auditoria', 'shield', 'auditoria_logs', ('analytics.ver',), ('auditoria_logs', 'auditoria_logs_alias')),
    ('equipe', 'Equipe', 'user-cog', 'gom_team', (ANY,), ('gom_team',)),
    ('config', 'Configurações', 'settings', 'gom_settings', ('gom.perfil', 'pix.alterar', 'gom.envio'), ('gom_settings', 'gom_settings_tab')),
]

PLATFORM_MENU = [
    ('goms', 'GOMs da plataforma', 'building-2', 'platform_goms', ('platform_goms',)),
    ('whatsapp', 'Bot do WhatsApp', 'message-circle', 'admin_whatsapp', ('admin_whatsapp',)),
]


def build_gom_menu(request, granted, unread=0):
    """Itens visíveis para quem está logado, com o ativo marcado. `granted`: gom_permissions(request)."""
    match = getattr(request, 'resolver_match', None)
    current = match.url_name if match else ''
    items = []
    for key, label, icon, url_name, perms, active_names in GOM_MENU:
        if not granted or not any(p == ANY or p in granted for p in perms):
            continue
        items.append({'key': key, 'label': label, 'icon': icon, 'url': reverse(url_name),
                      'active': current in active_names, 'badge': unread if key == 'avisos' else 0})
    return items


def build_platform_menu(request):
    match = getattr(request, 'resolver_match', None)
    current = match.url_name if match else ''
    return [{'key': k, 'label': label, 'icon': icon, 'url': reverse(url_name), 'active': current in active}
            for k, label, icon, url_name, active in PLATFORM_MENU]
