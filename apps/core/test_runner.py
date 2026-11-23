"""
Runner de testes do projeto.

Usa storage de estáticos sem manifest e desliga o 2FA obrigatório de staff por padrão para que os testes de funcionalidade
possam usar `force_login(staff)` diretamente. O 2FA é testado explicitamente com
`@override_settings(STAFF_2FA_REQUIRED=True)` em `apps/core/tests_two_factor.py`
e na matriz de permissões (`apps/core/tests.py`).
"""
from django.conf import settings
from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class ProjectTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        # Storage sem manifest: os testes não dependem de um `collectstatic` prévio.
        storages = {**settings.STORAGES, 'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
        self._two_factor_override = override_settings(STAFF_2FA_REQUIRED=False, STORAGES=storages)
        self._two_factor_override.enable()

    def teardown_test_environment(self, **kwargs):
        self._two_factor_override.disable()
        super().teardown_test_environment(**kwargs)
