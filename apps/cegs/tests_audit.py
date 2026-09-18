from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot, ClaimAttemptLog, AuditLog
from apps.groups.models import KpopGroup, Era
from apps.participants.models import Participant
from apps.cegs.audit_service import AuditService

User = get_user_model()


class AuditLogSystemTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username='staff_admin',
            password='password123',
            is_staff=True
        )
        self.non_staff_user = User.objects.create_user(
            username='normal_user',
            password='password123',
            is_staff=False
        )

        self.group = KpopGroup.objects.create(name='TWICE')
        self.era = Era.objects.create(group=self.group, name='With YOU-th')
        self.ceg = CEG.objects.create(
            title='CEG TWICE With YOU-th Digipack',
            era=self.era,
            status=CEG.Status.OPEN,
            frete_inter=15.00,
            taxa_aduaneira=8.00,
        )
        self.set_obj = CEGSet.objects.create(ceg=self.ceg, set_number=1)
        self.item_def = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Photocard Jihyo',
            order_index=1
        )
        self.slot = ItemSlot.objects.create(
            set=self.set_obj,
            item_definition=self.item_def,
            price=30.00,
            status=ItemSlot.Status.AVAILABLE
        )

    def test_account_creation_auto_logs(self):
        """Ao criar um participante, um registro de AuditLog deve ser criado automaticamente via signal."""
        p = Participant.objects.create(
            name='Momo Hirai',
            whatsapp='5511988887777',
            social_handle='@momo'
        )

        log = AuditLog.objects.filter(
            event_type=AuditLog.EventType.ACCOUNT_CREATED,
            participant=p
        ).first()

        self.assertIsNotNone(log)
        self.assertEqual(log.participant_name, 'Momo Hirai')
        self.assertEqual(log.participant_phone, '5511988887777')
        self.assertIn('Momo Hirai', log.action_label)

    def test_claim_attempt_auto_logs(self):
        """Ao registrar uma tentativa de claim, um AuditLog correspondente deve ser gerado."""
        claim_log = ClaimAttemptLog.objects.create(
            slot=self.slot,
            attempt_number=1,
            participant_name='Sana Minatozaki',
            phone='5511977776666',
            social_handle='@sanacute',
            result=ClaimAttemptLog.Result.SUCCESS,
            details='Venceu corrida de claim'
        )

        audit = AuditLog.objects.filter(
            event_type=AuditLog.EventType.CLAIM_SUCCESS,
            slot=self.slot
        ).first()

        self.assertIsNotNone(audit)
        self.assertEqual(audit.participant_name, 'Sana Minatozaki')
        self.assertEqual(audit.participant_phone, '5511977776666')
        self.assertIn('Sana Minatozaki', audit.action_label)

    def test_toggle_payment_audit_logging(self):
        """Ao alternar status de pagamento de um slot, o evento e o usuário staff devem ser auditados."""
        p = Participant.objects.create(name='Nayeon Im', whatsapp='5511966665555')
        self.slot.claimed_by = p
        self.slot.save()

        # 1. Marca item como pago
        new_val = self.slot.toggle_payment('is_item_paid', value=True, actor=self.staff_user)
        self.assertTrue(new_val)

        log_item = AuditLog.objects.filter(
            event_type=AuditLog.EventType.PAYMENT_ITEM,
            slot=self.slot
        ).first()

        self.assertIsNotNone(log_item)
        self.assertEqual(log_item.actor, self.staff_user)
        self.assertEqual(log_item.participant, p)
        self.assertEqual(log_item.old_value, 'Pendente ⏳')
        self.assertEqual(log_item.new_value, 'Pago ✔')

        # 2. Marca frete internacional como pago
        self.slot.toggle_payment('frete_inter', value=True, actor=self.staff_user)
        log_frete = AuditLog.objects.filter(
            event_type=AuditLog.EventType.PAYMENT_FRETE_INTER,
            slot=self.slot
        ).first()
        self.assertIsNotNone(log_frete)
        self.assertEqual(log_frete.new_value, 'Pago ✔')

        # 3. Marca taxa aduaneira como paga
        self.slot.toggle_payment('taxa_aduaneira', value=True, actor=self.staff_user)
        log_taxa = AuditLog.objects.filter(
            event_type=AuditLog.EventType.PAYMENT_TAXA,
            slot=self.slot
        ).first()
        self.assertIsNotNone(log_taxa)
        self.assertEqual(log_taxa.new_value, 'Pago ✔')

    def test_dashboard_view_staff_security(self):
        """Verifica que apenas usuários staff conseguem acessar a view de auditoria."""
        # Não autenticado
        res_anon = self.client.get('/auditoria/')
        self.assertEqual(res_anon.status_code, 302)

        # Autenticado mas não staff
        self.client.force_login(self.non_staff_user)
        res_user = self.client.get('/auditoria/')
        self.assertEqual(res_user.status_code, 403)

        # Staff autenticado
        self.client.force_login(self.staff_user)
        res_staff = self.client.get('/auditoria/')
        self.assertEqual(res_staff.status_code, 200)
        self.assertContains(res_staff, 'Auditoria & Logs do Sistema')

    def test_dashboard_filtering_and_csv_export(self):
        """Testa filtros e exportação para CSV."""
        self.client.force_login(self.staff_user)

        # Cria participante e claim para gerar logs
        p = Participant.objects.create(name='Mina Myoui', whatsapp='5511955554444')
        self.slot.claimed_by = p
        self.slot.save()
        self.slot.toggle_payment('is_item_paid', value=True, actor=self.staff_user)

        # Filtro por busca textual
        res_q = self.client.get('/auditoria/?q=Mina')
        self.assertEqual(res_q.status_code, 200)
        self.assertContains(res_q, 'Mina Myoui')

        # Filtro por tipo de evento
        res_ev = self.client.get(f'/auditoria/?event_type={AuditLog.EventType.PAYMENT_ITEM}')
        self.assertEqual(res_ev.status_code, 200)
        self.assertContains(res_ev, 'Pagamento Item')

        # Exportação CSV
        res_csv = self.client.get('/auditoria/?export=csv')
        self.assertEqual(res_csv.status_code, 200)
        self.assertEqual(res_csv['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="auditoria_logs_', res_csv['Content-Disposition'])
        content = res_csv.content.decode('utf-8')
        self.assertIn('Mina Myoui', content)
        self.assertIn('Pagamento do Item', content)
