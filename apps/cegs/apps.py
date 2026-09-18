from django.apps import AppConfig


class CegsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.cegs'
    verbose_name = 'Gestão de CEGs e Sets'

    def ready(self):
        import apps.cegs.signals  # noqa
