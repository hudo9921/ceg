"""Painel lateral do joiner: resumo do GOM ativo, sem endereço nem telefone completo, e isolado entre GOMs."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot
from apps.goms.models import Gom, GomMembership
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Claim, Endereco, Participant

User = get_user_model()


class JoinerPainelTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja P', slug='loja-p')
        self.staff = User.objects.create_user('dono-p', password='x')
        GomMembership.objects.create(user=self.staff, gom=self.gom, role='OWNER')
        self.joiner = Participant.objects.create(whatsapp='5511987654321', name='Carla Dias', username='carlinha')
        self.joiner.known_by_goms.add(self.gom)
        era = Era.objects.create(group=KpopGroup.objects.create(name='IVE', slug='ive'), name='IVE SECRET')
        ceg = CEG.objects.create(gom=self.gom, era=era, title='IVE SECRET POB', slug='ive-secret-pob')
        d = CEGItemDefinition.objects.create(ceg=ceg, name='Wonyoung POB', default_price=Decimal('40'))
        slot = ItemSlot.objects.create(set=CEGSet.objects.create(ceg=ceg, set_number=1), item_definition=d,
                                       price=Decimal('40'), unit_number=1, status=ItemSlot.Status.RESERVED,
                                       claimed_by=self.joiner)
        Claim.objects.create(slot=slot, participant=self.joiner, total_price=Decimal('40'))
        Endereco.objects.create(participant=self.joiner, nome_destinatario='Carla Dias', cep='01001000',
                                logradouro='Rua Segredo', numero='7', bairro='Centro', cidade='São Paulo', uf='SP')
        self.url = reverse('joiner_painel', args=[self.joiner.id])

    def test_resumo_com_divida_e_itens_sem_dados_sensiveis(self):
        self.client.force_login(self.staff)
        html = self.client.get(self.url).content.decode()
        self.assertIn('carlinha', html)
        self.assertIn('Wonyoung POB', html)
        self.assertIn('R$ 40,00', html)
        self.assertIn('Tem endereço cadastrado', html)
        self.assertNotIn('Rua Segredo', html)
        self.assertNotIn('5511987654321', html)
        self.assertIn('4321', html)

    def test_joiner_de_outro_gom_nao_abre(self):
        outro = Gom.objects.create(name='Outro', slug='outro-p')
        estranho = Participant.objects.create(whatsapp='5511900001111', name='Fora')
        estranho.known_by_goms.add(outro)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('joiner_painel', args=[estranho.id])).status_code, 404)

    def test_visitante_nao_abre(self):
        self.assertNotEqual(self.client.get(self.url).status_code, 200)

    def test_painel_vem_no_layout_da_equipe(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse('gom_mensagens')), 'painelJoiner()')
