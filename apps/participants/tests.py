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

    def test_my_claims_frete_and_taxa_not_shown_as_pending_when_zero_or_none(self):
        from decimal import Decimal
        from apps.groups.models import KpopGroup, Era
        from apps.cegs.models import CEG, CEGSet, CEGItemDefinition, ItemSlot
        from apps.participants.models import Claim
        from django.utils import timezone

        group = KpopGroup.objects.create(name='TWICE')
        era = Era.objects.create(group=group, name='With YOU-th')
        ceg = CEG.objects.create(
            era=era,
            title='CEG Makestar',
            opens_at=timezone.now() - timezone.timedelta(hours=1),
            frete_inter=Decimal('0.00'),
            taxa_aduaneira=Decimal('0.00')
        )
        set_obj = CEGSet.objects.create(ceg=ceg, set_number=1)
        item = CEGItemDefinition.objects.create(ceg=ceg, name='Photocard Momo', item_type='PHOTOCARD')
        slot = ItemSlot.objects.create(
            set=set_obj, item_definition=item, price=45.00,
            status=ItemSlot.Status.RESERVED, claimed_by=self.participant,
            is_frete_inter_paid=False, is_taxa_aduaneira_paid=False
        )
        Claim.objects.create(slot=slot, participant=self.participant, status=Claim.Status.PENDING, total_price=45.00)

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        response = self.client.get('/me/')
        self.assertEqual(response.status_code, 200)

        # Contagens de inadimplência devem ser zero porque frete e taxa são 0
        self.assertEqual(response.context['inter_unpaid_count'], 0)
        self.assertEqual(response.context['taxa_unpaid_count'], 0)

        # Não deve mostrar (R$ 0,00) nos cabeçalhos
        content = response.content.decode('utf-8')
        self.assertNotIn('(R$ 0,00)', content)
        self.assertNotIn('(r$ 0,00)', content)

    def test_my_claims_frete_and_taxa_shown_when_greater_than_zero(self):
        from decimal import Decimal
        from apps.groups.models import KpopGroup, Era
        from apps.cegs.models import CEG, CEGSet, CEGItemDefinition, ItemSlot
        from apps.participants.models import Claim
        from django.utils import timezone

        group = KpopGroup.objects.create(name='LE SSERAFIM')
        era = Era.objects.create(group=group, name='EASY')
        ceg = CEG.objects.create(
            era=era,
            title='CEG Weverse EASY',
            opens_at=timezone.now() - timezone.timedelta(hours=1),
            frete_inter=Decimal('12.50'),
            taxa_aduaneira=Decimal('6.00')
        )
        set_obj = CEGSet.objects.create(ceg=ceg, set_number=1)
        item = CEGItemDefinition.objects.create(ceg=ceg, name='Photocard Chaewon', item_type='PHOTOCARD')
        slot = ItemSlot.objects.create(
            set=set_obj, item_definition=item, price=50.00,
            status=ItemSlot.Status.RESERVED, claimed_by=self.participant,
            is_frete_inter_paid=False, is_taxa_aduaneira_paid=False
        )
        Claim.objects.create(slot=slot, participant=self.participant, status=Claim.Status.PENDING, total_price=50.00)

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        response = self.client.get('/me/')
        self.assertEqual(response.status_code, 200)

        # Contagens de inadimplência devem contabilizar o item com frete/taxa > 0
        self.assertEqual(response.context['inter_unpaid_count'], 1)
        self.assertEqual(response.context['taxa_unpaid_count'], 1)

        # Cabeçalhos com os valores
        self.assertContains(response, 'R$ 12,50')
        self.assertContains(response, 'R$ 6,00')
        # Filtros pills
        self.assertContains(response, 'Inter Não Pago')
        self.assertContains(response, 'Taxa Não Paga')

    def test_my_claims_rates_accordion_and_totals_by_item_type(self):
        from decimal import Decimal
        from apps.groups.models import KpopGroup, Era
        from apps.cegs.models import CEG, CEGSet, CEGItemDefinition, ItemSlot, TipoItem
        from apps.participants.models import Claim
        from django.utils import timezone

        group = KpopGroup.objects.create(name='NewJeans')
        era = Era.objects.create(group=group, name='Get Up')
        ceg = CEG.objects.create(
            era=era,
            title='CEG Bag Version',
            opens_at=timezone.now() - timezone.timedelta(hours=1),
            frete_inter=Decimal('10.00'),
            taxa_aduaneira=Decimal('5.00')
        )
        set_obj = CEGSet.objects.create(ceg=ceg, set_number=1)

        tipo_pc, _ = TipoItem.objects.get_or_create(nome='Photocard')
        tipo_album, _ = TipoItem.objects.get_or_create(nome='Álbum')

        item_pc = CEGItemDefinition.objects.create(ceg=ceg, name='Photocard Hanni', item_type='PHOTOCARD', tipo_item=tipo_pc)
        item_pc2 = CEGItemDefinition.objects.create(ceg=ceg, name='Photocard Minji', item_type='PHOTOCARD', tipo_item=tipo_pc)
        item_album = CEGItemDefinition.objects.create(ceg=ceg, name='Álbum Completo', item_type='ALBUM', tipo_item=tipo_album)

        # Slot 1: Photocard com frete 10.00 e taxa 5.00 (pendentes)
        slot1 = ItemSlot.objects.create(
            set=set_obj, item_definition=item_pc, price=40.00,
            status=ItemSlot.Status.RESERVED, claimed_by=self.participant,
            frete_inter_valor=Decimal('10.00'), taxa_aduaneira_valor=Decimal('5.00'),
            is_frete_inter_paid=False, is_taxa_aduaneira_paid=False
        )
        Claim.objects.create(slot=slot1, participant=self.participant, status=Claim.Status.PENDING, total_price=40.00)

        # Slot 2: Outro Photocard (mesmo tipo)
        slot2 = ItemSlot.objects.create(
            set=set_obj, item_definition=item_pc2, price=40.00,
            status=ItemSlot.Status.RESERVED, claimed_by=self.participant,
            frete_inter_valor=Decimal('10.00'), taxa_aduaneira_valor=Decimal('5.00'),
            is_frete_inter_paid=True, is_taxa_aduaneira_paid=False
        )
        Claim.objects.create(slot=slot2, participant=self.participant, status=Claim.Status.PAID, total_price=40.00)

        # Slot 3: Álbum com frete 45.00 e taxa 20.00 (pendentes)
        slot3 = ItemSlot.objects.create(
            set=set_obj, item_definition=item_album, price=120.00,
            status=ItemSlot.Status.RESERVED, claimed_by=self.participant,
            frete_inter_valor=Decimal('45.00'), taxa_aduaneira_valor=Decimal('20.00'),
            is_frete_inter_paid=False, is_taxa_aduaneira_paid=False
        )
        Claim.objects.create(slot=slot3, participant=self.participant, status=Claim.Status.PENDING, total_price=120.00)

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        response = self.client.get('/me/')
        self.assertEqual(response.status_code, 200)

        ceg_data = response.context['cegs_groups'][0]
        # Totais consolidados
        # Frete total: 10 + 10 + 45 = 65.00; Frete pendente: 10 + 45 = 55.00; Frete pago: 10.00
        self.assertEqual(ceg_data['total_frete_inter'], Decimal('65.00'))
        self.assertEqual(ceg_data['total_frete_inter_pendente'], Decimal('55.00'))
        self.assertEqual(ceg_data['total_frete_inter_pago'], Decimal('10.00'))

        # Taxa total: 5 + 5 + 20 = 30.00; Taxa pendente: 30.00; Taxa paga: 0.00
        self.assertEqual(ceg_data['total_taxa_aduaneira'], Decimal('30.00'))
        self.assertEqual(ceg_data['total_taxa_aduaneira_pendente'], Decimal('30.00'))

        # Total devido frete + taxa: 55.00 + 30.00 = 85.00
        self.assertEqual(ceg_data['total_devido_frete_taxa'], Decimal('85.00'))

        # Total geral pendente (itens pendentes 40 + 120 = 160 + 85 = 245.00)
        self.assertEqual(ceg_data['total_geral_pendente'], Decimal('245.00'))

        # Resumo por tipos de item
        self.assertEqual(len(ceg_data['tipos_resumo']), 2)
        self.assertTrue(ceg_data['has_multiple_fretes'])
        self.assertTrue(ceg_data['has_multiple_taxas'])

        # HTML deve conter totais no cabeçalho da CEG e valores individuais na tabela
        self.assertContains(response, 'Frete a Pagar:')
        self.assertContains(response, 'R$ 55,00')
        self.assertContains(response, 'Taxa a Pagar:')
        self.assertContains(response, 'R$ 30,00')
        self.assertContains(response, 'Total a Pagar nesta CEG:')
        self.assertContains(response, 'R$ 245,00')
        self.assertNotContains(response, 'Valores de Frete')


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


class ParticipantPrazosProximosTests(TestCase):
    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.groups.models import KpopGroup, Era
        from apps.cegs.models import CEG, CEGItemDefinition, ItemSlot, CEGSet, Caixa
        from apps.participants.models import Claim

        self.client = Client()
        self.participant, _ = Participant.objects.get_or_create(
            whatsapp='5581999998888',
            defaults={'name': 'Test Joiner'}
        )
        self.participant.claims.all().delete()
        self.group, _ = KpopGroup.objects.get_or_create(name='Prazos Test Group')
        self.era, _ = Era.objects.get_or_create(group=self.group, name='Prazos Era')

        now = timezone.now()
        self.ceg = CEG.objects.create(
            title='LE SSERAFIM - CRAZY POB',
            era=self.era,
            status=CEG.Status.OPEN,
            prazo_pagamento_item=now + timedelta(hours=12),
            pix_key='lessera@pix.com'
        )
        self.item_def = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Photocard Chaewon'
        )
        self.set_obj = CEGSet.objects.create(ceg=self.ceg, set_number=1)
        self.slot = ItemSlot.objects.create(
            set=self.set_obj,
            item_definition=self.item_def,
            status=ItemSlot.Status.RESERVED,
            price=50.00
        )
        self.claim = Claim.objects.create(
            participant=self.participant,
            slot=self.slot,
            total_price=50.00,
            status=Claim.Status.PENDING
        )

    def test_prazos_proximos_appears_when_pending(self):
        from django.urls import reverse
        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        res = self.client.get(reverse('my_claims'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('prazos_proximos', res.context)
        prazos = res.context['prazos_proximos']
        self.assertEqual(len(prazos), 1)
        self.assertEqual(prazos[0]['tipo'], 'ITEM')
        self.assertEqual(prazos[0]['ceg_id'], str(self.ceg.id))
        self.assertEqual(prazos[0]['valor'], 50.00)
        self.assertContains(res, 'Prazos Próximos de Pagamento')
        self.assertContains(res, 'LE SSERAFIM - CRAZY POB')

    def test_prazos_proximos_disappears_when_paid(self):
        from django.urls import reverse
        from apps.participants.models import Claim
        from apps.cegs.models import ItemSlot
        self.claim.status = Claim.Status.PAID
        self.claim.save()
        self.slot.status = ItemSlot.Status.PAID
        self.slot.is_item_paid = True
        self.slot.save()

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        res = self.client.get(reverse('my_claims'))
        self.assertEqual(res.status_code, 200)
        prazos = res.context['prazos_proximos']
        self.assertEqual(len(prazos), 0)
        self.assertNotContains(res, 'Prazos Próximos de Pagamento')

    def test_claim_lifecycle_property_stages(self):
        from apps.participants.models import Claim
        from apps.cegs.models import ItemSlot, PacoteNacional

        # 1. Aguardando pagamento
        self.assertEqual(self.claim.lifecycle['code'], 'PENDING_PAYMENT')
        self.assertEqual(self.claim.lifecycle['stage'], 1)

        # 2. Pago e sem caixa em trânsito => Pronto na Caixinha
        self.claim.status = Claim.Status.PAID
        self.claim.save()
        self.slot.status = ItemSlot.Status.PAID
        self.slot.is_item_paid = True
        self.slot.save()
        self.assertEqual(self.claim.lifecycle['code'], 'READY_CAIXINHA')
        self.assertEqual(self.claim.lifecycle['stage'], 4)

        # 3. Pacote Nacional (Enviado)
        pacote = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-TEST-01',
            status=PacoteNacional.Status.ENVIADO,
            codigo_rastreio='BR123456789BR'
        )
        self.slot.pacote_nacional = pacote
        self.slot.save()
        self.assertEqual(self.claim.lifecycle['code'], 'SHIPPED')
        self.assertEqual(self.claim.lifecycle['stage'], 5)

        # 4. Pacote Entregue
        pacote.status = PacoteNacional.Status.ENTREGUE
        pacote.save()
        self.assertEqual(self.claim.lifecycle['code'], 'DELIVERED')
        self.assertEqual(self.claim.lifecycle['stage'], 5)

    def test_my_claims_view_quick_pix_and_search_data(self):
        from django.urls import reverse
        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        res = self.client.get(reverse('my_claims'))
        self.assertEqual(res.status_code, 200)

        # Quick Pix assertions
        self.assertIn('cegs_com_pendencias', res.context)
        self.assertEqual(len(res.context['cegs_com_pendencias']), 1)
        self.assertEqual(res.context['total_geral_pendente_todas_cegs'], 50.00)
        self.assertContains(res, 'Central de Pagamento Rápido (Pix)')

        # Search text presence in JSON script
        self.assertIn('search_text', res.context['cegs_filter_list'][0])
        self.assertIn('chaewon', res.context['cegs_filter_list'][0]['search_text'])

        # View mode toggle buttons present
        self.assertContains(res, 'Galeria')
        self.assertContains(res, 'Tabela')

    def test_my_claims_caixa_filter_and_unpaid_rates_counting(self):
        from decimal import Decimal
        from apps.cegs.models import Caixa, ItemSlot
        from apps.participants.models import Claim
        from django.urls import reverse

        # Criar caixa e vincular a CEG
        caixa = Caixa.objects.create(nome='KR Remessa Teste', origem='KR', status='EM_TRANSITO')
        self.ceg.caixa = caixa
        self.ceg.save()

        # Marcar item como pago, mas frete internacional não pago
        self.ceg.frete_inter = Decimal('22.00')
        self.ceg.taxa_aduaneira = Decimal('2.00')
        self.ceg.save()

        self.claim.status = Claim.Status.PAID
        self.claim.save()
        self.slot.status = ItemSlot.Status.PAID
        self.slot.is_item_paid = True
        self.slot.is_frete_inter_paid = False
        self.slot.is_taxa_aduaneira_paid = False
        self.slot.save()

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        res = self.client.get(reverse('my_claims'))
        self.assertEqual(res.status_code, 200)

        # Context assertions
        self.assertEqual(res.context['pending_claims_count'], 0) # Item price is paid
        self.assertEqual(res.context['paid_claims_count'], 1)
        self.assertEqual(res.context['inter_unpaid_count'], 1)
        self.assertEqual(res.context['taxa_unpaid_count'], 1)
        self.assertEqual(res.context['total_any_unpaid_count'], 1) # Item has unpaid rates!

        # In cegs_filter_list
        ceg_filter_data = res.context['cegs_filter_list'][0]
        self.assertEqual(ceg_filter_data['count_pending'], 0)
        self.assertEqual(ceg_filter_data['count_inter_unpaid'], 1)
        self.assertEqual(ceg_filter_data['count_taxa_unpaid'], 1)
        self.assertEqual(ceg_filter_data['count_any_unpaid'], 1)
        self.assertEqual(ceg_filter_data['caixa_id'], str(caixa.id))

        # In cegs_com_pendencias
        self.assertEqual(len(res.context['cegs_com_pendencias']), 1)
        self.assertEqual(res.context['total_geral_pendente_todas_cegs'], Decimal('24.00'))

        # Template contains interactive filters and clear filter button
        self.assertContains(res, 'filterByCegPayment')
        self.assertContains(res, 'filteredCounts.pending')
        self.assertContains(res, 'visibleCegsCount')
        self.assertContains(res, 'Limpar Filtros')
        self.assertContains(res, 'clearFilters()')
        self.assertContains(res, 'hasActiveFilters')

    def test_quick_pix_caixa_and_mercari_consolidation(self):
        from decimal import Decimal
        from apps.cegs.models import Caixa, ItemSlot, ItemIndividual
        from apps.participants.models import Claim
        from django.urls import reverse

        caixa = Caixa.objects.create(nome='Caixa Japão #01', origem='JP', status='ENVIADO')
        self.ceg.caixa = caixa
        self.ceg.save()

        # CEG tem pendência de 50.00 no item da setUp
        # Agora adicionar um item avulso Mercari vinculado à mesma caixa
        item_mercari = ItemIndividual.objects.create(
            comprador=self.participant,
            caixa=caixa,
            nome='Photobar Mercari Sakura',
            quantidade=1,
            preco_produto=Decimal('35.00'),
            produto_pago=False,
            frete_inter=Decimal('15.00'),
            frete_inter_pago=False,
            taxa_aduaneira=Decimal('5.00'),
            taxa_aduaneira_paga=False,
        )

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        res = self.client.get(reverse('my_claims'))
        self.assertEqual(res.status_code, 200)

        # 1. Consolidação por CEG
        self.assertIn('cegs_com_pendencias', res.context)
        self.assertEqual(len(res.context['cegs_com_pendencias']), 1)
        self.assertEqual(res.context['total_geral_pendente_todas_cegs'], Decimal('50.00'))

        # 2. Consolidação por Caixa
        self.assertIn('caixas_com_pendencias', res.context)
        self.assertEqual(len(res.context['caixas_com_pendencias']), 1)
        caixa_pend = res.context['caixas_com_pendencias'][0]
        self.assertEqual(caixa_pend['nome'], 'Caixa Japão #01')
        self.assertEqual(caixa_pend['total_items_pending'], Decimal('50.00') + Decimal('35.00')) # 85.00
        self.assertEqual(caixa_pend['total_frete_pending'], Decimal('15.00'))
        self.assertEqual(caixa_pend['total_taxa_pending'], Decimal('5.00'))
        self.assertEqual(caixa_pend['total_geral_pendente'], Decimal('105.00'))
        self.assertEqual(res.context['total_geral_pendente_caixas'], Decimal('105.00'))

        # 3. Consolidação Mercari
        self.assertIn('mercari_pendencias', res.context)
        mercari_info = res.context['mercari_pendencias']
        self.assertEqual(mercari_info['items_count'], 1)
        self.assertEqual(mercari_info['total_produtos_pendente'], Decimal('35.00'))
        self.assertEqual(mercari_info['total_frete_pendente'], Decimal('15.00'))
        self.assertEqual(mercari_info['total_taxa_pendente'], Decimal('5.00'))
        self.assertEqual(mercari_info['total_geral_pendente'], Decimal('55.00'))
        self.assertEqual(res.context['total_geral_pendente_mercari'], Decimal('55.00'))
        self.assertEqual(res.context['total_geral_pendente_global'], Decimal('105.00'))

        # 4. Renderização no template
        self.assertContains(res, 'Por CEG')
        self.assertContains(res, 'Por Caixa')
        self.assertContains(res, 'Mercari')
        self.assertContains(res, 'quickPixTab')
        self.assertContains(res, 'Photobar Mercari Sakura')
        self.assertContains(res, 'Caixa Japão #01')

    def test_distinct_pix_keys_for_item_frete_taxa(self):
        from decimal import Decimal
        from django.utils import timezone
        from datetime import timedelta
        from apps.cegs.models import Caixa, ItemSlot
        from apps.participants.models import Claim
        from django.urls import reverse

        # 1. Configurar chaves distintas na CEG
        self.ceg.pix_key = 'pix_item@banco.com'
        self.ceg.pix_instructions = 'Comprovante item com nome'
        self.ceg.pix_key_frete = 'pix_frete_ceg@transportadora.com'
        self.ceg.pix_instructions_frete = 'Comprovante frete com código CEG'
        self.ceg.pix_key_taxa = 'pix_taxa_ceg@alfandega.com'
        self.ceg.pix_instructions_taxa = 'Comprovante taxa urgente'
        self.ceg.prazo_pagamento_item = timezone.now() + timedelta(days=2)
        self.ceg.prazo_pagamento_frete_inter = timezone.now() + timedelta(days=3)
        self.ceg.prazo_pagamento_taxa_aduaneira = timezone.now() + timedelta(days=4)
        self.ceg.save()

        # Configurar slot com pendências de item, frete e taxa
        self.ceg.frete_inter = Decimal('20.00')
        self.ceg.taxa_aduaneira = Decimal('10.00')
        self.ceg.save()
        self.slot.is_frete_inter_paid = False
        self.slot.is_taxa_aduaneira_paid = False
        self.slot.save()

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        # Requisição para my_claims
        res = self.client.get(reverse('my_claims'))
        self.assertEqual(res.status_code, 200)

        # Asserções no context da CEG
        ceg_pend = res.context['cegs_com_pendencias'][0]
        self.assertTrue(ceg_pend['has_distinct_pix_keys'])
        self.assertEqual(ceg_pend['pix_key_item'], 'pix_item@banco.com')
        self.assertEqual(ceg_pend['pix_key_frete'], 'pix_frete_ceg@transportadora.com')
        self.assertEqual(ceg_pend['pix_key_taxa'], 'pix_taxa_ceg@alfandega.com')
        self.assertEqual(ceg_pend['pix_instructions_item'], 'Comprovante item com nome')
        self.assertEqual(ceg_pend['pix_instructions_frete'], 'Comprovante frete com código CEG')
        self.assertEqual(ceg_pend['pix_instructions_taxa'], 'Comprovante taxa urgente')

        # Asserções no Semáforo de Prazos
        prazos = {p['tipo']: p for p in res.context['prazos_proximos']}
        self.assertIn('ITEM', prazos)
        self.assertIn('FRETE', prazos)
        self.assertIn('TAXA', prazos)
        self.assertEqual(prazos['ITEM']['pix_key'], 'pix_item@banco.com')
        self.assertEqual(prazos['FRETE']['pix_key'], 'pix_frete_ceg@transportadora.com')
        self.assertEqual(prazos['TAXA']['pix_key'], 'pix_taxa_ceg@alfandega.com')

        # Asserções no HTML renderizado
        self.assertContains(res, 'pix_item@banco.com')
        self.assertContains(res, 'pix_frete_ceg@transportadora.com')
        self.assertContains(res, 'pix_taxa_ceg@alfandega.com')
        self.assertContains(res, 'Pix Itens:')
        self.assertContains(res, 'Pix Frete:')
        self.assertContains(res, 'Pix Taxa:')

        # 2. Testar sobrescrita pela Caixa (Caixa com chaves próprias de Frete e Taxa)
        caixa = Caixa.objects.create(
            nome='Caixa KR Chaves Específicas',
            origem='KR',
            status='EM_TRANSITO',
            pix_key_frete='pix_caixa_frete@courier.com',
            pix_instructions_frete='Frete Caixa KR',
            pix_key_taxa='pix_caixa_taxa@receita.com',
            pix_instructions_taxa='Taxa Caixa KR'
        )
        self.ceg.caixa = caixa
        self.ceg.save()

        # Verificar fallback no modelo CEG
        self.assertEqual(self.ceg.get_pix_key_frete(), 'pix_caixa_frete@courier.com')
        self.assertEqual(self.ceg.get_pix_key_taxa(), 'pix_caixa_taxa@receita.com')
        self.assertEqual(self.ceg.get_pix_key_item(), 'pix_item@banco.com')

        res2 = self.client.get(reverse('my_claims'))
        self.assertEqual(res2.status_code, 200)

        # Na visualização por Caixa
        caixa_pend = res2.context['caixas_com_pendencias'][0]
        self.assertTrue(caixa_pend['has_distinct_pix_keys'])
        self.assertEqual(caixa_pend['pix_key_frete'], 'pix_caixa_frete@courier.com')
        self.assertEqual(caixa_pend['pix_key_taxa'], 'pix_caixa_taxa@receita.com')

        # No Semáforo de Prazos, Frete e Taxa agora usam as chaves da Caixa
        prazos2 = {p['tipo']: p for p in res2.context['prazos_proximos']}
        self.assertEqual(prazos2['FRETE']['pix_key'], 'pix_caixa_frete@courier.com')
        self.assertEqual(prazos2['TAXA']['pix_key'], 'pix_caixa_taxa@receita.com')
        self.assertEqual(prazos2['ITEM']['pix_key'], 'pix_item@banco.com')


