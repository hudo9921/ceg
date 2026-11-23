from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_static.models import StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core.permissions import is_staff_user
from apps.core.two_factor import regenerate_backup_codes

SETUP = reverse('staff_2fa_setup')
VERIFY = reverse('staff_2fa_verify')
MANAGE = reverse('staff_2fa_manage')


def current_code(device):
    return TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift).token()


def fmt(code):
    return str(code).zfill(6)


@override_settings(STAFF_2FA_REQUIRED=True)
class StaffTwoFactorTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user('gom', password='Senha-Forte-123', is_staff=True)
        self.client.force_login(self.staff)

    def _enroll(self):
        device = TOTPDevice.objects.create(user=self.staff, name='Autenticador', confirmed=True)
        codes = regenerate_backup_codes(self.staff)
        return device, codes

    # --- bloqueio antes do 2FA -------------------------------------------------
    def test_staff_without_device_is_sent_to_setup_everywhere(self):
        for path in ('/admin/', reverse('creations_hub'), reverse('home')):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 302, path)
            self.assertTrue(res['Location'].startswith(SETUP), res['Location'])

    def test_enrolled_but_unverified_staff_is_sent_to_verify(self):
        self._enroll()
        res = self.client.get('/admin/')
        self.assertTrue(res['Location'].startswith(VERIFY))

    def test_ajax_request_gets_json_403(self):
        res = self.client.get(reverse('creations_hub'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 403)
        self.assertTrue(res.json()['requires_2fa'])

    def test_is_staff_user_requires_verified_session(self):
        self.staff.is_verified = lambda: False
        self.assertFalse(is_staff_user(self.staff))
        self.staff.is_verified = lambda: True
        self.assertTrue(is_staff_user(self.staff))

    # --- cadastro ---------------------------------------------------------------
    def test_setup_flow_confirms_device_and_shows_backup_codes(self):
        res = self.client.get(SETUP)
        self.assertContains(res, 'data:image/svg+xml;base64,')
        device = TOTPDevice.objects.get(user=self.staff, confirmed=False)

        res = self.client.post(SETUP, {'token': '000000'})
        device.refresh_from_db()
        self.assertFalse(device.confirmed)
        device.throttle_reset()  # erro gera espera crescente (throttling do django-otp)

        res = self.client.post(SETUP, {'token': fmt(current_code(device))})
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(len(res.context['codes']), 10)
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        self.assertLessEqual(self.client.session.get_expiry_age(), 60 * 60 * 12)

    def test_setup_qr_is_stable_between_reloads(self):
        self.client.get(SETUP)
        self.client.get(SETUP)
        self.assertEqual(TOTPDevice.objects.filter(user=self.staff).count(), 1)

    # --- verificação ------------------------------------------------------------
    def test_verify_with_totp_unlocks_backoffice(self):
        device, _ = self._enroll()
        res = self.client.post(VERIFY + '?next=/admin/', {'token': fmt(current_code(device))})
        self.assertRedirects(res, '/admin/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    def test_backup_code_works_only_once(self):
        _, codes = self._enroll()
        self.client.post(VERIFY, {'token': codes[0]})
        self.assertEqual(self.client.get('/admin/').status_code, 200)

        self.client.logout()
        self.client.force_login(self.staff)
        self.client.post(VERIFY, {'token': codes[0]})
        self.assertNotEqual(self.client.get('/admin/').status_code, 200)
        self.assertEqual(StaticToken.objects.filter(device__user=self.staff).count(), 9)

    def test_failed_attempts_are_throttled(self):
        device, _ = self._enroll()
        for _ in range(3):
            self.client.post(VERIFY, {'token': '000000'})
        self.client.post(VERIFY, {'token': fmt(current_code(device))})
        self.assertNotEqual(self.client.get('/admin/').status_code, 200)

    def test_next_cannot_redirect_off_site(self):
        device, _ = self._enroll()
        res = self.client.post(VERIFY + '?next=https://evil.example/', {'token': fmt(current_code(device))})
        self.assertEqual(res['Location'], '/painel/')

    # --- gerenciamento ----------------------------------------------------------
    def test_regenerate_codes_invalidates_old_ones(self):
        device, old = self._enroll()
        self.client.post(VERIFY, {'token': fmt(current_code(device))})
        res = self.client.post(MANAGE)
        self.assertEqual(len(res.context['codes']), 10)
        self.assertFalse(StaticToken.objects.filter(token__in=old).exists())

    def test_reset_command_removes_devices(self):
        self._enroll()
        call_command('reset_2fa', 'gom', stdout=StringIO())
        self.assertFalse(TOTPDevice.objects.filter(user=self.staff).exists())
        self.assertTrue(self.client.get('/admin/')['Location'].startswith(SETUP))


@override_settings(STAFF_2FA_REQUIRED=True)
class TwoFactorAccessTests(TestCase):
    def test_anonymous_is_sent_to_login(self):
        res = self.client.get(SETUP)
        self.assertTrue(res['Location'].startswith('/entrar/'))

    def test_non_staff_user_gets_403(self):
        user = get_user_model().objects.create_user('comum', password='x')
        self.client.force_login(user)
        self.assertEqual(self.client.get(SETUP).status_code, 403)
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)
