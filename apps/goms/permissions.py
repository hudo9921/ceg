"""
Permissões por admin de GOM (docs/MULTI_GOM_DESIGN.md §3.1). Catálogo único.

- Dono do GOM e administrador da plataforma têm tudo.
- Admin com `GomMembership.permissions = None` tem tudo (admins anteriores a esta função).
- Admin com lista salva tem só o que está na lista. Equipe continua só do dono.

Views de backoffice declaram `gom_permission` (ver apps.core.permissions.StaffRequiredMixin);
um teste falha se alguma view de staff não declarar.
"""

# Qualquer membro da equipe (ex.: notificações do GOM).
ANY = '*'

# (chave, área, rótulo, ajuda, sensível)
CATALOG = [
    ('ceg.editar', 'CEGs', 'Criar e editar CEGs', 'Itens, sets, preços, fotos, recortes, enquetes, grupos e eras', False),
    ('ceg.excluir', 'CEGs', 'Excluir CEGs e sets', 'Apaga a CEG ou o set inteiro', False),
    ('ceg.espera', 'CEGs', 'Ver disputas e lista de espera', 'Tentativas no segundo zero e fila por item', False),
    ('pedidos.ver', 'Pedidos e pagamentos', 'Ver pedidos e joiners', 'Consulta Joiner 360º e busca de participantes', False),
    ('pag.confirmar', 'Pedidos e pagamentos', 'Marcar pagamentos como recebidos', 'Item, frete e taxa', False),
    ('pedidos.editar', 'Pedidos e pagamentos', 'Editar pedidos', 'Trocar dono de item, liberar vaga, alocar em massa e itens avulsos', False),
    ('caixas.editar', 'Caixas', 'Criar e editar caixas', 'Juntar CEGs e itens numa remessa', False),
    ('caixas.valores', 'Caixas', 'Definir frete e taxa', 'O valor que cada joiner paga', False),
    ('caixas.etapa', 'Caixas', 'Mudar a etapa da caixa', 'Embalada, enviada, no Brasil…', False),
    ('envios.pacotes', 'Envios nacionais', 'Montar pacotes e marcar envios', 'Pacotes, rastreio e entregas', False),
    ('vitrine.editar', 'Vitrine', 'Adicionar e editar itens', 'Fotos, preço e destaque', False),
    ('vitrine.reservar', 'Vitrine', 'Marcar reservado ou vendido', '', False),
    ('analytics.ver', 'Relatórios', 'Ver faturamento, relatórios e auditoria', 'Status das CEGs, vendas e logs', False),
    ('gom.perfil', 'GOM', 'Editar perfil do GOM', 'Nome, logo, banner e contatos', False),
    ('pix.alterar', 'GOM', 'Alterar chaves Pix', 'Do GOM, das CEGs e das caixas: para onde vai o dinheiro', True),
    ('gom.envio', 'GOM', 'Configuração de envio', 'Regras e prazos dos envios nacionais', False),
]

ALL = frozenset(key for key, *_ in CATALOG)
SENSITIVE = frozenset(key for key, *rest in CATALOG if rest[-1])
LABELS = {key: label for key, _area, label, *_ in CATALOG}

PRESETS = {
    'completo': ('Ajudante completo', 'Tudo, menos as chaves Pix.', sorted(ALL - SENSITIVE)),
    'logistica': ('Só logística', 'Caixas, pacotes e consulta de pedidos.',
                  ['pedidos.ver', 'caixas.editar', 'caixas.etapa', 'envios.pacotes']),
    'pagamentos': ('Só pagamentos', 'Consulta e confirma pagamentos.',
                   ['pedidos.ver', 'pag.confirmar', 'pedidos.editar', 'analytics.ver']),
    'criacao': ('Só criação', 'Cria CEGs e itens da vitrine.',
                ['ceg.editar', 'ceg.espera', 'vitrine.editar', 'vitrine.reservar']),
}
DEFAULT_PRESET = 'completo'

# Itens do menu de gestão e as permissões que os mostram (prévia na tela de equipe e sidebar).
MENU = [
    ('Hub de Criações', ['ceg.editar']),
    ('Status das CEGs', ['analytics.ver']),
    ('Caixas', ['caixas.editar', 'caixas.valores', 'caixas.etapa']),
    ('Consulta Joiner', ['pedidos.ver']),
    ('Envios Nacionais', ['envios.pacotes', 'gom.envio']),
    ('Auditoria', ['analytics.ver']),
    ('Relatório de Vendas', ['analytics.ver']),
    ('Perfil do GOM', ['gom.perfil', 'pix.alterar']),
]


def clean(keys):
    """Lista ordenada só com chaves conhecidas."""
    return sorted(set(keys or []) & ALL)


def preset_of(keys):
    """Chave do modelo que bate exatamente com a lista, ou None (personalizado)."""
    keys = set(keys)
    return next((k for k, (_n, _h, perms) in PRESETS.items() if set(perms) == keys), None)


def areas():
    """Catálogo agrupado por área, na ordem do CATALOG (para a tela de equipe)."""
    grouped = {}
    for key, area, label, help_text, sensitive in CATALOG:
        grouped.setdefault(area, []).append(
            {'key': key, 'label': label, 'help': help_text, 'sensitive': sensitive})
    return [{'name': name, 'perms': perms} for name, perms in grouped.items()]


def membership_permissions(membership):
    """Conjunto efetivo de um vínculo."""
    if membership is None or not membership.is_active:
        return frozenset()
    if membership.is_owner or membership.permissions is None:
        return ALL
    return frozenset(membership.permissions) & ALL


def summary(membership):
    """Texto curto da tela de equipe: 'Só logística · 4 de 16'."""
    if membership.is_owner:
        return 'Dono · acesso total'
    perms = membership_permissions(membership)
    name = PRESETS[preset_of(perms)][0] if preset_of(perms) else 'Personalizado'
    if perms == ALL:
        name = 'Acesso completo'
    return f'{name} · {len(perms)} de {len(ALL)}'
