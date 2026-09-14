import re
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from apps.groups.models import Era


class TipoItem(models.Model):
    """Tipo/categoria de item (ex: Photocard, Álbum, CD, Labubu, etc.) gerenciável dinamicamente."""
    nome = models.CharField('Nome do Tipo de Item', max_length=100, unique=True)
    descricao = models.TextField('Descrição', blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        verbose_name = 'Tipo de Item'
        verbose_name_plural = 'Tipos de Itens'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Caixa(models.Model):
    class Origem(models.TextChoices):
        KR = 'KR', 'Coreia do Sul (KR)'
        JP = 'JP', 'Japão (JP / Mercari)'
        CN = 'CN', 'China (CN)'
        US = 'US', 'Estados Unidos (US)'
        OTHER = 'OTHER', 'Outro'

    class Status(models.TextChoices):
        EM_CONSOLIDACAO = 'EM_CONSOLIDACAO', 'Em Consolidação (No armazém)'
        PRONTA_ENVIO = 'PRONTA_ENVIO', 'Embalada (Pronta para envio)'
        ENVIADA = 'ENVIADA', 'Enviada (Em trânsito internacional)'
        NO_BRASIL = 'NO_BRASIL', 'No Brasil (Fiscalização aduaneira)'
        TRIBUTADA = 'TRIBUTADA', 'Tributada (Aguardando taxa)'
        LIBERADA = 'LIBERADA', 'Liberada pela alfândega (A caminho)'
        ENTREGUE = 'ENTREGUE', 'Entregue ao organizador (Em triagem)'
        FINALIZADA = 'FINALIZADA', 'Finalizada (Envios nacionais concluídos)'

    nome = models.CharField('Nome da Caixa / Remessa', max_length=150)
    slug = models.SlugField('Slug', max_length=180, unique=True, blank=True)
    origem = models.CharField(
        'Origem da Remessa',
        max_length=10,
        choices=Origem.choices,
        default=Origem.KR,
        db_index=True
    )
    status = models.CharField(
        'Status do Envio',
        max_length=30,
        choices=Status.choices,
        default=Status.EM_CONSOLIDACAO,
        db_index=True
    )
    codigo_rastreio = models.CharField('Código de Rastreio', max_length=100, blank=True)
    transportadora = models.CharField(
        'Transportadora / Modalidade',
        max_length=100,
        blank=True,
        help_text='Ex: Correios / EMS, K-Packet, FedEx, DHL, etc.'
    )
    data_envio = models.DateField('Data de Envio', null=True, blank=True)
    data_previsao = models.DateField('Previsão de Entrega', null=True, blank=True)
    data_recebimento = models.DateField('Data de Recebimento no Brasil', null=True, blank=True)
    frete_inter_total = models.DecimalField(
        'Frete Internacional Total (R$)',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Custo total pago pelo frete internacional desta caixa.'
    )
    taxa_aduaneira_total = models.DecimalField(
        'Taxa Aduaneira Total (R$)',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Custo total pago em impostos/taxas alfandegárias desta caixa.'
    )
    prazo_frete = models.DateTimeField(
        'Prazo Pagamento Frete Internacional',
        null=True,
        blank=True,
        help_text='Data limite para os compradores pagarem o frete internacional desta caixa.'
    )
    prazo_taxa = models.DateTimeField(
        'Prazo Pagamento Taxa Aduaneira',
        null=True,
        blank=True,
        help_text='Data limite para os compradores pagarem a taxa aduaneira desta caixa.'
    )
    observacoes = models.TextField('Anotações Internas', blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Caixa (Remessa Internacional)'
        verbose_name_plural = 'Caixas (Remessas Internacionais)'
        ordering = ['-created_at']

    def __str__(self):
        flag = '🇰🇷' if self.origem == 'KR' else ('🇯🇵' if self.origem == 'JP' else '📦')
        return f"{flag} {self.nome} [{self.get_status_display()}]"

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        from decimal import Decimal
        if self.frete_inter_total is not None and self.frete_inter_total > Decimal('9999999999.99'):
            raise ValidationError({'frete_inter_total': 'Valor do frete excede o limite permitido (máximo R$ 9.999.999.999,99).'})
        if self.taxa_aduaneira_total is not None and self.taxa_aduaneira_total > Decimal('9999999999.99'):
            raise ValidationError({'taxa_aduaneira_total': 'Valor da taxa excede o limite permitido (máximo R$ 9.999.999.999,99).'})

    def save(self, *args, **kwargs):
        self.clean()
        if not self.slug:
            base_slug = slugify(self.nome)
            slug = base_slug
            counter = 1
            while Caixa.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def tracking_url(self) -> str:
        """Gera link direto de rastreamento para o código."""
        if not self.codigo_rastreio:
            return ""
        code = self.codigo_rastreio.strip().upper()
        if re.match(r'^[A-Z]{2}\d{9}[A-Z]{2}$', code):
            return f"https://rastreamento.correios.com.br/app/index.php?codigo={code}"
        return f"https://www.google.com/search?q=rastreio+{code}"

    @property
    def total_cegs_count(self) -> int:
        return self.cegs.count()

    @property
    def total_itens_individuais_count(self) -> int:
        return self.itens_individuais.count()

    def atualizar_status(self, novo_status: str, data_evento=None, notify_participants=True) -> int:
        """
        Atualiza o status da Caixa e propaga em cascata para todas as CEGs e Itens Individuais atrelados.
        Notifica os participantes que compraram itens nas CEGs ou pedidos individuais dessa caixa.
        """
        if novo_status not in self.Status.values:
            raise ValueError(f"Status inválido: {novo_status}")

        self.status = novo_status
        hoje = data_evento or timezone.now().date()
        if novo_status == self.Status.ENVIADA and not self.data_envio:
            self.data_envio = hoje
        elif novo_status in (self.Status.ENTREGUE, self.Status.FINALIZADA) and not self.data_recebimento:
            self.data_recebimento = hoje

        self.save(update_fields=['status', 'data_envio', 'data_recebimento', 'updated_at'])

        # Atualiza em cascata todas as CEGs vinculadas a esta Caixa
        updated_cegs_count = self.cegs.update(shipping_status=novo_status)

        # Atualiza em cascata todos os Itens Individuais vinculados a esta Caixa
        status_item_mapping = {
            self.Status.EM_CONSOLIDACAO: 'EM_CONSOLIDACAO',
            self.Status.PRONTA_ENVIO: 'EM_CONSOLIDACAO',
            self.Status.ENVIADA: 'ENVIADO',
            self.Status.NO_BRASIL: 'NO_BRASIL',
            self.Status.TRIBUTADA: 'TRIBUTADO',
            self.Status.LIBERADA: 'LIBERADO',
            self.Status.ENTREGUE: 'NA_GOM',
            self.Status.FINALIZADA: 'FINALIZADO',
        }
        item_status = status_item_mapping.get(novo_status)
        if item_status:
            self.itens_individuais.update(status=item_status)

        # Dispara notificações aos participantes compradores se solicitado
        if notify_participants:
            self._notificar_participantes_atualizacao(novo_status)

        return updated_cegs_count

    def _notificar_participantes_atualizacao(self, novo_status: str):
        try:
            from apps.participants.models import Claim, ParticipantNotification
            claims = Claim.objects.filter(
                slot__set__ceg__caixa=self
            ).exclude(status=Claim.Status.CANCELLED).select_related('participant', 'slot__set__ceg')

            notified_participants = set()
            status_label = dict(self.Status.choices).get(novo_status, novo_status)

            for c in claims:
                p = c.participant
                if p.id in notified_participants:
                    continue
                notified_participants.add(p.id)

                ceg_title = c.slot.set.ceg.title
                title = f"📦 Atualização de Envio: {self.nome} ({status_label})"
                msg = f"A remessa '{self.nome}', contendo sua CEG '{ceg_title}', teve seu status atualizado para: {status_label}."
                if self.codigo_rastreio:
                    msg += f"\nCódigo de Rastreio: {self.codigo_rastreio}"

                ParticipantNotification.objects.create(
                    participant=p,
                    title=title,
                    message=msg,
                    notification_type=ParticipantNotification.NotificationType.CLAIM_UPDATE
                )

            # Notifica também compradores de Itens Individuais desta Caixa
            for item in self.itens_individuais.select_related('comprador'):
                p = item.comprador
                if p.id in notified_participants:
                    continue
                notified_participants.add(p.id)

                title = f"📦 Atualização de Envio: {self.nome} ({status_label})"
                msg = f"A remessa '{self.nome}', contendo seu pedido individual '{item.nome}', teve seu status atualizado para: {status_label}."
                if self.codigo_rastreio:
                    msg += f"\nCódigo de Rastreio: {self.codigo_rastreio}"

                ParticipantNotification.objects.create(
                    participant=p,
                    title=title,
                    message=msg,
                    notification_type=ParticipantNotification.NotificationType.CLAIM_UPDATE
                )
        except Exception:
            pass

    def recalcular_totais_frete_taxa(self):
        """Recalcula e atualiza frete_inter_total e taxa_aduaneira_total somando itens individuais e slots da caixa."""
        from decimal import Decimal
        total_frete = Decimal('0.00')
        total_taxa = Decimal('0.00')

        for item in self.itens_individuais.all():
            if item.frete_inter:
                total_frete += item.frete_inter
            if item.taxa_aduaneira:
                total_taxa += item.taxa_aduaneira

        for ceg in self.cegs.all():
            for s in ItemSlot.objects.filter(set__ceg=ceg):
                if s.frete_inter:
                    total_frete += s.frete_inter
                if s.taxa_aduaneira:
                    total_taxa += s.taxa_aduaneira

        self.frete_inter_total = total_frete if total_frete > 0 else None
        self.taxa_aduaneira_total = total_taxa if total_taxa > 0 else None
        self.save(update_fields=['frete_inter_total', 'taxa_aduaneira_total', 'updated_at'])
        return total_frete, total_taxa

    def propagar_taxas_e_prazos_em_cascata(self):
        """
        Propaga em cascata os prazos (prazo_frete, prazo_taxa) e valores de frete/taxa
        da Caixa para todas as CEGs atreladas (e seus slots) e para todos os Itens Individuais Mercari.
        """
        from decimal import Decimal
        from django.db import transaction

        with transaction.atomic():
            # Mapeia rates configuradas nesta caixa por tipo_item_id
            rates_map = {r.tipo_item_id: r for r in self.item_rates.select_related('tipo_item').all()}
            photocard_tipo = TipoItem.objects.filter(nome__icontains='Photocard').first()
            photocard_rate = rates_map.get(photocard_tipo.id) if photocard_tipo else None

            # 1. Propaga para Itens Individuais (Mercari)
            for item in self.itens_individuais.all():
                update_fields = ['updated_at']
                rate = rates_map.get(item.tipo_item_id) or photocard_rate
                if rate:
                    qtd = item.quantidade or 1
                    item.frete_inter = rate.frete_unitario * qtd
                    item.taxa_aduaneira = rate.taxa_unitaria * qtd
                    update_fields.extend(['frete_inter', 'taxa_aduaneira'])

                if self.prazo_frete is not None:
                    item.prazo_frete_inter = self.prazo_frete
                    update_fields.append('prazo_frete_inter')
                if self.prazo_taxa is not None:
                    item.prazo_taxa_aduaneira = self.prazo_taxa
                    update_fields.append('prazo_taxa_aduaneira')

                item.save(update_fields=list(set(update_fields)))

            # 2. Propaga para CEGs e seus ItemSlots
            for ceg in self.cegs.all():
                ceg_fields = ['updated_at', 'shipping_status']
                ceg.shipping_status = self.status

                if self.prazo_frete is not None:
                    ceg.prazo_pagamento_frete_inter = self.prazo_frete
                    ceg_fields.append('prazo_pagamento_frete_inter')
                if self.prazo_taxa is not None:
                    ceg.prazo_pagamento_taxa_aduaneira = self.prazo_taxa
                    ceg_fields.append('prazo_pagamento_taxa_aduaneira')

                ceg_slots = ItemSlot.objects.filter(set__ceg=ceg).select_related('item_definition__tipo_item')
                slot_fretes = []
                slot_taxas = []

                for slot in ceg_slots:
                    slot_fields = []
                    t_id = slot.item_definition.tipo_item_id
                    rate = rates_map.get(t_id) or photocard_rate

                    if rate:
                        slot.frete_inter_valor = rate.frete_unitario
                        slot.taxa_aduaneira_valor = rate.taxa_unitaria
                        slot_fields.extend(['frete_inter_valor', 'taxa_aduaneira_valor'])

                    if self.prazo_frete is not None:
                        slot.prazo_frete_inter = self.prazo_frete
                        slot_fields.append('prazo_frete_inter')
                    if self.prazo_taxa is not None:
                        slot.prazo_taxa_aduaneira = self.prazo_taxa
                        slot_fields.append('prazo_taxa_aduaneira')

                    if slot_fields:
                        slot.save(update_fields=list(set(slot_fields)))

                    if slot.frete_inter is not None:
                        slot_fretes.append(slot.frete_inter)
                    if slot.taxa_aduaneira is not None:
                        slot_taxas.append(slot.taxa_aduaneira)

                if slot_fretes:
                    unique_fretes = {f for f in slot_fretes if f > 0}
                    if unique_fretes:
                        ceg.frete_inter = min(unique_fretes)
                    elif slot_fretes:
                        ceg.frete_inter = Decimal('0.00')
                    ceg_fields.append('frete_inter')

                if slot_taxas:
                    unique_taxas = {t for t in slot_taxas if t > 0}
                    if unique_taxas:
                        ceg.taxa_aduaneira = min(unique_taxas)
                    elif slot_taxas:
                        ceg.taxa_aduaneira = Decimal('0.00')
                    ceg_fields.append('taxa_aduaneira')

                ceg.save(update_fields=list(set(ceg_fields)))

            # 3. Recalcula totais gerais da Caixa
            self.recalcular_totais_frete_taxa()


class CaixaItemRate(models.Model):
    """Valores unitários e prazos de frete internacional e taxa aduaneira por tipo de item em uma Caixa."""
    caixa = models.ForeignKey(
        Caixa,
        on_delete=models.CASCADE,
        related_name='item_rates',
        verbose_name='Caixa / Remessa'
    )
    tipo_item = models.ForeignKey(
        TipoItem,
        on_delete=models.CASCADE,
        related_name='caixa_rates',
        verbose_name='Tipo de Item'
    )
    frete_unitario = models.DecimalField(
        'Frete Internacional Unitário (R$)',
        max_digits=10,
        decimal_places=2,
        default=0.00
    )
    taxa_unitaria = models.DecimalField(
        'Taxa Aduaneira Unitária (R$)',
        max_digits=10,
        decimal_places=2,
        default=0.00
    )
    prazo_frete = models.DateTimeField('Prazo Pagamento Frete Inter', null=True, blank=True)
    prazo_taxa = models.DateTimeField('Prazo Pagamento Taxa Aduaneira', null=True, blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Taxa por Tipo de Item na Caixa'
        verbose_name_plural = 'Taxas por Tipos de Itens na Caixa'
        unique_together = ('caixa', 'tipo_item')
        ordering = ['tipo_item__nome']

    def __str__(self):
        return f"{self.caixa.nome} - {self.tipo_item.nome}: Frete R$ {self.frete_unitario:.2f} | Taxa R$ {self.taxa_unitaria:.2f}"


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
    caixa = models.ForeignKey(
        Caixa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cegs',
        verbose_name='Caixa / Remessa'
    )
    shipping_status = models.CharField(
        'Status de Envio',
        max_length=30,
        choices=Caixa.Status.choices,
        default=Caixa.Status.EM_CONSOLIDACAO,
        db_index=True,
        help_text='Sincronizado automaticamente com a Caixa vinculada.'
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

    def clean_title(self, group_name: str = None) -> str:
        """
        Retorna o título da CEG sem o prefixo redundante do nome do grupo,
        já que os cards da interface já exibem a badge/tag com o nome do grupo.
        Ex: 'LE SSERAFIM — WEVERSE GLOBAL 1.0 (Mini camera weverse global) (PF-32)'
            -> 'WEVERSE GLOBAL 1.0 (Mini camera weverse global) (PF-32)'
            'LE SSERAFIM — SET SAKURA PUREFLOW' -> 'SET SAKURA PUREFLOW'
            'Le sserafim - weverse global' -> 'weverse global'
            'TWICE: Makestar Special' -> 'Makestar Special'
        """
        if not self.title:
            return ""
        grp = group_name
        if not grp:
            try:
                if hasattr(self, 'era') and self.era and hasattr(self.era, 'group') and self.era.group:
                    grp = self.era.group.name
            except Exception:
                pass

        if grp:
            grp_escaped = re.escape(grp.strip())
            pattern = rf'^(?:ceg\s+)?{grp_escaped}\s*(?:[—–\-:]\s*|\s+)'
            cleaned = re.sub(pattern, '', self.title, flags=re.IGNORECASE).strip()
            if cleaned:
                return cleaned
        return self.title

    @property
    def display_title(self) -> str:
        """Título amigável para exibição em cards onde a tag do grupo já está presente."""
        return self.clean_title()

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while CEG.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        if self.caixa and ('update_fields' not in kwargs or 'shipping_status' in (kwargs.get('update_fields') or [])):
            self.shipping_status = self.caixa.status
        super().save(*args, **kwargs)

    @property
    def tracking_code(self) -> str:
        return self.caixa.codigo_rastreio if self.caixa else ""

    @property
    def tracking_url(self) -> str:
        return self.caixa.tracking_url if self.caixa else ""

    def sync_shipping_status(self):
        if self.caixa:
            self.shipping_status = self.caixa.status
            self.save(update_fields=['shipping_status'])

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
                has_available = ItemSlot.objects.filter(
                    set__ceg=self,
                    set__is_active=True,
                    status=ItemSlot.Status.AVAILABLE
                ).exists()
                if not has_available:
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

    @property
    def frete_rates_summary(self):
        """Retorna resumo das taxas de frete internacional configuradas para os slots desta CEG."""
        if not hasattr(self, '_frete_rates_summary'):
            slots = ItemSlot.objects.filter(set__ceg=self, set__is_active=True).select_related('item_definition')
            fretes = [s.frete_inter for s in slots if s.frete_inter is not None and s.frete_inter > 0]
            if fretes:
                min_f = min(fretes)
                max_f = max(fretes)
                has_multiple = (min_f != max_f)
            elif self.frete_inter is not None and self.frete_inter > 0:
                min_f = self.frete_inter
                max_f = self.frete_inter
                has_multiple = False
            else:
                min_f = None
                max_f = None
                has_multiple = False
            self._frete_rates_summary = {
                'min': min_f,
                'max': max_f,
                'has_multiple': has_multiple,
            }
        return self._frete_rates_summary

    @property
    def has_multiple_frete_rates(self) -> bool:
        return self.frete_rates_summary['has_multiple']

    @property
    def min_frete_inter(self):
        return self.frete_rates_summary['min']

    @property
    def max_frete_inter(self):
        return self.frete_rates_summary['max']

    @property
    def taxa_rates_summary(self):
        """Retorna resumo das taxas alfandegárias configuradas para os slots desta CEG."""
        if not hasattr(self, '_taxa_rates_summary'):
            slots = ItemSlot.objects.filter(set__ceg=self, set__is_active=True).select_related('item_definition')
            taxas = [s.taxa_aduaneira for s in slots if s.taxa_aduaneira is not None and s.taxa_aduaneira > 0]
            if taxas:
                min_t = min(taxas)
                max_t = max(taxas)
                has_multiple = (min_t != max_t)
            elif self.taxa_aduaneira is not None and self.taxa_aduaneira > 0:
                min_t = self.taxa_aduaneira
                max_t = self.taxa_aduaneira
                has_multiple = False
            else:
                min_t = None
                max_t = None
                has_multiple = False
            self._taxa_rates_summary = {
                'min': min_t,
                'max': max_t,
                'has_multiple': has_multiple,
            }
        return self._taxa_rates_summary

    @property
    def has_multiple_taxa_rates(self) -> bool:
        return self.taxa_rates_summary['has_multiple']

    @property
    def min_taxa_aduaneira(self):
        return self.taxa_rates_summary['min']

    @property
    def max_taxa_aduaneira(self):
        return self.taxa_rates_summary['max']



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
    tipo_item = models.ForeignKey(
        TipoItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='item_definitions',
        verbose_name='Tipo de Item (Dinâmico)'
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

    @classmethod
    def resolve_item_type_from_tipo_item(cls, tipo_item):
        """Mapeia um TipoItem da pool compartilhada para a categoria base item_type."""
        if not tipo_item or not tipo_item.nome:
            return cls.ItemType.OTHER
        nome = tipo_item.nome.lower()
        if 'pob' in nome or 'pre-order' in nome:
            return cls.ItemType.POB
        elif 'álbum' in nome or 'album' in nome:
            return cls.ItemType.ALBUM
        elif 'inclus' in nome:
            return cls.ItemType.INCLUSION
        elif 'photocard' in nome or 'card' in nome:
            return cls.ItemType.PHOTOCARD
        else:
            return cls.ItemType.OTHER

    def save(self, *args, **kwargs):
        if self.tipo_item:
            resolved = self.resolve_item_type_from_tipo_item(self.tipo_item)
            if resolved != self.ItemType.OTHER or self.item_type not in self.ItemType.values:
                self.item_type = resolved
        super().save(*args, **kwargs)

    @property
    def tipo_item_nome(self) -> str:
        if self.tipo_item:
            return self.tipo_item.nome
        return self.get_item_type_display()



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
        if hasattr(self, '_slots_count'):
            return self._slots_count
        return self.slots.count()

    @slots_count.setter
    def slots_count(self, value: int):
        self._slots_count = value

    @property
    def reserved_count(self) -> int:
        if hasattr(self, '_reserved_count'):
            return self._reserved_count
        return self.slots.filter(status__in=[ItemSlot.Status.RESERVED, ItemSlot.Status.PAID]).count()

    @reserved_count.setter
    def reserved_count(self, value: int):
        self._reserved_count = value

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


class PacoteNacional(models.Model):
    class Status(models.TextChoices):
        EM_PREPARACAO = 'EM_PREPARACAO', 'Em Preparação / Embalando'
        ENVIADO = 'ENVIADO', 'Enviado Nacionalmente'
        ENTREGUE = 'ENTREGUE', 'Entregue'

    identificador = models.CharField(
        'Identificador do Pacote',
        max_length=50,
        blank=True,
        unique=True,
        db_index=True,
        help_text='Ex: PAC-2026-0001 (gerado automaticamente se vazio)'
    )
    participant = models.ForeignKey(
        'participants.Participant',
        on_delete=models.CASCADE,
        related_name='pacotes_nacionais',
        verbose_name='Destinatário (Joiner)'
    )
    status = models.CharField(
        'Status do Pacote',
        max_length=20,
        choices=Status.choices,
        default=Status.EM_PREPARACAO,
        db_index=True
    )
    codigo_rastreio = models.CharField(
        'Código de Rastreio',
        max_length=100,
        blank=True,
        help_text='Ex: NL123456789BR, QD123456789BR'
    )
    transportadora = models.CharField(
        'Transportadora / Modalidade',
        max_length=100,
        default='Correios',
        blank=True,
        help_text='Ex: Mini Envios, Carta Registrada, PAC, Sedex, Jadlog'
    )
    valor_frete_nacional = models.DecimalField(
        'Valor do Frete Nacional (R$)',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    is_frete_pago = models.BooleanField(
        'Frete Nacional Pago?',
        default=False,
        help_text='Indica se o participante já pagou o frete nacional deste pacote'
    )
    data_envio = models.DateTimeField('Data do Envio', null=True, blank=True)
    data_entrega = models.DateTimeField('Data da Entrega', null=True, blank=True)
    observacoes = models.TextField('Anotações do Organizador / Endereço', blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Pacote de Envio Nacional'
        verbose_name_plural = 'Pacotes de Envios Nacionais'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.identificador or f'Pacote #{self.id}'} - {self.participant.display_name} [{self.get_status_display()}]"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.identificador:
            self.identificador = f"PAC-{timezone.now().year}-{self.pk:04d}"
            super().save(update_fields=['identificador'])

    @property
    def tracking_url(self) -> str:
        if not self.codigo_rastreio:
            return ""
        code = self.codigo_rastreio.strip().upper()
        return f"https://rastreamento.correios.com.br/app/index.php?codigo={code}"

    @property
    def total_itens(self) -> int:
        return self.slots.count() + self.itens_individuais.count()

    def marcar_como_enviado(self, codigo_rastreio: str = '', transportadora: str = ''):
        """Marca o pacote como enviado, registra data_envio e envia notificação ao participante."""
        from apps.participants.models import ParticipantNotification
        self.status = self.Status.ENVIADO
        self.data_envio = timezone.now()
        if codigo_rastreio:
            self.codigo_rastreio = codigo_rastreio.strip().upper()
        if transportadora:
            self.transportadora = transportadora.strip()
        self.save(update_fields=['status', 'data_envio', 'codigo_rastreio', 'transportadora', 'updated_at'])

        # Notificação ao participante
        total = self.total_itens
        rastreio_txt = f" Código de rastreio: {self.codigo_rastreio}." if self.codigo_rastreio else ""
        ParticipantNotification.objects.create(
            participant=self.participant,
            title=f"📦 Seu pacote ({self.identificador}) foi enviado nacionalmente!",
            message=f"Olá, {self.participant.display_name}! Seu pacote com {total} item(ns) foi despachado via {self.transportadora}.{rastreio_txt} Acompanhe pelo seu painel!",
            notification_type=ParticipantNotification.NotificationType.ENVIO_NACIONAL
        )


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
    frete_inter_valor = models.DecimalField(
        'Frete Inter Específico (R$)',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Valor do frete rateado especificamente para este slot pela Caixa.'
    )
    taxa_aduaneira_valor = models.DecimalField(
        'Taxa Aduaneira Específica (R$)',
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Valor da taxa aduaneira rateada especificamente para este slot pela Caixa.'
    )
    prazo_frete_inter = models.DateTimeField('Prazo Pagamento Frete Inter', null=True, blank=True)
    prazo_taxa_aduaneira = models.DateTimeField('Prazo Pagamento Taxa Aduaneira', null=True, blank=True)
    pacote_nacional = models.ForeignKey(
        PacoteNacional,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='slots',
        verbose_name='Pacote Nacional'
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
        """Retorna o frete internacional definido especificamente para o slot ou da CEG."""
        if self.frete_inter_valor is not None:
            return self.frete_inter_valor
        return self.set.ceg.frete_inter

    @property
    def taxa_aduaneira(self):
        """Retorna a taxa aduaneira definida especificamente para o slot ou da CEG."""
        if self.taxa_aduaneira_valor is not None:
            return self.taxa_aduaneira_valor
        return self.set.ceg.taxa_aduaneira

    @property
    def prazo_frete_inter_efetivo(self):
        if self.prazo_frete_inter is not None:
            return self.prazo_frete_inter
        return self.set.ceg.prazo_pagamento_frete_inter

    @property
    def prazo_taxa_aduaneira_efetivo(self):
        if self.prazo_taxa_aduaneira is not None:
            return self.prazo_taxa_aduaneira
        return self.set.ceg.prazo_pagamento_taxa_aduaneira


class ClaimAttemptLog(models.Model):
    class Result(models.TextChoices):
        SUCCESS = 'SUCCESS', '1º Lugar (Reserva Garantida)'
        AUTO_FALLBACK = 'AUTO_FALLBACK', 'Venceu via Auto-Fallback (Próximo Set)'
        WAITING_LIST = 'WAITING_LIST', 'Adicionado à Lista de Espera'
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


class ItemWaitingList(models.Model):
    class Status(models.TextChoices):
        WAITING = 'WAITING', 'Aguardando Vaga'
        PROMOTED = 'PROMOTED', 'Promovido para Reserva'
        CANCELLED = 'CANCELLED', 'Cancelado / Desistiu'

    item_definition = models.ForeignKey(
        CEGItemDefinition,
        on_delete=models.CASCADE,
        related_name='waiting_list',
        verbose_name='Item'
    )
    participant = models.ForeignKey(
        'participants.Participant',
        on_delete=models.CASCADE,
        related_name='waiting_entries',
        verbose_name='Participante'
    )
    name = models.CharField('Nome do Participante', max_length=150)
    phone = models.CharField('WhatsApp', max_length=30)
    social_handle = models.CharField('@ Rede Social', max_length=100, blank=True)
    position = models.PositiveIntegerField('Posição na Fila', default=1)
    status = models.CharField('Status na Fila', max_length=20, choices=Status.choices, default=Status.WAITING, db_index=True)
    allocated_slot = models.ForeignKey(
        'ItemSlot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='promoted_waiting_entries',
        verbose_name='Slot Alocado'
    )
    notes = models.TextField('Observações', blank=True)
    created_at = models.DateTimeField('Entrou na Fila em', auto_now_add=True)
    promoted_at = models.DateTimeField('Promovido em', null=True, blank=True)

    class Meta:
        verbose_name = 'Entrada na Fila de Espera'
        verbose_name_plural = 'Fila de Espera por Item'
        ordering = ['item_definition', 'position', 'created_at']

    def __str__(self):
        handle = f" ({self.social_handle})" if self.social_handle else ""
        return f"{self.item_definition.name} - #{self.position}º na Fila: {self.name}{handle} [{self.get_status_display()}]"


class ItemIndividual(models.Model):
    class Status(models.TextChoices):
        COMPRADO = 'COMPRADO', 'Comprado'
        WAREHOUSE = 'WAREHOUSE', 'Na Warehouse (Armazém)'
        EM_CONSOLIDACAO = 'EM_CONSOLIDACAO', 'Em Consolidação'
        ENVIADO = 'ENVIADO', 'Enviado / Em Trânsito'
        NO_BRASIL = 'NO_BRASIL', 'No Brasil / Fiscalização'
        TRIBUTADO = 'TRIBUTADO', 'Tributado'
        LIBERADO = 'LIBERADO', 'Liberado pela Alfândega'
        NA_GOM = 'NA_GOM', 'Chegou na GOM (Organizador)'
        FINALIZADO = 'FINALIZADO', 'Entregue / Finalizado'

    caixa = models.ForeignKey(
        Caixa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='itens_individuais',
        verbose_name='Caixa / Remessa'
    )
    comprador = models.ForeignKey(
        'participants.Participant',
        on_delete=models.PROTECT,
        related_name='itens_individuais',
        verbose_name='Comprador'
    )
    tipo_item = models.ForeignKey(
        TipoItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='itens_individuais',
        verbose_name='Tipo de Item'
    )
    nome = models.CharField('Nome / Descrição do Item', max_length=255)
    link_pedido = models.URLField('Link do Pedido (Mercari, etc.)', max_length=600, blank=True)
    quantidade = models.PositiveIntegerField('Quantidade', default=1)
    foto_arquivo = models.FileField('Arquivo de Foto', upload_to='itens_individuais/%Y/%m/', blank=True, null=True)
    foto_url = models.CharField('URL Externa da Foto', max_length=600, blank=True)
    status = models.CharField(
        'Status do Item',
        max_length=30,
        choices=Status.choices,
        default=Status.COMPRADO,
        db_index=True
    )
    preco_produto = models.DecimalField('Preço do Produto (R$)', max_digits=10, decimal_places=2, null=True, blank=True, help_text='Preço pago no produto.')
    produto_pago = models.BooleanField('Produto / Item Pago?', default=True)
    frete_inter = models.DecimalField('Frete Internacional (R$)', max_digits=10, decimal_places=2, null=True, blank=True)
    frete_inter_pago = models.BooleanField('Frete Inter Pago?', default=False)
    prazo_frete_inter = models.DateTimeField('Prazo Pagamento Frete Inter', null=True, blank=True)
    taxa_aduaneira = models.DecimalField('Taxa Aduaneira (R$)', max_digits=10, decimal_places=2, null=True, blank=True)
    taxa_aduaneira_paga = models.BooleanField('Taxa Aduaneira Paga?', default=False)
    prazo_taxa_aduaneira = models.DateTimeField('Prazo Pagamento Taxa Aduaneira', null=True, blank=True)
    pacote_nacional = models.ForeignKey(
        PacoteNacional,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='itens_individuais',
        verbose_name='Pacote Nacional'
    )
    observacoes = models.TextField('Anotações Internas', blank=True)
    created_at = models.DateTimeField('Cadastrado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Item Individual (Mercari)'
        verbose_name_plural = 'Itens Individuais (Mercari)'
        ordering = ['-created_at']

    def __str__(self):
        caixa_info = f" [{self.caixa.nome}]" if self.caixa else " [Sem Caixa]"
        return f"{self.nome} (Qtd: {self.quantidade}) - {self.comprador.display_name}{caixa_info}"

    @property
    def image_display_url(self) -> str:
        if self.foto_arquivo:
            return self.foto_arquivo.url
        if self.foto_url:
            return self.foto_url
        return ""

    @property
    def tipo_item_nome(self) -> str:
        if self.tipo_item:
            return self.tipo_item.nome
        return "Item"
