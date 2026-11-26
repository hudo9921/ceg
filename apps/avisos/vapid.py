"""
Chaves VAPID do push. Usa VAPID_PRIVATE_KEY do .env se houver; senão deriva uma chave fixa do SECRET_KEY (mesma chave
a cada reinício, sem passo extra no deploy). Trocar o SECRET_KEY invalida as inscrições (o joiner ativa de novo).
"""
import base64
import hashlib
from functools import lru_cache

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings

ORDEM_P256 = int('FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551', 16)


def _b64url(dados):
    return base64.urlsafe_b64encode(dados).rstrip(b'=').decode()


@lru_cache(maxsize=1)
def chave_privada():
    texto = getattr(settings, 'VAPID_PRIVATE_KEY', '') or ''
    if texto:
        bruto = base64.urlsafe_b64decode(texto + '=' * (-len(texto) % 4))
        return serialization.load_der_private_key(bruto, password=None)
    semente = int.from_bytes(hashlib.sha256(('vapid:' + settings.SECRET_KEY).encode()).digest(), 'big')
    return ec.derive_private_key(semente % (ORDEM_P256 - 1) + 1, ec.SECP256R1())


def chave_publica():
    """Chave pública no formato que o navegador pede (applicationServerKey, base64url do ponto não comprimido)."""
    ponto = chave_privada().public_key().public_bytes(serialization.Encoding.X962,
                                                      serialization.PublicFormat.UncompressedPoint)
    return _b64url(ponto)


def chave_privada_pem():
    return chave_privada().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()).decode()
