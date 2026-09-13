import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from apps.groups.models import KpopGroup, Era
from apps.cegs.models import Caixa, CEG, CEGItemDefinition, CEGSet, ItemSlot
from apps.participants.models import Participant, Claim, ParticipantNotification


class CaixaModelAndCascadeTests(TestCase):
    def setUp(self):
        self.group = KpopGroup.objects.create(name="NewJeans", slug="newjeans")
        self.era = Era.objects.create(group=self.group, name="How Sweet", slug="how-sweet")

        # Cria 2 CEGs
        self.ceg1 = CEG.objects.create(
            era=self.era,
            title="NewJeans How Sweet Standard",
            slug="newjeans-how-sweet-standard",
            status=CEG.Status.OPEN
        )
        self.ceg2 = CEG.objects.create(
            era=self.era,
            title="NewJeans How Sweet Weverse POB",
            slug="newjeans-how-sweet-weverse-pob",
            status=CEG.Status.OPEN
        )

        # Definições de itens e sets
        self.item_def1 = CEGItemDefinition.objects.create(
            ceg=self.ceg1, name="Hanni Photocard", default_price=Decimal("45.00")
        )
        self.set1 = CEGSet.objects.create(ceg=self.ceg1, set_number=1, is_active=True)
        self.slot1 = ItemSlot.objects.create(
            set=self.set1, item_definition=self.item_def1, price=Decimal("45.00"), status=ItemSlot.Status.AVAILABLE
        )

        # Participante comprador
        self.participant = Participant.objects.create(
            whatsapp="5511999998888",
            name="Minji Stan",
            username="minjistan"
        )
        self.slot1.claimed_by = self.participant
        self.slot1.status = ItemSlot.Status.RESERVED
        self.slot1.save()
        self.claim1 = Claim.objects.create(
            slot=self.slot1,
            participant=self.participant,
            total_price=Decimal("45.00"),
            status=Claim.Status.PAID
        )

    def test_caixa_creation_and_tracking_url(self):
        caixa_kr = Caixa.objects.create(
            nome="Caixa KR #14 - Encomendas Seul",
            origem=Caixa.Origem.KR,
            codigo_rastreio="EG123456789KR",
            transportadora="EMS / Correios",
            frete_inter_total=Decimal("350.00"),
            taxa_aduaneira_total=Decimal("120.00")
        )
        self.assertEqual(caixa_kr.origem, Caixa.Origem.KR)
        self.assertEqual(caixa_kr.status, Caixa.Status.EM_CONSOLIDACAO)
        self.assertIn("rastreamento.correios.com.br", caixa_kr.tracking_url)
        self.assertIn("EG123456789KR", caixa_kr.tracking_url)

        caixa_jp = Caixa.objects.create(
            nome="Caixa Mercari JP #05",
            origem=Caixa.Origem.JP,
            codigo_rastreio="JP987654321BR"
        )
        self.assertEqual(caixa_jp.origem, Caixa.Origem.JP)
        self.assertTrue(caixa_jp.slug.startswith("caixa-mercari-jp-05"))

    def test_linking_cegs_to_caixa(self):
        caixa = Caixa.objects.create(
            nome="Caixa KR #01",
            origem=Caixa.Origem.KR,
            status=Caixa.Status.EM_CONSOLIDACAO
        )
        self.ceg1.caixa = caixa
        self.ceg1.sync_shipping_status()
        self.ceg1.save()

        self.ceg2.caixa = caixa
        self.ceg2.sync_shipping_status()
        self.ceg2.save()

        self.assertEqual(caixa.cegs.count(), 2)
        self.assertEqual(self.ceg1.shipping_status, Caixa.Status.EM_CONSOLIDACAO)
        self.assertEqual(self.ceg2.shipping_status, Caixa.Status.EM_CONSOLIDACAO)

    def test_atualizar_status_cascades_to_cegs_and_notifies_participants(self):
        caixa = Caixa.objects.create(
            nome="Caixa KR #10 - Remessa Principal",
            origem=Caixa.Origem.KR,
            status=Caixa.Status.EM_CONSOLIDACAO,
            codigo_rastreio="EG999888777KR"
        )
        self.ceg1.caixa = caixa
        self.ceg1.shipping_status = caixa.status
        self.ceg1.save()

        self.ceg2.caixa = caixa
        self.ceg2.shipping_status = caixa.status
        self.ceg2.save()

        # Dispara atualização de status para ENVIADA
        updated_count = caixa.atualizar_status(Caixa.Status.ENVIADA, notify_participants=True)
        self.assertEqual(updated_count, 2)

        # Recarrega do banco
        caixa.refresh_from_db()
        self.ceg1.refresh_from_db()
        self.ceg2.refresh_from_db()

        self.assertEqual(caixa.status, Caixa.Status.ENVIADA)
        self.assertIsNotNone(caixa.data_envio)
        self.assertEqual(self.ceg1.shipping_status, Caixa.Status.ENVIADA)
        self.assertEqual(self.ceg2.shipping_status, Caixa.Status.ENVIADA)

        # Verifica notificação do participante comprador
        notifications = ParticipantNotification.objects.filter(participant=self.participant)
        self.assertEqual(notifications.count(), 1)
        notif = notifications.first()
        self.assertIn("Atualização de Envio", notif.title)
        self.assertIn("EG999888777KR", notif.message)

        # Atualiza status para ENTREGUE
        caixa.atualizar_status(Caixa.Status.ENTREGUE, notify_participants=False)
        caixa.refresh_from_db()
        self.ceg1.refresh_from_db()
        self.assertEqual(caixa.status, Caixa.Status.ENTREGUE)
        self.assertIsNotNone(caixa.data_recebimento)
        self.assertEqual(self.ceg1.shipping_status, Caixa.Status.ENTREGUE)

    def test_unlinking_ceg_resets_shipping_status(self):
        caixa = Caixa.objects.create(
            nome="Caixa KR #02",
            origem=Caixa.Origem.KR,
            status=Caixa.Status.ENVIADA
        )
        self.ceg1.caixa = caixa
        self.ceg1.shipping_status = Caixa.Status.ENVIADA
        self.ceg1.save()

        # Desvincula a CEG
        self.ceg1.caixa = None
        self.ceg1.shipping_status = Caixa.Status.EM_CONSOLIDACAO
        self.ceg1.save()

        self.ceg1.refresh_from_db()
        self.assertIsNone(self.ceg1.caixa)
        self.assertEqual(self.ceg1.shipping_status, Caixa.Status.EM_CONSOLIDACAO)


class CaixasViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser('admin', 'admin@example.com', 'adminpass123')
        self.group = KpopGroup.objects.create(name="IVE", slug="ive")
        self.era = Era.objects.create(group=self.group, name="SWITCH", slug="switch")
        self.ceg = CEG.objects.create(
            era=self.era,
            title="IVE SWITCH Digipack",
            slug="ive-switch-digipack",
            status=CEG.Status.OPEN
        )
        self.caixa = Caixa.objects.create(
            nome="Caixa Mercari IVE #01",
            origem=Caixa.Origem.JP,
            status=Caixa.Status.EM_CONSOLIDACAO,
            codigo_rastreio="JP123456789BR"
        )
        self.ceg.caixa = self.caixa
        self.ceg.shipping_status = self.caixa.status
        self.ceg.save()

    def test_caixas_dashboard_view_public_access(self):
        # Visitante anônimo deve ser bloqueado e redirecionado para login
        response = self.client.get(reverse('caixas_dashboard'))
        self.assertEqual(response.status_code, 302)

        # Admin acessa com sucesso
        self.client.login(username='admin', password='adminpass123')
        response = self.client.get(reverse('caixas_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Caixa Mercari IVE #01")
        self.assertContains(response, "Caixas & Remessas Internacionais")

    def test_caixa_detail_view(self):
        # Visitante anônimo deve ser bloqueado
        self.client.logout()
        response = self.client.get(reverse('caixa_detail', kwargs={'slug': self.caixa.slug}))
        self.assertEqual(response.status_code, 302)

        # Admin acessa com sucesso
        self.client.login(username='admin', password='adminpass123')
        response = self.client.get(reverse('caixa_detail', kwargs={'slug': self.caixa.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Caixa Mercari IVE #01")
        self.assertContains(response, "IVE SWITCH Digipack")

    def test_caixa_create_view_permissions(self):
        # Visitante anônimo deve ser redirecionado para login
        response = self.client.get(reverse('caixa_create'))
        self.assertEqual(response.status_code, 302)

        # Admin cria com sucesso
        self.client.login(username='admin', password='adminpass123')
        response = self.client.get(reverse('caixa_create'))
        self.assertEqual(response.status_code, 200)

        post_data = {
            'nome': 'Caixa KR IVE Starship POB',
            'origem': Caixa.Origem.KR,
            'status': Caixa.Status.EM_CONSOLIDACAO,
            'codigo_rastreio': 'EG111222333KR',
            'transportadora': 'Correios EMS',
        }
        create_resp = self.client.post(reverse('caixa_create'), post_data)
        self.assertEqual(create_resp.status_code, 302)
        self.assertTrue(Caixa.objects.filter(codigo_rastreio='EG111222333KR').exists())

    def test_caixa_update_status_post_view(self):
        self.client.login(username='admin', password='adminpass123')
        url = reverse('caixa_update_status', kwargs={'slug': self.caixa.slug})
        resp = self.client.post(url, {'novo_status': Caixa.Status.ENVIADA})
        self.assertEqual(resp.status_code, 302)

        self.caixa.refresh_from_db()
        self.ceg.refresh_from_db()
        self.assertEqual(self.caixa.status, Caixa.Status.ENVIADA)
        self.assertEqual(self.ceg.shipping_status, Caixa.Status.ENVIADA)

    def test_caixa_unlink_ceg_view(self):
        self.client.login(username='admin', password='adminpass123')
        url = reverse('caixa_unlink_ceg', kwargs={'slug': self.caixa.slug, 'ceg_id': self.ceg.id})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)

        self.ceg.refresh_from_db()
        self.assertIsNone(self.ceg.caixa)
        self.assertEqual(self.ceg.shipping_status, Caixa.Status.EM_CONSOLIDACAO)

    def test_caixa_create_view_large_decimal_validation(self):
        """Testa que valores decimais gigantescos ou inválidos não causam 500 nem corrompem o banco."""
        self.client.login(username='admin', password='adminpass123')
        post_data = {
            'nome': 'Caixa Teste Decimais Gigantes',
            'origem': Caixa.Origem.KR,
            'status': Caixa.Status.EM_CONSOLIDACAO,
            'frete_inter_total': '99999999999999999999',  # Número absurdo
            'taxa_aduaneira_total': '123456789012345',
        }
        resp = self.client.post(reverse('caixa_create'), post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        # Deve exibir mensagem de erro amigável e NÃO criar caixa com dados corrompidos
        self.assertFalse(Caixa.objects.filter(nome='Caixa Teste Decimais Gigantes').exists())

    def test_caixa_model_clean_validation(self):
        """Testa validação de clean() do modelo Caixa."""
        from django.core.exceptions import ValidationError
        caixa = Caixa(
            nome="Caixa Inválida",
            origem=Caixa.Origem.KR,
            frete_inter_total=Decimal("9999999999999.00")
        )
        with self.assertRaises(ValidationError):
            caixa.clean()

    def test_create_ceg_with_caixa_linked(self):
        """Testa abertura de CEG atrelando a uma Caixa existente via CreateCEGView."""
        self.client.login(username='admin', password='adminpass123')
        caixa_kr = Caixa.objects.create(
            nome="Caixa KR Teste Vinculação",
            origem=Caixa.Origem.KR,
            status=Caixa.Status.NO_BRASIL
        )
        post_data = {
            'era_id': self.era.id,
            'title': 'CEG Vinculada na Criação',
            'status': CEG.Status.OPEN,
            'caixa_id': str(caixa_kr.id),
            'pix_key': 'pix@test.com',
            'item_name[]': ['Photocard Especial'],
            'item_price[]': ['50.00'],
        }
        resp = self.client.post(reverse('create_ceg'), post_data)
        self.assertEqual(resp.status_code, 302)

        ceg_criada = CEG.objects.get(title='CEG Vinculada na Criação')
        self.assertEqual(ceg_criada.caixa, caixa_kr)
        self.assertEqual(ceg_criada.shipping_status, Caixa.Status.NO_BRASIL)

    def test_create_ceg_without_caixa(self):
        """Testa abertura de CEG sem caixa vinculada."""
        self.client.login(username='admin', password='adminpass123')
        post_data = {
            'era_id': self.era.id,
            'title': 'CEG Sem Caixa Inicial',
            'status': CEG.Status.OPEN,
            'caixa_id': '',
            'pix_key': 'pix@test.com',
            'item_name[]': ['Photocard Regular'],
            'item_price[]': ['40.00'],
        }
        resp = self.client.post(reverse('create_ceg'), post_data)
        self.assertEqual(resp.status_code, 302)

        ceg_criada = CEG.objects.get(title='CEG Sem Caixa Inicial')
        self.assertIsNone(ceg_criada.caixa)
        self.assertEqual(ceg_criada.shipping_status, Caixa.Status.EM_CONSOLIDACAO)

    def test_update_ceg_fees_view_can_link_and_unlink_caixa(self):
        """Testa alteração da caixa vinculada à CEG via modal/view UpdateCEGFeesView."""
        self.client.login(username='admin', password='adminpass123')
        nova_caixa = Caixa.objects.create(
            nome="Caixa Mercari Nova",
            origem=Caixa.Origem.JP,
            status=Caixa.Status.ENVIADA
        )
        url = reverse('update_ceg_fees', kwargs={'slug': self.ceg.slug})

        # Vincula
        resp = self.client.post(url, {'caixa_id': str(nova_caixa.id)})
        self.assertEqual(resp.status_code, 302)
        self.ceg.refresh_from_db()
        self.assertEqual(self.ceg.caixa, nova_caixa)
        self.assertEqual(self.ceg.shipping_status, Caixa.Status.ENVIADA)

        # Desvincula
        resp2 = self.client.post(url, {'caixa_id': ''})
        self.assertEqual(resp2.status_code, 302)
        self.ceg.refresh_from_db()
        self.assertIsNone(self.ceg.caixa)
