"""
Reservar na Vitrine (S5b). A situação do item acompanha as reservas: Disponível enquanto sobra unidade,
Reservado quando todas estão reservadas e falta pagamento, Vendido quando todas as unidades foram pagas.
"""
from django.db import transaction
from django.utils import timezone

from . import services
from .models import Conversa, Mensagem, ReservaVitrine


def _brl(valor):
    return f'{valor:.2f}'.replace('.', ',')


class ReservaError(ValueError):
    pass


def disponiveis(item):
    ativas = item.reservas.exclude(status=ReservaVitrine.Status.CANCELADA).count()
    return max(0, item.quantidade - ativas)


def atualizar_status(item):
    from apps.cegs.models import ItemVitrine
    ativas = list(item.reservas.exclude(status=ReservaVitrine.Status.CANCELADA))
    if len(ativas) < item.quantidade:
        novo = ItemVitrine.Status.DISPONIVEL
    elif all(r.status == ReservaVitrine.Status.PAGA for r in ativas):
        novo = ItemVitrine.Status.VENDIDO
    else:
        novo = ItemVitrine.Status.RESERVADO
    if item.status != novo:
        item.status = novo
        item.save(update_fields=['status', 'updated_at'])


@transaction.atomic
def reservar(item, participant):
    from apps.cegs.models import ItemVitrine
    item = ItemVitrine.objects.select_for_update().get(pk=item.pk)
    if disponiveis(item) <= 0:
        raise ReservaError('Este item acabou de ser reservado por outra pessoa.')
    reserva = ReservaVitrine.objects.create(item=item, participant=participant, preco=item.preco)
    atualizar_status(item)
    conversa = services.abrir(participant, item.gom, Conversa.Tipo.VITRINE, item)
    services.enviar(conversa, Mensagem.Autor.SISTEMA,
                    f'{participant.display_name} reservou "{item.titulo}" por R$ {_brl(item.preco)}. '
                    f'O pagamento é pelo Pix em Pagar.')
    return reserva, conversa


def _resolver(reserva, status, aviso):
    reserva.status = status
    reserva.resolvida_em = timezone.now()
    reserva.save(update_fields=['status', 'resolvida_em'])
    atualizar_status(reserva.item)
    conversa = services.abrir(reserva.participant, reserva.item.gom, Conversa.Tipo.VITRINE, reserva.item)
    services.enviar(conversa, Mensagem.Autor.SISTEMA, aviso)


def cancelar(reserva, por='gom'):
    if reserva.status != ReservaVitrine.Status.RESERVADA:
        raise ReservaError('Esta reserva já foi resolvida.')
    quem = reserva.item.gom.name if por == 'gom' else reserva.participant.display_name
    _resolver(reserva, ReservaVitrine.Status.CANCELADA, f'{quem} cancelou a reserva de "{reserva.item.titulo}".')


def marcar_paga(reserva):
    """GOM recebeu (Pix confirmado ou em mãos)."""
    if reserva.status != ReservaVitrine.Status.RESERVADA:
        raise ReservaError('Esta reserva já foi resolvida.')
    _resolver(reserva, ReservaVitrine.Status.PAGA, f'Pagamento de "{reserva.item.titulo}" confirmado. Obrigado!')
