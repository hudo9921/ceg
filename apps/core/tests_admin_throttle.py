"""Força bruta no /admin/login/: bloqueio por IP e por username após MAX_FAILURES falhas."""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

from apps.core.admin_throttle import MAX_FAILURES

LOGIN = '/admin/login/'


class AdminLoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_superuser('gom', 'gom@test.com', 'senha-correta-123')

    def _fail(self, username='gom', ip='203.0.113.7'):
        return self.client.post(LOGIN, {'username': username, 'password': 'errada'}, REMOTE_ADDR=ip)

    def test_correct_password_is_blocked_after_too_many_failures(self):
        for _ in range(MAX_FAILURES):
            self.assertEqual(self._fail().status_code, 200)
        res = self.client.post(LOGIN, {'username': 'gom', 'password': 'senha-correta-123'},
                               REMOTE_ADDR='203.0.113.7')
        self.assertEqual(res.status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_username_lock_applies_from_another_ip(self):
        for i in range(MAX_FAILURES):
            self._fail(ip=f'198.51.100.{i + 1}')
        res = self.client.post(LOGIN, {'username': 'gom', 'password': 'senha-correta-123'},
                               REMOTE_ADDR='192.0.2.50')
        self.assertEqual(res.status_code, 429)

    def test_success_before_limit_resets_counters(self):
        for _ in range(MAX_FAILURES - 1):
            self._fail()
        res = self.client.post(LOGIN, {'username': 'gom', 'password': 'senha-correta-123'},
                               REMOTE_ADDR='203.0.113.7')
        self.assertEqual(res.status_code, 302)
        self.client.logout()
        self.assertEqual(self._fail().status_code, 200)
