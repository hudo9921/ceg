from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from apps.groups.models import Era


class CEG(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Rascunho'
        SCHEDULED = 'SCHEDULED', 'Agendada (Standby / Countdown)'
        OPEN = 'OPEN', 'Aberta para Reservas'
        CLOSED = 'CLOSED', 'Encerrada'
        COMPLETED = 'COMPLETED', 'Concluída'
        CANCELLED = 'CANCELLED', 'Cancelada'

    era = models.ForeignKey(
        Era,
        on_delete=models.CASCADE,
        related_name='cegs',
        verbose_name='Era / Comeback'
    )
    title = models.CharField('Título da CEG', max_length=200)
    slug = models.SlugField('Slug', max_length=220, unique=True, blank=True)
    description = models.TextField(
        'Regras e Informações da CEG',
        blank=True,
        help_text='Regras de frete (nacional/internacional), prazos e avisos aos participantes.'
    )
    banner_url = models.URLField('URL do Banner da CEG', max_length=500, blank=True)
    pix_key = models.CharField('Chave Pix do Organizador', max_length=150, blank=True)
    pix_instructions = models.TextField(
        'Instruções para Pagamento Pix',
        blank=True,
        help_text='Orientações como envio de comprovante, identificação no Pix, etc.'
    )
    status = models.CharField(
        'Status',
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True
    )
    opens_at = models.DateTimeField(
        'Data e Hora de Abertura (Standby / Countdown)',
        null=True,
        blank=True,
        help_text='Se preenchido com data futura, a página pública exibirá o cronômetro regressivo.'
    )
    closes_at = models.DateTimeField('Data e Hora de Encerramento', null=True, blank=True)
    prazo_pagamento_item = models.DateTimeField(
        'Prazo de Pagamento do Item',
        null=True,
        blank=True,
        help_text='Data e hora limite para pagamento do valor do item (opcional).'
    )
    frete_inter = models.DecimalField(
        'Frete Internacional (R$)',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Valor do frete internacional (começa nulo e depois atualiza).'
    )
    taxa_aduaneira = models.DecimalField(
        'Taxa Aduaneira (R$)',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Valor da taxa aduaneira / alfandegária (começa nulo e depois atualiza).'
    )
    prazo_pagamento_frete_inter = models.DateTimeField(
        'Prazo de Pagamento do Frete Inter',
        null=True,
        blank=True,
        help_text='Data e hora limite para pagamento do frete internacional (opcional).'
    )
    prazo_pagamento_taxa_aduaneira = models.DateTimeField(
        'Prazo de Pagamento da Taxa Aduaneira',
        null=True,
        blank=True,
        help_text='Data e hora limite para pagamento da taxa aduaneira (opcional).'
    )
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'CEG (Compra em Grupo)'
        verbose_name_plural = 'CEGs (Compras em Grupo)'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.era.group.name})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while CEG.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_standby(self) -> bool:
        """Indica se a CEG está em modo de contagem regressiva aguardando horário de abertura."""
        if self.status == self.Status.CANCELLED or self.status == self.Status.CLOSED:
            return False
        if self.opens_at and timezone.now() < self.opens_at:
            return True
        return False

    @property
    def is_open_for_claims(self) -> bool:
        """Indica se os botões de reserva devem estar destravados."""
        if self.is_standby:
            return False
        if self.status in (self.Status.OPEN, self.Status.SCHEDULED):
            if self.closes_at and timezone.now() > self.closes_at:
                return False
            return True
        return False

    @property
    def countdown_seconds(self) -> int:
        """Segundos restantes para abertura"""
        if self.opens_at and timezone.now() < self.opens_at:
            delta = self.opens_at - timezone.now()
            return max(0, int(delta.total_seconds()))
        return 0

    @property
    def total_slots_count(self) -> int:
        if hasattr(self, '_total_slots_count'):
            return self._total_slots_count
        return ItemSlot.objects.filter(set__ceg=self, set__is_active=True).count()

    @total_slots_count.setter
    def total_slots_count(self, value: int):
        self._total_slots_count = value

    @property
    def reserved_slots_count(self) -> int:
        if hasattr(self, '_reserved_slots_count'):
            return self._reserved_slots_count
        return ItemSlot.objects.filter(
            set__ceg=self,
            set__is_active=True,
            status__in=[ItemSlot.Status.RESERVED, ItemSlot.Status.PAID]
        ).count()

    @reserved_slots_count.setter
    def reserved_slots_count(self, value: int):
        self._reserved_slots_count = value

    @property
    def available_slots_count(self) -> int:
        if hasattr(self, '_available_slots_count'):
            return self._available_slots_count
        return ItemSlot.objects.filter(
            set__ceg=self,
            set__is_active=True,
            status=ItemSlot.Status.AVAILABLE
        ).count()

    @available_slots_count.setter
    def available_slots_count(self, value: int):
        self._available_slots_count = value

    @property
    def progress_percentage(self) -> int:
        if hasattr(self, '_progress_percentage'):
            return self._progress_percentage
        total = self.total_slots_count
        if total == 0:
            return 0
        return int((self.reserved_slots_count / total) * 100)

    @progress_percentage.setter
    def progress_percentage(self, value: int):
        self._progress_percentage = value

    @property
    def has_single_price(self) -> bool:
        if not hasattr(self, '_has_single_price'):
            from apps.cegs.services import enrich_cegs_with_availability
            enrich_cegs_with_availability([self])
        return getattr(self, '_has_single_price', False)

    @has_single_price.setter
    def has_single_price(self, value: bool):
        self._has_single_price = value

    @property
    def single_price(self):
        if not hasattr(self, '_single_price'):
            from apps.cegs.services import enrich_cegs_with_availability
            enrich_cegs_with_availability([self])
        return getattr(self, '_single_price', None)

    @single_price.setter
    def single_price(self, value):
        self._single_price = value

    @property
    def has_different_prices(self) -> bool:
        if not hasattr(self, '_has_different_prices'):
            from apps.cegs.services import enrich_cegs_with_availability
            enrich_cegs_with_availability([self])
        return getattr(self, '_has_different_prices', False)

    @has_different_prices.setter
    def has_different_prices(self, value: bool):
        self._has_different_prices = value

    @property
    def grouped_available_items(self) -> list:
        if not hasattr(self, '_grouped_available_items'):
            from apps.cegs.services import enrich_cegs_with_availability
            enrich_cegs_with_availability([self])
        return getattr(self, '_grouped_available_items', [])

    @grouped_available_items.setter
    def grouped_available_items(self, value: list):
        self._grouped_available_items = value



class CEGItemDefinition(models.Model):
    class ItemType(models.TextChoices):
        PHOTOCARD = 'PHOTOCARD', 'Photocard'
        POB = 'POB', 'Pre-Order Benefit (POB)'
        ALBUM = 'ALBUM', 'Álbum'
        INCLUSION = 'INCLUSION', 'Inclusão / Avulso'
        OTHER = 'OTHER', 'Outro'

    ceg = models.ForeignKey(
        CEG,
        on_delete=models.CASCADE,
        related_name='item_definitions',
        verbose_name='CEG'
    )
    name = models.CharField('Nome do Item', max_length=150)
    member_name = models.CharField(
        'Integrante (se aplicável)',
        max_length=100,
        blank=True,
        help_text='Usado para análises de popularidade e tempo de esgotamento'
    )
    item_type = models.CharField(
        'Tipo do Item',
        max_length=20,
        choices=ItemType.choices,
        default=ItemType.PHOTOCARD
    )
    default_price = models.DecimalField(
        'Preço Padrão (R$)',
        max_digits=10,
        decimal_places=2,
        default=0.00
    )
    image_url = models.URLField('URL da Foto / Prévia', max_length=500, blank=True)
    order_index = models.PositiveIntegerField('Ordem de Exibição', default=0)

    class Meta:
        verbose_name = 'Definição de Item da CEG'
        verbose_name_plural = 'Definições de Itens da CEG'
        ordering = ['order_index', 'name']

    def __str__(self):
        member = f" [{self.member_name}]" if self.member_name else ""
        return f"{self.name}{member} - R$ {self.default_price:.2f}"


class CEGSet(models.Model):
    ceg = models.ForeignKey(
        CEG,
        on_delete=models.CASCADE,
        related_name='sets',
        verbose_name='CEG'
    )
    set_number = models.PositiveIntegerField('Número do Set', default=1)
    is_active = models.BooleanField('Ativo para Reservas', default=True)
    notes = models.CharField('Anotações do Set', max_length=255, blank=True)

    class Meta:
        verbose_name = 'Set da CEG'
        verbose_name_plural = 'Sets da CEG'
        ordering = ['set_number']
        unique_together = ('ceg', 'set_number')

    def __str__(self):
        return f"Set #{self.set_number} - {self.ceg.title}"

    @property
    def slots_count(self) -> int:
        return self.slots.count()

    @property
    def reserved_count(self) -> int:
        return self.slots.filter(status__in=[ItemSlot.Status.RESERVED, ItemSlot.Status.PAID]).count()

    @property
    def is_full(self) -> bool:
        total = self.slots_count
        return total > 0 and self.reserved_count == total

    def generate_slots(self):
        """Gera automaticamente todos os ItemSlots baseados nas definições de itens da CEG."""
        created_slots = []
        for item_def in self.ceg.item_definitions.all():
            slot, created = ItemSlot.objects.get_or_create(
                set=self,
                item_definition=item_def,
                defaults={'price': item_def.default_price}
            )
            if created:
                created_slots.append(slot)
        return created_slots


class ItemSlot(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Disponível'
        RESERVED = 'RESERVED', 'Reservado'
        PAID = 'PAID', 'Pago'
        CANCELLED = 'CANCELLED', 'Cancelado'

    set = models.ForeignKey(
        CEGSet,
        on_delete=models.CASCADE,
        related_name='slots',
        verbose_name='Set'
    )
    item_definition = models.ForeignKey(
        CEGItemDefinition,
        on_delete=models.CASCADE,
        related_name='slots',
        verbose_name='Item Definido'
    )
    price = models.DecimalField('Preço do Slot (R$)', max_digits=10, decimal_places=2)
    status = models.CharField(
        'Status do Slot',
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
        db_index=True
    )
    claimed_by = models.ForeignKey(
        'participants.Participant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reserved_slots',
        verbose_name='Reservado por'
    )
    claimed_at = models.DateTimeField('Reservado em', null=True, blank=True)
    is_item_paid = models.BooleanField(
        'Item Pago',
        default=False,
        help_text='Check mark indicando se o valor do item foi pago.'
    )
    is_frete_inter_paid = models.BooleanField(
        'Frete Inter Pago',
        default=False,
        help_text='Check mark indicando se o frete internacional foi pago.'
    )
    is_taxa_aduaneira_paid = models.BooleanField(
        'Taxa Aduaneira Paga',
        default=False,
        help_text='Check mark indicando se a taxa aduaneira foi paga.'
    )
    is_frete_nacional_paid = models.BooleanField(
        'Frete Nacional Pago',
        default=False,
        help_text='Check mark indicando se o frete nacional foi pago.'
    )

    def sync_payment_status(self):
        """Sincroniza o status do slot e da reserva (Claim) com base na flag is_item_paid."""
        if self.is_item_paid:
            self.status = self.Status.PAID
            if hasattr(self, 'claim') and self.claim:
                self.claim.status = 'PAID'
                if not self.claim.paid_at:
                    self.claim.paid_at = timezone.now()
                self.claim.save(update_fields=['status', 'paid_at'])
        else:
            if self.claimed_by:
                self.status = self.Status.RESERVED
                if hasattr(self, 'claim') and self.claim:
                    self.claim.status = 'PENDING'
                    self.claim.save(update_fields=['status'])
            else:
                self.status = self.Status.AVAILABLE

    def toggle_payment(self, field_name: str, value=None) -> bool:
        """Alterna ou define o status de um dos campos de pagamento do item/slot."""
        field_map = {
            'item': 'is_item_paid',
            'is_item_paid': 'is_item_paid',
            'frete_inter': 'is_frete_inter_paid',
            'inter': 'is_frete_inter_paid',
            'is_frete_inter_paid': 'is_frete_inter_paid',
            'taxa': 'is_taxa_aduaneira_paid',
            'taxa_aduaneira': 'is_taxa_aduaneira_paid',
            'is_taxa_aduaneira_paid': 'is_taxa_aduaneira_paid',
            'nacional': 'is_frete_nacional_paid',
            'frete_nacional': 'is_frete_nacional_paid',
            'is_frete_nacional_paid': 'is_frete_nacional_paid',
        }
        attr = field_map.get(field_name)
        if not attr:
            raise ValueError(f"Campo de pagamento desconhecido: '{field_name}'")
        current_val = getattr(self, attr)
        new_val = not current_val if value is None else bool(value)
        setattr(self, attr, new_val)
        update_fields = [attr]

        if attr == 'is_item_paid':
            self.sync_payment_status()
            update_fields.append('status')

        self.save(update_fields=update_fields)
        return new_val

    class Meta:
        verbose_name = 'Slot de Item'
        verbose_name_plural = 'Slots de Itens'
        ordering = ['set__set_number', 'item_definition__order_index', 'item_definition__name']
        unique_together = ('set', 'item_definition')

    def __str__(self):
        return f"Set {self.set.set_number} | {self.item_definition.name} ({self.get_status_display()})"

    @property
    def is_available(self) -> bool:
        return self.status == self.Status.AVAILABLE

    @property
    def frete_inter(self):
        """Retorna o frete internacional definido para a CEG deste slot."""
        return self.set.ceg.frete_inter

    @property
    def taxa_aduaneira(self):
        """Retorna a taxa aduaneira definida para a CEG deste slot."""
        return self.set.ceg.taxa_aduaneira


class ClaimAttemptLog(models.Model):
    class Result(models.TextChoices):
        SUCCESS = 'SUCCESS', '1º Lugar (Reserva Garantida)'
        LOST_RACE = 'LOST_RACE', 'Perdeu por Concorrência'
        STANDBY_BLOCKED = 'STANDBY_BLOCKED', 'Bloqueado (Modo Standby)'
        ERROR = 'ERROR', 'Erro / Falha'

    slot = models.ForeignKey(
        ItemSlot,
        on_delete=models.CASCADE,
        related_name='attempt_logs',
        verbose_name='Slot'
    )
    attempt_number = models.PositiveIntegerField('Ordem da Tentativa (Chegada)', default=1)
    participant_name = models.CharField('Nome do Participante', max_length=150)
    phone = models.CharField('WhatsApp', max_length=30)
    social_handle = models.CharField('@ Rede Social', max_length=100, blank=True)
    result = models.CharField('Resultado', max_length=30, choices=Result.choices)
    details = models.TextField('Detalhes da Tentativa', blank=True)
    created_at = models.DateTimeField('Data e Hora Exata', auto_now_add=True)

    class Meta:
        verbose_name = 'Log de Tentativa de Claim'
        verbose_name_plural = 'Logs de Tentativas de Claim (Ordem de Chegada)'
        ordering = ['slot', 'attempt_number']

    def __str__(self):
        handle = f" ({self.social_handle})" if self.social_handle else ""
        return f"Slot #{self.slot.id} - {self.attempt_number}º a dar claim: {self.participant_name}{handle} [{self.get_result_display()}]"
