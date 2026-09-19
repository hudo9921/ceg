import math
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
        ENTREGUE = 'ENTREGUE', 'Chegou na casa da GOM'
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

    @property
    def display_image_url(self) -> str:
        """
        Retorna a melhor imagem representativa para a CEG:
        1. Banner próprio da CEG (se houver)
        2. Banner da Era vinculada (se houver)
        3. Foto/Logo do Grupo vinculado (se houver)
        """
        if self.banner_url and self.banner_url.strip():
            return self.banner_url.strip()
        if hasattr(self, 'era') and self.era:
            if self.era.banner_url and self.era.banner_url.strip():
                return self.era.banner_url.strip()
            if hasattr(self.era, 'group') and self.era.group and self.era.group.image_url and self.era.group.image_url.strip():
                return self.era.group.image_url.strip()
        return ""

    @property
    def theme_color(self) -> str:
        """
        Retorna a cor temática com a seguinte cascata de prioridades:
        1. Cor da Era vinculada (color_hex)
        2. Cor do Grupo vinculado (color_hex)
        3. Paleta vibrante determinística baseada na Era/Grupo
        4. Fallback padrão (#EC4899)
        """
        try:
            era = getattr(self, 'era', None)
            if era and getattr(era, 'color_hex', None) and era.color_hex.strip():
                return era.color_hex.strip()

            group = getattr(era, 'group', None) if era else getattr(self, 'group', None)
            if group and getattr(group, 'color_hex', None) and group.color_hex.strip():
                return group.color_hex.strip()

            palette = ['#EC4899', '#8B5CF6', '#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#06B6D4', '#84CC16']
            if era and getattr(era, 'name', None):
                return palette[sum(ord(c) for c in era.name) % len(palette)]
            if group and getattr(group, 'name', None):
                return palette[sum(ord(c) for c in group.name) % len(palette)]
        except Exception:
            pass
        return "#EC4899"

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
            return max(0, int(math.ceil(delta.total_seconds())))
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
    sub_category = models.CharField(
        'Subcategoria',
        max_length=50,
        blank=True,
        default='',
        help_text='Subcategoria do Photocard (ex: Regulares, Pob, LD, VCE, Broadcast)'
    )

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
        SOLICITADO = 'SOLICITADO', 'Solicitado pelo Joiner'
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
    endereco_destinatario = models.TextField('Endereço de Destino Informado', blank=True)
    cep_destinatario = models.CharField('CEP de Destino', max_length=15, blank=True)
    observacoes_joiner = models.TextField('Observações / Preferências do Joiner', blank=True)
    solicitado_em = models.DateTimeField('Data da Solicitação pelo Joiner', null=True, blank=True)
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
    entregue_por = models.CharField(
        'Confirmado recebimento por',
        max_length=20,
        default='ADMIN',
        choices=[('ADMIN', 'Administrador'), ('JOINER', 'Joiner / Participante')],
        blank=True
    )
    feedback_rating = models.PositiveSmallIntegerField(
        'Avaliação (1 a 5 estrelas)',
        null=True,
        blank=True,
        help_text='Nota de 1 a 5 dada pelo participante'
    )
    feedback_texto = models.TextField(
        'Feedback / Depoimento do Joiner',
        blank=True,
        help_text='Comentário ou depoimento do joiner após o recebimento'
    )
    feedback_data = models.DateTimeField(
        'Data do Feedback',
        null=True,
        blank=True
    )
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

    def marcar_como_enviado(self, codigo_rastreio: str = '', transportadora: str = '', actor=None):
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

        # Audit Log
        try:
            AuditLog.objects.create(
                event_type=AuditLog.EventType.PACKAGE_SENT,
                actor=actor,
                actor_name=actor.get_full_name() or actor.username if actor else 'Sistema / Admin',
                participant=self.participant,
                participant_name=self.participant.name,
                participant_phone=self.participant.whatsapp,
                pacote_nacional=self,
                action_label=f"Pacote {self.identificador} despachado via {self.transportadora}",
                field_name='status',
                old_value='EM_PREPARACAO',
                new_value='ENVIADO',
                metadata={
                    'pacote_id': self.id,
                    'codigo_rastreio': self.codigo_rastreio,
                    'transportadora': self.transportadora,
                    'total_itens': total,
                }
            )
        except Exception:
            pass

    def marcar_como_entregue(self, by='ADMIN', rating=None, feedback='', actor=None):
        """Marca o pacote como entregue, salva feedback e gera log de auditoria."""
        from apps.participants.models import ParticipantNotification
        self.status = self.Status.ENTREGUE
        if not self.data_entrega:
            self.data_entrega = timezone.now()
        self.entregue_por = by
        fields_to_update = ['status', 'data_entrega', 'entregue_por', 'updated_at']

        if rating:
            try:
                self.feedback_rating = max(1, min(5, int(rating)))
                fields_to_update.append('feedback_rating')
            except (ValueError, TypeError):
                pass

        if feedback:
            self.feedback_texto = feedback.strip()
            self.feedback_data = timezone.now()
            fields_to_update.extend(['feedback_texto', 'feedback_data'])
        elif rating and not self.feedback_data:
            self.feedback_data = timezone.now()
            fields_to_update.append('feedback_data')

        self.save(update_fields=list(set(fields_to_update)))

        if by == 'ADMIN':
            ParticipantNotification.objects.create(
                participant=self.participant,
                title=f"🎉 Seu pacote ({self.identificador}) foi marcado como entregue!",
                message=f"Seu pacote com {self.total_itens} item(ns) foi concluído. Não se esqueça de deixar seu feedback e avaliação no seu painel!",
                notification_type=ParticipantNotification.NotificationType.ENVIO_NACIONAL
            )

        # Audit Log
        try:
            actor_display = actor.get_full_name() or actor.username if actor else (self.participant.display_name if by == 'JOINER' else 'Sistema / Admin')
            AuditLog.objects.create(
                event_type=AuditLog.EventType.PACKAGE_DELIVERED,
                actor=actor,
                actor_name=actor_display,
                participant=self.participant,
                participant_name=self.participant.name,
                participant_phone=self.participant.whatsapp,
                pacote_nacional=self,
                action_label=f"Pacote {self.identificador} marcado como entregue ({'pelo Joiner com feedback' if by == 'JOINER' else 'pelo Administrador'})",
                field_name='status',
                old_value='ENVIADO',
                new_value='ENTREGUE',
                metadata={
                    'pacote_id': self.id,
                    'entregue_por': by,
                    'rating': self.feedback_rating,
                    'feedback': self.feedback_texto,
                }
            )
        except Exception:
            pass


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

    def toggle_payment(self, field_name: str, value=None, actor=None) -> bool:
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

        # Registra auditoria da alteração de pagamento
        try:
            from apps.cegs.audit_service import AuditService
            AuditService.log_payment_change(
                slot=self,
                field_name=attr,
                old_value=current_val,
                new_value=new_val,
                actor=actor,
            )
        except Exception:
            pass

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

    def check_packaging_eligibility(self):
        """
        Verifica se o slot está elegível para ser empacotado pela GOM ou solicitado pelo Joiner.
        Retorna (is_eligible: bool, motivo_bloqueio: str).
        """
        # 1. Já está em pacote ativo?
        if self.pacote_nacional:
            st = self.pacote_nacional.status
            if st in [PacoteNacional.Status.SOLICITADO, PacoteNacional.Status.EM_PREPARACAO, PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE]:
                return False, f"Já no pacote {self.pacote_nacional.identificador} ({self.pacote_nacional.get_status_display()})"

        # 2. Produto pago?
        is_item_paid = self.is_item_paid or self.status == ItemSlot.Status.PAID
        if not is_item_paid:
            return False, "Item pendente de pagamento"

        # 3. Posse física com a GOM no Brasil
        ceg = self.set.ceg
        caixa = ceg.caixa
        if caixa:
            if caixa.status not in [Caixa.Status.ENTREGUE, Caixa.Status.FINALIZADA]:
                return False, f"Caixa em trânsito internacional ({caixa.nome} - {caixa.get_status_display()})"
            frete_val = self.frete_inter or 0
            if frete_val > 0 and not self.is_frete_inter_paid:
                return False, "Frete internacional pendente de pagamento"
            taxa_val = self.taxa_aduaneira or 0
            if taxa_val > 0 and not self.is_taxa_aduaneira_paid:
                return False, "Taxa aduaneira pendente de pagamento"

        return True, ""

    @property
    def pode_empacotar(self) -> bool:
        eligible, _ = self.check_packaging_eligibility()
        return eligible

    @property
    def motivo_bloqueio(self) -> str:
        _, motivo = self.check_packaging_eligibility()
        return motivo


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

    def check_packaging_eligibility(self):
        """
        Verifica se o item individual está elegível para ser empacotado pela GOM ou solicitado pelo Joiner.
        Retorna (is_eligible: bool, motivo_bloqueio: str).
        """
        # 1. Já está em pacote ativo?
        if self.pacote_nacional:
            st = self.pacote_nacional.status
            if st in [PacoteNacional.Status.SOLICITADO, PacoteNacional.Status.EM_PREPARACAO, PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE]:
                return False, f"Já no pacote {self.pacote_nacional.identificador} ({self.pacote_nacional.get_status_display()})"

        # 2. Produto pago?
        if not self.produto_pago:
            return False, "Item pendente de pagamento"

        # 3. Posse física com a GOM no Brasil
        caixa = self.caixa
        if caixa:
            if caixa.status not in [Caixa.Status.ENTREGUE, Caixa.Status.FINALIZADA]:
                return False, f"Caixa em trânsito internacional ({caixa.nome} - {caixa.get_status_display()})"
            frete_val = self.frete_inter or 0
            if frete_val > 0 and not self.frete_inter_pago:
                return False, "Frete internacional pendente de pagamento"
            taxa_val = self.taxa_aduaneira or 0
            if taxa_val > 0 and not self.taxa_aduaneira_paga:
                return False, "Taxa aduaneira pendente de pagamento"

        return True, ""

    @property
    def pode_empacotar(self) -> bool:
        eligible, _ = self.check_packaging_eligibility()
        return eligible

    @property
    def motivo_bloqueio(self) -> str:
        _, motivo = self.check_packaging_eligibility()
        return motivo


class AuditLog(models.Model):
    class EventType(models.TextChoices):
        ACCOUNT_CREATED = 'ACCOUNT_CREATED', 'Cadastro de Participante'
        CLAIM_ATTEMPT = 'CLAIM_ATTEMPT', 'Tentativa de Claim'
        CLAIM_SUCCESS = 'CLAIM_SUCCESS', 'Claim Vencedor (Garantido)'
        CLAIM_CANCELLED = 'CLAIM_CANCELLED', 'Claim Cancelado / Liberado'
        PAYMENT_ITEM = 'PAYMENT_ITEM', 'Pagamento do Item'
        PAYMENT_FRETE_INTER = 'PAYMENT_FRETE_INTER', 'Pagamento de Frete Internacional'
        PAYMENT_TAXA = 'PAYMENT_TAXA', 'Pagamento de Taxa Aduaneira'
        PAYMENT_FRETE_NACIONAL = 'PAYMENT_FRETE_NACIONAL', 'Pagamento de Frete Nacional'
        PACKAGE_REQUESTED = 'PACKAGE_REQUESTED', 'Solicitação de Envio Nacional'
        PACKAGE_SENT = 'PACKAGE_SENT', 'Pacote Despachado / Enviado'
        PACKAGE_DELIVERED = 'PACKAGE_DELIVERED', 'Pacote Entregue / Feedback Registrado'
        SLOT_ASSIGNED = 'SLOT_ASSIGNED', 'Slot Vinculado Manualmente'
        SLOT_RELEASED = 'SLOT_RELEASED', 'Slot Desvinculado Manualmente'
        OTHER = 'OTHER', 'Outra Operação'

    event_type = models.CharField('Tipo de Evento', max_length=40, choices=EventType.choices, db_index=True)
    actor = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name='Usuário Responsável'
    )
    actor_name = models.CharField('Nome do Operador', max_length=150, blank=True)
    participant = models.ForeignKey(
        'participants.Participant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name='Participante'
    )
    participant_name = models.CharField('Nome do Participante', max_length=150, blank=True, db_index=True)
    participant_phone = models.CharField('WhatsApp do Participante', max_length=30, blank=True, db_index=True)
    ceg = models.ForeignKey(
        'cegs.CEG',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name='CEG'
    )
    slot = models.ForeignKey(
        'cegs.ItemSlot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name='Slot do Item'
    )
    item_individual = models.ForeignKey(
        'cegs.ItemIndividual',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name='Item Individual (Mercari)'
    )
    pacote_nacional = models.ForeignKey(
        'cegs.PacoteNacional',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name='Pacote Nacional'
    )
    action_label = models.CharField('Ação / Descrição', max_length=255)
    field_name = models.CharField('Campo Alterado', max_length=100, blank=True)
    old_value = models.CharField('Valor Anterior', max_length=255, blank=True)
    new_value = models.CharField('Novo Valor', max_length=255, blank=True)
    metadata = models.JSONField('Metadados Adicionais', default=dict, blank=True)
    created_at = models.DateTimeField('Data e Hora', default=timezone.now, db_index=True)

    class Meta:
        verbose_name = 'Log de Auditoria'
        verbose_name_plural = 'Logs de Auditoria'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_event_type_display()}] {self.action_label} ({self.created_at.strftime('%d/%m/%Y %H:%M')})"


class ConfiguracaoEnvio(models.Model):
    """
    Configuração singleton de envio nacional gerenciada pela GOM.
    Permite configurar o formulário externo (Google Forms) para coleta de endereços e regras.
    """
    link_formulario_google = models.URLField(
        'Link do Formulário de Envio (Google Forms)',
        max_length=500,
        blank=True,
        help_text='Link do Google Forms onde os joiners preenchem o endereço e preferências de envio nacional.'
    )
    instrucoes_envio = models.TextField(
        'Instruções / Informações de Envio',
        blank=True,
        help_text='Instruções exibidas para os joiners ao solicitar envio nacional na Minha Caixinha.'
    )
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Configuração de Envio Nacional'
        verbose_name_plural = 'Configurações de Envio Nacional'

    def __str__(self):
        return "Configuração de Envio Nacional"

    @classmethod
    def get_solo(cls):
        config, _ = cls.objects.get_or_create(id=1)
        return config


class ItemVitrine(models.Model):
    """
    Item para venda direta na Vitrine de Pronta Entrega da GOM.
    Pode ser cadastrado diretamente pela GOM ou transferido a partir de
    slots não claimados de Caixas internacionais que chegaram na casa da GOM.
    """
    class Status(models.TextChoices):
        DISPONIVEL = 'DISPONIVEL', 'Disponível à Pronta Entrega'
        RESERVADO = 'RESERVADO', 'Reservado'
        VENDIDO = 'VENDIDO', 'Vendido'

    titulo = models.CharField('Título / Nome do Item', max_length=200)
    slug = models.SlugField('Slug', max_length=220, unique=True, blank=True)
    descricao = models.TextField('Descrição / Detalhes', blank=True)
    tipo_item = models.ForeignKey(
        TipoItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='itens_vitrine',
        verbose_name='Tipo de Item'
    )
    group = models.ForeignKey(
        'groups.KpopGroup',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='itens_vitrine',
        verbose_name='Grupo / Solista'
    )
    era = models.ForeignKey(
        'groups.Era',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='itens_vitrine',
        verbose_name='Era / Comeback'
    )
    integrante = models.CharField('Integrante', max_length=100, blank=True)
    preco = models.DecimalField('Preço (R$)', max_digits=10, decimal_places=2)
    quantidade = models.PositiveIntegerField('Quantidade em Estoque', default=1)
    status = models.CharField(
        'Status do Item',
        max_length=20,
        choices=Status.choices,
        default=Status.DISPONIVEL,
        db_index=True
    )
    image_url = models.URLField('URL da Foto / Imagem', max_length=600, blank=True)
    foto_arquivo = models.FileField(
        'Arquivo de Foto',
        upload_to='vitrine/%Y/%m/',
        blank=True,
        null=True
    )
    origem_caixa = models.ForeignKey(
        Caixa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='itens_vitrine',
        verbose_name='Caixa de Origem'
    )
    origem_slot = models.OneToOneField(
        'ItemSlot',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='item_vitrine',
        verbose_name='Slot de Origem da CEG'
    )
    destaque = models.BooleanField('Destaque na Vitrine', default=False)
    views_count = models.PositiveIntegerField('Visualizações', default=0)
    created_at = models.DateTimeField('Cadastrado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Item da Vitrine'
        verbose_name_plural = 'Itens da Vitrine'
        ordering = ['-destaque', '-created_at']

    def __str__(self):
        return f"{self.titulo} - R$ {self.preco:.2f} [{self.get_status_display()}]"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.titulo) or 'item-vitrine'
            slug = base_slug
            counter = 1
            while ItemVitrine.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def display_image_url(self) -> str:
        if self.foto_arquivo:
            try:
                return self.foto_arquivo.url
            except Exception:
                pass
        if self.image_url:
            return self.image_url
        return ""

    @property
    def is_disponivel(self) -> bool:
        return self.status == self.Status.DISPONIVEL and self.quantidade > 0



