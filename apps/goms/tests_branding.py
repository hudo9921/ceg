"""Cor da marca (C4): só nas páginas de um GOM; o padrão não redefine nada."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .branding import BRAND_COLORS, CHOICES
from .models import Gom, GomMembership

User = get_user_model()
MARK = '--ui-accent: #0F766E'


class BrandingTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja V', slug='loja-v', cor_marca='verde')
        owner = User.objects.create_user('dono-v', password='x')
        GomMembership.objects.create(user=owner, gom=self.gom, role='OWNER')
        self.owner = owner

    def test_choices_match_presets(self):
        self.assertEqual(Gom._meta.get_field('cor_marca').choices, CHOICES)
        self.assertEqual(len(BRAND_COLORS), 6)

    def test_public_page_uses_gom_colour(self):
        self.assertContains(self.client.get(reverse('gom_public', args=['loja-v'])), MARK)

    def test_default_colour_adds_no_override(self):
        self.gom.cor_marca = 'padrao'
        self.gom.save()
        self.assertNotContains(self.client.get(reverse('gom_public', args=['loja-v'])), '--ui-accent:')

    def test_home_keeps_platform_colour(self):
        self.assertNotContains(self.client.get(reverse('home')), MARK)

    def test_panel_uses_active_gom_colour_and_profile_saves_it(self):
        self.client.force_login(self.owner)
        url = reverse('gom_settings_tab', args=['perfil'])
        self.assertContains(self.client.get(url), MARK)
        self.client.post(url, {'name': 'Loja V', 'bio': '', 'whatsapp_contato': '', 'instagram': '',
                               'logo_url': '', 'banner_url': '', 'cor_marca': 'lilas'})
        self.gom.refresh_from_db()
        self.assertEqual(self.gom.cor_marca, 'lilas')
        self.assertContains(self.client.get(url), '--ui-accent: #6D28D9')

    def test_invalid_colour_is_rejected(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('gom_settings_tab', args=['perfil']), {'name': 'Loja V', 'cor_marca': '#ff0000'})
        self.gom.refresh_from_db()
        self.assertEqual(self.gom.cor_marca, 'verde')
