import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Cria o superusuário inicial a partir de variáveis de ambiente.

    Segurança:
    - Só CRIA o usuário. Um usuário existente nunca tem a senha redefinida, a menos que
      ADMIN_PASSWORD_RESET=True seja definido explicitamente (use uma vez e remova).
    - Senhas fracas (validadores do Django) são recusadas fora do DEBUG.
    """
    help = 'Cria o superusuário inicial a partir de ADMIN_USERNAME / ADMIN_PASSWORD.'

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.getenv('ADMIN_USERNAME') or os.getenv('DJANGO_SUPERUSER_USERNAME') or 'admin'
        password = os.getenv('ADMIN_PASSWORD') or os.getenv('DJANGO_SUPERUSER_PASSWORD')
        email = os.getenv('ADMIN_EMAIL') or os.getenv('DJANGO_SUPERUSER_EMAIL') or 'admin@valcegs.com'
        force_reset = os.getenv('ADMIN_PASSWORD_RESET', '').lower() in ('1', 'true', 'yes')

        if not password:
            self.stdout.write("Nenhuma senha de admin informada (ADMIN_PASSWORD). Pulando criação automática.")
            return

        user = User.objects.filter(username=username).first()
        if user and not force_reset:
            self.stdout.write(f"Superusuário '{username}' já existe; senha mantida.")
            return

        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            if not settings.DEBUG:
                self.stderr.write(self.style.ERROR(
                    f"ADMIN_PASSWORD recusada (senha fraca): {' '.join(exc.messages)}"))
                return

        if not user:
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"Superusuário '{username}' criado."))
        else:
            user.set_password(password)
            user.save(update_fields=['password'])
            self.stdout.write(self.style.WARNING(
                f"Senha de '{username}' redefinida (ADMIN_PASSWORD_RESET). Remova essa variável do .env."))
