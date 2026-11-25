"""
Cor da marca do GOM (C4, docs/GOM_CUSTOMIZATION_PLAN.md): 6 opções prontas, cada uma com tokens claro e escuro
testados para contraste AA (texto branco no botão >= 4.5; texto de destaque na superfície >= 4.5).
Sem seletor livre: cor livre quebra o contraste e o modo escuro.

Aplicada só onde a página é de UM GOM (página pública, CEG, caixa e o painel do GOM) via `brand_gom` no
contexto; base.html inclui components/_brand_style.html, que redefine os tokens de static/css/ui.css.
"""

# chave: (rótulo, claro (accent, accent-text, accent-soft), escuro (accent, accent-text, accent-soft))
BRAND_COLORS = {
    'padrao': ('Padrão ValCegs', ('#C8307A', '#B0246A', '#FCE7F1'), ('#2A62F5', '#8FB2FF', 'rgba(42, 98, 245, 0.16)')),
    'lilas': ('Lilás', ('#6D28D9', '#6D28D9', '#EDE9FE'), ('#7C3AED', '#C4B5FD', 'rgba(124, 58, 237, 0.18)')),
    'azul': ('Azul', ('#1D4ED8', '#1D4ED8', '#DBEAFE'), ('#2563EB', '#93C5FD', 'rgba(37, 99, 235, 0.18)')),
    'verde': ('Verde-água', ('#0F766E', '#0F766E', '#CCFBF1'), ('#0F766E', '#5EEAD4', 'rgba(20, 184, 166, 0.16)')),
    'laranja': ('Laranja', ('#C2410C', '#C2410C', '#FFEDD5'), ('#C2410C', '#FDBA74', 'rgba(249, 115, 22, 0.16)')),
    'vermelho': ('Vermelho', ('#B91C1C', '#B91C1C', '#FEE2E2'), ('#DC2626', '#FCA5A5', 'rgba(239, 68, 68, 0.16)')),
}
DEFAULT = 'padrao'
CHOICES = [(key, value[0]) for key, value in BRAND_COLORS.items()]


def brand_tokens(key):
    """Tokens da cor escolhida, ou None para o padrão da plataforma (não redefine nada)."""
    if not key or key == DEFAULT or key not in BRAND_COLORS:
        return None
    label, light, dark = BRAND_COLORS[key]
    return {'key': key, 'label': label,
            'light': dict(zip(('accent', 'text', 'soft'), light)),
            'dark': dict(zip(('accent', 'text', 'soft'), dark))}


def swatches():
    """Opções para a aba Perfil (bolinha clara e escura)."""
    return [{'key': key, 'label': label, 'light': light[0], 'dark': dark[0], 'light_text': light[1], 'dark_text': dark[1]}
            for key, (label, light, dark) in BRAND_COLORS.items()]
