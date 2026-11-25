"""
Padrões de CEG do GOM (C2, docs/GOM_CUSTOMIZATION_PLAN.md): só pré-preenchem o Criar.
O prazo do item em dias vira data no salvamento, a partir do fechamento informado.
"""
from datetime import datetime, timedelta

from django.utils import timezone


def render_description(text, era):
    """Troca {grupo} e {era} pelos nomes escolhidos."""
    if not text or era is None:
        return text or ''
    return text.replace('{grupo}', era.group.name).replace('{era}', era.name)


def default_prazo_item(gom, closes_at):
    """Prazo do item = fechamento + N dias (padrão do GOM), ou None."""
    if gom is None or not gom.padrao_prazo_item_dias or not closes_at:
        return None
    return closes_at + timedelta(days=gom.padrao_prazo_item_dias)


def newest_open_caixa(gom):
    from apps.cegs.models import Caixa

    return (Caixa.objects.for_gom(gom).filter(status=Caixa.Status.EM_CONSOLIDACAO)
            .order_by('-created_at').first())


def creations_defaults(gom):
    """Valores iniciais do formulário Nova CEG."""
    opens_at = ''
    if gom.padrao_horario_abertura:
        tomorrow = timezone.localdate() + timedelta(days=1)
        opens_at = datetime.combine(tomorrow, gom.padrao_horario_abertura).strftime('%Y-%m-%dT%H:%M')
    caixa = newest_open_caixa(gom) if gom.padrao_caixa_aberta else None
    return {
        'opens_at': opens_at,
        'descricao': gom.padrao_descricao,
        'caixa_id': caixa.id if caixa else None,
        'prazo_dias': gom.padrao_prazo_item_dias,
    }
