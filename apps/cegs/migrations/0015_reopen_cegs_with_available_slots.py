from django.db import migrations
from django.utils import timezone


def reopen_cegs_with_available_slots(apps, schema_editor):
    CEG = apps.get_model('cegs', 'CEG')
    ItemSlot = apps.get_model('cegs', 'ItemSlot')

    # Encontra todas as CEGs que possuem slots AVAILABLE em sets ativos
    available_ceg_ids = set(
        ItemSlot.objects.filter(
            status='AVAILABLE',
            set__is_active=True
        ).values_list('set__ceg_id', flat=True)
    )

    # Reabre qualquer CEG com vagas disponíveis e limpa closes_at se estiver no passado
    now = timezone.now()
    for ceg in CEG.objects.filter(id__in=available_ceg_ids):
        changed = False
        if ceg.status != 'OPEN':
            ceg.status = 'OPEN'
            changed = True
        if ceg.closes_at and ceg.closes_at <= now:
            ceg.closes_at = None
            changed = True
        if changed:
            ceg.save()


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('cegs', '0014_itemindividual_produto_pago'),
    ]

    operations = [
        migrations.RunPython(reopen_cegs_with_available_slots, backwards),
    ]
