import os
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

STRONG = 'Kq7!vR2#pLx9-Zt4'


def run_initadmin(**env):
    out, err = StringIO(), StringIO()
    with mock.patch.dict(os.environ, env, clear=False):
        for key in ('ADMIN_PASSWORD', 'ADMIN_PASSWORD_RESET', 'ADMIN_USERNAME'):
            if key not in env:
                os.environ.pop(key, None)
        call_command('initadmin', stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


@override_settings(DEBUG=False)
class InitAdminTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

    def test_creates_superuser_with_strong_password(self):
        run_initadmin(ADMIN_USERNAME='boss', ADMIN_PASSWORD=STRONG)
        user = self.User.objects.get(username='boss')
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password(STRONG))

    def test_refuses_weak_password_in_production(self):
        output = run_initadmin(ADMIN_USERNAME='boss', ADMIN_PASSWORD='admin123')
        self.assertFalse(self.User.objects.filter(username='boss').exists())
        self.assertIn('recusada', output)

    def test_never_resets_existing_password_by_default(self):
        """Regressão: antes, todo restart do container voltava a senha para ADMIN_PASSWORD."""
        user = self.User.objects.create_superuser('boss', 'b@x.com', 'Senha-Trocada-Pelo-Admin-1')
        run_initadmin(ADMIN_USERNAME='boss', ADMIN_PASSWORD=STRONG)
        user.refresh_from_db()
        self.assertTrue(user.check_password('Senha-Trocada-Pelo-Admin-1'))

    def test_explicit_reset_flag_changes_password(self):
        user = self.User.objects.create_superuser('boss', 'b@x.com', 'Senha-Antiga-Longa-1')
        run_initadmin(ADMIN_USERNAME='boss', ADMIN_PASSWORD=STRONG, ADMIN_PASSWORD_RESET='True')
        user.refresh_from_db()
        self.assertTrue(user.check_password(STRONG))

    def test_skips_without_password(self):
        run_initadmin(ADMIN_USERNAME='boss')
        self.assertFalse(self.User.objects.filter(username='boss').exists())
