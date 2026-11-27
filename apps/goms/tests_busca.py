"""Busca rápida (Ctrl+K): acha joiner, CEG, caixa e pacote do GOM ativo; respeita permissões e isolamento."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG, Caixa, PacoteNacional
from apps.goms.models import Gom, GomMembership
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Participant

User = get_user_model()


class BuscaRapidaTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja B', slug='loja-b')
        self.dono = User.objects.create_user('dono-b', password='x')
        GomMembership.objects.create(user=self.dono, gom=self.gom, role='OWNER')
        self.joiner = Participant.objects.create(whatsapp='5511912345678', name='Wonyoungie Fã', username='wony')
        self.joiner.known_by_goms.add(self.gom)
        era = Era.objects.create(group=KpopGroup.objects.create(name='IVE', slug='ive'), name='Wonderful')
        CEG.objects.create(gom=self.gom, era=era, title='IVE Wonderful POB', slug='ive-wonderful')
        Caixa.objects.create(gom=self.gom, nome='Caixa Wonder KR')
        self.pacote = PacoteNacional.objects.create(gom=self.gom, participant=self.joiner)
        outro = Gom.objects.create(name='Outro', slug='outro-b')
        CEG.objects.create(gom=outro, era=era, title='IVE Wonderful de outro GOM', slug='ive-outro')
        self.url = reverse('painel_busca')

    def _grupos(self, q):
        return {g['titulo']: [i['titulo'] for i in g['itens']] for g in self.client.get(self.url, {'q': q}).json()['grupos']}

    def test_acha_tudo_do_gom(self):
        self.client.force_login(self.dono)
        grupos = self._grupos('wonder')
        self.assertEqual(grupos['CEGs'], ['IVE Wonderful POB'])
        self.assertEqual(grupos['Caixas'], ['Caixa Wonder KR'])
        self.assertEqual(self._grupos('5678')['Joiners'], ['wony'])
        self.assertEqual(self._grupos(self.pacote.identificador)['Pacotes'], [f'Pacote {self.pacote.identificador}'])

    def test_sem_permissao_nao_ve_joiners_nem_caixas(self):
        ajudante = User.objects.create_user('ajudante-b', password='x')
        GomMembership.objects.create(user=ajudante, gom=self.gom, role='ADMIN', permissions=['ceg.editar'])
        self.client.force_login(ajudante)
        grupos = self._grupos('wony')
        self.assertNotIn('Joiners', grupos)
        self.assertNotIn('Caixas', self._grupos('wonder'))

    def test_visitante_nao_busca(self):
        self.assertNotEqual(self.client.get(self.url, {'q': 'wonder'}).status_code, 200)

    def test_texto_curto_nao_busca(self):
        self.client.force_login(self.dono)
        self.assertEqual(self._grupos('w'), {})
