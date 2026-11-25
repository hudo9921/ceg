"""Endereços no site (S2): cadastro criptografado, CEP, escolha no pedido de envio e visualização registrada."""
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG, Caixa, CEGItemDefinition, CEGSet, ItemSlot, MetodoEnvio, PacoteNacional, AuditLog
from apps.goms.models import Gom, GomMembership
from apps.groups.models import Era, KpopGroup

from .models import Claim, Endereco, Participant

ADDR = {'apelido': 'Casa', 'nome_destinatario': 'Ana Souza', 'cep': '01001000', 'logradouro': 'Praça da Sé',
        'numero': '100', 'complemento': 'Apto 3', 'bairro': 'Sé', 'cidade': 'São Paulo', 'uf': 'SP'}


class EnderecoTests(TestCase):
    def setUp(self):
        self.joiner = Participant.objects.create(whatsapp='5511922221111', name='Ana')
        session = self.client.session
        session['participant_id'] = self.joiner.id
        session.save()

    def test_save_encrypts_and_first_is_main(self):
        self.client.post(reverse('endereco_salvar'), ADDR)
        e = Endereco.objects.get(participant=self.joiner)
        self.assertTrue(e.padrao)
        self.assertEqual(e.cep_formatado, '01001-000')
        with connection.cursor() as cur:
            cur.execute('SELECT logradouro FROM participants_endereco WHERE id = %s', [e.id])
            self.assertTrue(cur.fetchone()[0].startswith('enc:v1:'))

    def test_cannot_edit_or_delete_someone_elses(self):
        other = Participant.objects.create(whatsapp='5511922220000', name='Bia')
        e = Endereco.objects.create(participant=other, **{**ADDR, 'cep': '01001-000'})
        self.assertEqual(self.client.post(reverse('endereco_salvar'), {**ADDR, 'id': e.id}).status_code, 404)
        self.assertEqual(self.client.post(reverse('endereco_excluir', args=[e.id])).status_code, 404)

    def test_invalid_cep_is_refused(self):
        self.client.post(reverse('endereco_salvar'), {**ADDR, 'cep': '123'})
        self.assertFalse(Endereco.objects.exists())

    @mock.patch('apps.participants.enderecos_views.requests.get')
    def test_cep_lookup(self, get):
        get.return_value = mock.Mock(status_code=200, json=lambda: {'logradouro': 'Praça da Sé', 'bairro': 'Sé',
                                                                     'localidade': 'São Paulo', 'uf': 'SP'})
        data = self.client.get(reverse('endereco_cep', args=['01001-000'])).json()
        self.assertEqual((data['cidade'], data['uf']), ('São Paulo', 'SP'))
        self.assertIn('viacep.com.br/ws/01001000/json/', get.call_args[0][0])


class ShippingWithAddressTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.get(slug='valcegs')
        era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa-end'), name='Rich', slug='rich-end')
        caixa = Caixa.objects.create(nome='Caixa End', gom=self.gom, status='ENTREGUE')
        ceg = CEG.objects.create(era=era, gom=self.gom, title='CEG End', slug='ceg-end', status=CEG.Status.OPEN, caixa=caixa)
        idef = CEGItemDefinition.objects.create(ceg=ceg, name='PC Karina')
        self.joiner = Participant.objects.create(whatsapp='5511922223333', name='Ana')
        self.slot = ItemSlot.objects.create(set=CEGSet.objects.create(ceg=ceg, set_number=1), item_definition=idef,
                                            price=Decimal('40'), claimed_by=self.joiner, status=ItemSlot.Status.RESERVED,
                                            is_item_paid=True, is_frete_inter_paid=True, is_taxa_aduaneira_paid=True)
        Claim.objects.create(slot=self.slot, participant=self.joiner, status='PAID', total_price=Decimal('40'))
        self.addr = Endereco.objects.create(participant=self.joiner, padrao=True, **{**ADDR, 'cep': '01001-000'})
        session = self.client.session
        session['participant_id'] = self.joiner.id
        session.save()

    def _pedir(self, **extra):
        return self.client.post('/me/envios/solicitar/', {'selected_uids': f'slot_{self.slot.id}', **extra})

    def test_address_required_and_copied_to_package(self):
        self._pedir()
        self.assertFalse(PacoteNacional.objects.exists())
        self._pedir(endereco_id=self.addr.id)
        pacote = PacoteNacional.objects.get()
        self.assertIn('Praça da Sé, 100 — Apto 3', pacote.endereco_destinatario)
        self.assertEqual(pacote.cep_destinatario, '01001-000')

    def test_pickup_needs_no_address(self):
        retirada = MetodoEnvio.objects.create(gom=self.gom, nome='Retirada', pede_endereco=False)
        self._pedir(**{f'metodo_{self.gom.id}': retirada.id})
        self.assertEqual(PacoteNacional.objects.get().endereco_destinatario, '')

    def test_gom_reveal_is_logged(self):
        self._pedir(endereco_id=self.addr.id)
        pacote = PacoteNacional.objects.get()
        staff = get_user_model().objects.create_user('equipe-end', password='x')
        GomMembership.objects.create(user=staff, gom=self.gom, role='OWNER')
        self.client.force_login(staff)
        data = self.client.get(reverse('pacote_endereco', args=[pacote.id])).json()
        self.assertIn('São Paulo/SP', data['texto'])
        self.assertTrue(AuditLog.objects.filter(event_type=AuditLog.EventType.PII_ACCESS, pacote_nacional=pacote).exists())

    def test_envios_board_does_not_print_address(self):
        self._pedir(endereco_id=self.addr.id)
        staff = get_user_model().objects.create_user('equipe-end2', password='x')
        GomMembership.objects.create(user=staff, gom=self.gom, role='OWNER')
        self.client.force_login(staff)
        page = self.client.get(reverse('envios_nacionais')).content.decode()
        self.assertIn('Ver endereço', page)
        self.assertNotIn('Praça da Sé', page)
