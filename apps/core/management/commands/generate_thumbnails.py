"""
Gera as miniaturas (apps.core.thumbnails) das imagens já existentes no storage.

Idempotente: pula as que já existem. Roda no deploy (scripts/deploy.sh) e pode ser
executado à mão:  docker exec valcegs-web python manage.py generate_thumbnails
"""
from django.apps import apps
from django.core.management.base import BaseCommand

from apps.core.thumbnails import save_thumbnail, storage_name_from_url

# (modelo, campo de URL) e (modelo, FileField) que guardam fotos exibidas em listas.
URL_FIELDS = [
    ('groups.KpopGroup', 'image_url'),
    ('groups.Era', 'banner_url'),
    ('cegs.CEG', 'banner_url'),
    ('cegs.CEGItemDefinition', 'image_url'),
    ('cegs.ItemIndividual', 'foto_url'),
    ('cegs.ItemVitrine', 'image_url'),
]
FILE_FIELDS = [
    ('cegs.ItemIndividual', 'foto_arquivo'),
    ('cegs.ItemVitrine', 'foto_arquivo'),
]


def _model(label):
    try:
        return apps.get_model(label)
    except LookupError:
        return None


class Command(BaseCommand):
    help = 'Gera miniaturas WebP (640 px) das imagens hospedadas que ainda não têm uma.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Recria todas as miniaturas.')
        parser.add_argument('--dry-run', action='store_true', help='Só lista o que seria processado.')

    def _collect(self):
        names = set()
        for label, field in URL_FIELDS:
            model = _model(label)
            if model is None:
                continue
            for url in model.objects.exclude(**{field: ''}).exclude(**{f'{field}__isnull': True}) \
                    .values_list(field, flat=True).iterator():
                name = storage_name_from_url(url)
                if name:
                    names.add(name)
        for label, field in FILE_FIELDS:
            model = _model(label)
            if model is None:
                continue
            for name in model.objects.exclude(**{field: ''}).exclude(**{f'{field}__isnull': True}) \
                    .values_list(field, flat=True).iterator():
                names.add(name)
        return sorted(names)

    def handle(self, *args, force=False, dry_run=False, **options):
        names = self._collect()
        if dry_run:
            self.stdout.write(f"{len(names)} imagens hospedadas encontradas.")
            for name in names:
                self.stdout.write(f"  {name}")
            return
        created = skipped = failed = 0
        for name in names:
            try:
                if save_thumbnail(name, overwrite=force):
                    created += 1
                else:
                    skipped += 1
            except Exception as exc:  # arquivo apagado, corrompido etc.: segue para o próximo
                failed += 1
                self.stderr.write(f"  falhou: {name} ({exc})")
        self.stdout.write(self.style.SUCCESS(
            f"Miniaturas: {created} criadas, {skipped} já existiam, {failed} falharam ({len(names)} imagens)."))
