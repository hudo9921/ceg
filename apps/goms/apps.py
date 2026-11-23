from django.apps import AppConfig


class GomsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.goms'
    verbose_name = 'GOMs (organizadores)'

    def ready(self):
        from django.db.models.signals import post_migrate

        from .scoping import reset_default_gom_cache
        # flush/migrate (ex.: TransactionTestCase) recriam o ValCegs com outro id.
        post_migrate.connect(reset_default_gom_cache, dispatch_uid='goms-reset-default-gom')
