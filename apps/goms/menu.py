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
    ('pagamentos', 'Pagamentos', 'qr-code', 'pix_fila', ('pag.confirmar',), ('pix_fila', 'pix_cobrar')),
    ('mensagens', 'Mensagens', 'message-square', 'gom_mensagens', ('mensagens.responder',), ('gom_mensagens',)),
    ('caixas', 'Caixas', 'plane', 'caixas_dashboard', ('caixas.editar', 'caixas.valores', 'caixas.etapa'),
     ('caixas_dashboard', 'caixa_create', 'caixa_update', 'caixa_transfer_unclaimed_vitrine')),
    ('envios', 'Envios', 'truck', 'envios_nacionais', ('envios.pacotes', 'gom.envio'), ('envios_nacionais',)),
    ('joiners', 'Joiners', 'users', 'consulta_joiner', ('pedidos.ver',), ('consulta_joiner',)),
    ('repasses', 'Repasses', 'arrow-left-right', 'gom_repasses', ('pedidos.editar',), ('gom_repasses',)),
    ('relatorios', 'Relatórios', 'chart-column', 'sales_report', ('analytics.ver',), ('sales_report', 'sales_report_alias', 'analytics_dashboard', 'lucro_cegs')),
    ('avisos', 'Avisos', 'bell', 'gom_notifications', (ANY,), ('gom_notifications',)),
    ('auditoria', 'Auditoria', 'shield', 'auditoria_logs', ('analytics.ver',), ('auditoria_logs', 'auditoria_logs_alias')),
    ('equipe', 'Equipe', 'user-cog', 'gom_team', (ANY,), ('gom_team',)),
    ('config', 'Configurações', 'settings', 'gom_settings', ('gom.perfil', 'pix.alterar', 'gom.regras', 'ceg.padroes', 'gom.envio'), ('gom_settings', 'gom_settings_tab')),
]

PLATFORM_MENU = [
    ('goms', 'Gerenciar GOMs', 'building-2', 'platform_goms', ('platform_goms',)),
    ('catalogo', 'Catálogo', 'library', 'platform_catalogo', ('platform_catalogo', 'platform_catalogo_grupo')),
    ('whatsapp', 'Bot do WhatsApp', 'message-circle', 'admin_whatsapp', ('admin_whatsapp',)),
]


# Grupos da barra lateral (sanfona): (chave, rótulo, ícone, chaves dos itens). Itens fora daqui ficam sempre à vista.
GRUPOS = [
    ('vendas', 'Vendas', 'shopping-bag', ('cegs', 'criar', 'pagamentos', 'mensagens', 'joiners', 'repasses')),
    ('logistica', 'Logística', 'package', ('caixas', 'envios')),
    ('gestao', 'Gestão', 'briefcase', ('relatorios', 'avisos', 'auditoria', 'equipe', 'config')),
]


def agrupar(menu):
    """O menu já filtrado em blocos para a sanfona: {'grupo': None, 'itens': [item]} (sempre à vista) ou
    {'grupo': chave, 'label', 'icon', 'itens', 'active'}. Grupo com um item só vira item solto."""
    por_chave = {item['key']: item for item in menu}
    agrupados = {k for _, _, _, chaves in GRUPOS for k in chaves}
    blocos = [{'grupo': None, 'itens': [i for i in menu if i['key'] not in agrupados]}]
    for chave, label, icon, chaves in GRUPOS:
        itens = [por_chave[k] for k in chaves if k in por_chave]
        if len(itens) == 1:
            blocos.append({'grupo': None, 'itens': itens})
        elif itens:
            blocos.append({'grupo': chave, 'label': label, 'icon': icon, 'itens': itens,
                           'active': any(i['active'] for i in itens), 'chaves': [i['key'] for i in itens],
                           'badge': sum(i['badge'] for i in itens)})
    return [b for b in blocos if b['itens']]


def build_gom_menu(request, granted, unread=0):
    """Itens visíveis para quem está logado, com o ativo marcado. `granted`: gom_permissions(request)."""
    match = getattr(request, 'resolver_match', None)
    current = match.url_name if match else ''
    items = []
    for key, label, icon, url_name, perms, active_names in GOM_MENU:
        if not granted or not any(p == ANY or p in granted for p in perms):
            continue
        badge = unread if key == 'avisos' else (_repasses_pendentes(request) if key == 'repasses' else 0)
        items.append({'key': key, 'label': label, 'icon': icon, 'url': reverse(url_name),
                      'active': current in active_names, 'badge': badge})
    return items


def _repasses_pendentes(request):
    gom = getattr(request, 'active_gom', None)
    if gom is None:
        return 0
    from apps.repasses.models import Repasse
    return Repasse.objects.for_gom(gom).filter(status=Repasse.Status.AGUARDANDO_GOM).count()


def build_platform_menu(request):
    from apps.auth_otp.status import estado_do_bot

    match = getattr(request, 'resolver_match', None)
    current = match.url_name if match else ''
    bot = estado_do_bot()  # cache de 60 s; None fora da Evolution
    return [{'key': k, 'label': label, 'icon': icon, 'url': reverse(url_name), 'active': current in active,
             'alerta': k == 'whatsapp' and bot is not None and not bot['conectado']}
            for k, label, icon, url_name, active in PLATFORM_MENU]
