import logging
import requests
from abc import ABC, abstractmethod
from django.conf import settings

logger = logging.getLogger(__name__)

# Armazena em memória os últimos códigos enviados (útil para testes e modo dev)
LAST_SENT_MESSAGES = {}


class BaseWhatsAppProvider(ABC):
    @abstractmethod
    def send_message(self, phone: str, message: str) -> bool:
        """Envia mensagem de texto para o número especificado."""
        pass


class ConsoleMockWhatsAppProvider(BaseWhatsAppProvider):
    """
    Provedor padrão para desenvolvimento e testes locais.
    Exibe a mensagem formatada no terminal sem consumir créditos de API externa.
    """
    def send_message(self, phone: str, message: str) -> bool:
        LAST_SENT_MESSAGES[phone] = message
        try:
            print("\n" + "=" * 60)
            print(f"[WHATSAPP MOCK SIMULATOR] Mensagem para: +{phone}")
            print("-" * 60)
            # Remove emojis para evitar erro de codepage no Windows ao dar print no terminal
            safe_message = message.encode('ascii', 'ignore').decode('ascii')
            print(safe_message)
            print("=" * 60 + "\n")
        except Exception:
            pass
        logger.info(f"[WhatsApp Mock] Mensagem simulada enviada para {phone}: {message}")
        return True


class EvolutionApiWhatsAppProvider(BaseWhatsAppProvider):
    """
    Integração com Evolution API (v1 / v2).
    """
    def send_message(self, phone: str, message: str) -> bool:
        url = f"{settings.EVOLUTION_API_URL.rstrip('/')}/message/sendText/{settings.EVOLUTION_INSTANCE_NAME}"
        headers = {
            'Content-Type': 'application/json',
            'apikey': settings.EVOLUTION_API_KEY
        }
        payload = {
            'number': phone,
            'text': message,
            'delay': 1200
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code in (200, 201):
                logger.info(f"Mensagem enviada com sucesso via Evolution API para {phone}")
                return True
            else:
                logger.error(f"Erro Evolution API ({response.status_code}): {response.text}")
                return False
        except Exception as e:
            logger.error(f"Exceção ao conectar à Evolution API: {e}")
            return False


class ZApiWhatsAppProvider(BaseWhatsAppProvider):
    """
    Integração com Z-API.
    """
    def send_message(self, phone: str, message: str) -> bool:
        url = f"https://api.z-api.io/instances/{settings.ZAPI_INSTANCE_ID}/token/{settings.ZAPI_TOKEN}/send-text"
        headers = {
            'Content-Type': 'application/json',
        }
        if getattr(settings, 'ZAPI_CLIENT_TOKEN', None):
            headers['Client-Token'] = settings.ZAPI_CLIENT_TOKEN

        payload = {
            'phone': phone,
            'message': message
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code in (200, 201):
                logger.info(f"Mensagem enviada com sucesso via Z-API para {phone}")
                return True
            else:
                logger.error(f"Erro Z-API ({response.status_code}): {response.text}")
                return False
        except Exception as e:
            logger.error(f"Exceção ao conectar à Z-API: {e}")
            return False


def get_whatsapp_provider() -> BaseWhatsAppProvider:
    provider_name = getattr(settings, 'WHATSAPP_PROVIDER', 'console').lower()
    if provider_name == 'evolution':
        return EvolutionApiWhatsAppProvider()
    elif provider_name == 'zapi':
        return ZApiWhatsAppProvider()
    return ConsoleMockWhatsAppProvider()
