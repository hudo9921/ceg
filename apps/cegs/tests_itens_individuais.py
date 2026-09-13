import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from apps.groups.models import KpopGroup, Era
from apps.cegs.models import Caixa, CEG, CEGItemDefinition, CEGSet, ItemSlot, ItemIndividual
from apps.participants.models import Participant, Claim
from apps.analytics.services import AnalyticsService


class ItemIndividualTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='admin_test',
            email='admin@test.com',
            password='password123'
        )
        self.client.force_login(self.admin_user)

        self.group = KpopGroup.objects.create(name="TWICE", slug="twice")
        self.era = Era.objects.create(group=self.group, name="With YOU-th", slug="with-you-th")

        # Caixa Mercari (JP)
        self.caixa_jp = Caixa.objects.create(
            nome="Caixa Mercari #01 - Lotes Tóquio",
            origem=Caixa.Origem.JP,
            status=Caixa.Status.EM_CONSOLIDACAO
        )

        # CEG com Slot e Claim para testar analytics híbrido
        self.ceg = CEG.objects.create(
            era=self.era,
            title="TWICE With YOU-th Digipack",
            slug="twice-with-you-th-digipack",
            status=CEG.Status.OPEN,
            frete_inter=Decimal("20.00"),
            taxa_aduaneira=Decimal("15.00")
        )
        self.item_def = CEGItemDefinition.objects.create(
            ceg=self.ceg, name="Sana Photocard", default_price=Decimal("50.00")
        )
        self.set1 = CEGSet.objects.create(ceg=self.ceg, set_number=1, is_active=True)
        self.slot1 = ItemSlot.objects.create(
            set=self.set1, item_definition=self.item_def, price=Decimal("50.00"), status=ItemSlot.Status.RESERVED
        )
        self.participant = Participant.objects.create(
            whatsapp="5511999997777",
            name="Sana Lover",
            username="sanalover"
        )
        self.slot1.claimed_by = self.participant
        self.slot1.save()
        self.claim1 = Claim.objects.create(
            slot=self.slot1,
            participant=self.participant,
            total_price=Decimal("50.00"),
            status=Claim.Status.PAID
        )

    def test_create_item_individual_with_url(self):
        url = reverse('create_item_individual')
        data = {
            'nome': 'Photocard Jihyo Hare Hare Holo',
            'link_pedido': 'https://jp.mercari.com/item/m123456789',
            'foto_url': 'https://example.com/photo.jpg',
            'whatsapp': '(11) 98888-1234',
            'comprador_nome': 'Momo Stan',
            'quantidade': '2',
            'caixa_id': str(self.caixa_jp.id),
            'frete_inter': '18.50',
            'taxa_aduaneira': '12.00',
            'preco_produto': '85.00',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        item = ItemIndividual.objects.filter(nome='Photocard Jihyo Hare Hare Holo').first()
        self.assertIsNotNone(item)
        self.assertEqual(item.caixa, self.caixa_jp)
        self.assertEqual(item.quantidade, 2)
        self.assertEqual(item.frete_inter, Decimal('18.50'))
        self.assertEqual(item.taxa_aduaneira, Decimal('12.00'))
        self.assertEqual(item.preco_produto, Decimal('85.00'))
        self.assertEqual(item.status, ItemIndividual.Status.COMPRADO)
        self.assertFalse(item.frete_inter_pago)
        self.assertFalse(item.taxa_aduaneira_paga)

        # Comprador vinculado automaticamente
        self.assertIsNotNone(item.comprador)
        self.assertEqual(item.comprador.whatsapp, '5511988881234')
        self.assertEqual(item.comprador.name, 'Momo Stan')

    def test_create_item_individual_with_base64_paste(self):
        url = reverse('create_item_individual')
        # 1x1 transparent PNG base64
        tiny_png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        data = {
            'nome': 'Nayeon Pop Album POB',
            'link_pedido': 'https://jp.mercari.com/item/m987654321',
            'foto_base64': tiny_png,
            'whatsapp': '5511999997777',  # participante existente
            'quantidade': '1',
            'caixa_id': str(self.caixa_jp.id),
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        item = ItemIndividual.objects.filter(nome='Nayeon Pop Album POB').first()
        self.assertIsNotNone(item)
        self.assertEqual(item.comprador, self.participant)
        self.assertTrue(bool(item.foto_arquivo))
        self.assertTrue(item.foto_arquivo.name.endswith('.png'))

    def test_caixa_status_cascade_to_itens_individuais(self):
        item = ItemIndividual.objects.create(
            nome="Chaeyoung Rare Card",
            caixa=self.caixa_jp,
            comprador=self.participant,
            quantidade=1,
            status=ItemIndividual.Status.COMPRADO
        )

        # 1. Caixa em consolidação
        self.caixa_jp.atualizar_status(Caixa.Status.EM_CONSOLIDACAO)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemIndividual.Status.EM_CONSOLIDACAO)

        # 2. Caixa enviada
        self.caixa_jp.codigo_rastreio = "JP123456789BR"
        self.caixa_jp.save()
        self.caixa_jp.atualizar_status(Caixa.Status.ENVIADA)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemIndividual.Status.ENVIADO)

        # 3. Caixa liberada
        self.caixa_jp.atualizar_status(Caixa.Status.LIBERADA)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemIndividual.Status.LIBERADO)

        # 4. Caixa entregue ao organizador (Na GOM)
        self.caixa_jp.atualizar_status(Caixa.Status.ENTREGUE)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemIndividual.Status.NA_GOM)

        # 5. Caixa finalizada
        self.caixa_jp.atualizar_status(Caixa.Status.FINALIZADA)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemIndividual.Status.FINALIZADO)

    def test_toggle_payment_api(self):
        item = ItemIndividual.objects.create(
            nome="Dahyun Photocard",
            caixa=self.caixa_jp,
            comprador=self.participant,
            frete_inter=Decimal("15.00"),
            taxa_aduaneira=Decimal("10.00"),
            frete_inter_pago=False,
            taxa_aduaneira_paga=False
        )

        toggle_url = reverse('toggle_item_payment', kwargs={'item_id': item.id})

        # Alterna frete_inter_pago para True
        res = self.client.post(toggle_url, {'field': 'frete_inter_pago'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['is_paid'])
        item.refresh_from_db()
        self.assertTrue(item.frete_inter_pago)

        # Alterna frete_inter_pago de volta para False
        res = self.client.post(toggle_url, {'field': 'frete_inter_pago'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()['is_paid'])
        item.refresh_from_db()
        self.assertFalse(item.frete_inter_pago)

        # Alterna taxa_aduaneira_paga para True
        res = self.client.post(toggle_url, {'field': 'taxa_aduaneira_paga'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['is_paid'])
        item.refresh_from_db()
        self.assertTrue(item.taxa_aduaneira_paga)

    def test_participant_lookup_api(self):
        url = reverse('api_participant_lookup')
        res = self.client.get(url, {'phone': '11999997777'})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['found'])
        self.assertEqual(data['name'], 'Sana Lover')

        # Telefone inexistente
        res_empty = self.client.get(url, {'phone': '11000000000'})
        self.assertFalse(res_empty.json()['found'])

    def test_analytics_services_with_categories(self):
        # Cria item individual mercari
        ItemIndividual.objects.create(
            nome="Tzuyu Lucky Draw",
            caixa=self.caixa_jp,
            comprador=self.participant,
            preco_produto=Decimal("120.00"),
            frete_inter=Decimal("25.00"),
            taxa_aduaneira=Decimal("15.00"),
            frete_inter_pago=True,
            taxa_aduaneira_paga=False,
            status=ItemIndividual.Status.ENVIADO
        )

        # 1. Operational status
        status_all = AnalyticsService.get_cegs_operational_status(category='all')
        status_ceg = AnalyticsService.get_cegs_operational_status(category='ceg')
        status_mercari = AnalyticsService.get_cegs_operational_status(category='mercari')

        self.assertIn('mercari_status', status_all)
        self.assertEqual(status_all['mercari_status']['total_itens'], 1)
        self.assertEqual(status_mercari['mercari_status']['total_itens'], 1)
        self.assertEqual(len(status_ceg['cegs_overview']), 1)

        # 2. Sales analytics
        sales_all = AnalyticsService.get_sales_analytics(category='all')
        sales_ceg = AnalyticsService.get_sales_analytics(category='ceg')
        sales_mercari = AnalyticsService.get_sales_analytics(category='mercari')

        self.assertEqual(sales_ceg['summary']['total_claims'], 1)
        self.assertEqual(sales_mercari['summary']['total_claims'], 1)
        self.assertEqual(float(sales_mercari['summary']['total_sales']), 160.0)
        self.assertEqual(sales_all['summary']['total_claims'], 2)
        self.assertEqual(float(sales_all['summary']['total_sales']), 210.0)

    def test_hub_creations_view(self):
        url = reverse('creations_hub')
        res_all = self.client.get(url, {'category': 'all'})
        self.assertEqual(res_all.status_code, 200)
        self.assertEqual(res_all.context['category'], 'all')

        res_mercari = self.client.get(url, {'category': 'mercari'})
        self.assertEqual(res_mercari.status_code, 200)
        self.assertEqual(res_mercari.context['category'], 'mercari')

    def test_buyer_claims_view_with_itens_individuais(self):
        ItemIndividual.objects.create(
            nome="Jeongyeon Special Card",
            caixa=self.caixa_jp,
            comprador=self.participant,
            quantidade=1
        )
        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        res = self.client.get(reverse('my_claims'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['itens_individuais_count'], 1)
        self.assertEqual(len(res.context['itens_individuais']), 1)

    def test_create_item_with_existing_participant_id_and_no_shipping_tax(self):
        """Verifica cadastro selecionando cliente existente via participant_id e sem frete/taxa aduaneira."""
        url = reverse('create_item_individual')
        data = {
            'nome': 'Mina Masterpiece Trading Card',
            'link_pedido': 'https://jp.mercari.com/item/m555555555',
            'foto_url': 'https://example.com/mina.jpg',
            'participant_id': str(self.participant.id),
            'quantidade': '1',
            'preco_produto': '60.00',
            'caixa_id': str(self.caixa_jp.id),
            # Note: frete_inter and taxa_aduaneira are omitted from creation form
        }
        res = self.client.post(url, data)
        self.assertEqual(res.status_code, 302)

        item = ItemIndividual.objects.filter(nome='Mina Masterpiece Trading Card').first()
        self.assertIsNotNone(item)
        self.assertEqual(item.comprador, self.participant)
        self.assertEqual(item.caixa, self.caixa_jp)
        self.assertIsNone(item.frete_inter)
        self.assertIsNone(item.taxa_aduaneira)
        self.assertEqual(item.preco_produto, Decimal('60.00'))

    def test_caixa_link_and_unlink_item_individual(self):
        """Testa vincular itens avulsos a uma caixa e desvincular sem excluí-los."""
        # Cria item avulso (sem caixa)
        item_avulso = ItemIndividual.objects.create(
            nome="Jihyo Zone Card Avulso",
            comprador=self.participant,
            quantidade=1,
            status=ItemIndividual.Status.COMPRADO
        )
        self.assertIsNone(item_avulso.caixa)

        # 1. Vincular à caixa_jp
        link_url = reverse('caixa_link_itens', kwargs={'slug': self.caixa_jp.slug})
        res_link = self.client.post(link_url, {'item_ids': [str(item_avulso.id)]})
        self.assertEqual(res_link.status_code, 302)

        item_avulso.refresh_from_db()
        self.assertEqual(item_avulso.caixa, self.caixa_jp)
        # Status deve sincronizar com o status da caixa (EM_CONSOLIDACAO)
        self.assertEqual(item_avulso.status, ItemIndividual.Status.EM_CONSOLIDACAO)

        # 2. Desvincular da caixa_jp
        unlink_url = reverse('caixa_unlink_item', kwargs={'slug': self.caixa_jp.slug, 'item_id': item_avulso.id})
        res_unlink = self.client.post(unlink_url)
        self.assertEqual(res_unlink.status_code, 302)

        item_avulso.refresh_from_db()
        self.assertIsNone(item_avulso.caixa)
        self.assertEqual(item_avulso.status, ItemIndividual.Status.COMPRADO)
        # O item continua existindo no banco de dados
        self.assertTrue(ItemIndividual.objects.filter(id=item_avulso.id).exists())

    def test_creations_hub_with_preselected_caixa(self):
        """Verifica se CreationsHub carrega caixas_mercari e repassa preselected_caixa_id e auto_open_modal."""
        url = reverse('creations_hub')
        res = self.client.get(url, {
            'category': 'mercari',
            'caixa_id': str(self.caixa_jp.id),
            'open': 'item_individual'
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['preselected_caixa_id'], self.caixa_jp.id)
        self.assertEqual(res.context['auto_open_modal'], 'item_individual')
        self.assertIn('caixas_mercari', res.context)
        self.assertTrue(any(c.id == self.caixa_jp.id for c in res.context['caixas_mercari']))

    def test_create_item_with_name_correction_updates_participant(self):
        """Verifica se corrigir o nome de um participante existente atualiza seu registro."""
        url = reverse('create_item_individual')
        data = {
            'nome': 'Sana Zone Rare Card',
            'participant_id': str(self.participant.id),
            'comprador_nome': 'Sana Minatozaki Oficial',
            'whatsapp': self.participant.whatsapp,
            'quantidade': '1',
            'preco_produto': '90.00',
        }
        res = self.client.post(url, data)
        self.assertEqual(res.status_code, 302)

        self.participant.refresh_from_db()
        self.assertEqual(self.participant.name, 'Sana Minatozaki Oficial')

    def test_update_item_individual_tipo_item_and_details(self):
        """Verifica se o organizador consegue editar tipo de item, nome, status, prazos e detalhes de ItemIndividual."""
        from apps.cegs.models import TipoItem
        tipo_album, _ = TipoItem.objects.get_or_create(nome='Álbum')
        tipo_labubu, _ = TipoItem.objects.get_or_create(nome='Labubu')

        item = ItemIndividual.objects.create(
            comprador=self.participant,
            nome='Item Sem Tipo',
            tipo_item=tipo_album,
            quantidade=1,
            preco_produto=Decimal('50.00'),
            status=ItemIndividual.Status.COMPRADO
        )

        update_url = reverse('update_item_individual', kwargs={'item_id': item.id})
        post_data = {
            'nome': 'Labubu Pop Mart Monters Ver. 2',
            'tipo_item_id': str(tipo_labubu.id),
            'quantidade': '3',
            'preco_produto': '150.00',
            'status': ItemIndividual.Status.EM_CONSOLIDACAO,
            'link_pedido': 'https://jp.mercari.com/item/m123456789',
            'observacoes': 'Embalagem especial de colecionador',
            'frete_inter': '35.00',
            'frete_inter_pago': 'on',
            'prazo_frete_inter': '2026-10-15T23:59',
            'next_url': '/analytics/cegs/?category=mercari',
        }

        response = self.client.post(update_url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/analytics/cegs/?category=mercari')

        item.refresh_from_db()
        self.assertEqual(item.nome, 'Labubu Pop Mart Monters Ver. 2')
        self.assertEqual(item.tipo_item, tipo_labubu)
        self.assertEqual(item.quantidade, 3)
        self.assertEqual(item.preco_produto, Decimal('150.00'))
        self.assertEqual(item.status, ItemIndividual.Status.EM_CONSOLIDACAO)
        self.assertEqual(item.link_pedido, 'https://jp.mercari.com/item/m123456789')
        self.assertEqual(item.observacoes, 'Embalagem especial de colecionador')
        self.assertEqual(item.frete_inter, Decimal('35.00'))
        self.assertTrue(item.frete_inter_pago)
        self.assertIsNotNone(item.prazo_frete_inter)

    def test_analytics_ceg_status_shows_mercari_item_with_tipo_and_edit_controls(self):
        """Verifica se a tela de status exibe o badge do tipo de item e botão de editar."""
        from apps.cegs.models import TipoItem
        tipo_camisa, _ = TipoItem.objects.get_or_create(nome='Camisa')

        item = ItemIndividual.objects.create(
            comprador=self.participant,
            nome='Camisa Tour TWICE',
            tipo_item=tipo_camisa,
            quantidade=1,
            preco_produto=Decimal('120.00'),
            status=ItemIndividual.Status.COMPRADO
        )

        res = self.client.get('/analytics/cegs/?category=mercari')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Camisa Tour TWICE')
        self.assertContains(res, 'Camisa')
        self.assertContains(res, f'openEditItem({item.id})')
        self.assertContains(res, 'Editar Pedido Individual Mercari')



