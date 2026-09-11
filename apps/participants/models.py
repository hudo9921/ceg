from django.db import models
from django.utils import timezone
import re


def clean_phone_number(phone: str) -> str:
    """
    Remove caracteres não numéricos. Se não tiver DDI (+55), adiciona 55 caso seja padrão BR com DDD.
    """
    digits = re.sub(r'\D', '', phone)
    if len(digits) in (10, 11) and not digits.startswith('55'):
        digits = '55' + digits
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
        help_text='Apenas números com DDD e DDI (ex: 5511999998888)'
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
        """Retorna formato amigável (XX) XXXXX-XXXX se for BR"""
        w = self.whatsapp
        if w.startswith('55') and len(w) == 13:
            return f"+55 ({w[2:4]}) {w[4:9]}-{w[9:]}"
        return f"+{w}"


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
