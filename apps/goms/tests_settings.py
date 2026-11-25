"""Configurações do GOM (C0): abas por permissão, cada aba salva só os próprios campos."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import ConfiguracaoEnvio

from .models import Gom, GomMembership
from .services import set_permissions

User = get_user_model()


def tab(slug):
    return reverse('gom_settings_tab', args=[slug])


class GomSettingsTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja C', slug='loja-c', default_pix_key='pix-antigo')
        self.owner = User.objects.create_user('dono-c', password='x')
        GomMembership.objects.create(user=self.owner, gom=self.gom, role='OWNER')
        self.client.force_login(self.owner)

    def test_index_opens_first_tab_and_old_profile_url_redirects(self):
        self.assertRedirects(self.client.get(reverse('gom_settings')), tab('perfil'), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('gom_profile')), reverse('gom_settings'), fetch_redirect_response=False)

    def test_owner_sees_all_tabs(self):
        page = self.client.get(tab('perfil')).content.decode()
        for slug in ('perfil', 'pix', 'envio'):
            self.assertIn(tab(slug), page)

    def test_profile_tab_does_not_touch_pix(self):
        self.client.post(tab('perfil'), {'name': 'Loja C2', 'bio': '', 'whatsapp_contato': '', 'instagram': '',
                                         'logo_url': '', 'banner_url': ''})
        self.gom.refresh_from_db()
        self.assertEqual((self.gom.name, self.gom.default_pix_key), ('Loja C2', 'pix-antigo'))

    def test_envio_tab_saves_this_gom_config_only(self):
        res = self.client.post(tab('envio'), {'instrucoes_envio': 'Confira o CEP'})
        self.assertRedirects(res, tab('envio'), fetch_redirect_response=False)
        self.assertEqual(ConfiguracaoEnvio.get_for_gom(self.gom).instrucoes_envio, 'Confira o CEP')
        other = Gom.objects.create(name='Outra', slug='outra-c')
        self.assertEqual(ConfiguracaoEnvio.get_for_gom(other).instrucoes_envio, '')

    def test_admin_only_sees_allowed_tabs_and_is_sent_to_first(self):
        admin = User.objects.create_user('adm-c', password='x')
        m = GomMembership.objects.create(user=admin, gom=self.gom, role='ADMIN')
        set_permissions(m, ['gom.envio'], self.owner)
        self.client.force_login(admin)
        self.assertRedirects(self.client.get(reverse('gom_settings')), tab('envio'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(tab('perfil')).status_code, 403)
        page = self.client.get(tab('envio')).content.decode()
        self.assertNotIn(tab('pix'), page)

    def test_admin_without_any_settings_permission_is_denied(self):
        admin = User.objects.create_user('adm-c2', password='x')
        m = GomMembership.objects.create(user=admin, gom=self.gom, role='ADMIN')
        set_permissions(m, ['ceg.editar'], self.owner)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('gom_settings')).status_code, 403)

    def test_unknown_tab_is_404(self):
        self.assertEqual(self.client.get(tab('nada')).status_code, 404)
