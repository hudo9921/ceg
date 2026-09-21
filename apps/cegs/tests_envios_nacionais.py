from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.participants.models import Participant, Claim, ParticipantNotification
from apps.groups.models import KpopGroup, Era
from apps.cegs.models import (
    CEG,
    CEGSet,
    CEGItemDefinition,
    ItemSlot,
    ItemIndividual,
    PacoteNacional,
    Caixa,
    TipoItem,
)

User = get_user_model()


class EnviosNacionaisTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin / Staff User
        self.staff_user = User.objects.create_user(
            username='admin_staff',
            password='password123',
            is_staff=True
        )

        # Non-staff User
        self.regular_user = User.objects.create_user(
            username='regular_user',
            password='password123',
            is_staff=False
        )

        # Participante (Joiner)
        self.participant = Participant.objects.create(
            name='Maria Silva',
            username='mariakpop',
            whatsapp='5511999887766',
            social_handle='@mariakpop'
        )

        # Grupo e Era
        self.group = KpopGroup.objects.create(name='TWICE', slug='twice')
        self.era = Era.objects.create(group=self.group, name='With YOU-th')

        # Caixa KR
        self.caixa_kr = Caixa.objects.create(
            nome='Caixa KR 01',
            origem='KR',
            status=Caixa.Status.ENTREGUE
        )

        # CEG com Caixa
        self.ceg = CEG.objects.create(
            era=self.era,
            title='CEG With YOU-th POB',
            slug='ceg-with-youth-pob',
            caixa=self.caixa_kr,
            frete_inter=Decimal('5.00'),
            taxa_aduaneira=Decimal('2.50')
        )

        self.tipo_pc, _ = TipoItem.objects.get_or_create(nome='Photocard')

        self.item_def1 = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Jihyo POB Soundwave',
            member_name='Jihyo',
            tipo_item=self.tipo_pc,
            default_price=Decimal('45.00')
        )
        self.item_def2 = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Nayeon POB Soundwave',
            member_name='Nayeon',
            tipo_item=self.tipo_pc,
            default_price=Decimal('48.00')
        )

        self.set1 = CEGSet.objects.create(ceg=self.ceg, set_number=1)
        self.slots = self.set1.generate_slots()
        self.slot1 = self.slots[0]
        self.slot2 = self.slots[1]

        # Reserva os slots para a Maria
        self.slot1.claimed_by = self.participant
        self.slot1.is_item_paid = True
        self.slot1.is_frete_inter_paid = True
        self.slot1.is_taxa_aduaneira_paid = True
        self.slot1.save()

        self.slot2.claimed_by = self.participant
        self.slot2.is_item_paid = True
        self.slot2.is_frete_inter_paid = False
        self.slot2.is_taxa_aduaneira_paid = False
        self.slot2.save()

        # Cria reserva (Claim)
        Claim.objects.create(slot=self.slot1, participant=self.participant, status=Claim.Status.PAID)
        Claim.objects.create(slot=self.slot2, participant=self.participant, status=Claim.Status.PAID)

        # Item Individual Mercari
        self.item_mercari = ItemIndividual.objects.create(
            comprador=self.participant,
            nome='Momo Photocard Fancy Rare',
            tipo_item=self.tipo_pc,
            preco_produto=Decimal('60.00'),
            frete_inter=Decimal('10.00'),
            frete_inter_pago=True,
            taxa_aduaneira=Decimal('4.00'),
            taxa_aduaneira_paga=True
        )

    def test_permission_protection(self):
        """Usuário não-staff não deve acessar a aba de envios nacionais."""
        # Sem login
        resp = self.client.get(reverse('envios_nacionais'))
        self.assertEqual(resp.status_code, 302)

        # Com login de usuário comum
        self.client.login(username='regular_user', password='password123')
        resp = self.client.get(reverse('envios_nacionais'))
        self.assertEqual(resp.status_code, 302)

        # Com login de admin/staff
        self.client.login(username='admin_staff', password='password123')
        resp = self.client.get(reverse('consulta_joiner'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Consulta Joiner')

    def test_view_participant_items_and_filters(self):
        """Ao selecionar um participante na Consulta Joiner, exibe seus slots e itens Mercari com métricas financeiras."""
        self.client.login(username='admin_staff', password='password123')
        resp = self.client.get(f"{reverse('consulta_joiner')}?participant_id={self.participant.id}")

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Maria Silva')
        self.assertContains(resp, 'Jihyo POB Soundwave')
        self.assertContains(resp, 'Momo Photocard Fancy Rare')
        # Confirma contagem de itens
        self.assertEqual(resp.context['stats']['total_items'], 3)
        self.assertEqual(resp.context['stats']['unpacked_count'], 3)

    def test_empacotar_itens_novo_pacote(self):
        """Testa o empacotamento de slots e mercari em um novo PacoteNacional."""
        self.client.login(username='admin_staff', password='password123')

        uids = f"slot_{self.slot1.id},mercari_{self.item_mercari.id}"
        resp = self.client.post(reverse('empacotar_itens'), {
            'participant_id': self.participant.id,
            'action_type': 'novo_pacote',
            'selected_uids': uids,
            'identificador': 'PAC-TESTE-01',
            'transportadora': 'Correios Mini Envios',
            'valor_frete_nacional': '18,50',
            'is_frete_pago': 'on',
            'observacoes': 'Embalar com toploader e plástico bolha duplo',
        })

        self.assertEqual(resp.status_code, 302)

        pacote = PacoteNacional.objects.get(identificador='PAC-TESTE-01')
        self.assertEqual(pacote.participant, self.participant)
        self.assertEqual(pacote.status, PacoteNacional.Status.EM_PREPARACAO)
        self.assertEqual(pacote.transportadora, 'Correios Mini Envios')
        self.assertEqual(pacote.valor_frete_nacional, Decimal('18.50'))
        self.assertTrue(pacote.is_frete_pago)
        self.assertEqual(pacote.total_itens, 2)

        self.slot1.refresh_from_db()
        self.item_mercari.refresh_from_db()
        self.assertEqual(self.slot1.pacote_nacional, pacote)
        self.assertEqual(self.item_mercari.pacote_nacional, pacote)

    def test_empacotar_adicionar_a_pacote_existente(self):
        """Testa a adição de um item a um pacote existente em preparação."""
        self.client.login(username='admin_staff', password='password123')

        # Torna slot2 elegível para empacotar
        self.slot2.is_frete_inter_paid = True
        self.slot2.is_taxa_aduaneira_paid = True
        self.slot2.save()

        pacote = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-EXISTENTE-01',
            status=PacoteNacional.Status.EM_PREPARACAO
        )
        self.slot1.pacote_nacional = pacote
        self.slot1.save()

        # Adiciona o slot2 ao mesmo pacote existente
        resp = self.client.post(reverse('empacotar_itens'), {
            'participant_id': self.participant.id,
            'action_type': 'adicionar_existente',
            'pacote_id': pacote.id,
            'selected_uids': f"slot_{self.slot2.id}",
        })

        self.assertEqual(resp.status_code, 302)
        self.slot2.refresh_from_db()
        self.assertEqual(self.slot2.pacote_nacional, pacote)
        self.assertEqual(pacote.total_itens, 2)

    def test_marcar_pacote_enviado_nacionalmente_e_notificacao(self):
        """Testa o despacho de pacote com código de rastreamento e disparo de notificação."""
        self.client.login(username='admin_staff', password='password123')

        pacote = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-DESPACHO-01',
            status=PacoteNacional.Status.EM_PREPARACAO
        )
        self.slot1.pacote_nacional = pacote
        self.slot1.save()

        resp = self.client.post(reverse('marcar_pacote_enviado', args=[pacote.id]), {
            'codigo_rastreio': 'NL123456789BR',
            'transportadora': 'Correios Sedex'
        })

        self.assertEqual(resp.status_code, 302)
        pacote.refresh_from_db()
        self.assertEqual(pacote.status, PacoteNacional.Status.ENVIADO)
        self.assertEqual(pacote.codigo_rastreio, 'NL123456789BR')
        self.assertEqual(pacote.transportadora, 'Correios Sedex')
        self.assertIsNotNone(pacote.data_envio)
        self.assertIn('NL123456789BR', pacote.tracking_url)

        # Verifica se o participante recebeu notificação
        notif = ParticipantNotification.objects.filter(
            participant=self.participant,
            notification_type=ParticipantNotification.NotificationType.ENVIO_NACIONAL
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn('PAC-DESPACHO-01', notif.title)
        self.assertIn('NL123456789BR', notif.message)

    def test_desempacotar_item(self):
        """Testa desvincular um item de um pacote nacional."""
        self.client.login(username='admin_staff', password='password123')

        pacote = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-DESFAZER-01',
            status=PacoteNacional.Status.EM_PREPARACAO
        )
        self.slot1.pacote_nacional = pacote
        self.slot1.save()

        resp = self.client.post(reverse('desempacotar_item'), {
            'item_uid': f"slot_{self.slot1.id}",
            'participant_id': self.participant.id
        })

        self.assertEqual(resp.status_code, 302)
        self.slot1.refresh_from_db()
        self.assertIsNone(self.slot1.pacote_nacional)
        self.assertEqual(pacote.total_itens, 0)

    def test_excluir_pacote(self):
        """Testa exclusão de pacote desvinculando itens automaticamente."""
        self.client.login(username='admin_staff', password='password123')

        pacote = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-EXCLUIR-01'
        )
        self.slot1.pacote_nacional = pacote
        self.slot1.save()

        resp = self.client.post(reverse('excluir_pacote', args=[pacote.id]))
        self.assertEqual(resp.status_code, 302)

        self.assertFalse(PacoteNacional.objects.filter(id=pacote.id).exists())
        self.slot1.refresh_from_db()
        self.assertIsNone(self.slot1.pacote_nacional)

    def test_my_claims_dashboard_exibe_pacotes_e_rastreio(self):
        """Testa se o participante logado via OTP visualiza seus pacotes e links de rastreio em /me/claims/."""
        pacote = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-RASTREIO-99',
            codigo_rastreio='QD987654321BR',
            transportadora='Correios Mini Envios',
            status=PacoteNacional.Status.ENVIADO
        )
        self.slot1.pacote_nacional = pacote
        self.slot1.save()

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        resp = self.client.get(reverse('my_claims'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Meus Pacotes & Envios Nacionais')
        self.assertContains(resp, 'PAC-RASTREIO-99')
        self.assertContains(resp, 'QD987654321BR')
        self.assertContains(resp, 'rastreamento.correios.com.br')

    def test_pacote_entregue_movido_para_recebidos_e_sem_badge_envio(self):
        """Quando o pacote é entregue, ele deve ser exibido em 'Pacotes Recebidos',
        não em 'Meus Pacotes & Envios Nacionais', e o badge no botão da aba Caixinha
        não deve exibir '1 envio(s)'."""
        pacote = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-ENTREGUE-01',
            transportadora='Correios',
            status=PacoteNacional.Status.ENTREGUE,
            feedback_rating=5,
            feedback_texto='Chegou perfeito!'
        )
        self.slot1.pacote_nacional = pacote
        self.slot1.save()

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        resp = self.client.get(reverse('my_claims'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Pacotes Recebidos')
        self.assertContains(resp, 'PAC-ENTREGUE-01')
        self.assertContains(resp, 'Chegou perfeito!')
        # Não deve exibir a seção de em andamento já que não há outros pacotes
        self.assertNotContains(resp, 'Meus Pacotes & Envios Nacionais')
        # Nem deve exibir o badge '1 envio(s)' na aba superior
        self.assertNotContains(resp, '1 envio(s)')
        self.assertNotContains(resp, 'envio(s)')

    def test_item_enviado_bloqueado_para_reempacotar(self):
        """Itens que já foram enviados nacionalmente não podem ser re-empacotados."""
        self.client.login(username='admin_staff', password='password123')

        # Cria pacote já ENVIADO
        pacote_enviado = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-JA-ENVIADO',
            status=PacoteNacional.Status.ENVIADO,
            codigo_rastreio='BR123456789XX'
        )
        self.slot1.pacote_nacional = pacote_enviado
        self.slot1.save()

        # Tenta empacotar o slot1 em um novo pacote
        resp = self.client.post(reverse('empacotar_itens'), {
            'participant_id': self.participant.id,
            'action_type': 'novo_pacote',
            'selected_uids': f"slot_{self.slot1.id}",
            'identificador': 'PAC-NOVO-TENTATIVA',
        })
        self.assertEqual(resp.status_code, 302)

        # O slot1 deve continuar no pacote_enviado e o novo pacote não deve ter sido criado
        self.slot1.refresh_from_db()
        self.assertEqual(self.slot1.pacote_nacional, pacote_enviado)
        self.assertFalse(PacoteNacional.objects.filter(identificador='PAC-NOVO-TENTATIVA').exists())

    def test_toggle_payment_slot_and_mercari_api(self):
        """Testa a alternância de pagamento (item, inter, taxa) via API AJAX."""
        self.client.login(username='admin_staff', password='password123')

        # 1. Toggle em Slot (item, inter, taxa)
        resp = self.client.post(
            reverse('toggle_slot_payment', args=[self.slot1.id]),
            data='{"field": "item"}',
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertFalse(data['is_item_paid'])  # Era True no setUp, virou False

        resp = self.client.post(
            reverse('toggle_slot_payment', args=[self.slot1.id]),
            data='{"field": "inter"}',
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['is_frete_inter_paid'])  # Era True, virou False

        # 2. Toggle em Item Individual Mercari (item/produto, frete, taxa)
        self.assertTrue(self.item_mercari.produto_pago)
        resp = self.client.post(
            reverse('toggle_item_payment', args=[self.item_mercari.id]),
            data='{"field": "item"}',
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertFalse(data['is_item_paid'])

        self.item_mercari.refresh_from_db()
        self.assertFalse(self.item_mercari.produto_pago)

        # Toggle de volta para pago
        resp = self.client.post(
            reverse('toggle_item_payment', args=[self.item_mercari.id]),
            data='{"field": "item"}',
            content_type='application/json'
        )
        data = resp.json()
        self.assertTrue(data['is_item_paid'])
        self.item_mercari.refresh_from_db()
        self.assertTrue(self.item_mercari.produto_pago)

    def test_envios_nacionais_global_dashboard(self):
        """Testa o painel geral de envios nacionais (sem selecionar participante) e filtros."""
        self.client.login(username='admin_staff', password='password123')

        pacote1 = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-GLOBAL-01',
            status=PacoteNacional.Status.EM_PREPARACAO
        )
        pacote2 = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-GLOBAL-02',
            status=PacoteNacional.Status.ENVIADO,
            codigo_rastreio='NL999888777BR'
        )
        pacote3 = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-GLOBAL-03',
            status=PacoteNacional.Status.ENTREGUE,
            feedback_rating=5,
            feedback_texto='Melhor embalagem de todas!'
        )

        resp = self.client.get(reverse('envios_nacionais'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'PAC-GLOBAL-01')
        self.assertContains(resp, 'PAC-GLOBAL-02')
        self.assertContains(resp, 'PAC-GLOBAL-03')
        self.assertEqual(resp.context['stats']['total_pacotes'], 3)
        self.assertEqual(resp.context['stats']['em_preparacao_count'], 1)
        self.assertEqual(resp.context['stats']['enviados_count'], 1)
        self.assertEqual(resp.context['stats']['entregues_count'], 1)
        self.assertEqual(resp.context['stats']['com_feedback_count'], 1)
        self.assertEqual(resp.context['stats']['media_feedback'], 5.0)

        # Filtro por feedback
        resp_feedback = self.client.get(f"{reverse('envios_nacionais')}?feedback=com_feedback")
        self.assertEqual(resp_feedback.status_code, 200)
        self.assertContains(resp_feedback, 'PAC-GLOBAL-03')
        self.assertNotContains(resp_feedback, 'PAC-GLOBAL-01')

    def test_marcar_pacote_entregue_admin(self):
        """Testa o operador staff marcando o pacote como entregue."""
        self.client.login(username='admin_staff', password='password123')

        pacote = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-ENTREGA-ADMIN',
            status=PacoteNacional.Status.ENVIADO
        )

        resp = self.client.post(reverse('marcar_pacote_entregue', args=[pacote.id]))
        self.assertEqual(resp.status_code, 302)

        pacote.refresh_from_db()
        self.assertEqual(pacote.status, PacoteNacional.Status.ENTREGUE)
        self.assertEqual(pacote.entregue_por, 'ADMIN')
        self.assertIsNotNone(pacote.data_entrega)

    def test_confirmar_entrega_joiner_com_feedback(self):
        """Testa o joiner confirmando a entrega do pacote e enviando nota e depoimento."""
        pacote = PacoteNacional.objects.create(
            participant=self.participant,
            identificador='PAC-FEEDBACK-TEST',
            status=PacoteNacional.Status.ENVIADO,
            codigo_rastreio='BR000111222BR'
        )

        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        resp = self.client.post(reverse('confirmar_entrega_pacote', args=[pacote.id]), {
            'rating': '5',
            'feedback': 'Chegou super rápido e os cards vieram com toploader! Amei muito! ❤️'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse('my_claims'))

        pacote.refresh_from_db()
        self.assertEqual(pacote.status, PacoteNacional.Status.ENTREGUE)
        self.assertEqual(pacote.entregue_por, 'JOINER')
        self.assertEqual(pacote.feedback_rating, 5)
        self.assertEqual(pacote.feedback_texto, 'Chegou super rápido e os cards vieram com toploader! Amei muito! ❤️')
        self.assertIsNotNone(pacote.feedback_data)

        # Verifica na página de meus claims
        resp_claims = self.client.get(reverse('my_claims'))
        self.assertContains(resp_claims, 'Sua Avaliação:')
        self.assertContains(resp_claims, 'Chegou super rápido e os cards vieram com toploader!')

    def test_consulta_joiner_search_by_name(self):
        """Testa busca de joiner por nome (parcial ou completo)."""
        self.client.login(username='admin_staff', password='password123')
        resp = self.client.get(f"{reverse('consulta_joiner')}?q=Maria")
        self.assertEqual(resp.status_code, 200)
        # Se 1 único resultado, auto-seleciona a Maria
        self.assertIsNotNone(resp.context['selected_participant'])
        self.assertEqual(resp.context['selected_participant'].id, self.participant.id)
        self.assertContains(resp, 'Maria Silva')

    def test_consulta_joiner_search_by_phone(self):
        """Testa busca de joiner por telefone (com ou sem formatação)."""
        self.client.login(username='admin_staff', password='password123')
        # Busca por dígitos
        resp = self.client.get(f"{reverse('consulta_joiner')}?q=999887766")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.context['selected_participant'])
        self.assertEqual(resp.context['selected_participant'].id, self.participant.id)

        # Busca por formato com parênteses e hífen
        resp2 = self.client.get(f"{reverse('consulta_joiner')}?q=(11) 99988-7766")
        self.assertEqual(resp2.status_code, 200)
        self.assertIsNotNone(resp2.context['selected_participant'])
        self.assertEqual(resp2.context['selected_participant'].id, self.participant.id)

    def test_consulta_joiner_search_by_forma_que_quer_ser_chamado(self):
        """Testa busca de joiner pela forma que quer ser chamado (username ou rede social @)."""
        self.client.login(username='admin_staff', password='password123')
        # Busca por username (como quer ser chamado)
        resp = self.client.get(f"{reverse('consulta_joiner')}?q=mariakpop")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.context['selected_participant'])
        self.assertEqual(resp.context['selected_participant'].id, self.participant.id)

        # Busca por @social
        resp2 = self.client.get(f"{reverse('consulta_joiner')}?q=@mariakpop")
        self.assertEqual(resp2.status_code, 200)
        self.assertIsNotNone(resp2.context['selected_participant'])
        self.assertEqual(resp2.context['selected_participant'].id, self.participant.id)

    def test_consulta_joiner_financial_debt_and_historical_paid(self):
        """Testa o cálculo preciso de itens, frete, taxa devidos e total pago historicamente."""
        self.client.login(username='admin_staff', password='password123')

        # Cria um terceiro slot com item NÃO pago para Maria
        slot3 = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Chaeyoung POB Soundwave',
            member_name='Chaeyoung',
            tipo_item=self.tipo_pc,
            default_price=Decimal('50.00')
        )
        item_slot3 = ItemSlot.objects.create(
            set=self.set1,
            item_definition=slot3,
            price=Decimal('50.00'),
            claimed_by=self.participant,
            status=ItemSlot.Status.RESERVED,
            is_item_paid=False,
            is_frete_inter_paid=False,
            is_taxa_aduaneira_paid=False
        )

        # 1. Verifica método no modelo Participant
        summary = self.participant.get_financial_summary()
        self.assertEqual(summary['deve_itens'], Decimal('50.00'))
        # frete inter não pago: slot2 (5.00) + slot3 (5.00) = 10.00
        self.assertEqual(summary['deve_frete'], Decimal('10.00'))
        # taxa aduaneira não paga: slot2 (2.50) + slot3 (2.50) = 5.00
        self.assertEqual(summary['deve_taxa'], Decimal('5.00'))
        self.assertEqual(summary['total_devido'], Decimal('65.00'))

        # Itens pagos: slot1 (45.00) + slot2 (48.00) + mercari (60.00) = 153.00
        self.assertEqual(summary['pago_itens'], Decimal('153.00'))
        # Fretes pagos: slot1 (5.00) + mercari (10.00) = 15.00
        self.assertEqual(summary['pago_frete'], Decimal('15.00'))
        # Taxas pagas: slot1 (2.50) + mercari (4.00) = 6.50
        self.assertEqual(summary['pago_taxa'], Decimal('6.50'))
        # Total pago historico = 153 + 15 + 6.50 = 174.50
        self.assertEqual(summary['total_pago_historico'], Decimal('174.50'))

        # 2. Verifica a view Consulta Joiner
        resp = self.client.get(f"{reverse('consulta_joiner')}?participant_id={self.participant.id}")
        self.assertEqual(resp.status_code, 200)
        stats = resp.context['stats']
        self.assertEqual(stats['deve_itens'], 50.00)
        self.assertEqual(stats['deve_frete'], 10.00)
        self.assertEqual(stats['deve_taxa'], 5.00)
        self.assertEqual(stats['total_devido'], 65.00)
        self.assertEqual(stats['pago_itens'], 153.00)
        self.assertEqual(stats['pago_frete'], 15.00)
        self.assertEqual(stats['pago_taxa'], 6.50)
        self.assertEqual(stats['total_pago_historico'], 174.50)

        # Confirma presença no HTML renderizado
        self.assertContains(resp, 'Quanto Deve Atualmente')
        self.assertContains(resp, 'Quanto Já Pagou Historicamente')
        self.assertContains(resp, 'R$ 65,00')
        self.assertContains(resp, 'R$ 174,50')


