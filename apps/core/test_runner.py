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
        # Testes antigos criam usuários `is_staff` sem GOM: viram admins do ValCegs, como a
        # migração goms.0002 faz em produção. Testes de isolamento usam membros explícitos.
        from django.contrib.auth import get_user_model
        from django.db.models.signals import post_save
        post_save.connect(_legacy_staff_joins_valcegs, sender=get_user_model(),
                          dispatch_uid='tests-legacy-staff-valcegs')
        # Fixtures criam joiners soltos; como dados legados, eles são conhecidos pelo ValCegs.
        from apps.participants.models import Participant
        post_save.connect(_legacy_joiner_known_by_valcegs, sender=Participant,
                          dispatch_uid='tests-legacy-joiner-valcegs')

    def teardown_test_environment(self, **kwargs):
        self._two_factor_override.disable()
        super().teardown_test_environment(**kwargs)


def _legacy_staff_joins_valcegs(sender, instance, created, **kwargs):
    if not (instance.is_staff and not instance.is_superuser):
        return
    from apps.goms.models import Gom, GomMembership
    from apps.goms.scoping import default_gom_id
    GomMembership.objects.get_or_create(user=instance, gom=Gom.objects.get(pk=default_gom_id()),
                                        defaults={'role': GomMembership.Role.ADMIN})


def _legacy_joiner_known_by_valcegs(sender, instance, created, **kwargs):
    if created:
        from apps.goms.scoping import default_gom_id
        instance.known_by_goms.add(default_gom_id())
