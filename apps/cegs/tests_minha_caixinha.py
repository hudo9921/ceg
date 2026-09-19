from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from apps.cegs.models import (
    CEG, CEGItemDefinition, CEGSet, ItemSlot, Caixa, ItemIndividual,
    PacoteNacional, ConfiguracaoEnvio, AuditLog
)
from apps.groups.models import KpopGroup, Era
from apps.participants.models import Participant


class MinhaCaixinhaTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_superuser('admin', 'admin@example.com', 'pass123')
        self.client = Client()

        self.participant = Participant.objects.create(
            whatsapp='5511999998888',
            name='Test Participant',
            username='testjoiner'
        )

        self.group = KpopGroup.objects.create(name='TWICE', slug='twice')
        self.era = Era.objects.create(group=self.group, name='With YOU-th')

        self.ceg_national = CEG.objects.create(
            era=self.era,
            title='CEG Nacional',
            slug='ceg-nacional',
            status=CEG.Status.OPEN
        )
        self.item_def_nat = CEGItemDefinition.objects.create(ceg=self.ceg_national, name='PC Nacional')
        self.set_nat = CEGSet.objects.create(ceg=self.ceg_national, set_number=1)
        self.slot_nat = ItemSlot.objects.create(
            set=self.set_nat,
            item_definition=self.item_def_nat,
            price=Decimal('50.00'),
            claimed_by=self.participant,
            status=ItemSlot.Status.RESERVED,
            is_item_paid=False
        )

        # Caixa internacional
        self.caixa = Caixa.objects.create(
            nome='Caixa JP #01',
            origem='JP',
            status='EM_TRANSITO'
        )
        self.ceg_inter = CEG.objects.create(
            era=self.era,
            title='CEG Internacional',
            slug='ceg-internacional',
            status=CEG.Status.OPEN,
            caixa=self.caixa
        )
        self.item_def_inter = CEGItemDefinition.objects.create(ceg=self.ceg_inter, name='PC Japão')
        self.set_inter = CEGSet.objects.create(ceg=self.ceg_inter, set_number=1)
        self.slot_inter = ItemSlot.objects.create(
            set=self.set_inter,
            item_definition=self.item_def_inter,
            price=Decimal('70.00'),
            frete_inter_valor=Decimal('15.00'),
            taxa_aduaneira_valor=Decimal('10.00'),
            claimed_by=self.participant,
            status=ItemSlot.Status.RESERVED,
            is_item_paid=True,
            is_frete_inter_paid=False,
            is_taxa_aduaneira_paid=False
        )

    def test_packaging_eligibility_national_item(self):
        # Unpaid national slot -> not eligible
        pode, motivo = self.slot_nat.check_packaging_eligibility()
        self.assertFalse(pode)
        self.assertIn("pendente de pagamento", motivo)

        # Mark paid -> eligible immediately (national items are already with GOM)
        self.slot_nat.is_item_paid = True
        self.slot_nat.save()
        pode, motivo = self.slot_nat.check_packaging_eligibility()
        self.assertTrue(pode)
        self.assertEqual(motivo, "")

    def test_packaging_eligibility_international_item(self):
        # Caixa in transit -> not eligible even if item is paid
        pode, motivo = self.slot_inter.check_packaging_eligibility()
        self.assertFalse(pode)
        self.assertIn("trânsito internacional", motivo)

        # Caixa delivered, but frete and taxa unpaid -> not eligible
        self.caixa.status = 'ENTREGUE'
        self.caixa.save()
        pode, motivo = self.slot_inter.check_packaging_eligibility()
        self.assertFalse(pode)
        self.assertIn("Frete internacional pendente", motivo)

        # Pay frete, but taxa unpaid -> not eligible
        self.slot_inter.is_frete_inter_paid = True
        self.slot_inter.save()
        pode, motivo = self.slot_inter.check_packaging_eligibility()
        self.assertFalse(pode)
        self.assertIn("Taxa aduaneira pendente", motivo)

        # Pay taxa -> eligible!
        self.slot_inter.is_taxa_aduaneira_paid = True
        self.slot_inter.save()
        pode, motivo = self.slot_inter.check_packaging_eligibility()
        self.assertTrue(pode)
        self.assertEqual(motivo, "")

    def test_mercari_packaging_eligibility(self):
        item = ItemIndividual.objects.create(
            nome='Card Mercari',
            preco_produto=Decimal('40.00'),
            frete_inter=Decimal('10.00'),
            taxa_aduaneira=Decimal('5.00'),
            comprador=self.participant,
            caixa=self.caixa,
            produto_pago=True,
            frete_inter_pago=False,
            taxa_aduaneira_paga=False
        )
        self.caixa.status = 'EM_TRANSITO'
        self.caixa.save()

        pode, motivo = item.check_packaging_eligibility()
        self.assertFalse(pode)
        self.assertIn("trânsito internacional", motivo)

        self.caixa.status = 'ENTREGUE'
        self.caixa.save()
        pode, motivo = item.check_packaging_eligibility()
        self.assertFalse(pode)
        self.assertIn("Frete internacional pendente", motivo)

        item.frete_inter_pago = True
        item.taxa_aduaneira_paga = True
        item.save()
        pode, motivo = item.check_packaging_eligibility()
        self.assertTrue(pode)

    def test_solicitar_envio_nacional_flow(self):
        # Make slot_nat eligible
        self.slot_nat.is_item_paid = True
        self.slot_nat.save()

        # Log in participant session
        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        response = self.client.post('/me/envios/solicitar/', {
            'selected_uids': f'slot_{self.slot_nat.id}',
            'observacoes': 'Por favor embalar com carinho!'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('tab=caixinha', response.url)

        pacote = PacoteNacional.objects.filter(participant=self.participant).first()
        self.assertIsNotNone(pacote)
        self.assertEqual(pacote.status, PacoteNacional.Status.SOLICITADO)
        self.assertEqual(pacote.observacoes_joiner, 'Por favor embalar com carinho!')
        self.assertIn(self.slot_nat, pacote.slots.all())

        # Once in a SOLICITADO package, slot cannot be requested again
        self.slot_nat.refresh_from_db()
        pode, motivo = self.slot_nat.check_packaging_eligibility()
        self.assertFalse(pode)
        self.assertIn("Já no pacote", motivo)

    def test_cancelar_solicitacao_envio_flow(self):
        self.slot_nat.is_item_paid = True
        self.slot_nat.save()

        pacote = PacoteNacional.objects.create(
            participant=self.participant,
            status=PacoteNacional.Status.SOLICITADO
        )
        self.slot_nat.pacote_nacional = pacote
        self.slot_nat.save()

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        response = self.client.post(f'/me/pacotes/{pacote.id}/cancelar-solicitacao/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('tab=caixinha', response.url)

        self.assertFalse(PacoteNacional.objects.filter(id=pacote.id).exists())
        self.slot_nat.refresh_from_db()
        self.assertIsNone(self.slot_nat.pacote_nacional)
        self.assertTrue(self.slot_nat.pode_empacotar)

    def test_configuracao_envio_google_form(self):
        self.client.force_login(self.staff_user)

        response = self.client.post('/envios/configuracao/', {
            'link_formulario_google': 'https://forms.google.com/test-form-link',
            'instrucoes_envio': 'Preencha com o mesmo nome do WhatsApp'
        })
        self.assertEqual(response.status_code, 302)

        config = ConfiguracaoEnvio.get_solo()
        self.assertEqual(config.link_formulario_google, 'https://forms.google.com/test-form-link')
        self.assertEqual(config.instrucoes_envio, 'Preencha com o mesmo nome do WhatsApp')

    def test_empacotar_itens_rejects_ineligible_items(self):
        self.client.force_login(self.staff_user)

        # slot_nat is unpaid -> ineligible for packing by GOM
        response = self.client.post(reverse('empacotar_itens'), {
            'participant_id': self.participant.id,
            'selected_uids': f'slot_{self.slot_nat.id}',
            'action_type': 'novo_pacote'
        })
        self.assertEqual(response.status_code, 302)

        # No package should be created
        self.assertFalse(PacoteNacional.objects.filter(participant=self.participant).exists())
