"""
Direitos do titular (LGPD) e auditoria de acesso a dados pessoais.

- export_participant_data: tudo que guardamos sobre o joiner (download em JSON no /me/).
- request_deletion: o joiner pede a exclusão; a GOM recebe uma notificação.
- open_obligations / anonymize_participant: a GOM anonimiza a conta quando não há
  reservas, itens ou pacotes em andamento. Registros financeiros (claims, valores)
  são mantidos sem identificação pessoal.
- log_pii_access: registra no AuditLog quando o staff visualiza dados pessoais
  sensíveis (ex.: endereço de entrega).
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

ANONYMIZED_NAME = 'Participante removido'


def _audit(event_type, action_label, participant=None, actor=None, metadata=None, **extra):
    from apps.cegs.audit_service import AuditService
    return AuditService.log_event(
        event_type=event_type, action_label=action_label, actor=actor,
        participant=participant, metadata=metadata or {}, **extra,
    )


def log_pii_access(request, participant, reason: str, pacote=None):
    """Registra que um usuário staff visualizou dados pessoais sensíveis de um joiner."""
    from apps.cegs.models import AuditLog
    return _audit(
        AuditLog.EventType.PII_ACCESS, f"Acesso a dados pessoais: {reason}",
        participant=participant, actor=getattr(request, 'user', None), pacote_nacional=pacote,
        metadata={'path': getattr(request, 'path', ''), 'reason': reason},
    )


def _iso(dt):
    return dt.isoformat() if dt else None


def export_participant_data(participant) -> dict:
    """Retorna um dicionário serializável com todos os dados pessoais do joiner."""
    claims = participant.claims.select_related(
        'slot__set__ceg', 'slot__item_definition'
    ).order_by('claimed_at')
    pacotes = participant.pacotes_nacionais.order_by('created_at')
    itens = participant.itens_individuais.order_by('created_at')
    votos = participant.ceg_interest_votes.select_related('ceg', 'item_definition').order_by('created_at')

    return {
        'gerado_em': _iso(timezone.now()),
        'perfil': {
            'nome': participant.name,
            'apelido': participant.username,
            'whatsapp': participant.whatsapp,
            'rede_social': participant.social_handle,
            'cadastrado_em': _iso(participant.created_at),
        },
        'reservas': [{
            'ceg': c.slot.set.ceg.title if c.slot_id else None,
            'item': c.slot.item_definition.name if c.slot_id else None,
            'set': c.slot.set.set_number if c.slot_id else None,
            'valor': str(c.total_price),
            'status': c.get_status_display(),
            'reservado_em': _iso(c.claimed_at),
            'pago_em': _iso(c.paid_at),
            'observacoes': c.participant_notes,
        } for c in claims],
        'compras_avulsas': [{
            'item': i.nome,
            'valor': str(i.preco_produto) if i.preco_produto is not None else None,
            'status': i.get_status_display(),
            'criado_em': _iso(i.created_at),
        } for i in itens],
        'pacotes_nacionais': [{
            'identificador': p.identificador,
            'status': p.get_status_display(),
            'endereco': p.endereco_destinatario,
            'cep': p.cep_destinatario,
            'codigo_rastreio': p.codigo_rastreio,
            'solicitado_em': _iso(p.solicitado_em),
            'enviado_em': _iso(p.data_envio),
            'entregue_em': _iso(p.data_entrega),
        } for p in pacotes],
        'votos_em_enquetes': [{
            'ceg': v.ceg.title,
            'item': v.item_definition.name,
            'votado_em': _iso(v.created_at),
        } for v in votos],
        'notificacoes': [{
            'titulo': n.title,
            'mensagem': n.message,
            'criada_em': _iso(n.created_at),
        } for n in participant.notifications.order_by('created_at')],
    }


def open_obligations(participant) -> list[str]:
    """Motivos que impedem anonimizar agora (itens/pacotes/pagamentos em andamento)."""
    from apps.cegs.models import PacoteNacional
    from apps.participants.models import Claim

    reasons = []
    active_claims = [
        c for c in participant.claims.exclude(status=Claim.Status.CANCELLED)
        if c.lifecycle.get('code') != 'DELIVERED'
    ]
    if active_claims:
        reasons.append(f"{len(active_claims)} reserva(s) ainda não entregue(s) ou não paga(s)")
    itens = participant.itens_individuais.exclude(pacote_nacional__status=PacoteNacional.Status.ENTREGUE)
    if itens.exists():
        reasons.append(f"{itens.count()} compra(s) avulsa(s) ainda em andamento")
    pacotes = participant.pacotes_nacionais.exclude(status=PacoteNacional.Status.ENTREGUE)
    if pacotes.exists():
        reasons.append(f"{pacotes.count()} pacote(s) nacional(is) ainda não entregue(s)")
    return reasons


def request_deletion(participant) -> bool:
    """Joiner solicita exclusão. Retorna False se já houver pedido nos últimos 7 dias."""
    from apps.cegs.models import AuditLog, GOMNotification
    from apps.participants.models import ParticipantNotification

    recent = AuditLog.objects.filter(
        participant=participant, event_type=AuditLog.EventType.DATA_DELETION_REQUEST,
        created_at__gte=timezone.now() - timedelta(days=7),
    ).exists()
    if recent:
        return False

    obligations = open_obligations(participant)
    log = _audit(
        AuditLog.EventType.DATA_DELETION_REQUEST, "Joiner solicitou exclusão da conta (LGPD)",
        participant=participant, metadata={'pendencias': obligations},
    )
    pendencias = ("Pendências: " + "; ".join(obligations) + ".") if obligations else "Sem pendências abertas."
    GOMNotification.objects.create(
        notification_type=GOMNotification.NotificationType.SYSTEM,
        title=f"Pedido de exclusão de dados (LGPD): {participant.display_name}",
        message=(f"{participant.display_name} pediu a exclusão da conta. {pendencias} "
                 "Após concluir as pendências, use a ação 'Anonimizar (LGPD)' no admin de Participantes."),
        participant=participant, audit_log=log,
        action_url=f"/admin/participants/participant/{participant.id}/change/",
        action_label="Abrir no Admin",
    )
    ParticipantNotification.objects.create(
        participant=participant,
        title="Pedido de exclusão recebido",
        message=("Recebemos seu pedido de exclusão de dados. A organização vai concluir as "
                 "pendências em aberto e anonimizar sua conta. Você será avisado(a) por aqui."),
        notification_type=ParticipantNotification.NotificationType.GENERAL,
    )
    return True


class AnonymizationBlocked(Exception):
    def __init__(self, reasons):
        self.reasons = reasons
        super().__init__("; ".join(reasons))


@transaction.atomic
def anonymize_participant(participant, actor=None, force: bool = False):
    """
    Remove os dados pessoais do joiner mantendo os registros financeiros/operacionais.
    Sem `force`, recusa enquanto houver pendências (AnonymizationBlocked).
    """
    from apps.auth_otp.models import WhatsAppOTP
    from apps.cegs.models import AuditLog, GOMNotification

    reasons = open_obligations(participant)
    if reasons and not force:
        raise AnonymizationBlocked(reasons)

    old_name, old_phone = participant.name, participant.whatsapp
    old_labels = {v for v in (old_name, participant.username, participant.display_name) if v}

    # update() em vez de save(): o save() normaliza o WhatsApp para apenas dígitos, e o
    # marcador precisa conter letras para nunca coincidir com um número usado no login OTP.
    type(participant).objects.filter(pk=participant.pk).update(
        name=ANONYMIZED_NAME, username='', social_handle='', notes='',
        whatsapp=f'removido-{participant.pk}',
    )
    participant.refresh_from_db()

    participant.claims.update(participant_notes='')
    participant.pacotes_nacionais.update(endereco_destinatario='', cep_destinatario='', observacoes_joiner='')
    participant.notifications.all().delete()
    WhatsAppOTP.objects.filter(phone=old_phone).delete()
    AuditLog.objects.filter(participant=participant).update(
        participant_name=ANONYMIZED_NAME, participant_phone='', metadata={},
    )
    for notif in GOMNotification.objects.filter(participant=participant):
        for label in old_labels:
            notif.title = notif.title.replace(label, ANONYMIZED_NAME)
            notif.message = notif.message.replace(label, ANONYMIZED_NAME)
        notif.metadata = {}
        notif.save(update_fields=['title', 'message', 'metadata'])

    _audit(
        AuditLog.EventType.DATA_ANONYMIZED, "Conta anonimizada (LGPD)",
        participant=participant, actor=actor, participant_name=ANONYMIZED_NAME,
        metadata={'forcado': bool(force and reasons)},
    )
    return participant
