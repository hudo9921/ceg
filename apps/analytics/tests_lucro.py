"""Lucro por CEG: custo em moeda estrangeira × câmbio + taxas contra o vendido dos itens."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot
from apps.goms.models import Gom, GomMembership
from apps.goms.services import set_permissions
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Claim, Participant

User = get_user_model()


class LucroTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja L', slug='loja-l')
        self.owner = User.objects.create_user('dono-l', password='x')
        GomMembership.objects.create(user=self.owner, gom=self.gom, role='OWNER')
        self.client.force_login(self.owner)
        era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa-l'), name='Rich', slug='rich-l')
        self.ceg = CEG.objects.create(era=era, gom=self.gom, title='CEG L', slug='ceg-l', status=CEG.Status.OPEN)
        idef = CEGItemDefinition.objects.create(ceg=self.ceg, name='PC', default_price=40)
        cset = CEGSet.objects.create(ceg=self.ceg, set_number=1)
        joiner = Participant.objects.create(whatsapp='5511911110000', name='J')
        for i, status in enumerate(('PAID', 'PENDING', 'CANCELLED')):
            slot = ItemSlot.objects.create(set=cset, item_definition=idef, unit_number=i + 1, price=Decimal('40'), claimed_by=joiner,
                                           status=ItemSlot.Status.RESERVED)
            Claim.objects.create(slot=slot, participant=joiner, status=status, total_price=Decimal('40'))

    def test_custo_in_won_converts_and_profit(self):
        self.client.post(reverse('lucro_cegs'), {'ceg_id': self.ceg.id, 'custo_moeda': 'KRW', 'custo_valor': '10000',
                                                 'custo_cambio': '0.004', 'custo_taxas_brl': '5', 'custo_obs': ''})
        self.ceg.refresh_from_db()
        self.assertEqual(self.ceg.custo_brl, Decimal('45.00'))
        row = self.client.get(reverse('lucro_cegs')).context['rows'][0]
        self.assertEqual((row['vendido'], row['recebido'], row['lucro'], row['margem']),
                         (Decimal('80'), Decimal('40'), Decimal('35.00'), 44))

    def test_foreign_currency_needs_rate(self):
        self.client.post(reverse('lucro_cegs'), {'ceg_id': self.ceg.id, 'custo_moeda': 'JPY', 'custo_valor': '5000'})
        self.ceg.refresh_from_db()
        self.assertIsNone(self.ceg.custo_valor)

    def test_other_gom_ceg_cannot_be_edited(self):
        other = CEG.objects.create(era=self.ceg.era, gom=Gom.objects.create(name='X', slug='x-l'), title='Alheia', slug='alheia-l')
        res = self.client.post(reverse('lucro_cegs'), {'ceg_id': other.id, 'custo_moeda': 'BRL', 'custo_valor': '1'})
        self.assertEqual(res.status_code, 404)

    def test_needs_reports_permission(self):
        admin = User.objects.create_user('adm-l', password='x')
        set_permissions(GomMembership.objects.create(user=admin, gom=self.gom, role='ADMIN'), ['ceg.editar'], self.owner)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('lucro_cegs')).status_code, 403)
