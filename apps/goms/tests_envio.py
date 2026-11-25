"""Formas de envio e prazo da caixinha (C3)."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cegs.models import CEG, Caixa, CEGItemDefinition, CEGSet, ItemSlot, MetodoEnvio, PacoteNacional
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Claim, Participant

from .models import Gom, GomMembership

User = get_user_model()
SOLICITAR = '/me/envios/solicitar/'


class EnvioSettingsTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja E', slug='loja-e')
        owner = User.objects.create_user('dono-e', password='x')
        GomMembership.objects.create(user=owner, gom=self.gom, role='OWNER')
        self.client.force_login(owner)
        self.url = reverse('gom_settings_tab', args=['envio'])

    def _post(self, rows, prazo=''):
        data = {'link_formulario_google': '', 'instrucoes_envio': '', 'caixinha_prazo_dias': prazo,
                'metodos-TOTAL_FORMS': str(len(rows)), 'metodos-INITIAL_FORMS': str(sum(1 for r in rows if r.get('id'))),
                'metodos-MIN_NUM_FORMS': '0', 'metodos-MAX_NUM_FORMS': '1000'}
        for i, row in enumerate(rows):
            for k, v in row.items():
                if v is not None:
                    data[f'metodos-{i}-{k}'] = v
        return self.client.post(self.url, data)

    def test_add_methods_and_prazo(self):
        res = self._post([{'nome': 'PAC', 'descricao': '5 a 10 dias', 'ativo': 'on', 'pede_endereco': 'on'},
                          {'nome': 'Retirada', 'ativo': 'on'}, {'nome': ''}], prazo='30')
        self.assertRedirects(res, self.url, fetch_redirect_response=False)
        metodos = list(MetodoEnvio.objects.for_gom(self.gom).values_list('nome', 'pede_endereco'))
        self.assertEqual(metodos, [('PAC', True), ('Retirada', False)])
        self.gom.refresh_from_db()
        self.assertEqual(self.gom.caixinha_prazo_dias, 30)

    def test_remove_method(self):
        m = MetodoEnvio.objects.create(gom=self.gom, nome='Jadlog')
        self._post([{'id': str(m.id), 'nome': 'Jadlog', 'ativo': 'on', 'DELETE': 'on'}])
        self.assertFalse(MetodoEnvio.objects.filter(pk=m.pk).exists())

    def test_tab_lists_only_this_gom_methods(self):
        other = Gom.objects.create(name='Outra', slug='outra-e')
        MetodoEnvio.objects.create(gom=other, nome='Método alheio')
        MetodoEnvio.objects.create(gom=self.gom, nome='SEDEX')
        page = self.client.get(self.url).content.decode()
        self.assertIn('SEDEX', page)
        self.assertNotIn('Método alheio', page)


class JoinerShippingChoiceTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.get(slug='valcegs')
        self.gom.caixinha_prazo_dias = 30
        self.gom.save()
        era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa-e'), name='Rich', slug='rich-e')
        caixa = Caixa.objects.create(nome='Caixa E', gom=self.gom, status='ENTREGUE',
                                     data_recebimento=timezone.localdate() - timedelta(days=5))
        ceg = CEG.objects.create(era=era, gom=self.gom, title='CEG E', slug='ceg-e', status=CEG.Status.OPEN, caixa=caixa)
        idef = CEGItemDefinition.objects.create(ceg=ceg, name='PC Karina')
        self.joiner = Participant.objects.create(whatsapp='5511955554444', name='Joiner E')
        self.slot = ItemSlot.objects.create(set=CEGSet.objects.create(ceg=ceg, set_number=1), item_definition=idef,
                                            price=Decimal('40'), claimed_by=self.joiner, status=ItemSlot.Status.RESERVED,
                                            is_item_paid=True, is_frete_inter_paid=True, is_taxa_aduaneira_paid=True)
        Claim.objects.create(slot=self.slot, participant=self.joiner, status='PAID', total_price=Decimal('40'))
        self.pac = MetodoEnvio.objects.create(gom=self.gom, nome='PAC', ordem=0)
        self.retirada = MetodoEnvio.objects.create(gom=self.gom, nome='Retirada', pede_endereco=False, ordem=1)
        session = self.client.session
        session['participant_id'] = self.joiner.id
        session.save()

    def test_caixinha_shows_methods_and_deadline(self):
        self.assertTrue(self.slot.pode_empacotar, self.slot.check_packaging_eligibility()[1])
        page = self.client.get(reverse('my_claims') + '?tab=caixinha').content.decode()
        self.assertIn('Como você quer receber?', page)
        self.assertIn(f'name="metodo_{self.gom.id}" value="{self.retirada.id}"', page)
        prazo = (timezone.localdate() + timedelta(days=25)).strftime('%d/%m')
        self.assertIn(f'peça o envio até {prazo}', page)

    def test_request_stores_chosen_method(self):
        self.client.post(SOLICITAR, {'selected_uids': f'slot_{self.slot.id}', f'metodo_{self.gom.id}': self.retirada.id})
        pacote = PacoteNacional.objects.get(participant=self.joiner)
        self.assertEqual((pacote.metodo_envio, pacote.metodo_nome), (self.retirada, 'Retirada'))

    def test_request_without_method_is_refused_when_gom_has_methods(self):
        self.client.post(SOLICITAR, {'selected_uids': f'slot_{self.slot.id}'})
        self.assertFalse(PacoteNacional.objects.filter(participant=self.joiner).exists())

    def test_method_of_another_gom_is_refused(self):
        alheio = MetodoEnvio.objects.create(gom=Gom.objects.create(name='X', slug='x-e'), nome='Alheio')
        self.client.post(SOLICITAR, {'selected_uids': f'slot_{self.slot.id}', f'metodo_{self.gom.id}': alheio.id})
        self.assertFalse(PacoteNacional.objects.filter(participant=self.joiner).exists())

    def test_gom_without_methods_works_as_before(self):
        MetodoEnvio.objects.all().delete()
        from apps.participants.models import Endereco
        e = Endereco.objects.create(participant=self.joiner, nome_destinatario='Joiner E', cep='01001-000',
                                    logradouro='Rua A', numero='1', bairro='Centro', cidade='SP', uf='SP')
        self.client.post(SOLICITAR, {'selected_uids': f'slot_{self.slot.id}', 'endereco_id': e.id})
        self.assertEqual(PacoteNacional.objects.get(participant=self.joiner).metodo_nome, '')
