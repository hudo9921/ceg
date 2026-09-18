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
