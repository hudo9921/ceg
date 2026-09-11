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
        return ItemSlot.objects.filter(set__ceg=self, set__is_active=True).count()

    @property
    def reserved_slots_count(self) -> int:
        return ItemSlot.objects.filter(
            set__ceg=self,
            set__is_active=True,
            status__in=[ItemSlot.Status.RESERVED, ItemSlot.Status.PAID]
        ).count()

    @property
    def progress_percentage(self) -> int:
        total = self.total_slots_count
        if total == 0:
            return 0
        return int((self.reserved_slots_count / total) * 100)


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
