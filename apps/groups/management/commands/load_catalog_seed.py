"""
Carrega o catálogo de grupos/solistas/eras a partir do seed (docs/CATALOG_IMPORT_PLAN.md §4.3).

    python manage.py load_catalog_seed data/catalog_seed.json --dry-run    # só o relatório
    python manage.py load_catalog_seed data/catalog_seed.json              # carrega e copia as imagens
    python manage.py load_catalog_seed data/catalog_seed.json --sem-imagens --limite 20
"""
import json

from django.core.management.base import BaseCommand, CommandError

from apps.groups.catalog import load_seed


class Command(BaseCommand):
    help = 'Cria/completa o catálogo de grupos, integrantes e eras a partir do seed JSON (idempotente).'

    def add_arguments(self, parser):
        parser.add_argument('arquivo', nargs='?', default='data/catalog_seed.json')
        parser.add_argument('--dry-run', action='store_true', help='Mostra o que seria feito e desfaz tudo.')
        parser.add_argument('--sem-imagens', action='store_true', help='Não copia fotos/capas para o storage.')
        parser.add_argument('--limite', type=int, default=0, help='Carrega só os N primeiros artistas do ranking.')

    def handle(self, *args, **opts):
        try:
            with open(opts['arquivo'], encoding='utf-8') as f:
                seed = json.load(f)
        except (OSError, ValueError) as exc:
            raise CommandError(f'Não consegui ler o seed: {exc}')
        artistas = sorted(seed.get('artists') or [], key=lambda a: a.get('rank') or 10 ** 6)
        if opts['limite']:
            artistas = artistas[:opts['limite']]
        self.stdout.write(f'{len(artistas)} artistas no seed{" (simulação)" if opts["dry_run"] else ""}...')
        report = load_seed({'artists': artistas}, copy_images=not opts['sem_imagens'], dry_run=opts['dry_run'])
        for aviso in report.avisos[:50]:
            self.stdout.write(self.style.WARNING(f'  {aviso}'))
        self.stdout.write(self.style.SUCCESS(report.resumo()))
