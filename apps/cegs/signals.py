import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='participants.Participant')
def log_participant_creation(sender, instance, created, **kwargs):
    """Registra automaticamente no AuditLog quando um novo participante é cadastrado."""
    if created:
        try:
            from apps.cegs.audit_service import AuditService
            AuditService.log_account_created(instance)
        except Exception as e:
            logger.error(f"Erro no signal de criação de participante para AuditLog: {e}")


@receiver(post_save, sender='cegs.ClaimAttemptLog')
def log_claim_attempt_creation(sender, instance, created, **kwargs):
    """Registra automaticamente no AuditLog quando uma tentativa de claim ocorre."""
    if created:
        try:
            from apps.cegs.audit_service import AuditService
            AuditService.log_claim_attempt(instance)
        except Exception as e:
            logger.error(f"Erro no signal de tentativa de claim para AuditLog: {e}")


@receiver(post_save, sender='participants.Claim')
def log_claim_creation(sender, instance, created, **kwargs):
    """
    Rede de segurança: registra automaticamente no AuditLog quando uma Claim é criada,
    caso nenhum log recente (últimos 10s) tenha sido registrado para o slot e participante.
    """
    if created and instance.slot and instance.participant:
        try:
            from datetime import timedelta
            from django.utils import timezone
            from apps.cegs.models import AuditLog
            from apps.cegs.audit_service import AuditService

            recent_thresh = timezone.now() - timedelta(seconds=10)
            already_logged = AuditLog.objects.filter(
                slot=instance.slot,
                participant=instance.participant,
                event_type__in=[AuditLog.EventType.CLAIM_SUCCESS, AuditLog.EventType.SLOT_ASSIGNED],
                created_at__gte=recent_thresh
            ).exists()

            if not already_logged:
                AuditService.log_claim_success_from_claim(instance)
        except Exception as e:
            logger.error(f"Erro no signal de Claim para AuditLog: {e}")
