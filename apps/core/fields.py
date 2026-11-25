"""Campos de model com criptografia transparente (ver apps/core/crypto.py)."""
from django.db import models

from .crypto import decrypt_str, encrypt_str


class EncryptedTextField(models.TextField):
    """
    TextField criptografado em repouso. No Python o valor é sempre texto puro;
    no banco fica "enc:v1:<token>".

    Atenção: buscas/filtros pelo conteúdo (`filter(campo='...')`, `icontains`) NÃO
    funcionam, pois cada criptografia gera um token diferente. Não use em campos
    que precisam ser pesquisados ou ordenados.
    """
    description = "Texto criptografado (Fernet)"

    def from_db_value(self, value, expression, connection):
        return decrypt_str(value)

    def to_python(self, value):
        return decrypt_str(value) if isinstance(value, str) else value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt_str(value)
