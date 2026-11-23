"""
Rotação da chave de criptografia de dados pessoais.

1. Gere uma chave nova e coloque-a NO INÍCIO de FIELD_ENCRYPTION_KEY (separada por vírgula):
       FIELD_ENCRYPTION_KEY=<nova>,<antiga>
2. Reinicie a aplicação e rode:  python manage.py rotate_encryption_keys
3. Depois de concluído, remova a chave antiga do .env e reinicie novamente.

Funcionamento: carregar o registro descriptografa com qualquer chave configurada;
salvar criptografa de novo com a chave primária (a primeira da lista).
"""
from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from apps.core.fields import EncryptedTextField


class Command(BaseCommand):
    help = "Re-criptografa todos os campos EncryptedTextField com a chave primária atual."

    def handle(self, *args, **options):
        total = 0
        for model in apps.get_models():
            fields = [f.name for f in model._meta.concrete_fields if isinstance(f, EncryptedTextField)]
            if not fields:
                continue
            not_empty = Q()
            for name in fields:
                not_empty |= ~Q(**{name: ''})
            with transaction.atomic():
                for obj in model.objects.filter(not_empty).only('pk', *fields).iterator():
                    obj.save(update_fields=fields)
                    total += 1
            self.stdout.write(f"{model._meta.label}: {', '.join(fields)}")
        self.stdout.write(self.style.SUCCESS(f"{total} registro(s) re-criptografado(s) com a chave primária."))
