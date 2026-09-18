from django.db import migrations

PALETTE = ['#EC4899', '#8B5CF6', '#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#06B6D4', '#84CC16']


def get_deterministic_color(name: str) -> str:
    if not name:
        return '#EC4899'
    idx = sum(ord(c) for c in name) % len(PALETTE)
    return PALETTE[idx]


def populate_colors(apps, schema_editor):
    KpopGroup = apps.get_model('groups', 'KpopGroup')
    Era = apps.get_model('groups', 'Era')

    try:
        from apps.groups.color_utils import extract_dominant_color
    except Exception:
        extract_dominant_color = None

    # 1. Popula Grupos sem cor
    for group in KpopGroup.objects.filter(color_hex=''):
        color = ''
        if group.image_url and extract_dominant_color:
            try:
                extracted = extract_dominant_color(group.image_url)
                if extracted and extracted.startswith('#'):
                    color = extracted
            except Exception:
                pass
        if not color:
            color = get_deterministic_color(group.name)
        group.color_hex = color
        group.save(update_fields=['color_hex'])

    # 2. Popula Eras sem cor
    for era in Era.objects.filter(color_hex=''):
        color = ''
        if era.banner_url and extract_dominant_color:
            try:
                extracted = extract_dominant_color(era.banner_url)
                if extracted and extracted.startswith('#'):
                    color = extracted
            except Exception:
                pass

        if not color and era.group and getattr(era.group, 'color_hex', None):
            color = era.group.color_hex

        if not color and era.group and getattr(era.group, 'image_url', None) and extract_dominant_color:
            try:
                extracted = extract_dominant_color(era.group.image_url)
                if extracted and extracted.startswith('#'):
                    color = extracted
            except Exception:
                pass

        if not color:
            color = get_deterministic_color(era.name)

        era.color_hex = color
        era.save(update_fields=['color_hex'])


def reverse_populate(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('groups', '0003_kpopgroup_color_hex'),
    ]

    operations = [
        migrations.RunPython(populate_colors, reverse_populate),
    ]
