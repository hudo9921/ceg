"""Eras = comebacks: singles dobrados no álbum (catalog_mb), busca do ID no MusicBrainz e "Juntar com outra era"."""
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG
from apps.goms.models import Gom

from .catalog import load_seed
from .catalog_mb import agrupar, buscar_mbid, classificar
from .eras import era_por_nome
from .models import Era, KpopGroup

HOJE = date(2026, 11, 26)


def rel(rgid, titulo, tipo, data, faixas, fisico=True, sec=(), pais='KR'):
    return {'country': pais, 'release-group': {'id': rgid, 'title': titulo, 'primary-type': tipo,
                                               'first-release-date': data, 'secondary-types': list(sec)},
            'media': [{'format': 'CD' if fisico else 'Digital Media',
                       'tracks': [{'title': t, 'recording': {'id': r, 'title': t}} for r, t in faixas]}]}


class ClassificarErasTests(TestCase):
    def eras(self, releases):
        eras, dobradas = classificar(agrupar(releases), HOJE)
        return [e['name'] for e in eras], {d['name']: d['dentro_de_nome'] for d in dobradas}

    def test_single_da_faixa_titulo_vira_parte_do_album(self):
        nomes, dobradas = self.eras([
            rel('a1', 'ARIRANG', 'Album', '2026-03-20', [('r1', 'SWIM'), ('r2', 'Body to Body')]),
            rel('s1', 'SWIM', 'Single', '2026-03-20', [('r1', 'SWIM')]),
            rel('s2', 'Pré', 'Single', '2026-01-10', [('rx', 'Body to Body (Inst.)'), ('r2b', 'Body to Body')]),
            rel('s3', 'NORMAL', 'Single', '2026-07-17', [('r9', 'NORMAL')]),
            rel('s4', 'Digital', 'Single', '2025-05-01', [('r8', 'Digital')], fisico=False),
            rel('c1', 'Proof', 'Album', '2022-06-10', [('r1', 'SWIM'), ('r7', 'Run')], sec=['Compilation']),
            rel('c2', 'THE BEST', 'Album', '2021-06-16', [('r6', 'Nova')], sec=['Compilation']),
            rel('l1', 'Live', 'Album', '2026-04-01', [('r1', 'SWIM')], sec=['Live']),
        ])
        self.assertEqual(dobradas, {'SWIM': 'ARIRANG', 'Pré': 'ARIRANG'})  # por gravação e pelo título
        self.assertEqual(nomes, ['NORMAL', 'ARIRANG', 'Proof'])  # single digital, best of e ao vivo ficam de fora

    def test_single_longe_do_album_nao_dobra(self):
        _, dobradas = self.eras([
            rel('a1', 'Album', 'Album', '2026-06-01', [('r1', 'Hit')]),
            rel('s1', 'Hit', 'Single', '2025-06-01', [('r1', 'Hit')]),
        ])
        self.assertEqual(dobradas, {})

    def test_so_singles_digitais_entram_os_3_mais_recentes(self):
        nomes, _ = self.eras([rel(f's{i}', f'S{i}', 'Single', f'202{i}-01-01', [(f'r{i}', f'S{i}')], fisico=False)
                              for i in range(1, 6)])
        self.assertEqual(nomes, ['S5', 'S4', 'S3'])


class FakeHttp:
    def __init__(self, respostas):
        self.respostas = respostas

    def get(self, url, **kw):
        return next((v for k, v in self.respostas.items() if k in url), None)


class BuscarMbidTests(TestCase):
    def test_confirma_pelo_wikidata_ou_unico_coreano(self):
        http = FakeHttp({
            'artist?': {'artists': [{'id': 'mb-how', 'name': 'HEART OF WOMAN', 'type': 'Group', 'score': 100, 'country': 'KR'},
                                    {'id': 'mb-outro', 'name': 'Heart of Woman', 'type': 'Group', 'score': 100, 'country': 'US'}]},
            'artist/mb-how': {'relations': []}, 'artist/mb-outro': {'relations': []},
        })
        self.assertEqual(buscar_mbid(http, ['Heart Of Woman'], 'Q1', False), ('mb-how', 'nome'))
        http.respostas['artist/mb-outro'] = {'relations': [{'type': 'wikidata', 'url': {'resource': 'https://www.wikidata.org/wiki/Q1'}}]}
        self.assertEqual(buscar_mbid(http, ['Heart Of Woman'], 'Q1', False), ('mb-outro', 'wikidata'))

    def test_recusa_tipo_errado_ou_ambiguo(self):
        http = FakeHttp({'artist?': {'artists': [
            {'id': 'a', 'name': 'Venus', 'type': 'Group', 'score': 100, 'country': 'KR'},
            {'id': 'b', 'name': 'Venus', 'type': 'Group', 'score': 100, 'area': {'name': 'South Korea'}},
            {'id': 'c', 'name': 'Venus', 'type': 'Person', 'score': 100, 'country': 'KR'}]}})
        self.assertEqual(buscar_mbid(http, ['Venus'], 'Q9', False), (None, None))


class JuntarErasTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('root-j', 'j@example.com', 'Senha-Forte-123')
        self.bts = KpopGroup.objects.create(name='BTS', slug='bts-j', wikidata_id='Q13580495')
        self.album = Era.objects.create(group=self.bts, name='ARIRANG', slug='arirang', musicbrainz_id='a1')
        self.swim = Era.objects.create(group=self.bts, name='SWIM', slug='swim', musicbrainz_id='s1',
                                       banner_url='https://example.com/swim.jpg')
        self.gom = Gom.objects.create(name='G', slug='g-j')

    def test_carga_junta_single_sem_ceg_e_marca_o_que_tem_ceg(self):
        outro = Era.objects.create(group=self.bts, name='Come Over', slug='come-over', musicbrainz_id='s2')
        CEG.objects.create(era=outro, gom=self.gom, title='CEG Come Over', slug='ceg-co')
        dobradas = [{'musicbrainz_id': 's1', 'dentro_de': 'a1'}, {'musicbrainz_id': 's2', 'dentro_de': 'a1'}]
        report = load_seed({'artists': [{'wikidata_id': 'Q13580495', 'name': 'BTS', 'eras_dobradas': dobradas}]},
                           copy_images=False)
        self.assertEqual((report.eras_juntadas, report.eras_para_revisar), (1, 1))
        self.assertFalse(Era.objects.filter(pk=self.swim.pk).exists())
        self.album.refresh_from_db()
        self.assertEqual((self.album.aliases, self.album.banner_url), ('SWIM', 'https://example.com/swim.jpg'))
        outro.refresh_from_db()
        self.assertEqual(outro.parte_de, self.album)
        self.assertEqual(era_por_nome(self.bts, 'swim'), self.album)  # GOM digitando "SWIM" usa ARIRANG

    def test_botao_juntar_move_as_cegs(self):
        ceg = CEG.objects.create(era=self.swim, gom=self.gom, title='CEG SWIM', slug='ceg-swim')
        self.client.force_login(self.root)
        res = self.client.post(reverse('platform_catalogo_era_juntar', args=[self.swim.pk]),
                               {'acao': 'juntar', 'destino': self.album.pk})
        self.assertRedirects(res, reverse('platform_catalogo_grupo', args=[self.bts.pk]), fetch_redirect_response=False)
        ceg.refresh_from_db()
        self.assertEqual(ceg.era, self.album)
        self.assertFalse(Era.objects.filter(pk=self.swim.pk).exists())

    def test_manter_separada_e_outro_grupo_recusado(self):
        self.swim.parte_de = self.album
        self.swim.save()
        self.client.force_login(self.root)
        url = reverse('platform_catalogo_era_juntar', args=[self.swim.pk])
        outra = Era.objects.create(group=KpopGroup.objects.create(name='X', slug='x-j'), name='Y', slug='y')
        self.client.post(url, {'acao': 'juntar', 'destino': outra.pk})
        self.assertTrue(Era.objects.filter(pk=self.swim.pk).exists())
        self.client.post(url, {'acao': 'manter'})
        self.swim.refresh_from_db()
        self.assertIsNone(self.swim.parte_de)

    def test_so_superusuario(self):
        self.client.force_login(User.objects.create_user('comum-j', password='Senha-Forte-123'))
        self.client.post(reverse('platform_catalogo_era_juntar', args=[self.swim.pk]), {'acao': 'juntar', 'destino': self.album.pk})
        self.assertTrue(Era.objects.filter(pk=self.swim.pk).exists())
