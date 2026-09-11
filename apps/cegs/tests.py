from django.test import TestCase, TransactionTestCase, Client
from django.utils import timezone
from datetime import timedelta
import threading
from django.contrib.auth.models import User
from apps.groups.models import KpopGroup, Era
from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot, ClaimAttemptLog
from apps.cegs.services import ClaimService, CEGNotOpenYetError, SlotUnavailableError, LAST_CLAIM_DISPUTES
from apps.participants.models import Participant, Claim
from apps.auth_otp.services import OTPService
from apps.analytics.services import AnalyticsService


class CEGConcurrencyAndStandbyTests(TransactionTestCase):
    def setUp(self):
        ClaimService.reset_in_memory_counters()
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
            social_handle='@biakpop',
            username='Bia'
        )
        self.assertIsNotNone(claim)
        self.assertEqual(claim.status, Claim.Status.PENDING)
        self.assertEqual(claim.total_price, 50.00)
        self.assertEqual(claim.participant.whatsapp, '5511988887777')
        self.assertEqual(claim.participant.name, 'Beatriz Kpop')
        self.assertEqual(claim.participant.username, 'Bia')
        self.assertEqual(claim.participant.display_name, 'Bia')

        # Slot deve estar RESERVED
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, ItemSlot.Status.RESERVED)
        self.assertEqual(self.slot.claimed_by.name, 'Beatriz Kpop')
        self.assertEqual(self.slot.claimed_by.display_name, 'Bia')

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

        # Valida que os logs em memória registraram a ordem de claim
        disputes = [d for d in LAST_CLAIM_DISPUTES if d['slot_id'] == self.slot.id]
        self.assertGreaterEqual(len(disputes), 2)
        winner_dispute = [d for d in disputes if d['won'] is True]
        loser_dispute = [d for d in disputes if d['won'] is False]
        self.assertEqual(len(winner_dispute), 1)
        self.assertGreaterEqual(len(loser_dispute), 1)

    def test_claim_order_logging_sequence(self):
        """
        Verifica a atribuição sequencial da ordem de chegada (1º lugar, 2º lugar, 3º lugar)
        e a persistência dos logs no modelo ClaimAttemptLog.
        """
        item_def2 = CEGItemDefinition.objects.create(
            ceg=self.open_ceg,
            name='Photocard Visual',
            member_name='Visual',
            default_price=45.00
        )
        slot2 = self.cset.slots.create(
            item_definition=item_def2,
            price=45.00,
            status=ItemSlot.Status.AVAILABLE
        )

        # 1ª tentativa: Vencedor
        claim1 = ClaimService.claim_slot(
            slot_id=slot2.id,
            name='Participante Primeiro',
            phone='5511911111111',
            social_handle='@primeiro'
        )
        self.assertIsNotNone(claim1)

        # 2ª tentativa: Perde a disputa
        with self.assertRaises(SlotUnavailableError):
            ClaimService.claim_slot(
                slot_id=slot2.id,
                name='Participante Segundo',
                phone='5511922222222',
                social_handle='@segundo'
            )

        # 3ª tentativa: Também perde a disputa
        with self.assertRaises(SlotUnavailableError):
            ClaimService.claim_slot(
                slot_id=slot2.id,
                name='Participante Terceiro',
                phone='5511933333333',
                social_handle='@terceiro'
            )

        # Consulta o histórico ordenado gravado no banco
        logs = ClaimService.get_slot_dispute_history(slot2.id)
        self.assertEqual(logs.count(), 3)

        first = logs[0]
        self.assertEqual(first.attempt_number, 1)
        self.assertEqual(first.participant_name, 'Participante Primeiro')
        self.assertEqual(first.result, ClaimAttemptLog.Result.SUCCESS)

        second = logs[1]
        self.assertEqual(second.attempt_number, 2)
        self.assertEqual(second.participant_name, 'Participante Segundo')
        self.assertEqual(second.result, ClaimAttemptLog.Result.LOST_RACE)

        third = logs[2]
        self.assertEqual(third.attempt_number, 3)
        self.assertEqual(third.participant_name, 'Participante Terceiro')
        self.assertEqual(third.result, ClaimAttemptLog.Result.LOST_RACE)


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
        participant = Participant.objects.create(
            name='Mariana Souza',
            username='Mari',
            whatsapp='5511944445555',
            social_handle='@mari_kpop'
        )
        session = self.client.session
        session['participant_id'] = participant.id
        session.save()

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

        # Como a sessão está ativa, acessar /me/ deve listar o claim
        me_response = self.client.get('/me/')
        self.assertEqual(me_response.status_code, 200)
        self.assertContains(me_response, 'Mariana Souza')
        self.assertContains(me_response, 'Photocard Seoyeon')
        self.assertContains(me_response, 'triples@pix.com')

    def test_unauthenticated_claim_redirects_to_login(self):
        """Usuário anônimo/não autenticado deve ser redirecionado para a tela de login OTP"""
        slot = self.set1.slots.first()
        response = self.client.post(f'/slots/{slot.id}/claim/', data={'name': 'Anonimo'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'/me/login/?next=/ceg/{self.ceg.slug}/', response.url)

        # Via AJAX deve retornar 401 JSON com requires_auth=True
        ajax_response = self.client.post(
            f'/slots/{slot.id}/claim/',
            data={'name': 'Anonimo'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(ajax_response.status_code, 401)
        data = ajax_response.json()
        self.assertTrue(data.get('requires_auth'))
        self.assertEqual(data.get('redirect_url'), f'/me/login/?next=/ceg/{self.ceg.slug}/')

        # O slot deve continuar disponível
        slot.refresh_from_db()
        self.assertEqual(slot.status, ItemSlot.Status.AVAILABLE)

    def test_authenticated_participant_auto_fills_missing_fields(self):
        """Participante logado tem seus dados (nome, username, whatsapp, etc.) reaproveitados"""
        participant = Participant.objects.create(
            name='Camila Mendes',
            username='Mimi',
            whatsapp='5511977778888',
            social_handle='@mimi_kpop'
        )
        session = self.client.session
        session['participant_id'] = participant.id
        session.save()

        slot = self.set1.slots.first()
        # Envia apenas as observações, os campos essenciais devem cair no fallback do participante logado
        response = self.client.post(f'/slots/{slot.id}/claim/', data={'notes': 'Toploader rosa'}, follow=True)
        self.assertEqual(response.status_code, 200)

        slot.refresh_from_db()
        self.assertEqual(slot.status, ItemSlot.Status.RESERVED)
        self.assertEqual(slot.claimed_by.id, participant.id)
        self.assertEqual(slot.claimed_by.name, 'Camila Mendes')
        self.assertEqual(slot.claimed_by.username, 'Mimi')
        self.assertEqual(slot.claimed_by.whatsapp, '5511977778888')

    def test_admin_can_view_participants_and_claim_on_behalf(self):
        """Administrador vê lista de participantes cadastrados e pode reservar em nome de um participante"""
        admin_user = User.objects.create_superuser(
            username='admin_test',
            email='admin@test.com',
            password='password123'
        )
        participant = Participant.objects.create(
            name='Lucas Silva',
            username='Lukinha',
            whatsapp='5511966667777',
            social_handle='@luks'
        )

        self.client.force_login(admin_user)

        # 1. Página de detalhe da CEG deve carregar os participantes para o dropdown do admin
        ceg_resp = self.client.get(f'/ceg/{self.ceg.slug}/')
        self.assertEqual(ceg_resp.status_code, 200)
        self.assertIn('all_participants', ceg_resp.context)
        self.assertEqual(len(ceg_resp.context['all_participants']), 1)
        self.assertEqual(ceg_resp.context['all_participants'][0]['name'], 'Lucas Silva')
        self.assertContains(ceg_resp, 'Modo Organizador (Admin)')
        self.assertContains(ceg_resp, 'Selecione um participante cadastrado')

        # 2. Admin reserva slot em nome do Lucas
        slot = self.set1.slots.first()
        claim_data = {
            'name': participant.name,
            'username': participant.username,
            'whatsapp': participant.whatsapp,
            'social_handle': participant.social_handle,
            'notes': 'Reserva efetuada pelo adm'
        }
        response = self.client.post(f'/slots/{slot.id}/claim/', data=claim_data, follow=True)
        self.assertEqual(response.status_code, 200)

        slot.refresh_from_db()
        self.assertEqual(slot.status, ItemSlot.Status.RESERVED)
        self.assertEqual(slot.claimed_by.id, participant.id)
        self.assertEqual(slot.claimed_by.name, 'Lucas Silva')

        # A sessão do admin NÃO deve ser corrompida com participant_id
        self.assertIsNone(self.client.session.get('participant_id'))

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

    def test_home_auto_promotes_scheduled_ceg_and_provides_group_filters(self):
        """Verifica que CEGs com opens_at no passado são promovidas automaticamente para OPEN e agrupadas nos filtros da Home"""
        # Cria uma CEG com status SCHEDULED, mas cujo horário de abertura já passou (como ocorreu na foto)
        group2 = KpopGroup.objects.create(name='NewJeans', slug='newjeans-test')
        era2 = Era.objects.create(group=group2, name='How Sweet', slug='how-sweet-test')
        expired_scheduled_ceg = CEG.objects.create(
            era=era2,
            title='CEG NewJeans Passada',
            slug='ceg-newjeans-passada',
            status=CEG.Status.SCHEDULED,
            opens_at=timezone.now() - timedelta(minutes=10),
            pix_key='newjeans@pix.com'
        )

        # Ao acessar a Home, a CEG deve ser promovida para OPEN
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

        expired_scheduled_ceg.refresh_from_db()
        self.assertEqual(expired_scheduled_ceg.status, CEG.Status.OPEN)

        # O HTML deve conter os botões de filtro para os grupos com CEGs abertas
        self.assertContains(response, 'Filtrar Grupo:')
        self.assertContains(response, 'tripleS')
        self.assertContains(response, 'NewJeans')


class CreationsHubIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='organizador',
            email='organizador@ceg.com',
            password='password123'
        )
        self.regular_user = User.objects.create_user(
            username='colecionador',
            email='colecionador@ceg.com',
            password='password123'
        )
        self.group = KpopGroup.objects.create(name='TWICE', slug='twice')
        self.era = Era.objects.create(group=self.group, name='With YOU-th', slug='with-you-th')

    def test_creations_hub_requires_staff_access(self):
        # Usuário anônimo deve ser redirecionado para o login admin
        resp_anon = self.client.get('/creations/')
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn('/admin/login/?next=/creations/', resp_anon.url)

        # Usuário logado comum sem is_staff também é redirecionado
        self.client.force_login(self.regular_user)
        resp_reg = self.client.get('/creations/')
        self.assertEqual(resp_reg.status_code, 302)
        self.assertIn('/admin/login/?next=/creations/', resp_reg.url)

        # Usuário staff acessa perfeitamente
        self.client.force_login(self.admin_user)
        resp_admin = self.client.get('/creations/')
        self.assertEqual(resp_admin.status_code, 200)
        self.assertContains(resp_admin, 'Hub de Criações')
        self.assertContains(resp_admin, 'Cadastrar CEG Nova')
        self.assertContains(resp_admin, 'Cadastrar Grupo Novo')
        self.assertContains(resp_admin, 'Cadastrar Era Nova')
        self.assertContains(resp_admin, 'Adicionar Novo Set')

    def test_create_group_via_post(self):
        self.client.force_login(self.admin_user)
        post_data = {
            'name': 'LE SSERAFIM',
            'image_url': 'https://example.com/lesserafim.jpg',
            'description': 'Grupo da Source Music com 5 integrantes.'
        }
        response = self.client.post('/creations/group/create/', data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Grupo criado no banco
        group = KpopGroup.objects.get(name='LE SSERAFIM')
        self.assertEqual(group.slug, 'le-sserafim')
        self.assertContains(response, 'LE SSERAFIM')

    def test_create_era_via_post(self):
        self.client.force_login(self.admin_user)
        post_data = {
            'group_id': self.group.id,
            'name': 'READY TO BE',
            'release_date': '2023-03-10',
            'description': '12º Mini Álbum com o single SET ME FREE'
        }
        response = self.client.post('/creations/era/create/', data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Era criada vinculada ao TWICE
        era = Era.objects.get(group=self.group, name='READY TO BE')
        self.assertEqual(era.slug, 'ready-to-be')
        self.assertContains(response, 'READY TO BE')

    def test_create_ceg_complete_with_items_and_slots(self):
        self.client.force_login(self.admin_user)

        import json
        items_payload = [
            {'name': 'Photocard POB Nayeon', 'member_name': 'Nayeon', 'item_type': 'PHOTOCARD', 'default_price': '45.00'},
            {'name': 'Photocard POB Momo', 'member_name': 'Momo', 'item_type': 'PHOTOCARD', 'default_price': '45.00'},
            {'name': 'Photocard POB Sana', 'member_name': 'Sana', 'item_type': 'PHOTOCARD', 'default_price': '45.00'},
            {'name': 'Álbum Selado', 'member_name': '', 'item_type': 'ALBUM', 'default_price': '120.00'},
        ]

        post_data = {
            'era_id': self.era.id,
            'title': 'CEG TWICE With YOU-th - Digipack Split',
            'status': 'OPEN',
            'pix_key': 'twice@pix.com',
            'pix_instructions': 'Enviar comprovante com @ no WhatsApp',
            'description': 'Frete internacional incluso. Envio com toploader.',
            'initial_sets_count': '2',
            'items_json': json.dumps(items_payload),
        }

        response = self.client.post('/creations/ceg/create/', data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Valida que a CEG foi criada no banco
        ceg = CEG.objects.get(title='CEG TWICE With YOU-th - Digipack Split')
        self.assertEqual(ceg.era, self.era)
        self.assertEqual(ceg.status, CEG.Status.OPEN)
        self.assertEqual(ceg.pix_key, 'twice@pix.com')

        # Valida que as 4 definições de itens foram criadas
        self.assertEqual(ceg.item_definitions.count(), 4)
        item_names = set(ceg.item_definitions.values_list('name', flat=True))
        self.assertIn('Photocard POB Nayeon', item_names)
        self.assertIn('Álbum Selado', item_names)

        # Valida que os 2 Sets foram gerados (Set #1 e Set #2)
        self.assertEqual(ceg.sets.count(), 2)
        set1 = ceg.sets.get(set_number=1)
        set2 = ceg.sets.get(set_number=2)

        # Cada Set deve conter 4 slots físicos (total de 8 slots na CEG)
        self.assertEqual(set1.slots.count(), 4)
        self.assertEqual(set2.slots.count(), 4)
        self.assertTrue(all(slot.status == ItemSlot.Status.AVAILABLE for slot in set1.slots.all()))

        # A resposta redireciona para a página da CEG exibindo os itens
        self.assertContains(response, 'CEG TWICE With YOU-th - Digipack Split')
        self.assertContains(response, 'Photocard POB Nayeon')
        self.assertContains(response, 'Photocard POB Momo')

    def test_create_set_for_existing_ceg(self):
        self.client.force_login(self.admin_user)

        # Cria uma CEG com 2 itens
        ceg = CEG.objects.create(
            era=self.era,
            title='CEG Existente Teste',
            slug='ceg-existente-teste',
            status=CEG.Status.OPEN,
            pix_key='pix@test.com'
        )
        item1 = CEGItemDefinition.objects.create(ceg=ceg, name='Photocard Jihyo', default_price=40.00)
        item2 = CEGItemDefinition.objects.create(ceg=ceg, name='Photocard Mina', default_price=40.00)
        set1 = CEGSet.objects.create(ceg=ceg, set_number=1)
        set1.generate_slots()
        self.assertEqual(set1.slots.count(), 2)

        # Adiciona o Set #2 via POST
        post_data = {
            'ceg_id': ceg.id,
            'set_number': '2',
            'notes': 'Set 2 Adicional',
            'is_active': 'on'
        }
        response = self.client.post('/creations/set/create/', data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Set #2 deve estar criado com os 2 slots físicos gerados automaticamente
        self.assertEqual(ceg.sets.count(), 2)
        set2 = ceg.sets.get(set_number=2)
        self.assertEqual(set2.slots.count(), 2)
        self.assertEqual(set2.notes, 'Set 2 Adicional')

    def test_create_ceg_with_pre_assigned_participant(self):
        """Valida que o admin pode pré-reservar slots para participantes pré-existentes na abertura da CEG"""
        self.client.force_login(self.admin_user)
        participant = Participant.objects.create(
            name='Beatriz VIP',
            username='BiaVIP',
            whatsapp='5511999998888',
            social_handle='@biavip'
        )

        import json
        items_payload = [
            {
                'name': 'Photocard VIP Nayeon',
                'member_name': 'Nayeon',
                'item_type': 'PHOTOCARD',
                'default_price': '50.00',
                'participant_id': str(participant.id)  # Pré-reservado para a Beatriz
            },
            {
                'name': 'Photocard Aberto Momo',
                'member_name': 'Momo',
                'item_type': 'PHOTOCARD',
                'default_price': '50.00',
                'participant_id': ''  # Aberto para claim geral
            }
        ]

        post_data = {
            'era_id': self.era.id,
            'title': 'CEG TWICE Com Pré-Reserva VIP',
            'status': 'OPEN',
            'pix_key': 'twice@pix.com',
            'initial_sets_count': '1',
            'items_json': json.dumps(items_payload),
        }

        response = self.client.post('/creations/ceg/create/', data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        ceg = CEG.objects.get(title='CEG TWICE Com Pré-Reserva VIP')
        set1 = ceg.sets.get(set_number=1)

        # O slot da Nayeon deve nascer RESERVADO para Beatriz
        slot_vip = set1.slots.get(item_definition__name='Photocard VIP Nayeon')
        self.assertEqual(slot_vip.status, ItemSlot.Status.RESERVED)
        self.assertEqual(slot_vip.claimed_by, participant)

        # O slot da Momo deve nascer AVAILABLE (livre)
        slot_livre = set1.slots.get(item_definition__name='Photocard Aberto Momo')
        self.assertEqual(slot_livre.status, ItemSlot.Status.AVAILABLE)
        self.assertIsNone(slot_livre.claimed_by)

        # Deve existir um Claim registrado para a Beatriz
        self.assertTrue(Claim.objects.filter(slot=slot_vip, participant=participant).exists())



