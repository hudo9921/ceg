"""Seletor "busca primeiro" do catálogo na Nova CEG: busca, adicionar grupo/era sem duplicar e Hub mais leve."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.goms.models import Gom, GomMembership
from apps.groups.models import Era, KpopGroup, Source

from .models import CEG


class CatalogoBuscaTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja B', slug='loja-b')
        self.user = get_user_model().objects.create_user('membro-b', password='x')
        GomMembership.objects.create(user=self.user, gom=self.gom, role='OWNER')
        self.client.force_login(self.user)
        s = self.client.session
        s['active_gom_id'] = self.gom.id
        s.save()
        imp = dict(source=Source.IMPORTADO, color_hex='#000000')
        self.nct = KpopGroup.objects.create(name='NCT', popularity_rank=5, **imp)
        self.nct127 = KpopGroup.objects.create(name='NCT 127', kind='SUBUNIDADE', parent=self.nct, popularity_rank=9, **imp)
        self.dream = KpopGroup.objects.create(name='NCT Dream', kind='SUBUNIDADE', parent=self.nct, popularity_rank=7, **imp)
        self.aespa = KpopGroup.objects.create(name='aespa', name_native='에스파', aliases='æspa', popularity_rank=2, **imp)
        Era.objects.create(group=self.aespa, name='Rich Man', color_hex='#000000')

    def buscar(self, q):
        return [g['name'] for g in self.client.get(reverse('catalogo_buscar'), {'q': q}).json()['grupos']]

    def test_igual_primeiro_depois_comeca_com_e_popularidade(self):
        self.assertEqual(self.buscar('nct'), ['NCT', 'NCT Dream', 'NCT 127'])
        self.assertEqual(self.buscar('NCT 127'), ['NCT 127'])

    def test_busca_por_hangul_apelido_e_sem_acento(self):
        self.assertEqual(self.buscar('에스파'), ['aespa'])
        self.assertEqual(self.buscar('ÆSPA'), ['aespa'])
        res = self.client.get(reverse('catalogo_buscar'), {'q': 'aespa'}).json()['grupos'][0]
        self.assertEqual([e['name'] for e in res['eras']], ['Rich Man'])

    def test_adicionar_grupo_novo_com_integrantes(self):
        data = self.client.post(reverse('catalogo_grupo_novo'), {'name': 'Hearts2Hearts', 'members': 'Jiwoo, Carmen, Jiwoo'}).json()
        self.assertTrue(data['success'])
        self.assertFalse(data['existente'])
        g = KpopGroup.objects.get(name='Hearts2Hearts')
        self.assertEqual((g.source, g.kind), (Source.MANUAL, 'GRUPO'))
        self.assertEqual(list(g.members.values_list('name', flat=True)), ['Jiwoo', 'Carmen'])

    def test_adicionar_grupo_que_ja_existe_devolve_o_existente(self):
        data = self.client.post(reverse('catalogo_grupo_novo'), {'name': 'Æspa'}).json()
        self.assertTrue(data['existente'])
        self.assertEqual(data['grupo']['id'], self.aespa.id)
        self.assertEqual(KpopGroup.objects.filter(name__iexact='aespa').count(), 1)

    def test_adicionar_era_sem_duplicar(self):
        url = reverse('catalogo_era_nova')
        d1 = self.client.post(url, {'group_id': self.aespa.id, 'name': 'Dirty Work', 'release_date': '2025-06-27', 'kind': 'SINGLE'}).json()
        d2 = self.client.post(url, {'group_id': self.aespa.id, 'name': 'dirty work'}).json()
        self.assertEqual(d1['era_id'], d2['era_id'])
        era = Era.objects.get(pk=d1['era_id'])
        self.assertEqual((era.kind, str(era.release_date)), ('SINGLE', '2025-06-27'))
        self.assertEqual(self.aespa.eras.count(), 2)

    def test_joiner_ou_anonimo_nao_adiciona(self):
        self.client.logout()
        res = self.client.post(reverse('catalogo_grupo_novo'), {'name': 'Grupo X'})
        self.assertIn(res.status_code, (302, 403))
        self.assertFalse(KpopGroup.objects.filter(name='Grupo X').exists())

    def test_hub_preenche_so_grupos_relevantes(self):
        for i in range(30):
            KpopGroup.objects.create(name=f'Importado {i}', popularity_rank=100 + i, source=Source.IMPORTADO, color_hex='#000000')
        usado = KpopGroup.objects.create(name='Usado pelo GOM', popularity_rank=999, source=Source.IMPORTADO, color_hex='#000000')
        CEG.objects.create(gom=self.gom, era=Era.objects.create(group=usado, name='E1', color_hex='#000000'), title='X')
        res = self.client.get(reverse('creations_hub'))
        nomes = {g['name'] for g in json.loads(res.context['groups_json'])}
        self.assertIn('Usado pelo GOM', nomes)
        self.assertIn('aespa', nomes)
        self.assertNotIn('Importado 29', nomes)
        self.assertEqual(len(nomes), 25)  # top 24 + o usado
