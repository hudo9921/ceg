from django.db import models
from django.utils import timezone
import re


# Conjunto oficial de DDDs válidos no Brasil (Anatel)
BRAZIL_DDDS = {
    11, 12, 13, 14, 15, 16, 17, 18, 19,
    21, 22, 24, 27, 28,
    31, 32, 33, 34, 35, 37, 38,
    41, 42, 43, 44, 45, 46, 47, 48, 49,
    51, 53, 54, 55,
    61, 62, 63, 64, 65, 66, 67, 68, 69,
    71, 73, 74, 75, 77, 79,
    81, 82, 83, 84, 85, 86, 87, 88, 89,
    91, 92, 93, 94, 95, 96, 97, 98, 99
}


def clean_phone_number(phone: str, default_country: str = '55') -> str:
    """
    Remove caracteres não numéricos e formata o telefone para um padrão canônico único (apenas dígitos internacionais E.164 sem o '+').
    Função idempotente: clean_phone_number(clean_phone_number(x)) == clean_phone_number(x).
    
    Padronização para qualquer formato de entrada:
      - 'DDD 91234-5678', 'DDD912345678', 'DDD91234-5678', '(DDD) 91234-5678' -> '55DDD912345678'
      - '+55 DDD 91234-5678', '+55DDD912345678', '55 DDD 91234-5678' -> '55DDD912345678'
      - '0DDD 91234-5678' (zero comum de discagem) -> '55DDD912345678'
      - '0XX DDD 91234-5678' (código de operadora 015, 021, 031, 041, etc.) -> '55DDD912345678'
      - '+55 (0DDD) 91234-5678' -> '55DDD912345678'
      - Números internacionais com '+' ou '00' (ex: '+1 202 555-0199', '+82 10 1234 5678') -> '12025550199', '821012345678'
    """
    if not phone:
        return ""

    phone_str = str(phone).strip()
    is_explicit_intl = phone_str.startswith('+') or phone_str.startswith('00')
    if phone_str.startswith('00'):
        phone_str = phone_str[2:]

    digits = re.sub(r'\D', '', phone_str)
    if not digits:
        return ""

    # Se começa com 55 e tem zero logo após (ex: +55 011 91234-5678 -> 55011912345678)
    if digits.startswith('550') and len(digits) in (13, 14):
        candidate_ddd = int(digits[3:5]) if digits[3:5].isdigit() else 0
        if candidate_ddd in BRAZIL_DDDS:
            digits = '55' + digits[3:]

    if is_explicit_intl:
        # Usuário informou DDI explicitamente com '+' ou '00'
        return digits

    # Remove zero à esquerda no padrão de discagem nacional (ex: 011 91234-5678 -> 011...)
    if digits.startswith('0'):
        # Caso 1: 0 + DDD (2 dígitos) + 8 ou 9 dígitos (total 11 ou 12 dígitos)
        if len(digits) in (11, 12):
            candidate_ddd = int(digits[1:3]) if digits[1:3].isdigit() else 0
            if candidate_ddd in BRAZIL_DDDS:
                digits = digits[1:]
        # Caso 2: 0 + Operadora (2 dígitos) + DDD (2 dígitos) + 8 ou 9 dígitos (total 13 ou 14 dígitos)
        elif len(digits) in (13, 14):
            candidate_ddd = int(digits[3:5]) if digits[3:5].isdigit() else 0
            if candidate_ddd in BRAZIL_DDDS:
                digits = digits[3:]

    # Se já possui DDI 55 (12 dígitos fixo ou 13 dígitos celular BR): já está normalizado!
    if digits.startswith('55') and len(digits) in (12, 13):
        return digits

    # Se default_country for '55':
    if str(default_country) == '55':
        # Telefone fixo brasileiro com DDD: 10 dígitos (ex: 11 3456-7890)
        if len(digits) == 10:
            ddd = int(digits[:2]) if digits[:2].isdigit() else 0
            if ddd in BRAZIL_DDDS:
                return '55' + digits

        # 11 dígitos: pode ser Celular BR (DDD + 9XXXX-XXXX) ou EUA/Canadá (1 + 10 dígitos)
        elif len(digits) == 11:
            # Verifica se é formato EUA/Canadá (DDI 1 seguido de área 200-999)
            if digits.startswith('1') and digits[1] in '23456789' and digits[2] != '9':
                return digits
            # Se DDD válido do Brasil e o terceiro dígito for 9 (celular BR)
            ddd = int(digits[:2]) if digits[:2].isdigit() else 0
            if ddd in BRAZIL_DDDS and digits[2] == '9':
                return '55' + digits
            elif ddd in BRAZIL_DDDS:
                return '55' + digits

    elif default_country:
        clean_default = re.sub(r'\D', '', str(default_country))
        if clean_default and not digits.startswith(clean_default):
            digits = clean_default + digits

    return digits


class Participant(models.Model):
    name = models.CharField('Nome Completo do Participante', max_length=150)
    username = models.CharField(
        'Nome de Usuário / Apelido',
        max_length=60,
        blank=True,
        help_text='Como você prefere ser chamado(a) no sistema (ex: Bia, Hudo, JihyoStan)'
    )
    whatsapp = models.CharField(
        'WhatsApp',
        max_length=30,
        unique=True,
        db_index=True,
        help_text='Apenas números com DDD e DDI (ex: 5511999998888 ou 12025550199)'
    )
    social_handle = models.CharField(
        '@ Rede Social (Twitter / Instagram)',
        max_length=100,
        blank=True,
        help_text='Identificador público na comunidade de K-pop (ex: @jihyolover)'
    )
    notes = models.TextField('Notas Internas do Organizador', blank=True)
    created_at = models.DateTimeField('Cadastrado em', auto_now_add=True)

    class Meta:
        verbose_name = 'Participante'
        verbose_name_plural = 'Participantes'
        ordering = ['name']

    def __str__(self):
        user = f" [{self.username}]" if self.username else ""
        handle = f" ({self.social_handle})" if self.social_handle else ""
        return f"{self.name}{user}{handle} - {self.whatsapp}"

    def save(self, *args, **kwargs):
        if self.whatsapp:
            self.whatsapp = clean_phone_number(self.whatsapp)
        if self.social_handle:
            handle = self.social_handle.strip()
            if handle and not handle.startswith('@'):
                self.social_handle = f"@{handle}"
            else:
                self.social_handle = handle
        if self.name:
            self.name = self.name.strip()
        if self.username:
            self.username = self.username.strip()
        super().save(*args, **kwargs)

    @property
    def display_name(self) -> str:
        """Retorna o nome de usuário/apelido escolhido ou o nome completo."""
        if self.username:
            return self.username
        if self.name:
            return self.name
        return f"Participante {self.whatsapp[-4:]}"

    @property
    def formatted_phone(self):
        """Retorna formato amigável para exibição."""
        w = self.whatsapp
        if not w:
            return ""
        # Brasil celular: +55 (XX) XXXXX-XXXX
        if w.startswith('55') and len(w) == 13:
            return f"+55 ({w[2:4]}) {w[4:9]}-{w[9:]}"
        # Brasil fixo: +55 (XX) XXXX-XXXX
        if w.startswith('55') and len(w) == 12:
            return f"+55 ({w[2:4]}) {w[4:8]}-{w[8:]}"
        # EUA / Canadá: +1 (XXX) XXX-XXXX
        if w.startswith('1') and len(w) == 11:
            return f"+1 ({w[1:4]}) {w[4:7]}-{w[7:]}"
        # Coreia do Sul: +82 XX XXXX-XXXX ou +82 XXX XXXX-XXXX
        if w.startswith('82') and len(w) in (11, 12):
            return f"+82 {w[2:4]} {w[4:8]}-{w[8:]}"
        return f"+{w}"

    @property
    def unread_notifications_count(self) -> int:
        """Retorna a contagem de notificações não lidas deste participante."""
        return self.notifications.filter(is_read=False).count()


class Claim(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Aguardando Pagamento'
        PAID = 'PAID', 'Pago / Confirmado'
        CANCELLED = 'CANCELLED', 'Cancelado'

    slot = models.OneToOneField(
        'cegs.ItemSlot',
        on_delete=models.CASCADE,
        related_name='claim',
        verbose_name='Slot Reservado'
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name='claims',
        verbose_name='Participante'
    )
    status = models.CharField(
        'Status do Pagamento',
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    total_price = models.DecimalField(
        'Valor da Reserva (R$)',
        max_digits=10,
        decimal_places=2,
        default=0.00
    )
    payment_proof_url = models.URLField('Link do Comprovante (Pix/Drive)', max_length=500, blank=True)
    participant_notes = models.TextField('Observações do Participante', blank=True)
    organizer_notes = models.TextField('Notas do Organizador', blank=True)
    claimed_at = models.DateTimeField('Reservado em', auto_now_add=True)
    paid_at = models.DateTimeField('Data de Confirmação do Pagamento', null=True, blank=True)

    class Meta:
        verbose_name = 'Reserva (Claim)'
        verbose_name_plural = 'Reservas (Claims)'
        ordering = ['-claimed_at']

    def __str__(self):
        return f"Claim #{self.id} - {self.slot} por {self.participant.name} [{self.get_status_display()}]"

    def mark_as_paid(self):
        self.status = self.Status.PAID
        self.paid_at = timezone.now()
        self.save(update_fields=['status', 'paid_at'])
        # Sincroniza o slot
        if self.slot:
            self.slot.status = 'PAID'
            self.slot.save(update_fields=['status'])

    def cancel(self):
        self.status = self.Status.CANCELLED
        self.save(update_fields=['status'])
        # Libera o slot
        if self.slot:
            self.slot.status = 'AVAILABLE'
            self.slot.claimed_by = None
            self.slot.claimed_at = None
            self.slot.save(update_fields=['status', 'claimed_by', 'claimed_at'])


class ParticipantNotification(models.Model):
    class NotificationType(models.TextChoices):
        SET_CANCELLED = 'SET_CANCELLED', 'Set Cancelado'
        CLAIM_UPDATE = 'CLAIM_UPDATE', 'Atualização de Reserva'
        GENERAL = 'GENERAL', 'Aviso Geral'
        ENVIO_NACIONAL = 'ENVIO_NACIONAL', 'Envio Nacional Despachado'

    participant = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='Participante'
    )
    title = models.CharField('Título', max_length=200)
    message = models.TextField('Mensagem / Detalhes')
    notification_type = models.CharField(
        'Tipo de Notificação',
        max_length=40,
        choices=NotificationType.choices,
        default=NotificationType.SET_CANCELLED,
        db_index=True
    )
    is_read = models.BooleanField('Lida', default=False, db_index=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True, db_index=True)
    read_at = models.DateTimeField('Lida em', null=True, blank=True)

    class Meta:
        verbose_name = 'Notificação de Participante'
        verbose_name_plural = 'Notificações de Participantes'
        ordering = ['-created_at']

    def __str__(self):
        return f"Notificação para {self.participant.display_name}: {self.title}"

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

