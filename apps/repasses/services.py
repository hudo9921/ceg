"""
Regras do repasse (apps/repasses/models.py). Toda mudança de dono passa por `aprovar`, chamada só pela equipe do GOM.
"""
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Repasse


class RepasseError(Exception):
    pass


def descricao(slot):
    item = slot.item_definition
    nome = item.name + (f' · {item.member_name}' if getattr(item, 'member_name', '') else '')
    return f'{nome} — {slot.set.ceg.title}'


def pendencias(slot):
    """O que ainda falta pagar e vai junto com a vaga."""
    faltam = []
    if not slot.is_item_paid:
        faltam.append(('Item', slot.price))
    if slot.frete_inter and not slot.is_frete_inter_paid:
        faltam.append(('Frete internacional', slot.frete_inter))
    if slot.taxa_aduaneira and not slot.is_taxa_aduaneira_paid:
        faltam.append(('Taxa', slot.taxa_aduaneira))
    return faltam


def checar_vaga(slot, dono, ignorar=None):
    """Levanta RepasseError se a vaga não pode ser repassada agora (por `dono`)."""
    from apps.pagamentos.models import Cobranca, CobrancaLinha

    claim = getattr(slot, 'claim', None)
    if claim is None or claim.participant_id != dono.pk or claim.status == claim.Status.CANCELLED \
            or slot.claimed_by_id != dono.pk:
        raise RepasseError('Esta vaga não é sua.')
    if slot.pacote_nacional_id:
        raise RepasseError('A vaga já está num pacote de envio nacional.')
    if CobrancaLinha.objects.filter(slot=slot, cobranca__status__in=Cobranca.OPEN).exists():
        raise RepasseError('Há um Pix em aberto com esta vaga. Pague ou cancele o Pix antes de repassar.')
    if Repasse.objects.filter(slot=slot, status__in=Repasse.ATIVOS).exclude(pk=ignorar).exists():
        raise RepasseError('Esta vaga já tem um repasse em andamento.')


def _notificar_joiner(participante, titulo, mensagem):
    from apps.participants.models import ParticipantNotification
    if participante:
        ParticipantNotification.objects.create(participant=participante, title=titulo, message=mensagem, categoria='repasses',
                                               notification_type=ParticipantNotification.NotificationType.CLAIM_UPDATE)


def _notificar_gom(rep):
    from apps.cegs.models import GOMNotification
    GOMNotification.objects.create(
        gom=rep.gom, notification_type=GOMNotification.NotificationType.REPASSE, participant=rep.de,
        ceg=rep.slot.set.ceg, slot=rep.slot, title='Repasse para aprovar',
        message=f'{rep.de.display_name} quer repassar {descricao(rep.slot)} para {rep.para.display_name}.',
        action_url=reverse('gom_repasses'), action_label='Ver repasses')


def criar(dono, slot, whatsapp='', publico=False, recado=''):
    """A pede o repasse: para um número (B aceita depois) ou público (quem quiser pede)."""
    from apps.participants.models import Participant, clean_phone_number

    with transaction.atomic():
        slot = type(slot).objects.select_for_update().select_related('set__ceg').get(pk=slot.pk)
        checar_vaga(slot, dono)
        rep = Repasse(gom_id=slot.set.ceg.gom_id, slot=slot, de=dono, recado=(recado or '').strip()[:280])
        if publico:
            rep.publico, rep.status = True, Repasse.Status.DISPONIVEL
        else:
            numero = clean_phone_number(whatsapp or '')
            if len(numero) < 10:
                raise RepasseError('Digite o WhatsApp de quem vai receber, com DDD.')
            if numero == dono.whatsapp:
                raise RepasseError('Esse número é o seu.')
            rep.para_whatsapp = numero
            rep.para = Participant.objects.filter(whatsapp=numero).first()
            rep.status = Repasse.Status.AGUARDANDO_ACEITE
        rep.save()
    if rep.para:
        _notificar_joiner(rep.para, 'Querem repassar um item para você',
                          f'{dono.display_name} quer repassar {descricao(slot)} para você. Aceite ou recuse em Meus itens.')
    return rep


def recebidos(participante):
    """Pedidos para `participante` aceitar (inclui os feitos para o número dele antes de ter conta)."""
    from django.db.models import Q
    return (Repasse.objects.filter(status=Repasse.Status.AGUARDANDO_ACEITE)
            .filter(Q(para=participante) | Q(para__isnull=True, para_whatsapp=participante.whatsapp))
            .select_related('de', 'slot__set__ceg__gom', 'slot__item_definition'))


def responder(rep, participante, aceitar):
    """B aceita (vai para o GOM) ou recusa."""
    with transaction.atomic():
        rep = Repasse.objects.select_for_update().get(pk=rep.pk)
        eh_destino = rep.para_id == participante.pk or (rep.para_id is None and rep.para_whatsapp == participante.whatsapp)
        if rep.status != Repasse.Status.AGUARDANDO_ACEITE or not eh_destino:
            raise RepasseError('Este pedido não está mais esperando sua resposta.')
        rep.para = participante
        if aceitar:
            rep.status, rep.aceito_em = Repasse.Status.AGUARDANDO_GOM, timezone.now()
        else:
            rep.status, rep.resolvido_em = Repasse.Status.RECUSADO_PESSOA, timezone.now()
        rep.save()
    if aceitar:
        _notificar_gom(rep)
    else:
        _notificar_joiner(rep.de, 'Repasse recusado', f'{participante.display_name} recusou {descricao(rep.slot)}.')
    return rep


def pedir_publico(rep, participante):
    """Alguém pede uma vaga disponível para repasse: o pedido já é o aceite; vai para o GOM."""
    with transaction.atomic():
        rep = Repasse.objects.select_for_update().get(pk=rep.pk)
        if rep.status != Repasse.Status.DISPONIVEL:
            raise RepasseError('Alguém já pediu esta vaga. Ela volta a ficar disponível se o GOM recusar.')
        if rep.de_id == participante.pk:
            raise RepasseError('Esta vaga já é sua.')
        rep.para, rep.status, rep.aceito_em = participante, Repasse.Status.AGUARDANDO_GOM, timezone.now()
        rep.save()
    _notificar_gom(rep)
    _notificar_joiner(rep.de, 'Pediram sua vaga',
                      f'{participante.display_name} pediu {descricao(rep.slot)}. Agora o GOM decide.')
    return rep


def cancelar(rep, participante):
    with transaction.atomic():
        rep = Repasse.objects.select_for_update().get(pk=rep.pk)
        if rep.de_id != participante.pk or not rep.ativo:
            raise RepasseError('Este repasse não pode mais ser cancelado.')
        rep.status, rep.resolvido_em = Repasse.Status.CANCELADO, timezone.now()
        rep.save()
    if rep.para:
        _notificar_joiner(rep.para, 'Repasse cancelado', f'{rep.de.display_name} desistiu de repassar {descricao(rep.slot)}.')
    return rep


def aprovar(rep, usuario):
    """O GOM aprova: a vaga (com o que falta pagar) passa para quem recebe."""
    from apps.cegs.audit_service import AuditService
    from apps.cegs.models import AuditLog, ItemSlot

    with transaction.atomic():
        rep = Repasse.objects.select_for_update().select_related('de', 'para').get(pk=rep.pk)
        if rep.status != Repasse.Status.AGUARDANDO_GOM or rep.para is None:
            raise RepasseError('Este repasse não está esperando aprovação.')
        slot = ItemSlot.objects.select_for_update().select_related('set__ceg').get(pk=rep.slot_id)
        checar_vaga(slot, rep.de, ignorar=rep.pk)
        claim = slot.claim
        claim.participant = rep.para
        claim.save(update_fields=['participant'])
        slot.claimed_by = rep.para
        slot.save(update_fields=['claimed_by'])
        rep.status, rep.resolvido_em, rep.resolvido_por = Repasse.Status.APROVADO, timezone.now(), usuario
        rep.save()
        rep.para.known_by_goms.add(rep.gom_id)
        AuditService.log_event(AuditLog.EventType.SLOT_ASSIGNED, f'Repasse aprovado: de {rep.de.display_name} '
                               f'para {rep.para.display_name}', actor=usuario, participant=rep.para, slot=slot,
                               old_value=rep.de.whatsapp, new_value=rep.para.whatsapp, metadata={'repasse': rep.pk})
    _notificar_joiner(rep.de, 'Repasse aprovado', f'{descricao(slot)} agora é de {rep.para.display_name}.')
    _notificar_joiner(rep.para, 'Item recebido por repasse',
                      f'{descricao(slot)} agora é seu.' + (' Confira o que falta pagar em Meus itens.' if pendencias(slot) else ''))
    return rep


def recusar(rep, usuario, motivo=''):
    """O GOM recusa. Repasse público volta a ficar disponível para outra pessoa."""
    with transaction.atomic():
        rep = Repasse.objects.select_for_update().select_related('de', 'para').get(pk=rep.pk)
        if rep.status != Repasse.Status.AGUARDANDO_GOM:
            raise RepasseError('Este repasse não está esperando aprovação.')
        quem = rep.para
        motivo = (motivo or '').strip()[:280]
        if rep.publico:
            rep.para, rep.status, rep.aceito_em = None, Repasse.Status.DISPONIVEL, None
        else:
            rep.status, rep.resolvido_em, rep.resolvido_por, rep.motivo = (Repasse.Status.RECUSADO_GOM, timezone.now(),
                                                                         usuario, motivo)
        rep.save()
    texto = f'O GOM recusou o repasse de {descricao(rep.slot)}.' + (f' Motivo: {motivo}' if motivo else '')
    _notificar_joiner(quem, 'Repasse recusado', texto)
    _notificar_joiner(rep.de, 'Repasse recusado',
                      texto + (' A vaga continua disponível para outra pessoa.' if rep.publico else ''))
    return rep
