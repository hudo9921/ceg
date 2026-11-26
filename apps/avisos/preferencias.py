"""
O que cada um quer receber no celular (push). A central de avisos do site recebe tudo sempre; isto só filtra o push.

Joiner: 4 grupos, todos ligados por padrão. "Importante" (set cancelado, Pix não recebido, pedido de exclusão de
dados) não pode ser desligado: mexe com o dinheiro ou o item do joiner.
Equipe do GOM: cada tipo de aviso só vai para quem tem a permissão daquela área (ex.: Pix avisado só para quem
confirma pagamentos) e, por cima disso, cada um pode desligar o que não quer.
"""
JOINER = [
    ('pagamentos', 'Pagamentos', 'Pix confirmado, frete e taxa lançados'),
    ('envios', 'Caixas e envios', 'Cada etapa da caixa, pacote enviado e entregue'),
    ('mensagens', 'Mensagens do GOM', 'Respostas nas conversas'),
    ('repasses', 'Repasses', 'Pedidos de repasse e quando o GOM aprova ou recusa'),
]
IMPORTANTE = 'importante'
TEXTO_IMPORTANTE = 'Set cancelado e Pix não recebido sempre chegam: mexem com o seu dinheiro ou o seu item.'

# Equipe: categoria → (rótulo, descrição, permissão necessária).
GOM = [
    ('pix', 'Pix avisado', 'Joiner avisou que pagou', 'pag.confirmar'),
    ('envios', 'Pedidos de envio', 'Joiner pediu o envio nacional', 'envios.pacotes'),
    ('repasses', 'Repasses', 'Repasse esperando aprovação', 'pedidos.editar'),
    ('mensagens', 'Mensagens', 'Mensagem nova de joiner', 'mensagens.responder'),
]
PERMISSAO_GOM = {chave: perm for chave, _r, _d, perm in GOM}
# Tipo da GOMNotification → categoria (SYSTEM de conversa vem marcado em metadata['categoria']).
TIPO_GOM = {'PAYMENT': 'pix', 'PACKAGE_REQUEST': 'envios', 'REPASSE': 'repasses'}
# Tipo da ParticipantNotification → categoria quando o aviso não diz.
TIPO_JOINER = {'SET_CANCELLED': IMPORTANTE, 'ENVIO_NACIONAL': 'envios'}


def categoria_joiner(notificacao):
    return notificacao.categoria or TIPO_JOINER.get(notificacao.notification_type, IMPORTANTE)


def categoria_gom(notificacao):
    return (notificacao.metadata or {}).get('categoria') or TIPO_GOM.get(notificacao.notification_type, '')


def desligados(participant=None, user=None):
    from .models import Preferencia
    p = Preferencia.objects.filter(participant=participant).first() if participant else \
        Preferencia.objects.filter(user=user).first() if user else None
    return set(p.desligados) if p else set()


def salvar(desligar, participant=None, user=None):
    """Guarda as categorias desligadas (só as que existem; 'importante' nunca)."""
    from .models import Preferencia
    validas = {c for c, *_ in (JOINER if participant else GOM)}
    lista = sorted(set(desligar) & validas)
    Preferencia.objects.update_or_create(participant=participant, user=user, defaults={'desligados': lista})
    return lista
