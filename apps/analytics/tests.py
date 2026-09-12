from django.test import TestCase, Client
from django.utils import timezone
from datetime import timedelta
from apps.groups.models import KpopGroup, Era
from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot
from apps.participants.models import Participant, Claim
from apps.analytics.services import AnalyticsService


class AnalyticsServiceAndDashboardTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Grupo 1: TWICE
        self.group_twice = KpopGroup.objects.create(name='TWICE', slug='twice-analytics')
        self.era_twice = Era.objects.create(group=self.group_twice, name='With YOU-th', slug='with-youth-analytics')
        self.ceg_twice = CEG.objects.create(
            era=self.era_twice,
            title='CEG TWICE Makestar',
            slug='ceg-twice-makestar-analytics',
            status=CEG.Status.OPEN,
            opens_at=timezone.now() - timedelta(days=5),
            pix_key='twice@pix.com'
        )
        self.item_jihyo = CEGItemDefinition.objects.create(
            ceg=self.ceg_twice,
            name='Photocard Jihyo',
            member_name='Jihyo',
            default_price=45.00
        )
        self.item_sana = CEGItemDefinition.objects.create(
            ceg=self.ceg_twice,
            name='Photocard Sana',
            member_name='Sana',
            default_price=55.00
        )
        self.set_twice = CEGSet.objects.create(ceg=self.ceg_twice, set_number=1)
        self.set_twice.generate_slots()
        self.slot_jihyo = self.set_twice.slots.get(item_definition=self.item_jihyo)
        self.slot_sana = self.set_twice.slots.get(item_definition=self.item_sana)

        # Grupo 2: tripleS
        self.group_triples = KpopGroup.objects.create(name='tripleS', slug='triples-analytics')
        self.era_triples = Era.objects.create(group=self.group_triples, name='ASSEMBLE24', slug='assemble24-analytics')
        self.ceg_triples = CEG.objects.create(
            era=self.era_triples,
            title='CEG tripleS Withmuu',
            slug='ceg-triples-withmuu-analytics',
            status=CEG.Status.OPEN,
            opens_at=timezone.now() - timedelta(days=2),
            pix_key='triples@pix.com'
        )
        self.item_seoyeon = CEGItemDefinition.objects.create(
            ceg=self.ceg_triples,
            name='Photocard Seoyeon',
            member_name='Seoyeon',
            default_price=35.00
        )
        self.set_triples = CEGSet.objects.create(ceg=self.ceg_triples, set_number=1)
        self.set_triples.generate_slots()
        self.slot_seoyeon = self.set_triples.slots.get(item_definition=self.item_seoyeon)

        # Participantes
        self.p1 = Participant.objects.create(name='Participante Um', whatsapp='5511999990001')
        self.p2 = Participant.objects.create(name='Participante Dois', whatsapp='5511999990002')

        # Claim 1: Jihyo pago (R$ 45.00)
        self.claim1 = Claim.objects.create(
            slot=self.slot_jihyo,
            participant=self.p1,
            status=Claim.Status.PAID,
            total_price=45.00,
            paid_at=timezone.now()
        )
        self.slot_jihyo.status = ItemSlot.Status.PAID
        self.slot_jihyo.claimed_by = self.p1
        self.slot_jihyo.save()

        # Claim 2: Seoyeon pendente (R$ 35.00)
        self.claim2 = Claim.objects.create(
            slot=self.slot_seoyeon,
            participant=self.p2,
            status=Claim.Status.PENDING,
            total_price=35.00
        )
        self.slot_seoyeon.status = ItemSlot.Status.RESERVED
        self.slot_seoyeon.claimed_by = self.p2
        self.slot_seoyeon.save()

        # slot_sana continua AVAILABLE (R$ 55.00)

    def test_summary_metrics_without_filter(self):
        metrics = AnalyticsService.get_summary_metrics()
        self.assertEqual(metrics['total_paid'], 45.00)
        self.assertEqual(metrics['total_pending'], 35.00)
        self.assertEqual(metrics['total_sold'], 80.00)
        # slot_sana disponível (55.00)
        self.assertEqual(metrics['total_remaining_to_sell'], 55.00)
        self.assertEqual(metrics['total_inventory_value'], 135.00)
        self.assertEqual(metrics['total_slots'], 3)
        self.assertEqual(metrics['reserved_slots'], 2)
        self.assertEqual(metrics['available_slots'], 1)
        self.assertEqual(metrics['occupancy_percentage'], 66)
        self.assertEqual(metrics['total_participants'], 2)
        self.assertEqual(metrics['avg_ticket'], 40.00)

    def test_summary_metrics_with_group_filter(self):
        # Filtro pelo TWICE: deve incluir apenas Jihyo (pago 45) e Sana (livre 55)
        metrics = AnalyticsService.get_summary_metrics(group_id=self.group_twice.id)
        self.assertEqual(metrics['total_paid'], 45.00)
        self.assertEqual(metrics['total_pending'], 0.00)
        self.assertEqual(metrics['total_sold'], 45.00)
        self.assertEqual(metrics['total_remaining_to_sell'], 55.00)
        self.assertEqual(metrics['total_inventory_value'], 100.00)
        self.assertEqual(metrics['total_slots'], 2)
        self.assertEqual(metrics['reserved_slots'], 1)
        self.assertEqual(metrics['available_slots'], 1)
        self.assertEqual(metrics['total_participants'], 1)

    def test_summary_metrics_with_era_filter(self):
        # Filtro pela Era do tripleS: deve incluir apenas Seoyeon (pendente 35)
        metrics = AnalyticsService.get_summary_metrics(era_id=self.era_triples.id)
        self.assertEqual(metrics['total_paid'], 0.00)
        self.assertEqual(metrics['total_pending'], 35.00)
        self.assertEqual(metrics['total_sold'], 35.00)
        self.assertEqual(metrics['total_remaining_to_sell'], 0.00)
        self.assertEqual(metrics['total_inventory_value'], 35.00)
        self.assertEqual(metrics['total_slots'], 1)
        self.assertEqual(metrics['reserved_slots'], 1)
        self.assertEqual(metrics['available_slots'], 0)

    def test_monthly_sales_flow(self):
        flow = AnalyticsService.get_monthly_sales_flow()
        self.assertGreaterEqual(len(flow), 1)
        current = flow[0]
        self.assertEqual(current['total_sales'], 80.00)
        self.assertEqual(current['paid_sales'], 45.00)
        self.assertEqual(current['pending_sales'], 35.00)
        self.assertEqual(current['claims_count'], 2)

    def test_detailed_inventory_table(self):
        table = AnalyticsService.get_detailed_inventory_table()
        self.assertEqual(len(table), 2)
        ceg_titles = [row['title'] for row in table]
        self.assertIn('CEG TWICE Makestar', ceg_titles)
        self.assertIn('CEG tripleS Withmuu', ceg_titles)

    def test_dashboard_view_renders_successfully(self):
        # Acesso ao dashboard legado
        response = self.client.get('/analytics/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Faturado (Confirmado)')
        self.assertContains(response, 'Falta Pagar (Pendente)')
        self.assertContains(response, 'Para Vender (Livre)')
        self.assertContains(response, 'monthlySalesChart')
        self.assertContains(response, 'financialDonutChart')

        # Acesso com filtro de grupo
        response_filtered = self.client.get(f'/analytics/dashboard/?group={self.group_twice.id}')
        self.assertEqual(response_filtered.status_code, 200)
        self.assertContains(response_filtered, 'TWICE')

    def test_ceg_status_view_renders_successfully(self):
        # Acesso ao novo painel de status das CEGs
        response = self.client.get('/analytics/cegs/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Status, Completude e Valores das CEGs')
        self.assertContains(response, 'Sets Incompletos')
        self.assertContains(response, 'Sets 100% Preenchidos')
        self.assertContains(response, 'Sana')

        # Rota raiz /analytics/ também carrega o status das CEGs
        res_root = self.client.get('/analytics/')
        self.assertEqual(res_root.status_code, 200)
        self.assertContains(res_root, 'Status, Completude e Valores das CEGs')

    def test_sales_report_view_renders_successfully(self):
        # Acesso ao novo relatório de vendas e BI
        response = self.client.get('/analytics/vendas/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Relatório de Vendas e Income')
        self.assertContains(response, 'salesMonthlyChart')
        self.assertContains(response, 'salesDonutChart')
        self.assertContains(response, 'salesGroupsChart')
        self.assertContains(response, 'Top Itens & Photocards Mais Vendidos')
        self.assertContains(response, 'Principais Compradores')

    def test_cegs_operational_status_service(self):
        data = AnalyticsService.get_cegs_operational_status()
        self.assertIn('sets_completed_pending', data)
        self.assertIn('sets_incomplete', data)
        self.assertIn('cegs_overview', data)
        self.assertIn('summary', data)

        # Set do tripleS tem 1 slot preenchido de 1 (100% fechado), porém frete inter e taxa não foram cotados
        self.assertGreaterEqual(len(data['sets_completed_pending']), 1)
        completed = data['sets_completed_pending'][0]
        reasons = [r['code'] for r in completed['pending_reasons']]
        self.assertIn('FRETE_INTER_NOT_SET', reasons)

        # Set do TWICE tem 1 slot preenchido (Jihyo) e 1 livre (Sana) -> incompleto
        self.assertGreaterEqual(len(data['sets_incomplete']), 1)
        incomplete = [s for s in data['sets_incomplete'] if s['ceg_title'] == 'CEG TWICE Makestar'][0]
        self.assertEqual(incomplete['remaining_slots'], 1)
        missing_names = [item['member_name'] for item in incomplete['missing_items']]
        self.assertIn('Sana', missing_names)

    def test_sales_analytics_service(self):
        data = AnalyticsService.get_sales_analytics(time_window='all')
        self.assertIn('summary', data)
        self.assertIn('monthly_flow', data)
        self.assertIn('group_sales', data)
        self.assertIn('top_items', data)
        self.assertIn('top_buyers', data)

        self.assertEqual(data['summary']['total_sales'], 80.00)
        self.assertEqual(data['summary']['claims_count'], 2)
        self.assertEqual(data['summary']['unique_participants'], 2)

    def test_analytics_new_api_endpoints(self):
        # API de status das CEGs
        res_cegs = self.client.get('/analytics/api/cegs/')
        self.assertEqual(res_cegs.status_code, 200)
        data_cegs = res_cegs.json()
        self.assertIn('sets_completed_pending', data_cegs)
        self.assertIn('sets_incomplete', data_cegs)

        # API de vendas
        res_sales = self.client.get('/analytics/api/sales/')
        self.assertEqual(res_sales.status_code, 200)
        data_sales = res_sales.json()
        self.assertIn('summary', data_sales)
        self.assertIn('monthly_flow', data_sales)

    def test_analytics_api_endpoint(self):
        response = self.client.get('/analytics/api/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('summary', data)
        self.assertIn('monthly_flow', data)
        self.assertIn('detailed_inventory', data)
        self.assertEqual(data['summary']['total_sold'], 80.00)

    def test_card_filter_flags_in_cegs_overview(self):
        status_data = AnalyticsService.get_cegs_operational_status()
        cegs_overview = status_data['cegs_overview']
        self.assertTrue(len(cegs_overview) >= 2)
        for c in cegs_overview:
            self.assertIn('has_completed_sets', c)
            self.assertIn('has_incomplete_sets', c)
            self.assertIn('completed_pending_sets', c)
            self.assertIn('incomplete_sets', c)

    def test_no_raw_javascript_leak_in_rendered_templates(self):
        # Verifica ceg_status.html
        res_cegs = self.client.get('/analytics/cegs/')
        self.assertEqual(res_cegs.status_code, 200)
        # O padrão que vazava anteriormente vinha de arrow functions e aspas em atributos
        self.assertNotContains(res_cegs, 'String(e.group_id) === String(this.selectedGroup)); }, onGroupChange()')
        self.assertContains(res_cegs, 'filter-options-data')
        self.assertContains(res_cegs, 'setCardFilter')
        self.assertContains(res_cegs, 'activeCardFilter')

        # Verifica sales_report.html
        res_sales = self.client.get('/analytics/vendas/')
        self.assertEqual(res_sales.status_code, 200)
        self.assertNotContains(res_sales, 'String(e.group_id) === String(this.selectedGroup)); }, onGroupChange()')
        self.assertContains(res_sales, 'filter-options-data')
        self.assertContains(res_sales, 'chart-data')
        self.assertContains(res_sales, 'salesReportApp')

