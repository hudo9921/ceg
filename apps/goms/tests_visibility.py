"""O joiner vê qual GOM organiza cada CEG e chega à página dele (cards, CEG, Vitrine, lista de GOMs)."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet
from apps.groups.models import Era, KpopGroup

from .models import Gom


class GomVisibilityTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja Vis', slug='loja-vis', bio='Desde 2019.', instagram='@lojavis')
        era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa-vis'), name='Rich', slug='rich-vis')
        self.ceg = CEG.objects.create(era=era, gom=self.gom, title='CEG Vis', slug='ceg-vis', status=CEG.Status.OPEN,
                                      opens_at=timezone.now() - timedelta(minutes=1))
        CEGItemDefinition.objects.create(ceg=self.ceg, name='PC Karina', default_price=40)
        CEGSet.objects.create(ceg=self.ceg, set_number=1).generate_slots()
        self.page = reverse('gom_public', args=['loja-vis'])

    def test_home_card_shows_gom_even_with_a_single_gom(self):
        res = self.client.get(reverse('home'))
        self.assertContains(res, 'por Loja Vis')
        self.assertContains(res, self.page)

    def test_ceg_page_has_organizer_card(self):
        res = self.client.get(reverse('ceg_detail', args=['ceg-vis']))
        self.assertContains(res, 'Organizado por')
        self.assertContains(res, 'Desde 2019.')
        self.assertContains(res, 'Ver página do GOM')

    def test_directory_lists_active_goms_with_open_cegs(self):
        Gom.objects.create(name='Loja Inativa', slug='loja-inativa', is_active=False)
        res = self.client.get(reverse('gom_directory'))
        self.assertContains(res, 'Loja Vis')
        self.assertContains(res, '1 CEG aberta')
        self.assertNotContains(res, 'Loja Inativa')
        self.assertContains(res, self.page)
