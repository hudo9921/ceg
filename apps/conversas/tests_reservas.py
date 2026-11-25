"""Reservar na Vitrine (S5b): estoque, conversa com aviso, pagamento pelo Pix e ações do GOM."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import ItemVitrine
from apps.goms.models import Gom, GomMembership
from apps.pagamentos import services as pix
from apps.participants.models import Participant

from .models import Conversa, ReservaVitrine

User = get_user_model()


class ReservaTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja V', slug='loja-vr', default_pix_key='loja@pix.com',
                                      pix_nome_recebedor='Loja V', pix_cidade='Sao Paulo')
        self.item = ItemVitrine.objects.create(gom=self.gom, titulo='PC Karina POB', preco=Decimal('45'), quantidade=1)
        self.ana = Participant.objects.create(whatsapp='5511944440001', name='Ana')
        self.staff = User.objects.create_user('dono-vr', password='x')
        GomMembership.objects.create(user=self.staff, gom=self.gom, role='OWNER')

    def _as(self, p):
        session = self.client.session
        session['participant_id'] = p.id
        session.save()

    def test_reserve_opens_conversation_and_blocks_stock(self):
        self._as(self.ana)
        res = self.client.post(reverse('vitrine_reservar', args=[self.item.slug]))
        c = Conversa.objects.get()
        self.assertRedirects(res, reverse('joiner_mensagens') + f'?c={c.id}', fetch_redirect_response=False)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'RESERVADO')
        self.assertIn('reservou', c.mensagens.get().texto)
        self.assertTrue(self.gom.notificacoes.exists())
        bia = Participant.objects.create(whatsapp='5511944440002', name='Bia')
        self._as(bia)
        self.client.post(reverse('vitrine_reservar', args=[self.item.slug]))
        self.assertEqual(ReservaVitrine.objects.count(), 1)

    def test_paid_by_pix_marks_sold(self):
        self._as(self.ana)
        self.client.post(reverse('vitrine_reservar', args=[self.item.slug]))
        r = ReservaVitrine.objects.get()
        page = self.client.get(reverse('my_claims') + '?tab=pagar').content.decode()
        self.assertIn(f'value="item:vitrine:{r.id}"', page)
        cob = pix.create_cobrancas(self.ana, self.gom, [f'item:vitrine:{r.id}'])[0]
        self.assertEqual(cob.valor_total, Decimal('45'))
        pix.confirmar(cob, self.staff)
        r.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual((r.status, self.item.status), ('PAGA', 'VENDIDO'))

    def test_gom_cancels_and_item_returns(self):
        self._as(self.ana)
        self.client.post(reverse('vitrine_reservar', args=[self.item.slug]))
        r = ReservaVitrine.objects.get()
        self.client.force_login(self.staff)
        self.client.post(reverse('gom_reserva_acao', args=[r.id, 'cancelar']))
        r.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual((r.status, self.item.status), ('CANCELADA', 'DISPONIVEL'))

    def test_gom_marks_paid_in_person(self):
        self._as(self.ana)
        self.client.post(reverse('vitrine_reservar', args=[self.item.slug]))
        r = ReservaVitrine.objects.get()
        self.client.force_login(self.staff)
        self.client.post(reverse('gom_reserva_acao', args=[r.id, 'paga']))
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'VENDIDO')

    def test_stock_of_two_allows_two_reservations(self):
        self.item.quantidade = 2
        self.item.save()
        self._as(self.ana)
        self.client.post(reverse('vitrine_reservar', args=[self.item.slug]))
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'DISPONIVEL')

    def test_other_gom_cannot_act_on_reservation(self):
        self._as(self.ana)
        self.client.post(reverse('vitrine_reservar', args=[self.item.slug]))
        r = ReservaVitrine.objects.get()
        other = User.objects.create_user('dono-outra-vr', password='x')
        GomMembership.objects.create(user=other, gom=Gom.objects.create(name='X', slug='x-vr'), role='OWNER')
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse('gom_reserva_acao', args=[r.id, 'cancelar'])).status_code, 404)

    def test_vitrine_page_works_for_item_without_type_and_shows_reservar(self):
        self._as(self.ana)
        res = self.client.get(reverse('vitrine_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, reverse('vitrine_reservar', args=[self.item.slug]))
        self.client.post(reverse('vitrine_reservar', args=[self.item.slug]))
        self.assertIn('R$ 45,00', Conversa.objects.get().mensagens.get().texto)

    def test_comprar_agora_creates_pix_and_opens_it(self):
        from apps.pagamentos.models import Cobranca
        self._as(self.ana)
        res = self.client.post(reverse('vitrine_comprar', args=[self.item.slug]))
        cob = Cobranca.objects.get()
        self.assertRedirects(res, reverse('my_claims') + f'?tab=pagar&pix={cob.referencia}', fetch_redirect_response=False)
        self.assertEqual(cob.valor_total, Decimal('45'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'RESERVADO')
        page = self.client.get(reverse('my_claims') + f'?tab=pagar&pix={cob.referencia}').content.decode()
        self.assertIn(f'data-refs="{cob.referencia} "', page)

    def test_comprar_without_pix_setup_falls_back_to_reservation(self):
        self.gom.pix_cidade = ''
        self.gom.save()
        self._as(self.ana)
        res = self.client.post(reverse('vitrine_comprar', args=[self.item.slug]))
        c = Conversa.objects.get()
        self.assertRedirects(res, reverse('joiner_mensagens') + f'?c={c.id}', fetch_redirect_response=False)
        self.assertEqual(ReservaVitrine.objects.get().status, 'RESERVADA')
