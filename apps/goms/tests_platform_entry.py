"""A plataforma (superusuário) escolhe em qual GOM atuar: não cai em nenhum painel sozinha."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .access import ACTIVE_GOM_SESSION_KEY
from .models import Gom, GomMembership

User = get_user_model()


class PlatformEntryTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('plat', 'p@x.com', 'Senha-Forte-123')
        self.valcegs = Gom.objects.get(slug='valcegs')
        self.other = Gom.objects.create(name='Loja Dois', slug='loja-dois')
        self.client.force_login(self.root)
        self.client.post(reverse('gom_switch'), {'gom_id': ''})  # o runner abre o ValCegs; sair dele

    def test_superuser_starts_without_gom_and_home_goes_to_platform(self):
        self.assertNotIn(ACTIVE_GOM_SESSION_KEY, self.client.session)
        res = self.client.get(reverse('backoffice_home'))
        self.assertRedirects(res, reverse('platform_goms'), fetch_redirect_response=False)

    def test_gom_pages_are_closed_until_a_gom_is_opened(self):
        self.assertEqual(self.client.get(reverse('cegs_status')).status_code, 403)

    def test_platform_list_offers_open_panel_for_each_gom(self):
        res = self.client.get(reverse('platform_goms'))
        self.assertContains(res, 'Abrir painel</button>', count=2, html=False)
        self.assertNotContains(res, 'Você está no painel de')

    def test_open_panel_shows_banner_and_opens_gom_pages(self):
        res = self.client.post(reverse('gom_switch'), {'gom_id': self.other.id, 'next': reverse('backoffice_home')})
        self.assertRedirects(res, reverse('backoffice_home'), fetch_redirect_response=False)
        page = self.client.get(reverse('backoffice_home'))
        self.assertContains(page, 'Você está no painel de <b>Loja Dois</b> como plataforma')
        self.assertContains(page, 'Sair do painel')
        status = self.client.get(reverse('cegs_status'))
        self.assertEqual(status.status_code, 200)

    def test_leave_panel_returns_to_platform(self):
        self.client.post(reverse('gom_switch'), {'gom_id': self.other.id})
        res = self.client.post(reverse('gom_switch'), {'gom_id': ''})
        self.assertRedirects(res, reverse('platform_goms'), fetch_redirect_response=False)
        self.assertNotIn(ACTIVE_GOM_SESSION_KEY, self.client.session)

    def test_superuser_with_own_membership_still_chooses(self):
        GomMembership.objects.create(user=self.root, gom=self.valcegs, role=GomMembership.Role.OWNER)
        res = self.client.get(reverse('backoffice_home'))
        self.assertRedirects(res, reverse('platform_goms'), fetch_redirect_response=False)

    def test_team_member_still_lands_in_own_gom_without_banner(self):
        member = User.objects.create_user('membro', password='x')
        GomMembership.objects.create(user=member, gom=self.other, role=GomMembership.Role.OWNER)
        self.client.force_login(member)
        res = self.client.get(reverse('backoffice_home'))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'como plataforma')

    def test_member_cannot_use_empty_switch_to_clear(self):
        member = User.objects.create_user('membro2', password='x')
        GomMembership.objects.create(user=member, gom=self.other, role=GomMembership.Role.OWNER)
        self.client.force_login(member)
        self.client.post(reverse('gom_switch'), {'gom_id': ''})
        self.assertEqual(self.client.get(reverse('backoffice_home')).status_code, 200)
