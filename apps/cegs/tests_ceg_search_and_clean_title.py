from decimal import Decimal
from django.urls import reverse
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from apps.groups.models import KpopGroup, Era
from apps.cegs.models import CEG, CEGSet, ItemSlot, CEGItemDefinition
from apps.analytics.services import AnalyticsService
from apps.analytics.views import CEGStatusView


class CEGCleanTitleAndSearchTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.staff_user = User.objects.create_user(
            username='staff_test',
            email='staff@test.com',
            password='pass',
            is_staff=True
        )

        # Cria Grupos e Eras
        self.group_lesserafim = KpopGroup.objects.create(name='LE SSERAFIM')
        self.era_lesserafim = Era.objects.create(group=self.group_lesserafim, name='Pureflow')

        self.group_twice = KpopGroup.objects.create(name='TWICE')
        self.era_twice = Era.objects.create(group=self.group_twice, name='With YOU-th')

    def test_clean_title_em_dash(self):
        """Testa limpeza com travessão em dash (—)"""
        ceg = CEG.objects.create(
            era=self.era_lesserafim,
            title='LE SSERAFIM — WEVERSE GLOBAL 1.0 (Mini camera weverse global) (PF-32)',
            status=CEG.Status.OPEN
        )
        self.assertEqual(
            ceg.clean_title(),
            'WEVERSE GLOBAL 1.0 (Mini camera weverse global) (PF-32)'
        )
        self.assertEqual(
            ceg.display_title,
            'WEVERSE GLOBAL 1.0 (Mini camera weverse global) (PF-32)'
        )

    def test_clean_title_hyphen(self):
        """Testa limpeza com hífen simples (-) e case insensitive"""
        ceg = CEG.objects.create(
            era=self.era_lesserafim,
            title='Le sserafim - SET SAKURA PUREFLOW',
            status=CEG.Status.OPEN
        )
        self.assertEqual(ceg.clean_title(), 'SET SAKURA PUREFLOW')
        self.assertEqual(ceg.display_title, 'SET SAKURA PUREFLOW')

    def test_clean_title_colon(self):
        """Testa limpeza com dois pontos (:)"""
        ceg = CEG.objects.create(
            era=self.era_twice,
            title='TWICE: Withmuu 2.0 POB',
            status=CEG.Status.OPEN
        )
        self.assertEqual(ceg.clean_title(), 'Withmuu 2.0 POB')

    def test_clean_title_prefix_ceg(self):
        """Testa limpeza quando começa com prefixo 'CEG ' antes do nome do grupo"""
        ceg = CEG.objects.create(
            era=self.era_twice,
            title='CEG TWICE Makestar',
            status=CEG.Status.OPEN
        )
        self.assertEqual(ceg.clean_title(), 'Makestar')

    def test_clean_title_without_group_name(self):
        """Testa que títulos que não contêm o nome do grupo permanecem intactos"""
        ceg = CEG.objects.create(
            era=self.era_twice,
            title='Special Lucky Draw Set',
            status=CEG.Status.OPEN
        )
        self.assertEqual(ceg.clean_title(), 'Special Lucky Draw Set')
        self.assertEqual(ceg.display_title, 'Special Lucky Draw Set')

    def test_clean_title_exact_group_name_only(self):
        """Testa que se o título for exatamente o nome do grupo, não fica em branco"""
        ceg = CEG.objects.create(
            era=self.era_twice,
            title='TWICE',
            status=CEG.Status.OPEN
        )
        self.assertEqual(ceg.clean_title(), 'TWICE')

    def test_analytics_operational_status_includes_ceg_clean_title_and_search(self):
        """Testa se AnalyticsService retorna ceg_clean_title e filtra por search"""
        ceg1 = CEG.objects.create(
            era=self.era_lesserafim,
            title='LE SSERAFIM — WEVERSE GLOBAL 1.0',
            status=CEG.Status.OPEN
        )
        set1 = CEGSet.objects.create(ceg=ceg1, set_number=1, is_active=True)
        item_def1 = CEGItemDefinition.objects.create(
            ceg=ceg1,
            name='Camera Photocard',
            member_name='Sakura',
            default_price=Decimal('50.00')
        )
        ItemSlot.objects.create(
            set=set1,
            item_definition=item_def1,
            price=Decimal('50.00'),
            status=ItemSlot.Status.AVAILABLE
        )

        ceg2 = CEG.objects.create(
            era=self.era_twice,
            title='TWICE — MAKESTAR ROUND 2',
            status=CEG.Status.OPEN
        )
        set2 = CEGSet.objects.create(ceg=ceg2, set_number=1, is_active=True)
        item_def2 = CEGItemDefinition.objects.create(
            ceg=ceg2,
            name='Jihyo Selfie PC',
            member_name='Jihyo',
            default_price=Decimal('45.00')
        )
        ItemSlot.objects.create(
            set=set2,
            item_definition=item_def2,
            price=Decimal('45.00'),
            status=ItemSlot.Status.AVAILABLE
        )

        # 1. Sem filtro de busca: ambas as CEGs retornam com ceg_clean_title limpo
        status_all = AnalyticsService.get_cegs_operational_status()
        incomplete_sets = status_all['sets_incomplete']
        self.assertEqual(len(incomplete_sets), 2)

        ls_set = [s for s in incomplete_sets if s['ceg_id'] == ceg1.id][0]
        self.assertEqual(ls_set['ceg_title'], 'LE SSERAFIM — WEVERSE GLOBAL 1.0')
        self.assertEqual(ls_set['ceg_clean_title'], 'WEVERSE GLOBAL 1.0')

        twice_set = [s for s in incomplete_sets if s['ceg_id'] == ceg2.id][0]
        self.assertEqual(twice_set['ceg_clean_title'], 'MAKESTAR ROUND 2')

        # 2. Com filtro de busca textual por nome da CEG
        status_search_weverse = AnalyticsService.get_cegs_operational_status(search='weverse')
        self.assertEqual(len(status_search_weverse['sets_incomplete']), 1)
        self.assertEqual(status_search_weverse['sets_incomplete'][0]['ceg_id'], ceg1.id)

        # 3. Com filtro de busca textual por integrante/photocard
        status_search_jihyo = AnalyticsService.get_cegs_operational_status(search='Jihyo')
        self.assertEqual(len(status_search_jihyo['sets_incomplete']), 1)
        self.assertEqual(status_search_jihyo['sets_incomplete'][0]['ceg_id'], ceg2.id)

    def test_ceg_status_view_with_search_query(self):
        """Testa requisição GET na CEGStatusView com ?search=weverse"""
        ceg = CEG.objects.create(
            era=self.era_lesserafim,
            title='LE SSERAFIM — WEVERSE GLOBAL 1.0',
            status=CEG.Status.OPEN
        )
        set1 = CEGSet.objects.create(ceg=ceg, set_number=1, is_active=True)
        item_def = CEGItemDefinition.objects.create(
            ceg=ceg,
            name='Camera PC',
            default_price=Decimal('50.00')
        )
        ItemSlot.objects.create(
            set=set1,
            item_definition=item_def,
            price=Decimal('50.00'),
            status=ItemSlot.Status.AVAILABLE
        )

        self.client.force_login(self.staff_user)
        url = reverse('cegs_status') + '?search=weverse'
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'WEVERSE GLOBAL 1.0')
        self.assertContains(response, 'weverse')
