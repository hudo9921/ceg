from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.cegs.audit_service import AuditService
from apps.cegs.models import (
    CEG,
    CEGItemDefinition,
    CEGSet,
    ItemSlot,
    PacoteNacional,
    AuditLog,
    GOMNotification,
)
from apps.groups.models import KpopGroup, Era
from apps.participants.models import Participant

User = get_user_model()


class GOMNotificationsTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='gom_staff',
            password='password123',
            is_staff=True,
        )
        self.regular_user = User.objects.create_user(
            username='regular_joiner',
            password='password123',
            is_staff=False,
        )
        self.participant = Participant.objects.create(
            name='Jihyo Park',
            whatsapp='5511999998888',
        )
        self.group = KpopGroup.objects.create(name='TWICE')
        self.era = Era.objects.create(group=self.group, name='With YOU-th')
        self.ceg = CEG.objects.create(
            era=self.era,
            title='CEG TWICE With YOU-th',
            slug='ceg-twice-with-youth',
        )
        self.item_def = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Photocard Jihyo',
            member_name='Jihyo',
            default_price=35.00,
        )
        self.set_obj = CEGSet.objects.create(ceg=self.ceg, set_number=1)
        self.slot = ItemSlot.objects.create(
            set=self.set_obj,
            item_definition=self.item_def,
            price=35.00,
        )

    def test_access_restrictions(self):
        """Acesso anônimo ou usuário comum é bloqueado; staff tem acesso 200 OK."""
        # 1. Anônimo -> redireciona para login
        res_anon = self.client.get('/notificacoes/')
        self.assertEqual(res_anon.status_code, 302)

        # 2. Usuário normal (não-staff) -> 403 Forbidden
        self.client.force_login(self.regular_user)
        res_normal = self.client.get('/notificacoes/')
        self.assertEqual(res_normal.status_code, 403)

        # 3. Staff -> 200 OK
        self.client.force_login(self.staff_user)
        res_staff = self.client.get('/notificacoes/')
        self.assertEqual(res_staff.status_code, 200)
        self.assertContains(res_staff, 'Central de Notificações')

    def test_filter_by_action_type_and_unread(self):
        """Testa filtros por tipo de ação (claims, solicitações, pagamentos) e status de leitura."""
        self.client.force_login(self.staff_user)

        # Cria notificações manuais de teste
        notif_claim = GOMNotification.objects.create(
            notification_type=GOMNotification.NotificationType.CLAIM,
            title='Novo Claim: Jihyo',
            message='Jihyo Park reservou o photocard Jihyo.',
            participant=self.participant,
            ceg=self.ceg,
            slot=self.slot,
            is_read=False,
        )
        notif_pkg = GOMNotification.objects.create(
            notification_type=GOMNotification.NotificationType.PACKAGE_REQUEST,
            title='Solicitação de Envio: Pacote #10',
            message='Jihyo Park pediu envio de itens.',
            participant=self.participant,
            is_read=True,
        )

        # Filtro claims
        res_claims = self.client.get('/notificacoes/?action_type=claims')
        self.assertEqual(res_claims.status_code, 200)
        self.assertContains(res_claims, 'Novo Claim: Jihyo')
        self.assertNotContains(res_claims, 'Solicitação de Envio: Pacote #10')

        # Filtro solicitações
        res_pkg_view = self.client.get('/notificacoes/?action_type=solicitacoes')
        self.assertEqual(res_pkg_view.status_code, 200)
        self.assertContains(res_pkg_view, 'Solicitação de Envio: Pacote #10')
        self.assertNotContains(res_pkg_view, 'Novo Claim: Jihyo')

        # Filtro não lidas
        res_unread = self.client.get('/notificacoes/?unread=true')
        self.assertEqual(res_unread.status_code, 200)
        self.assertContains(res_unread, 'Novo Claim: Jihyo')
        self.assertNotContains(res_unread, 'Solicitação de Envio: Pacote #10')

    def test_mark_single_notification_read_ajax(self):
        """Testa marcar notificação individual como lida via endpoint AJAX (/notificacoes/ e /cegs/notificacoes/)."""
        self.client.force_login(self.staff_user)

        notif = GOMNotification.objects.create(
            notification_type=GOMNotification.NotificationType.CLAIM,
            title='Claim Teste',
            message='Mensagem de teste',
            is_read=False,
        )

        # 1. Rota padrão /notificacoes/
        url = f'/notificacoes/{notif.id}/read/'
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['notification_id'], notif.id)

        notif.refresh_from_db()
        self.assertTrue(notif.is_read)
        self.assertIsNotNone(notif.read_at)

        # 2. Rota alias /cegs/notificacoes/
        notif2 = GOMNotification.objects.create(
            notification_type=GOMNotification.NotificationType.PACKAGE_REQUEST,
            title='Envio Teste',
            message='Mensagem envio',
            is_read=False,
        )
        url_alias = f'/cegs/notificacoes/{notif2.id}/read/'
        res_alias = self.client.post(url_alias)
        self.assertEqual(res_alias.status_code, 200)
        self.assertTrue(res_alias.json()['success'])
        notif2.refresh_from_db()
        self.assertTrue(notif2.is_read)

    def test_mark_all_notifications_read_ajax(self):
        """Testa marcar todas as notificações não lidas como lidas via endpoints AJAX (/notificacoes/ e /cegs/notificacoes/)."""
        self.client.force_login(self.staff_user)
        GOMNotification.objects.all().delete()

        GOMNotification.objects.create(
            notification_type=GOMNotification.NotificationType.CLAIM,
            title='Claim 1',
            message='Desc',
            is_read=False,
        )
        GOMNotification.objects.create(
            notification_type=GOMNotification.NotificationType.PACKAGE_REQUEST,
            title='Envio 1',
            message='Desc',
            is_read=False,
        )

        self.assertEqual(GOMNotification.objects.filter(is_read=False).count(), 2)

        res = self.client.post('/notificacoes/read-all/', {'action_type': 'all'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(GOMNotification.objects.filter(is_read=False).count(), 0)

        # Cria mais uma e testa rota alias
        GOMNotification.objects.create(
            notification_type=GOMNotification.NotificationType.PAYMENT,
            title='Pagamento 1',
            message='Desc',
            is_read=False,
        )
        res_alias = self.client.post('/cegs/notificacoes/read-all/', {'action_type': 'all'})
        self.assertEqual(res_alias.status_code, 200)
        self.assertEqual(GOMNotification.objects.filter(is_read=False).count(), 0)

    def test_auto_create_gom_notification_from_audit_event(self):
        """Testa se a criação de eventos via AuditService gera automaticamente a GOMNotification."""
        # 1. Evento de Claim
        log_claim = AuditService.log_event(
            event_type=AuditLog.EventType.CLAIM_SUCCESS,
            action_label='Claim Garantido Jihyo',
            participant=self.participant,
            ceg=self.ceg,
            slot=self.slot,
        )
        self.assertIsNotNone(log_claim)

        notif_claim = GOMNotification.objects.filter(
            notification_type=GOMNotification.NotificationType.CLAIM,
            participant=self.participant,
        ).first()
        self.assertIsNotNone(notif_claim)
        self.assertIn('Novo Claim', notif_claim.title)
        self.assertEqual(notif_claim.ceg, self.ceg)

        # 2. Evento de Solicitação de Pacote
        pacote = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PKG-TEST-01',
            status=PacoteNacional.Status.SOLICITADO,
        )
        log_pkg = AuditService.log_event(
            event_type=AuditLog.EventType.PACKAGE_REQUESTED,
            action_label='Solicitação de Envio',
            participant=self.participant,
            pacote_nacional=pacote,
        )
        self.assertIsNotNone(log_pkg)

        notif_pkg = GOMNotification.objects.filter(
            notification_type=GOMNotification.NotificationType.PACKAGE_REQUEST,
            pacote_nacional=pacote,
        ).first()
        self.assertIsNotNone(notif_pkg)
        self.assertIn('Solicitação de Envio', notif_pkg.title)
