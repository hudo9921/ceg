"""
Gera data/catalog_seed.json (top grupos e solistas de K-pop) a partir de dados abertos. Roda no PC, não na VM.

    python manage.py build_catalog_seed                     # 500 grupos (cotas girl/boy) + estreantes + 100 solistas
    python manage.py build_catalog_seed --grupos 20 --solistas 5 --saida data/catalog_seed_teste.json

Sempre inclui quem está em data/catalog_obrigatorios.txt e escreve data/catalog_relatorio.md com o que faltou.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.groups.catalog_build import build, ler_obrigatorios


class Command(BaseCommand):
    help = 'Gera o seed do catálogo de K-pop (Wikidata + Wikipedia + MusicBrainz + Commons).'

    def add_arguments(self, parser):
        parser.add_argument('--saida', default='data/catalog_seed.json')
        parser.add_argument('--cache', default='.catalog_cache')
        parser.add_argument('--grupos', type=int, default=500)
        parser.add_argument('--solistas', type=int, default=100)
        parser.add_argument('--estreantes', type=int, default=100)
        parser.add_argument('--obrigatorios', default='data/catalog_obrigatorios.txt')
        parser.add_argument('--relatorio', default='data/catalog_relatorio.md')

    def handle(self, *args, **opts):
        obrig = ler_obrigatorios(opts['obrigatorios'])
        seed = build(opts['cache'], opts['grupos'], opts['solistas'], log=lambda m: self.stdout.write(m),
                     obrigatorios=obrig, n_estreantes=opts['estreantes'])
        saida = Path(opts['saida'])
        saida.parent.mkdir(parents=True, exist_ok=True)
        saida.write_text(json.dumps(seed, ensure_ascii=False, indent=1), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'Seed salvo em {saida} ({saida.stat().st_size // 1024} KB).'))

        r = seed['relatorio']
        linhas = [
            f"# Relatório do catálogo ({seed['generated_at']})", '',
            f"- Artistas: {len(seed['artists'])} · grupos por tipo: {r['por_tipo']} · estreantes: {r['estreantes']}",
            f"- Lista obrigatória: {len(obrig)} nomes, {len(r['obrigatorios_nao_encontrados'])} não encontrados", '',
        ]
        for titulo, chave in [('Obrigatórios não encontrados (corrija o nome no .txt)', 'obrigatorios_nao_encontrados'),
                              ('Vendem no Circle Chart mas não achei no Wikidata', 'circle_sem_correspondencia'),
                              ('Top 200 sem integrantes', 'top200_sem_integrantes'),
                              ('Top 200 sem foto', 'top200_sem_foto'),
                              ('Top 200 sem eras no MusicBrainz', 'top200_sem_eras'),
                              ('ID do MusicBrainz achado pelo nome (confira)', 'musicbrainz_por_nome'),
                              ('Singles que viraram parte de um álbum', 'singles_dobrados')]:
            lista = r.get(chave) or []
            corpo = '\n'.join(f'- {x}' for x in lista) if chave in ('musicbrainz_por_nome', 'singles_dobrados') else ', '.join(lista)
            linhas += [f'## {titulo} ({len(lista)})', '', corpo or '—', '']
        Path(opts['relatorio']).write_text('\n'.join(linhas), encoding='utf-8')
        if r['obrigatorios_nao_encontrados']:
            self.stdout.write(self.style.WARNING('Não encontrados: ' + ', '.join(r['obrigatorios_nao_encontrados'])))
