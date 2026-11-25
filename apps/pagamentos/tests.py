"""Cobranças Pix (S1): o que está em aberto, divisão por chave, Já paguei, Recebi e Não recebi."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemIndividual, ItemSlot, PacoteNacional
from apps.goms.models import Gom
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Claim, Participant

from . import services
from .models import Cobranca
from .pix import crc16

User = get_user_model()


class CobrancaFixture(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja Pix', slug='loja-pix', default_pix_key='loja@pix.com',
                                      pix_nome_recebedor='Loja Pix LTDA', pix_cidade='Sao Paulo')
        era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa-pg'), name='Rich', slug='rich-pg')
        self.ceg = CEG.objects.create(era=era, gom=self.gom, title='CEG Pix', slug='ceg-pix', status=CEG.Status.OPEN)
        idef = CEGItemDefinition.objects.create(ceg=self.ceg, name='PC Karina', default_price=40)
        self.joiner = Participant.objects.create(whatsapp='5511933332222', name='Ana')
        cset = CEGSet.objects.create(ceg=self.ceg, set_number=1)
        self.slot = ItemSlot.objects.create(set=cset, item_definition=idef, price=Decimal('40'), claimed_by=self.joiner,
                                            status=ItemSlot.Status.RESERVED, frete_inter_valor=Decimal('12.50'))
        self.claim = Claim.objects.create(slot=self.slot, participant=self.joiner, status=Claim.Status.PENDING,
                                          total_price=Decimal('40'))
        self.staff = User.objects.create_user('equipe-pix', password='x')


class OpenUnitsAndCreateTests(CobrancaFixture):
    def test_open_groups_list_item_and_freight(self):
        groups = services.open_groups(self.joiner, self.gom)
        self.assertEqual([(g['tipo'], g['total']) for g in groups], [('item', Decimal('40')), ('frete', Decimal('12.50'))])

    def test_create_one_pix_per_key_and_valid_brcode(self):
        cobs = services.create_cobrancas(self.joiner, self.gom, ['item:ceg:%d' % self.ceg.id, 'frete:ceg:%d' % self.ceg.id])
        self.assertEqual(len(cobs), 1)
        cob = cobs[0]
        self.assertEqual(cob.valor_total, Decimal('52.50'))
        self.assertIn('5405' + '52.50', cob.copia_e_cola)
        self.assertEqual(cob.copia_e_cola[-4:], crc16(cob.copia_e_cola[:-4]))
        self.assertIn(cob.referencia.replace('-', ''), cob.copia_e_cola)

    def test_different_keys_split_into_two_pix(self):
        self.ceg.pix_key_frete = '+55 11 98765-4321'
        self.ceg.save()
        cobs = services.create_cobrancas(self.joiner, self.gom, ['item:ceg:%d' % self.ceg.id, 'frete:ceg:%d' % self.ceg.id])
        self.assertEqual(sorted(c.chave_pix for c in cobs), ['+5511987654321', 'loja@pix.com'])

    def test_units_in_open_charge_are_not_offered_again(self):
        services.create_cobrancas(self.joiner, self.gom, ['item:ceg:%d' % self.ceg.id])
        self.assertEqual([g['tipo'] for g in services.open_groups(self.joiner, self.gom)], ['frete'])

    def test_needs_receiver_and_valid_key(self):
        self.gom.pix_cidade = ''
        self.gom.save()
        with self.assertRaises(services.CobrancaError):
            services.create_cobrancas(self.joiner, self.gom, ['item:ceg:%d' % self.ceg.id])
        self.gom.pix_cidade = 'Sao Paulo'
        self.gom.default_pix_key = 'Nubank chave CPF'
        self.gom.save()
        with self.assertRaises(services.CobrancaError):
            services.create_cobrancas(self.joiner, self.gom, ['item:ceg:%d' % self.ceg.id])


class ResolveTests(CobrancaFixture):
    def _cob(self, *groups):
        return services.create_cobrancas(self.joiner, self.gom, list(groups))[0]

    def test_recebi_marks_everything_paid_and_notifies(self):
        cob = self._cob('item:ceg:%d' % self.ceg.id, 'frete:ceg:%d' % self.ceg.id)
        services.informar(cob, (b'%PDF-1.4', 'application/pdf'))
        cob.refresh_from_db()
        self.assertEqual(cob.status, Cobranca.Status.INFORMADA)
        self.assertTrue(self.gom.notificacoes.filter(title__startswith='Pix avisado').exists())
        services.confirmar(cob, self.staff)
        self.slot.refresh_from_db()
        self.claim.refresh_from_db()
        self.assertTrue(self.slot.is_item_paid and self.slot.is_frete_inter_paid)
        self.assertEqual(self.claim.status, Claim.Status.PAID)
        self.assertEqual(services.open_groups(self.joiner, self.gom), [])
        self.assertTrue(self.joiner.notifications.filter(title='Pagamento confirmado').exists())

    def test_nao_recebi_keeps_units_blocked_until_cancel(self):
        cob = self._cob('item:ceg:%d' % self.ceg.id)
        services.recusar(cob, self.staff, 'Não caiu ainda')
        self.slot.refresh_from_db()
        self.assertFalse(self.slot.is_item_paid)
        self.assertEqual([g['tipo'] for g in services.open_groups(self.joiner, self.gom)], ['frete'])
        services.cancelar(cob)
        self.assertEqual(len(services.open_groups(self.joiner, self.gom)), 2)

    def test_cannot_confirm_twice(self):
        cob = self._cob('item:ceg:%d' % self.ceg.id)
        services.confirmar(cob, self.staff)
        with self.assertRaises(services.CobrancaError):
            services.confirmar(cob, self.staff)

    def test_avulso_and_national_freight(self):
        item = ItemIndividual.objects.create(gom=self.gom, nome='Album', comprador=self.joiner,
                                             preco_produto=Decimal('90'), produto_pago=False)
        pacote = PacoteNacional.objects.create(gom=self.gom, participant=self.joiner, valor_frete_nacional=Decimal('22'))
        cob = self._cob('item:avulso:%d' % item.id, 'frete_nacional:pacote:%d' % pacote.id)
        services.confirmar(cob, self.staff)
        item.refresh_from_db()
        pacote.refresh_from_db()
        self.assertTrue(item.produto_pago and pacote.is_frete_pago)
