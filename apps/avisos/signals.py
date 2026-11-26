"""Toda notificação do site também vai por push para quem ativou no aparelho (regras em push.py)."""
from django.db.models.signals import post_save
from django.dispatch import receiver

# Para onde o toque na notificação leva o joiner, por tipo.
URL_JOINER = {'ENVIO_NACIONAL': '/me/?tab=envios', 'SET_CANCELLED': '/me/?tab=itens', 'CLAIM_UPDATE': '/me/?tab=itens'}


@receiver(post_save, sender='participants.ParticipantNotification')
def push_joiner(sender, instance, created, **kwargs):
    if created:
        from .preferencias import categoria_joiner
        from .push import para_joiner
        para_joiner(instance.participant, instance.title, instance.message,
                    URL_JOINER.get(instance.notification_type, '/me/'), tag=f'pn{instance.pk}',
                    categoria=categoria_joiner(instance))


@receiver(post_save, sender='cegs.GOMNotification')
def push_gom(sender, instance, created, **kwargs):
    from .preferencias import categoria_gom
    from .push import TIPOS_GOM, para_gom
    if created and instance.notification_type in TIPOS_GOM and instance.gom_id:
        para_gom(instance.gom, instance.title, instance.message, instance.action_url or '', tag=f'gn{instance.pk}',
                 categoria=categoria_gom(instance))
