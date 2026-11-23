from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
    verbose_name = 'Núcleo (segurança e permissões)'

    def ready(self):
        # Registra os receivers de login (rate limit + log de segurança do admin).
        from . import admin_throttle  # noqa: F401
