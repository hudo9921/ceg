import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Cria ou atualiza automaticamente o superusuário inicial a partir de variáveis de ambiente.'

    def handle(self, *args, **options):
        User = get_user_model()
        username = os.getenv('ADMIN_USERNAME') or os.getenv('DJANGO_SUPERUSER_USERNAME') or 'admin'
        password = os.getenv('ADMIN_PASSWORD') or os.getenv('DJANGO_SUPERUSER_PASSWORD')
        email = os.getenv('ADMIN_EMAIL') or os.getenv('DJANGO_SUPERUSER_EMAIL') or 'admin@valcegs.com'

        if not password:
            self.stdout.write("Nenhuma senha de admin informada (ADMIN_PASSWORD). Pulando criação automática.")
            return

        user = User.objects.filter(username=username).first()
        if not user:
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"Superusuario '{username}' criado com sucesso!"))
        else:
            user.set_password(password)
            user.is_staff = True
            user.is_superuser = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Superusuario '{username}' ja existia e foi atualizado!"))
