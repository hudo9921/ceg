"""
Gera data/catalog_seed.json (top grupos e solistas de K-pop) a partir de dados abertos. Roda no PC, não na VM.

    python manage.py build_catalog_seed                     # 500 grupos + 100 solistas
    python manage.py build_catalog_seed --grupos 20 --solistas 5 --saida data/catalog_seed_teste.json
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.groups.catalog_build import build


class Command(BaseCommand):
    help = 'Gera o seed do catálogo de K-pop (Wikidata + Wikipedia + MusicBrainz + Commons).'

    def add_arguments(self, parser):
        parser.add_argument('--saida', default='data/catalog_seed.json')
        parser.add_argument('--cache', default='.catalog_cache')
        parser.add_argument('--grupos', type=int, default=500)
        parser.add_argument('--solistas', type=int, default=100)

    def handle(self, *args, **opts):
        seed = build(opts['cache'], opts['grupos'], opts['solistas'], log=lambda m: self.stdout.write(m))
        saida = Path(opts['saida'])
        saida.parent.mkdir(parents=True, exist_ok=True)
        saida.write_text(json.dumps(seed, ensure_ascii=False, indent=1), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'Seed salvo em {saida} ({saida.stat().st_size // 1024} KB).'))
