import logging
import secrets
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from apps.participants.models import Participant, clean_phone_number
from .models import WhatsAppOTP
from .providers import get_whatsapp_provider

logger = logging.getLogger(__name__)

# Limites de envio de OTP (janela, máximo de códigos). Persistidos no banco via WhatsAppOTP,
# portanto valem entre todos os workers do Gunicorn.
SEND_LIMITS_PER_PHONE = (
    (timedelta(minutes=15), 3),
    (timedelta(hours=24), 10),
)
SEND_LIMIT_PER_IP = (timedelta(hours=1), 20)
# Total de tentativas incorretas aceitas por telefone em 24h (somando todos os códigos).
MAX_FAILED_VERIFICATIONS_PER_DAY = 10
MAX_ATTEMPTS_PER_CODE = 5

RATE_LIMIT_MESSAGE = "Muitas solicitações de código para este número. Aguarde alguns minutos e tente novamente."
LOCKED_MESSAGE = "Muitas tentativas incorretas para este número. Tente novamente em algumas horas."


class OTPService:
    @staticmethod
    def _send_rate_limited(phone: str, ip_address: str | None) -> bool:
        now = timezone.now()
        for window, limit in SEND_LIMITS_PER_PHONE:
            if WhatsAppOTP.objects.filter(phone=phone, created_at__gte=now - window).count() >= limit:
                return True
        if ip_address:
            window, limit = SEND_LIMIT_PER_IP
            if WhatsAppOTP.objects.filter(ip_address=ip_address, created_at__gte=now - window).count() >= limit:
                return True
        return False

    @staticmethod
    def _is_locked(phone: str) -> bool:
        since = timezone.now() - timedelta(hours=24)
        failed = WhatsAppOTP.objects.filter(phone=phone, created_at__gte=since).aggregate(
            total=Sum('attempts')
        )['total'] or 0
        return failed >= MAX_FAILED_VERIFICATIONS_PER_DAY

    @staticmethod
    def send_otp(phone: str, ip_address: str | None = None) -> tuple[bool, str, str | None]:
        """
        Gera um novo código OTP de 6 dígitos e envia pelo WhatsApp.
        Retorna (sucesso, mensagem, codigo_gerado).

        ATENÇÃO: o código retornado é para uso interno (testes / modo console).
        Ele NUNCA deve ser repassado ao cliente HTTP fora de DEBUG + provider console.
        """
        cleaned = clean_phone_number(phone)
        if not cleaned or len(cleaned) < 10:
            return False, "Por favor, informe um número de telefone com DDD válido.", None

        if OTPService._is_locked(cleaned):
            logger.warning("OTP bloqueado por excesso de falhas (final %s)", cleaned[-4:])
            return False, LOCKED_MESSAGE, None

        if OTPService._send_rate_limited(cleaned, ip_address):
            logger.warning("OTP rate limit atingido (final %s, ip %s)", cleaned[-4:], ip_address)
            return False, RATE_LIMIT_MESSAGE, None

        otp = WhatsAppOTP.create_for_phone(cleaned, valid_minutes=10, ip_address=ip_address)

        msg = (
            f"✨ *K-pop CEG Manager*\n\n"
            f"Seu código de acesso para consultar suas reservas é: *{otp.code}*\n\n"
            f"⏱️ Este código expira em 10 minutos.\n"
            f"Se você não solicitou este código, desconsidere esta mensagem."
        )

        provider = get_whatsapp_provider()
        sent = provider.send_message(cleaned, msg)

        if sent:
            return True, "Código de verificação enviado com sucesso para o seu WhatsApp!", otp.code
        return False, "Não foi possível enviar a mensagem no WhatsApp. Tente novamente.", None

    @staticmethod
    def verify_otp(phone: str, code: str) -> tuple[bool, str, Participant | None]:
        """
        Valida o código digitado pelo participante.
        Retorna (sucesso, mensagem_erro, participante).
        """
        cleaned = clean_phone_number(phone)
        input_code = (code or '').strip()

        if not cleaned:
            return False, "Número de telefone inválido.", None

        if OTPService._is_locked(cleaned):
            return False, LOCKED_MESSAGE, None

        latest_otp = WhatsAppOTP.objects.filter(phone=cleaned, is_used=False).first()

        if not latest_otp:
            return False, "Nenhum código ativo encontrado para este número. Solicite um novo código.", None

        if timezone.now() > latest_otp.expires_at:
            return False, "O código expirou. Solicite um novo código.", None

        if latest_otp.attempts >= MAX_ATTEMPTS_PER_CODE:
            return False, "Limite de tentativas excedido para este código. Solicite um novo.", None

        if not secrets.compare_digest(latest_otp.code.encode(), input_code.encode()):
            latest_otp.attempts += 1
            latest_otp.save(update_fields=['attempts'])
            remaining = MAX_ATTEMPTS_PER_CODE - latest_otp.attempts
            return False, f"Código incorreto. Você ainda tem {remaining} tentativa(s).", None

        latest_otp.is_used = True
        latest_otp.save(update_fields=['is_used'])

        participant, _ = Participant.objects.get_or_create(
            whatsapp=cleaned,
            defaults={'name': f'Participante {cleaned[-4:]}'}
        )

        return True, "Autenticado com sucesso!", participant
