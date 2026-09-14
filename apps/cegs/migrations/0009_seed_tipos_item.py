from django.db import migrations


def seed_tipos_item(apps, schema_editor):
    TipoItem = apps.get_model('cegs', 'TipoItem')
    CEGItemDefinition = apps.get_model('cegs', 'CEGItemDefinition')

    photocard, _ = TipoItem.objects.get_or_create(
        nome='Photocard',
        defaults={'descricao': 'Cards colecionáveis (POBs, inclusões, sorteios, fansigns)'}
    )
    album, _ = TipoItem.objects.get_or_create(
        nome='Álbum',
        defaults={'descricao': 'Álbuns selados ou unsealed de K-pop'}
    )
    cd, _ = TipoItem.objects.get_or_create(
        nome='CD',
        defaults={'descricao': 'CDs de música, jewel cases ou mini-álbuns'}
    )

    # Mapeia definições de itens existentes
    for item_def in CEGItemDefinition.objects.filter(tipo_item__isnull=True):
        t = item_def.item_type
        if t in ('PHOTOCARD', 'POB', 'INCLUSION'):
            item_def.tipo_item = photocard
        elif t == 'ALBUM':
            item_def.tipo_item = album
        else:
            item_def.tipo_item = photocard
        item_def.save(update_fields=['tipo_item'])


def reverse_seed(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('cegs', '0008_tipoitem_itemslot_frete_inter_valor_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_tipos_item, reverse_seed),
    ]
