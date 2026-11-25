"""Carga do catálogo (load_catalog_seed): idempotente, não sobrescreve edição manual, liga subunidades e solistas."""
import io
from unittest import mock

from django.test import TestCase, override_settings
from PIL import Image

from .catalog import load_seed
from .models import Era, GroupMember, KpopGroup, Source


def seed():
    return {'artists': [
        {'wikidata_id': 'Q1', 'musicbrainz_id': 'mb-aespa', 'name': 'aespa', 'name_native': '에스파', 'aliases': ['æspa'],
         'kind': 'GRUPO', 'rank': 3, 'agency': 'SM', 'debut_date': '2020-11-17', 'color_hex': '#111111',
         'image_url': 'https://commons.test/aespa.png', 'image_credit': 'Foto: X (CC BY)',
         'members': [{'name': 'Karina', 'name_native': '카리나', 'wikidata_id': 'Q11'},
                     {'name': 'Winter', 'wikidata_id': 'Q12'}],
         'eras': [{'musicbrainz_id': 'rg-1', 'name': 'Rich Man', 'kind': 'MINI', 'release_date': '2025-09-05',
                   'cover_url': 'https://caa.test/rich.jpg', 'color_hex': '#222222'},
                  {'musicbrainz_id': 'rg-2', 'name': 'Hot Mess', 'kind': 'JAPONES', 'release_date': '2024-07-03'}]},
        {'wikidata_id': 'Q2', 'name': 'NCT 127', 'kind': 'SUBUNIDADE', 'parent_wikidata_id': 'Q3', 'rank': 8, 'color_hex': '#333333'},
        {'wikidata_id': 'Q3', 'name': 'NCT', 'kind': 'GRUPO', 'rank': 5, 'color_hex': '#444444'},
        {'wikidata_id': 'Q4', 'name': 'Jisoo', 'kind': 'SOLISTA', 'rank': 9, 'color_hex': '#555555'},
        {'wikidata_id': 'Q5', 'name': 'BLACKPINK', 'kind': 'GRUPO', 'rank': 1, 'color_hex': '#666666',
         'members': [{'name': 'Jisoo', 'wikidata_id': 'Q41', 'solo_wikidata_id': 'Q4'}]},
    ]}


def _png():
    buf = io.BytesIO()
    Image.new('RGB', (20, 20), (200, 10, 90)).save(buf, 'PNG')
    return buf.getvalue()


class LoadCatalogTests(TestCase):
    def test_cria_tudo_e_rodar_de_novo_nao_duplica(self):
        r = load_seed(seed(), copy_images=False)
        self.assertEqual((r.grupos_criados, r.integrantes_criados, r.eras_criadas), (5, 3, 2))
        r2 = load_seed(seed(), copy_images=False)
        self.assertEqual((r2.grupos_criados, r2.integrantes_criados, r2.eras_criadas), (0, 0, 0))
        self.assertEqual(KpopGroup.objects.count(), 5)
        aespa = KpopGroup.objects.get(wikidata_id='Q1')
        self.assertEqual((aespa.source, aespa.popularity_rank, aespa.name_native), (Source.IMPORTADO, 3, '에스파'))
        self.assertEqual(Era.objects.get(musicbrainz_id='rg-2').kind, Era.Kind.JAPONES)

    def test_completa_grupo_manual_sem_sobrescrever(self):
        manual = KpopGroup.objects.create(name='Aespa', description='do GOM', agency='Agência manual', color_hex='#ABCDEF')
        GroupMember.objects.create(group=manual, name='KARINA', order=0)
        Era.objects.create(group=manual, name='rich man', color_hex='#ABCDEF')
        load_seed(seed(), copy_images=False)
        manual.refresh_from_db()
        self.assertEqual(KpopGroup.objects.filter(name__iexact='aespa').count(), 1)
        self.assertEqual((manual.wikidata_id, manual.name_native), ('Q1', '에스파'))
        self.assertEqual((manual.name, manual.agency, manual.color_hex, manual.source), ('Aespa', 'Agência manual', '#ABCDEF', Source.MANUAL))
        self.assertEqual(sorted(manual.members.values_list('name', flat=True)), ['KARINA', 'Winter'])
        self.assertEqual(manual.eras.count(), 2)
        self.assertEqual(manual.eras.get(name='rich man').musicbrainz_id, 'rg-1')

    def test_subunidade_e_solista_ligados(self):
        load_seed(seed(), copy_images=False)
        self.assertEqual(KpopGroup.objects.get(name='NCT 127').parent.name, 'NCT')
        jisoo = KpopGroup.objects.get(wikidata_id='Q4')
        self.assertEqual(jisoo.kind, KpopGroup.Kind.SOLISTA)
        self.assertEqual(GroupMember.objects.get(wikidata_id='Q41').solo, jisoo)

    def test_homonimo_ganha_qualificador(self):
        s = seed()
        s['artists'].append({'wikidata_id': 'Q99', 'name': 'JISOO', 'kind': 'SOLISTA', 'agency': 'Outra', 'color_hex': '#777777'})
        load_seed(s, copy_images=False)
        self.assertTrue(KpopGroup.objects.filter(name='JISOO (Outra)', wikidata_id='Q99').exists())

    def test_dry_run_desfaz(self):
        r = load_seed(seed(), dry_run=True)
        self.assertEqual(r.grupos_criados, 5)
        self.assertFalse(KpopGroup.objects.exists())

    @override_settings(STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
                                 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
    def test_copia_imagens_e_segue_se_falhar(self):
        def fake(url, **kw):
            if 'rich' in url:
                raise OSError('fora do ar')
            return _png()
        with mock.patch('apps.core.net.fetch_public_url', side_effect=fake):
            r = load_seed(seed())
        self.assertEqual((r.imagens_copiadas, r.imagens_falharam), (1, 1))
        aespa = KpopGroup.objects.get(wikidata_id='Q1')
        self.assertIn('catalogo/grupos/', aespa.image_url)
        self.assertEqual(Era.objects.get(musicbrainz_id='rg-1').banner_url, '')
