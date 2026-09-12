from django.test import TestCase, Client
from apps.participants.models import Participant


class ParticipantProfileTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.participant = Participant.objects.create(
            name='Participante 2104',
            whatsapp='5581994222104',
            social_handle=''
        )

    def test_profile_update_successful_with_name_and_twitter(self):
        # Simula a sessão logada do participante
        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        post_data = {
            'name': 'Hudo Silva',
            'username': 'Hudo',
            'social_handle': 'hudokpop'  # Sem @, deve adicionar automaticamente
        }

        response = self.client.post('/me/profile/', data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        self.participant.refresh_from_db()
        self.assertEqual(self.participant.name, 'Hudo Silva')
        self.assertEqual(self.participant.username, 'Hudo')
        self.assertEqual(self.participant.display_name, 'Hudo')
        self.assertEqual(self.participant.social_handle, '@hudokpop')
        self.assertEqual(self.participant.whatsapp, '5581994222104')
        self.assertContains(response, 'Olá, Hudo! 👋')
        self.assertContains(response, 'Hudo Silva')
        self.assertContains(response, '@hudokpop')

    def test_profile_update_without_username_uses_name_as_display(self):
        # Username é opcional; quando vazio, display_name usa o nome completo
        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        post_data = {
            'name': 'Beatriz Lima da Silva',
            'username': '',  # Sem apelido
            'social_handle': ''
        }

        response = self.client.post('/me/profile/', data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        self.participant.refresh_from_db()
        self.assertEqual(self.participant.name, 'Beatriz Lima da Silva')
        self.assertEqual(self.participant.username, '')
        self.assertEqual(self.participant.display_name, 'Beatriz Lima da Silva')
        self.assertContains(response, 'Olá, Beatriz Lima da Silva! 👋')

    def test_display_name_property_fallback(self):
        p = Participant(name='Lucas Ferreira', username='Luke', whatsapp='5511988887777')
        self.assertEqual(p.display_name, 'Luke')

        p.username = ''
        self.assertEqual(p.display_name, 'Lucas Ferreira')

        p.name = ''
        self.assertEqual(p.display_name, 'Participante 7777')

    def test_profile_update_without_twitter_is_valid(self):
        # Twitter é opcional, apenas nome e whatsapp são obrigatórios
        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        post_data = {
            'name': 'Maria Oliveira',
            'username': '',
            'social_handle': ''  # Vazio
        }

        response = self.client.post('/me/profile/', data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        self.participant.refresh_from_db()
        self.assertEqual(self.participant.name, 'Maria Oliveira')
        self.assertEqual(self.participant.social_handle, '')

    def test_profile_update_fails_when_name_is_empty(self):
        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        post_data = {
            'name': '   ',  # Nome vazio
            'username': 'ApelidoSemNome',
            'social_handle': '@teste'
        }

        response = self.client.post('/me/profile/', data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'O nome do participante é obrigatório.')

        # Não deve alterar no banco
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.name, 'Participante 2104')

    def test_profile_update_redirects_if_unauthenticated(self):
        response = self.client.post('/me/profile/', data={'name': 'Anonimo'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Consulta Sem Senha')

    def test_my_claims_view_metrics_and_filters(self):
        from apps.groups.models import KpopGroup, Era
        from apps.cegs.models import CEG, CEGSet, CEGItemDefinition, ItemSlot
        from apps.participants.models import Claim
        from django.utils import timezone

        group = KpopGroup.objects.create(name='tripleS')
        era = Era.objects.create(group=group, name='ASSEMBLE24')
        ceg = CEG.objects.create(
            era=era,
            title='CEG POB Withmuu',
            opens_at=timezone.now() - timezone.timedelta(hours=1),
            pix_key='chave@pix.com'
        )
        set_obj = CEGSet.objects.create(ceg=ceg, set_number=1)
        item1 = CEGItemDefinition.objects.create(ceg=ceg, name='POB HyeRin', item_type='PHOTOCARD')
        item2 = CEGItemDefinition.objects.create(ceg=ceg, name='POB JiWoo', item_type='PHOTOCARD')

        slot1 = ItemSlot.objects.create(set=set_obj, item_definition=item1, price=38.00, status=ItemSlot.Status.RESERVED, claimed_by=self.participant)
        slot2 = ItemSlot.objects.create(set=set_obj, item_definition=item2, price=38.00, status=ItemSlot.Status.PAID, claimed_by=self.participant)

        Claim.objects.create(slot=slot1, participant=self.participant, status=Claim.Status.PENDING, total_price=38.00)
        Claim.objects.create(slot=slot2, participant=self.participant, status=Claim.Status.PAID, total_price=38.00)

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        response = self.client.get('/me/')
        self.assertEqual(response.status_code, 200)

        # Context assertions
        self.assertEqual(response.context['total_claims_count'], 2)
        self.assertEqual(response.context['pending_claims_count'], 1)
        self.assertEqual(response.context['paid_claims_count'], 1)
        self.assertEqual(len(response.context['groups_filter_list']), 1)
        self.assertEqual(response.context['groups_filter_list'][0]['name'], 'tripleS')
        self.assertEqual(len(response.context['cegs_filter_list']), 1)
        self.assertEqual(response.context['cegs_filter_list'][0]['title'], 'CEG POB Withmuu')

        # Template content assertions
        self.assertContains(response, 'Grupo:')
        self.assertContains(response, 'CEG:')
        self.assertContains(response, 'Todos os Grupos')
        self.assertContains(response, 'Todas as CEGs')
        self.assertContains(response, 'Filtrar por Status:')
        self.assertContains(response, 'Faltam Pagar')
        self.assertContains(response, 'Confirmados')


class ParticipantNotificationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.participant = Participant.objects.create(
            name='Participante Notif',
            whatsapp='5511977776666',
            username='part_notif'
        )

    def test_notification_creation_and_unread_count(self):
        from apps.participants.models import ParticipantNotification
        self.assertEqual(self.participant.unread_notifications_count, 0)

        notif = ParticipantNotification.objects.create(
            participant=self.participant,
            title='Set #2 Cancelado — CEG Teste',
            message='O Set #2 precisou ser cancelado.',
            notification_type=ParticipantNotification.NotificationType.SET_CANCELLED
        )
        self.assertEqual(self.participant.unread_notifications_count, 1)

        notif.mark_as_read()
        self.assertTrue(notif.is_read)
        self.assertIsNotNone(notif.read_at)
        self.assertEqual(self.participant.unread_notifications_count, 0)

    def test_my_claims_view_renders_notifications(self):
        from apps.participants.models import ParticipantNotification
        ParticipantNotification.objects.create(
            participant=self.participant,
            title='Aviso de Set Cancelado',
            message='Item photocard cancelado.',
            notification_type=ParticipantNotification.NotificationType.SET_CANCELLED
        )

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        response = self.client.get('/me/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Avisos & Notificações')
        self.assertContains(response, 'Aviso de Set Cancelado')
        self.assertContains(response, 'Item photocard cancelado.')
        self.assertEqual(response.context['unread_notifications_count'], 1)

    def test_mark_notification_read_view(self):
        from apps.participants.models import ParticipantNotification
        notif = ParticipantNotification.objects.create(
            participant=self.participant,
            title='Aviso 1',
            message='Mensagem 1'
        )

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        res = self.client.post(
            f'/me/notifications/{notif.id}/read/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['unread_count'], 0)

        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_all_notifications_read_view(self):
        from apps.participants.models import ParticipantNotification
        ParticipantNotification.objects.create(
            participant=self.participant,
            title='Aviso 1',
            message='Mensagem 1'
        )
        ParticipantNotification.objects.create(
            participant=self.participant,
            title='Aviso 2',
            message='Mensagem 2'
        )
        self.assertEqual(self.participant.unread_notifications_count, 2)

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        res = self.client.post(
            '/me/notifications/read-all/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['unread_count'], 0)

        self.assertEqual(self.participant.unread_notifications_count, 0)

