"""
Respostas prontas (Mensagens da equipe): modelos de texto do GOM com {nome}, {valor} e {gom}.
No primeiro uso o GOM recebe PADRAO gravado (dá para editar ou apagar cada uma; apagar todas deixa a lista vazia).
"""
from decimal import Decimal

from .models import RespostaPronta

PADRAO = (
    ('Pagamento confirmado', 'Oi, {nome}! Seu pagamento foi confirmado. Obrigada!'),
    ('Lembrete de pagamento', 'Oi, {nome}! Passando para lembrar que ficou em aberto {valor} com a {gom}. '
                              'Dá para pagar pelo Pix em Pagar, no site.'),
    ('Caixa chegou', 'Oi, {nome}! A caixa chegou aqui. Já dá para pedir o envio dos seus itens em Envios.'),
    ('Pacote enviado', 'Oi, {nome}! Seu pacote foi enviado. O código de rastreio está em Envios.'),
)


def garantir(gom):
    """As respostas do GOM; no primeiro uso grava o padrão (marcado em Gom.respostas_iniciadas)."""
    if not gom.respostas_iniciadas:
        gom.respostas_iniciadas = True
        gom.save(update_fields=['respostas_iniciadas'])
        RespostaPronta.objects.bulk_create(
            [RespostaPronta(gom=gom, titulo=t, texto=x, ordem=i) for i, (t, x) in enumerate(PADRAO)])
    return list(RespostaPronta.objects.for_gom(gom))


def devendo(participant, gom):
    """Quanto o joiner deve a este GOM (o que está em Pagar + Pix gerados ainda abertos)."""
    from apps.pagamentos.models import Cobranca
    from apps.pagamentos.services import open_units
    total = sum((u['valor'] for u in open_units(participant, gom)), Decimal('0'))
    total += sum((c.valor_total for c in Cobranca.objects.filter(
        gom=gom, participant=participant, status__in=Cobranca.OPEN)), Decimal('0'))
    return total


def _brl(valor):
    inteiro, _, cent = f'{valor:,.2f}'.partition('.')
    return f"R$ {inteiro.replace(',', '.')},{cent}"


def preenchidas(conversa):
    """As respostas do GOM da conversa já com {nome}, {valor} e {gom} trocados."""
    modelos = [(r.titulo, r.texto) for r in garantir(conversa.gom)]
    precisa_valor = any('{valor}' in texto for _t, texto in modelos)
    campos = {
        '{nome}': (conversa.participant.display_name or '').split(' ')[0],
        '{gom}': conversa.gom.name,
        '{valor}': _brl(devendo(conversa.participant, conversa.gom)) if precisa_valor else '',
    }
    saida = []
    for titulo, texto in modelos:
        for chave, valor in campos.items():
            texto = texto.replace(chave, valor)
        saida.append({'titulo': titulo, 'texto': texto})
    return saida
