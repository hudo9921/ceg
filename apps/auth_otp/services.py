import logging
from django.utils import timezone
from apps.participants.models import Participant, clean_phone_number
from .models import WhatsAppOTP
from .providers import get_whatsapp_provider

logger = logging.getLogger(__name__)


class OTPService:
    @staticmethod
    def send_otp(phone: str) -> tuple[bool, str, str | None]:
        """
        Gera um novo código OTP de 6 dígitos e envia pelo WhatsApp.
        Retorna (sucesso, mensagem, codigo_gerado_se_dev).
        """
        cleaned = clean_phone_number(phone)
        if not cleaned or len(cleaned) < 10:
            return False, "Por favor, informe um número de telefone com DDD válido.", None

        # Cria novo OTP
        otp = WhatsAppOTP.create_for_phone(cleaned, valid_minutes=10)

        # Mensagem formatada para WhatsApp
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
        else:
            return False, "Não foi possível enviar a mensagem no WhatsApp. Tente novamente.", None

    @staticmethod
    def verify_otp(phone: str, code: str) -> tuple[bool, str, Participant | None]:
        """
        Valida o código digitado pelo participante.
        Retorna (sucesso, mensagem_erro, participante).
        """
        cleaned = clean_phone_number(phone)
        input_code = code.strip()

        if not cleaned:
            return False, "Número de telefone inválido.", None

        # Busca o OTP mais recente deste telefone
        latest_otp = WhatsAppOTP.objects.filter(phone=cleaned, is_used=False).first()

        if not latest_otp:
            return False, "Nenhum código ativo encontrado para este número. Solicite um novo código.", None

        if timezone.now() > latest_otp.expires_at:
            return False, "O código expirou. Solicite um novo código.", None

        if latest_otp.attempts >= 5:
            return False, "Limite de tentativas excedido para este código. Solicite um novo.", None

        if latest_otp.code != input_code:
            latest_otp.attempts += 1
            latest_otp.save(update_fields=['attempts'])
            remaining = 5 - latest_otp.attempts
            return False, f"Código incorreto. Você ainda tem {remaining} tentativa(s).", None

        # Código correto!
        latest_otp.is_used = True
        latest_otp.save(update_fields=['is_used'])

        # Localiza ou inicializa o participante
        participant, _ = Participant.objects.get_or_create(
            whatsapp=cleaned,
            defaults={'name': f'Participante {cleaned[-4:]}'}
        )

        return True, "Autenticado com sucesso!", participant
