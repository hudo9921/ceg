from django.test import TestCase, TransactionTestCase, Client
from django.utils import timezone
from datetime import timedelta
import threading
from apps.groups.models import KpopGroup, Era
from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot
from apps.cegs.services import ClaimService, CEGNotOpenYetError, SlotUnavailableError
from apps.participants.models import Participant, Claim
from apps.auth_otp.services import OTPService
from apps.analytics.services import AnalyticsService


class CEGConcurrencyAndStandbyTests(TransactionTestCase):
    def setUp(self):
        self.group = KpopGroup.objects.create(name='Test Group', slug='test-group')
        self.era = Era.objects.create(group=self.group, name='Test Era', slug='test-era')

        # CEG Aberta
        self.open_ceg = CEG.objects.create(
            era=self.era,
            title='CEG Open Test',
            slug='ceg-open-test',
            status=CEG.Status.OPEN,
            opens_at=timezone.now() - timedelta(hours=1),
            pix_key='pix@test.com'
        )
        self.item_def = CEGItemDefinition.objects.create(
            ceg=self.open_ceg,
            name='Photocard Leader',
            member_name='Leader',
            default_price=50.00
        )
        self.cset = CEGSet.objects.create(ceg=self.open_ceg, set_number=1)
        self.cset.generate_slots()
        self.slot = self.cset.slots.first()

        # CEG em Standby (futura)
        self.future_ceg = CEG.objects.create(
            era=self.era,
            title='CEG Future Test',
            slug='ceg-future-test',
            status=CEG.Status.SCHEDULED,
            opens_at=timezone.now() + timedelta(hours=2),
            pix_key='pix@test.com'
        )
        self.future_item_def = CEGItemDefinition.objects.create(
            ceg=self.future_ceg,
            name='Photocard Future',
            member_name='Maknae',
            default_price=40.00
        )
        self.future_set = CEGSet.objects.create(ceg=self.future_ceg, set_number=1)
        self.future_set.generate_slots()
        self.future_slot = self.future_set.slots.first()

    def test_standby_prevents_claim_before_opening(self):
        """Verifica que o backend bloqueia qualquer claim feito antes de opens_at"""
        with self.assertRaises(CEGNotOpenYetError):
            ClaimService.claim_slot(
                slot_id=self.future_slot.id,
                name='User Antecipado',
                phone='5511999990001'
            )

    def test_successful_single_claim(self):
        """Verifica que um claim normal no slot disponível é concluído com sucesso"""
        claim = ClaimService.claim_slot(
            slot_id=self.slot.id,
            name='Beatriz Kpop',
            phone='5511988887777',
            social_handle='@biakpop'
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.status, Claim.Status.PENDING)
        self.assertEqual(claim.total_price, 50.00)
        self.assertEqual(claim.participant.whatsapp, '5511988887777')

        # Slot deve estar RESERVED
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, ItemSlot.Status.RESERVED)
        self.assertEqual(self.slot.claimed_by.name, 'Beatriz Kpop')

        # Marca como pago e verifica atualização
        claim.mark_as_paid()
        self.assertEqual(claim.status, Claim.Status.PAID)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, ItemSlot.Status.PAID)

    def test_concurrency_race_condition(self):
        """
        Simula múltiplos participantes disputando o MESMO slot no milissegundo zero.
        Apenas 1 DEVE vencer e o outro DEVE receber erro de contenção/indisponibilidade.
        """
        results = []
        errors = []

        from django.db import connection
        def attempt_claim(user_idx):
            try:
                c = ClaimService.claim_slot(
                    slot_id=self.slot.id,
                    name=f'User {user_idx}',
                    phone=f'551199999000{user_idx}',
                    social_handle=f'@user{user_idx}'
                )
                results.append(c)
            except Exception as e:
                errors.append(e)
            finally:
                connection.close()

        # Dispara 2 threads concorrentes para o mesmo slot físico
        threads = [threading.Thread(target=attempt_claim, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 1, f"Exatamente 1 participante deve conseguir reservar o slot. Erros: {errors}")
        self.assertEqual(len(errors), 1, "O outro deve ter recebido erro de slot indisponível.")
        self.assertIsInstance(errors[0], SlotUnavailableError)


class OTPServiceTests(TestCase):
    def test_otp_send_and_verify_cycle(self):
        phone = '5511987654321'
        success, msg, dev_code = OTPService.send_otp(phone)
        self.assertTrue(success)
        self.assertIsNotNone(dev_code)
        self.assertEqual(len(dev_code), 6)

        # Tentativa com código incorreto
        v_success, v_msg, p = OTPService.verify_otp(phone, '000000')
        self.assertFalse(v_success)
        self.assertIsNone(p)

        # Tentativa com o código correto
        v_success, v_msg, p = OTPService.verify_otp(phone, dev_code)
        self.assertTrue(v_success)
        self.assertIsNotNone(p)
        self.assertEqual(p.whatsapp, phone)

        # Tentar reutilizar o mesmo código já usado deve falhar
        v_success2, v_msg2, _ = OTPService.verify_otp(phone, dev_code)
        self.assertFalse(v_success2)


class ViewsAndAnalyticsIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.group = KpopGroup.objects.create(name='tripleS', slug='triples')
        self.era = Era.objects.create(group=self.group, name='ASSEMBLE24', slug='assemble24')
        self.ceg = CEG.objects.create(
            era=self.era,
            title='CEG tripleS Test',
            slug='ceg-triples-test',
            status=CEG.Status.OPEN,
            opens_at=timezone.now() - timedelta(hours=1),
            pix_key='triples@pix.com'
        )
        self.item1 = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Photocard Seoyeon',
            member_name='Seoyeon',
            default_price=35.00,
            order_index=1
        )
        self.item2 = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Photocard Hyerin',
            member_name='Hyerin',
            default_price=35.00,
            order_index=2
        )
        self.set1 = CEGSet.objects.create(ceg=self.ceg, set_number=1)
        self.set1.generate_slots()

    def test_home_page_renders_ok(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'CEG tripleS Test')

    def test_ceg_detail_page_renders_ok(self):
        response = self.client.get(f'/ceg/{self.ceg.slug}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Photocard Seoyeon')
        self.assertContains(response, 'Photocard Hyerin')

    def test_claim_flow_via_post_and_my_claims(self):
        slot = self.set1.slots.first()
        post_data = {
            'name': 'Mariana Souza',
            'whatsapp': '5511944445555',
            'social_handle': '@mari_kpop',
            'notes': 'Por favor caprichar no toploader!'
        }
        response = self.client.post(f'/slots/{slot.id}/claim/', data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verifica que o slot agora está reservado
        slot.refresh_from_db()
        self.assertEqual(slot.status, ItemSlot.Status.RESERVED)
        self.assertEqual(slot.claimed_by.name, 'Mariana Souza')

        # Como a sessão é atualizada, acessar /me/ deve listar o claim
        me_response = self.client.get('/me/')
        self.assertEqual(me_response.status_code, 200)
        self.assertContains(me_response, 'Mariana Souza')
        self.assertContains(me_response, 'Photocard Seoyeon')
        self.assertContains(me_response, 'triples@pix.com')

    def test_analytics_metrics_calculations(self):
        # Cria um claim e marca como pago
        slot = self.set1.slots.first()
        claim = ClaimService.claim_slot(
            slot_id=slot.id,
            name='Teste Analitica',
            phone='5511999991234'
        )
        claim.mark_as_paid()

        summary = AnalyticsService.get_summary_metrics()
        self.assertGreater(summary['total_paid'], 0)
        self.assertEqual(summary['total_participants'], 1)

        members = AnalyticsService.get_member_popularity()
        self.assertGreater(len(members), 0)
        self.assertEqual(members[0]['member_name'], 'Seoyeon')

        sets_near = AnalyticsService.get_sets_near_completion()
        self.assertEqual(len(sets_near), 1)
        self.assertEqual(sets_near[0]['set_number'], 1)

        # Testa visualização do dashboard de analítica
        response = self.client.get('/analytics/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Seoyeon')
        self.assertContains(response, 'ASSEMBLE24')
