from django.apps import AppConfig


class AvisosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.avisos'
    verbose_name = 'Notificações no celular (push)'

    def ready(self):
        from . import signals  # noqa: F401
