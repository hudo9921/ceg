from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.core.two_factor import reset_two_factor


class Command(BaseCommand):
    help = ("Remove o 2FA de um usuário (celular perdido). No próximo login ele cadastra um novo "
            "autenticador. Em produção: docker exec -it valcegs-web python manage.py reset_2fa <usuario>")

    def add_arguments(self, parser):
        parser.add_argument('username')

    def handle(self, username, **options):
        user = get_user_model().objects.filter(username=username).first()
        if not user:
            raise CommandError(f"Usuário '{username}' não encontrado.")
        removed = reset_two_factor(user)
        # Sessões já verificadas continuam válidas até expirar; o usuário deve sair e entrar de novo.
        self.stdout.write(self.style.SUCCESS(
            f"2FA de '{username}' redefinido ({removed} registros removidos). "
            "No próximo login será pedido um novo cadastro."))
