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


# --- Miniaturas de fotos enviadas como arquivo (ItemIndividual / ItemVitrine) ---------
# Só gera quando o arquivo mudou: esses modelos são salvos com frequência (ex.: pagamento).
from django.db.models.signals import pre_save  # noqa: E402

_PHOTO_MODELS = ('cegs.ItemIndividual', 'cegs.ItemVitrine')


def _mark_new_photo(sender, instance, **kwargs):
    new_name = instance.foto_arquivo.name if instance.foto_arquivo else ''
    old_name = ''
    if instance.pk:
        old_name = sender.objects.filter(pk=instance.pk).values_list('foto_arquivo', flat=True).first() or ''
    instance._photo_changed = bool(new_name) and new_name != old_name


def _thumbnail_new_photo(sender, instance, **kwargs):
    if not getattr(instance, '_photo_changed', False):
        return
    instance._photo_changed = False
    from apps.core.thumbnails import ensure_thumbnail
    try:
        ensure_thumbnail(instance.foto_arquivo.url)
    except Exception as e:
        logger.warning(f"Miniatura da foto não gerada ({sender.__name__} #{instance.pk}): {e}")


for _model in _PHOTO_MODELS:
    pre_save.connect(_mark_new_photo, sender=_model, dispatch_uid=f'photo-mark-{_model}')
    post_save.connect(_thumbnail_new_photo, sender=_model, dispatch_uid=f'photo-thumb-{_model}')
