"""
Criptografia de dados pessoais em repouso (LGPD): endereço, CEP, CPF etc.

- Algoritmo: Fernet (AES-128-CBC + HMAC-SHA256), biblioteca `cryptography`.
- Chaves: `settings.FIELD_ENCRYPTION_KEYS` (lista). A PRIMEIRA criptografa; todas
  descriptografam — permite rotação: adicione a chave nova no início, rode
  `python manage.py rotate_encryption_keys` e depois remova a antiga.
- Formato salvo no banco: "enc:v1:<token Fernet>". Valores sem o prefixo são tratados
  como texto puro legado (antes da migração) e retornados como estão.
"""
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PREFIX = 'enc:v1:'


class DecryptionError(Exception):
    """Nenhuma das chaves configuradas descriptografa o valor (chave errada/perdida)."""


@lru_cache(maxsize=1)
def _fernet_for(keys: tuple) -> MultiFernet:
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY não configurada.")
    try:
        return MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY inválida. Gere com: python -c \"from cryptography.fernet import "
            "Fernet; print(Fernet.generate_key().decode())\""
        ) from exc


def get_fernet() -> MultiFernet:
    return _fernet_for(tuple(settings.FIELD_ENCRYPTION_KEYS))


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt_str(value: str) -> str:
    if value is None or value == '' or is_encrypted(value):
        return value
    return PREFIX + get_fernet().encrypt(str(value).encode('utf-8')).decode('ascii')


def decrypt_str(value: str) -> str:
    if not is_encrypted(value):
        return value
    try:
        return get_fernet().decrypt(value[len(PREFIX):].encode('ascii')).decode('utf-8')
    except InvalidToken as exc:
        raise DecryptionError("Não foi possível descriptografar um dado pessoal (chave incorreta?).") from exc


def rotate_str(value: str) -> str:
    """Re-criptografa com a chave primária atual (para rotação de chaves)."""
    if not is_encrypted(value):
        return encrypt_str(value)
    token = get_fernet().rotate(value[len(PREFIX):].encode('ascii'))
    return PREFIX + token.decode('ascii')
