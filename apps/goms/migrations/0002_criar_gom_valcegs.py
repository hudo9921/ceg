"""
Cria o GOM "ValCegs" (dono de todos os dados existentes) e vincula a equipe atual:
superusuários viram GOM principal (OWNER) e os demais usuários staff viram admins.
A atribuição dos dados (CEGs, caixas...) a este GOM vem na entrega M2.
"""
from django.db import migrations

VALCEGS_SLUG = 'valcegs'


def criar_valcegs(apps, schema_editor):
    Gom = apps.get_model('goms', 'Gom')
    GomMembership = apps.get_model('goms', 'GomMembership')
    User = apps.get_model('auth', 'User')

    gom, _ = Gom.objects.get_or_create(slug=VALCEGS_SLUG, defaults={'name': 'ValCegs'})
    for user in User.objects.filter(is_active=True).filter(is_superuser=True):
        GomMembership.objects.get_or_create(user=user, gom=gom, defaults={'role': 'OWNER'})
    for user in User.objects.filter(is_active=True, is_staff=True, is_superuser=False):
        GomMembership.objects.get_or_create(user=user, gom=gom, defaults={'role': 'ADMIN'})


def desfazer(apps, schema_editor):
    apps.get_model('goms', 'Gom').objects.filter(slug=VALCEGS_SLUG).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('goms', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [migrations.RunPython(criar_valcegs, desfazer)]
