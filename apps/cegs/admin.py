from django.contrib import admin
from django.utils.html import format_html
from .models import CEG, CEGItemDefinition, CEGSet, ItemSlot, ClaimAttemptLog, Caixa, ItemIndividual, TipoItem, CaixaItemRate, ItemWaitingList, PacoteNacional


@admin.register(TipoItem)
class TipoItemAdmin(admin.ModelAdmin):
    list_display = ('nome', 'descricao', 'created_at')
    search_fields = ('nome', 'descricao')


class CaixaItemRateInline(admin.TabularInline):
    model = CaixaItemRate
    extra = 0
    fields = ('tipo_item', 'frete_unitario', 'taxa_unitaria', 'prazo_frete', 'prazo_taxa')


class ItemIndividualInline(admin.TabularInline):
    model = ItemIndividual
    extra = 0
    fields = ('nome', 'tipo_item', 'comprador', 'quantidade', 'status', 'link_pedido', 'frete_inter', 'frete_inter_pago', 'taxa_aduaneira', 'taxa_aduaneira_paga')


@admin.register(Caixa)
class CaixaAdmin(admin.ModelAdmin):
    list_display = ('nome_com_flag', 'origem_badge', 'status_badge', 'cegs_count', 'itens_count', 'codigo_rastreio_link', 'data_envio', 'data_recebimento', 'created_at')
    list_filter = ('status', 'origem')
    search_fields = ('nome', 'codigo_rastreio', 'transportadora', 'observacoes')
    prepopulated_fields = {'slug': ('nome',)}
    inlines = [CaixaItemRateInline, ItemIndividualInline]
    actions = ['marcar_como_enviada', 'marcar_como_no_brasil', 'marcar_como_entregue']
    fieldsets = (
        ('Identificação da Caixa', {
            'fields': ('nome', 'slug', 'origem', 'status')
        }),
        ('Rastreio & Envio', {
            'fields': ('codigo_rastreio', 'transportadora', 'data_envio', 'data_previsao', 'data_recebimento')
        }),
        ('Custos da Remessa (Opcional)', {
            'fields': ('frete_inter_total', 'taxa_aduaneira_total')
        }),
        ('Anotações Internas', {
            'fields': ('observacoes',)
        }),
    )

    def nome_com_flag(self, obj):
        flag = '🇰🇷' if obj.origem == 'KR' else ('🇯🇵' if obj.origem == 'JP' else '📦')
        return f"{flag} {obj.nome}"
    nome_com_flag.short_description = 'Caixa / Remessa'

    def origem_badge(self, obj):
        colors = {'KR': '#0d6efd', 'JP': '#dc3545', 'CN': '#ffc107', 'US': '#198754'}
        color = colors.get(obj.origem, '#6c757d')
        text_color = '#000' if obj.origem == 'CN' else '#fff'
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color, text_color, obj.get_origem_display()
        )
    origem_badge.short_description = 'Origem'

    def status_badge(self, obj):
        colors = {
            Caixa.Status.EM_CONSOLIDACAO: '#6c757d',
            Caixa.Status.PRONTA_ENVIO: '#0dcaf0',
            Caixa.Status.ENVIADA: '#0d6efd',
            Caixa.Status.NO_BRASIL: '#ffc107',
            Caixa.Status.TRIBUTADA: '#fd7e14',
            Caixa.Status.LIBERADA: '#20c997',
            Caixa.Status.ENTREGUE: '#198754',
            Caixa.Status.FINALIZADA: '#212529',
        }
        color = colors.get(obj.status, '#333')
        text_color = '#000' if obj.status in [Caixa.Status.NO_BRASIL, Caixa.Status.PRONTA_ENVIO] else '#fff'
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color, text_color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def cegs_count(self, obj):
        count = obj.cegs.count()
        return format_html('<b>{}</b> CEG(s)', count)
    cegs_count.short_description = 'CEGs Atreladas'

    def itens_count(self, obj):
        count = obj.itens_individuais.count()
        return format_html('<b>{}</b> Item(ns)', count)
    itens_count.short_description = 'Itens Individuais'

    def codigo_rastreio_link(self, obj):
        if obj.codigo_rastreio:
            url = obj.tracking_url
            if url:
                return format_html('<a href="{}" target="_blank" style="font-weight: bold; color: #0d6efd;">🔗 {}</a>', url, obj.codigo_rastreio)
            return obj.codigo_rastreio
        return '-'
    codigo_rastreio_link.short_description = 'Rastreio'

    @admin.action(description="Marcar selecionadas como Enviadas (Em Trânsito ✈️)")
    def marcar_como_enviada(self, request, queryset):
        total_cegs = 0
        for caixa in queryset:
            total_cegs += caixa.atualizar_status(Caixa.Status.ENVIADA)
        self.message_user(request, f"{queryset.count()} caixa(s) e {total_cegs} CEG(s) atualizadas para Enviadas!")

    @admin.action(description="Marcar selecionadas como Chegou ao Brasil (Alfândega 🇧🇷)")
    def marcar_como_no_brasil(self, request, queryset):
        total_cegs = 0
        for caixa in queryset:
            total_cegs += caixa.atualizar_status(Caixa.Status.NO_BRASIL)
        self.message_user(request, f"{queryset.count()} caixa(s) e {total_cegs} CEG(s) atualizadas para No Brasil!")

    @admin.action(description="Marcar selecionadas como Entregues ao Organizador (✅)")
    def marcar_como_entregue(self, request, queryset):
        total_cegs = 0
        for caixa in queryset:
            total_cegs += caixa.atualizar_status(Caixa.Status.ENTREGUE)
        self.message_user(request, f"{queryset.count()} caixa(s) e {total_cegs} CEG(s) atualizadas para Entregues!")


@admin.register(ItemIndividual)
class ItemIndividualAdmin(admin.ModelAdmin):
    list_display = ('foto_thumbnail', 'nome', 'comprador', 'caixa_link', 'quantidade', 'status_badge', 'preco_produto', 'produto_pago', 'frete_inter', 'frete_inter_pago', 'taxa_aduaneira', 'taxa_aduaneira_paga', 'link_pedido_link', 'created_at')
    list_filter = ('status', 'produto_pago', 'frete_inter_pago', 'taxa_aduaneira_paga', 'caixa')
    search_fields = ('nome', 'comprador__name', 'comprador__whatsapp', 'comprador__username', 'link_pedido', 'observacoes')
    actions = ['marcar_frete_pago', 'marcar_taxa_paga']

    def foto_thumbnail(self, obj):
        img_url = obj.image_display_url
        if img_url:
            return format_html('<img src="{}" style="width: 40px; height: 40px; object-fit: cover; border-radius: 6px; border: 1px solid #ddd;" />', img_url)
        return format_html('<span style="color: #aaa; font-size: 11px;">Sem foto</span>')
    foto_thumbnail.short_description = 'Foto'

    def caixa_link(self, obj):
        if obj.caixa:
            flag = '🇰🇷' if obj.caixa.origem == 'KR' else ('🇯🇵' if obj.caixa.origem == 'JP' else '📦')
            return format_html('{} <a href="/admin/cegs/caixa/{}/change/">{}</a>', flag, obj.caixa.id, obj.caixa.nome)
        return format_html('<span style="color: #aaa;">Sem Caixa</span>')
    caixa_link.short_description = 'Caixa'

    def link_pedido_link(self, obj):
        if obj.link_pedido:
            return format_html('<a href="{}" target="_blank" style="font-weight: bold; color: #dc3545;">🔗 Pedido</a>', obj.link_pedido)
        return '-'
    link_pedido_link.short_description = 'Link Pedido'

    def status_badge(self, obj):
        colors = {
            ItemIndividual.Status.COMPRADO: '#6c757d',
            ItemIndividual.Status.WAREHOUSE: '#0dcaf0',
            ItemIndividual.Status.EM_CONSOLIDACAO: '#0d6efd',
            ItemIndividual.Status.ENVIADO: '#6610f2',
            ItemIndividual.Status.NO_BRASIL: '#ffc107',
            ItemIndividual.Status.TRIBUTADO: '#fd7e14',
            ItemIndividual.Status.LIBERADO: '#20c997',
            ItemIndividual.Status.NA_GOM: '#198754',
            ItemIndividual.Status.FINALIZADO: '#212529',
        }
        color = colors.get(obj.status, '#333')
        text_color = '#000' if obj.status in [ItemIndividual.Status.NO_BRASIL, ItemIndividual.Status.WAREHOUSE] else '#fff'
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color, text_color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    @admin.action(description="Marcar Frete Internacional como Pago")
    def marcar_frete_pago(self, request, queryset):
        count = queryset.update(frete_inter_pago=True)
        self.message_user(request, f"{count} item(ns) marcado(s) com Frete Internacional Pago!")

    @admin.action(description="Marcar Taxa Aduaneira como Paga")
    def marcar_taxa_paga(self, request, queryset):
        count = queryset.update(taxa_aduaneira_paga=True)
        self.message_user(request, f"{count} item(ns) marcado(s) com Taxa Aduaneira Paga!")



class ClaimAttemptLogInline(admin.TabularInline):
    model = ClaimAttemptLog
    extra = 0
    readonly_fields = ('attempt_number', 'participant_name', 'phone', 'social_handle', 'result', 'details', 'created_at')
    can_delete = False
    ordering = ('attempt_number',)


class CEGItemDefinitionInline(admin.TabularInline):
    model = CEGItemDefinition
    extra = 1
    fields = ('name', 'member_name', 'item_type', 'default_price', 'order_index')


class CEGSetInline(admin.TabularInline):
    model = CEGSet
    extra = 1
    fields = ('set_number', 'is_active', 'notes')


class ItemSlotInline(admin.TabularInline):
    model = ItemSlot
    extra = 0
    readonly_fields = ('item_definition', 'price', 'status', 'claimed_by', 'claimed_at')
    can_delete = False


@admin.register(CEG)
class CEGAdmin(admin.ModelAdmin):
    list_display = ('title', 'group_name', 'era', 'caixa_badge', 'shipping_status_badge', 'status_badge', 'prazo_pagamento_item', 'frete_inter', 'taxa_aduaneira', 'standby_badge', 'slots_progress', 'created_at')
    list_filter = ('status', 'shipping_status', 'caixa__origem', 'caixa', 'era__group', 'era')
    search_fields = ('title', 'era__name', 'era__group__name')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [CEGItemDefinitionInline, CEGSetInline]
    actions = ['make_open', 'make_closed', 'generate_all_slots_for_ceg']
    fieldsets = (
        ('Informações Principais', {
            'fields': ('title', 'slug', 'era', 'status', 'description', 'banner_url')
        }),
        ('Remessa & Envio', {
            'fields': ('caixa', 'shipping_status'),
            'description': 'Vincule a CEG a uma Caixa internacional (KR/JP) para sincronização automática de envio.'
        }),
        ('Horários & Abertura', {
            'fields': ('opens_at', 'closes_at')
        }),
        ('Prazos & Taxas de Pagamento', {
            'fields': (
                'prazo_pagamento_item',
                'frete_inter',
                'prazo_pagamento_frete_inter',
                'taxa_aduaneira',
                'prazo_pagamento_taxa_aduaneira',
            ),
            'description': 'Configure os prazos de pagamento e os valores de frete internacional e taxa aduaneira.'
        }),
        ('Instruções Pix', {
            'fields': ('pix_key', 'pix_instructions')
        }),
    )

    def caixa_badge(self, obj):
        if obj.caixa:
            flag = '🇰🇷' if obj.caixa.origem == 'KR' else ('🇯🇵' if obj.caixa.origem == 'JP' else '📦')
            return format_html(
                '<span style="background-color: #e9ecef; color: #212529; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 11px;">{} {}</span>',
                flag, obj.caixa.nome
            )
        return format_html('<span style="color: #adb5bd; font-size: 11px;">Sem caixa</span>')
    caixa_badge.short_description = 'Caixa'

    def shipping_status_badge(self, obj):
        colors = {
            Caixa.Status.EM_CONSOLIDACAO: '#6c757d',
            Caixa.Status.PRONTA_ENVIO: '#0dcaf0',
            Caixa.Status.ENVIADA: '#0d6efd',
            Caixa.Status.NO_BRASIL: '#ffc107',
            Caixa.Status.TRIBUTADA: '#fd7e14',
            Caixa.Status.LIBERADA: '#20c997',
            Caixa.Status.ENTREGUE: '#198754',
            Caixa.Status.FINALIZADA: '#212529',
        }
        color = colors.get(obj.shipping_status, '#6c757d')
        text_color = '#000' if obj.shipping_status in [Caixa.Status.NO_BRASIL, Caixa.Status.PRONTA_ENVIO] else '#fff'
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px;">{}</span>',
            color, text_color, obj.get_shipping_status_display()
        )
    shipping_status_badge.short_description = 'Status Envio'

    def group_name(self, obj):
        return obj.era.group.name
    group_name.short_description = 'Grupo'

    def status_badge(self, obj):
        colors = {
            CEG.Status.DRAFT: '#6c757d',
            CEG.Status.SCHEDULED: '#0d6efd',
            CEG.Status.OPEN: '#198754',
            CEG.Status.CLOSED: '#dc3545',
            CEG.Status.COMPLETED: '#6610f2',
            CEG.Status.CANCELLED: '#343a40',
        }
        color = colors.get(obj.status, '#333')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def standby_badge(self, obj):
        if obj.is_standby:
            seconds = obj.countdown_seconds
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            return format_html(
                '<span style="background-color: #ffc107; color: #000; padding: 2px 6px; border-radius: 4px; font-weight: bold;">⏳ Standby (~{}h {}m)</span>',
                hours, mins
            )
        return "Ativa / Aberta" if obj.is_open_for_claims else "-"
    standby_badge.short_description = 'Modo Standby'

    def slots_progress(self, obj):
        total = obj.total_slots_count
        reserved = obj.reserved_slots_count
        pct = obj.progress_percentage
        return format_html(
            '<div style="min-width: 100px;">'
            '<div style="background: #e9ecef; border-radius: 4px; overflow: hidden; height: 14px;">'
            '<div style="background: #198754; width: {}%; height: 100%;"></div>'
            '</div>'
            '<span style="font-size: 11px;">{}/{} ({}%)</span>'
            '</div>',
            pct, reserved, total, pct
        )
    slots_progress.short_description = 'Preenchimento de Slots'

    @admin.action(description='Marcar selecionadas como Abertas (OPEN)')
    def make_open(self, request, queryset):
        queryset.update(status=CEG.Status.OPEN)
        self.message_user(request, "CEGs selecionadas marcadas como Abertas.")

    @admin.action(description='Marcar selecionadas como Encerradas (CLOSED)')
    def make_closed(self, request, queryset):
        queryset.update(status=CEG.Status.CLOSED)
        self.message_user(request, "CEGs selecionadas marcadas como Encerradas.")

    @admin.action(description='Gerar slots para todos os Sets ativos desta CEG')
    def generate_all_slots_for_ceg(self, request, queryset):
        total_created = 0
        for ceg in queryset:
            for s in ceg.sets.filter(is_active=True):
                created = s.generate_slots()
                total_created += len(created)
        self.message_user(request, f"{total_created} novos slots de itens foram gerados com sucesso!")


@admin.register(CEGSet)
class CEGSetAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'ceg', 'set_number', 'is_active', 'slots_count', 'reserved_count', 'full_badge')
    list_filter = ('is_active', 'ceg__era__group', 'ceg')
    search_fields = ('ceg__title', 'notes')
    inlines = [ItemSlotInline]
    actions = ['generate_all_slots', 'activate_sets', 'deactivate_sets']

    def full_badge(self, obj):
        if obj.is_full:
            return format_html('<span style="color: green; font-weight: bold;">✔ 100% Fechado</span>')
        return format_html('<span style="color: #6c757d;">Em aberto</span>')
    full_badge.short_description = 'Status do Set'

    @admin.action(description='Gerar slots físicos a partir das definições da CEG')
    def generate_all_slots(self, request, queryset):
        total_created = 0
        for s in queryset:
            created = s.generate_slots()
            total_created += len(created)
        self.message_user(request, f"{total_created} slots foram criados para os Sets selecionados.")

    @admin.action(description='Ativar sets selecionados')
    def activate_sets(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description='Desativar sets selecionados')
    def deactivate_sets(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(ItemSlot)
class ItemSlotAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'set_info', 'item_name', 'price',
        'is_item_paid', 'is_frete_inter_paid', 'is_taxa_aduaneira_paid', 'is_frete_nacional_paid',
        'status_badge', 'claimed_by_info', 'claimed_at'
    )
    list_editable = ('is_item_paid', 'is_frete_inter_paid', 'is_taxa_aduaneira_paid', 'is_frete_nacional_paid')
    list_filter = ('status', 'is_item_paid', 'is_frete_inter_paid', 'is_taxa_aduaneira_paid', 'set__ceg', 'set__set_number')
    search_fields = ('item_definition__name', 'claimed_by__name', 'claimed_by__username', 'claimed_by__whatsapp', 'claimed_by__social_handle')
    raw_id_fields = ('claimed_by',)
    inlines = [ClaimAttemptLogInline]
    actions = ['mark_as_available', 'mark_as_paid']

    def set_info(self, obj):
        return f"{obj.set.ceg.title} - Set #{obj.set.set_number}"
    set_info.short_description = 'CEG / Set'

    def item_name(self, obj):
        return obj.item_definition.name
    item_name.short_description = 'Item'

    def claimed_by_info(self, obj):
        if obj.claimed_by:
            user = f" [{obj.claimed_by.username}]" if obj.claimed_by.username else ""
            handle = f" ({obj.claimed_by.social_handle})" if obj.claimed_by.social_handle else ""
            return f"{obj.claimed_by.name}{user}{handle}"
        return "-"
    claimed_by_info.short_description = 'Reservado por'

    def status_badge(self, obj):
        colors = {
            ItemSlot.Status.AVAILABLE: '#198754',
            ItemSlot.Status.RESERVED: '#fd7e14',
            ItemSlot.Status.PAID: '#0d6efd',
            ItemSlot.Status.CANCELLED: '#6c757d',
        }
        color = colors.get(obj.status, '#333')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    @admin.action(description='Liberar slots selecionados (tornar DISPONÍVEL)')
    def mark_as_available(self, request, queryset):
        for slot in queryset:
            if hasattr(slot, 'claim'):
                slot.claim.status = 'CANCELLED'
                slot.claim.save()
            slot.status = ItemSlot.Status.AVAILABLE
            slot.claimed_by = None
            slot.claimed_at = None
            slot.save()
        self.message_user(request, f"{queryset.count()} slots foram liberados com sucesso.")

    @admin.action(description='Marcar slots como Pagos')
    def mark_as_paid(self, request, queryset):
        for slot in queryset:
            slot.status = ItemSlot.Status.PAID
            slot.save(update_fields=['status'])
            if hasattr(slot, 'claim'):
                slot.claim.status = 'PAID'
                slot.claim.paid_at = timezone.now()
                slot.claim.save(update_fields=['status', 'paid_at'])
        self.message_user(request, f"{queryset.count()} slots marcados como pagos.")


@admin.register(ClaimAttemptLog)
class ClaimAttemptLogAdmin(admin.ModelAdmin):
    list_display = ('slot', 'attempt_number', 'participant_name', 'phone', 'social_handle', 'result_badge', 'created_at')
    list_filter = ('result', 'created_at')
    search_fields = ('participant_name', 'phone', 'social_handle', 'slot__item_definition__name')
    readonly_fields = ('slot', 'attempt_number', 'participant_name', 'phone', 'social_handle', 'result', 'details', 'created_at')

    def result_badge(self, obj):
        colors = {
            ClaimAttemptLog.Result.SUCCESS: '#198754',
            ClaimAttemptLog.Result.AUTO_FALLBACK: '#0d6efd',
            ClaimAttemptLog.Result.WAITING_LIST: '#fd7e14',
            ClaimAttemptLog.Result.LOST_RACE: '#dc3545',
            ClaimAttemptLog.Result.STANDBY_BLOCKED: '#ffc107',
            ClaimAttemptLog.Result.ERROR: '#6c757d',
        }
        text_color = '#000' if obj.result in (ClaimAttemptLog.Result.STANDBY_BLOCKED, ClaimAttemptLog.Result.WAITING_LIST) else '#fff'
        color = colors.get(obj.result, '#333')
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color, text_color, obj.get_result_display()
        )
    result_badge.short_description = 'Resultado da Concorrência'


@admin.register(ItemWaitingList)
class ItemWaitingListAdmin(admin.ModelAdmin):
    list_display = ('item_definition', 'position', 'name', 'phone', 'social_handle', 'status_badge', 'allocated_slot', 'created_at')
    list_filter = ('status', 'created_at', 'item_definition__ceg')
    search_fields = ('name', 'phone', 'social_handle', 'item_definition__name')
    readonly_fields = ('created_at', 'promoted_at')

    def status_badge(self, obj):
        colors = {
            ItemWaitingList.Status.WAITING: '#ffc107',
            ItemWaitingList.Status.PROMOTED: '#198754',
            ItemWaitingList.Status.CANCELLED: '#6c757d',
        }
        text_color = '#000' if obj.status == ItemWaitingList.Status.WAITING else '#fff'
        color = colors.get(obj.status, '#333')
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color, text_color, obj.get_status_display()
        )
    status_badge.short_description = 'Status na Fila'
 
 
class ItemSlotPacoteInline(admin.TabularInline):
    model = ItemSlot
    extra = 0
    fields = ('item_definition', 'claimed_by', 'status', 'is_item_paid', 'is_frete_inter_paid', 'is_taxa_aduaneira_paid')
    readonly_fields = ('item_definition', 'claimed_by', 'status')
    can_delete = True


class ItemIndividualPacoteInline(admin.TabularInline):
    model = ItemIndividual
    extra = 0
    fields = ('nome', 'comprador', 'status', 'frete_inter_pago', 'taxa_aduaneira_paga')
    readonly_fields = ('nome', 'comprador', 'status')
    can_delete = True


@admin.register(PacoteNacional)
class PacoteNacionalAdmin(admin.ModelAdmin):
    list_display = ('identificador', 'participant', 'status_badge', 'codigo_rastreio_link', 'transportadora', 'total_itens_display', 'valor_frete_nacional', 'is_frete_pago', 'data_envio', 'created_at')
    list_filter = ('status', 'transportadora', 'is_frete_pago')
    search_fields = ('identificador', 'codigo_rastreio', 'participant__name', 'participant__whatsapp', 'participant__social_handle', 'observacoes')
    inlines = [ItemSlotPacoteInline, ItemIndividualPacoteInline]

    def status_badge(self, obj):
        colors = {
            PacoteNacional.Status.EM_PREPARACAO: '#ffc107',
            PacoteNacional.Status.ENVIADO: '#0d6efd',
            PacoteNacional.Status.ENTREGUE: '#198754',
        }
        text_color = '#000' if obj.status == PacoteNacional.Status.EM_PREPARACAO else '#fff'
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color, text_color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def total_itens_display(self, obj):
        return f"{obj.total_itens} item(ns)"
    total_itens_display.short_description = 'Itens'

    def codigo_rastreio_link(self, obj):
        if obj.codigo_rastreio:
            url = obj.tracking_url
            return format_html('<a href="{}" target="_blank" style="font-weight:bold; color:#0d6efd;">{} ↗</a>', url, obj.codigo_rastreio)
        return "-"
    codigo_rastreio_link.short_description = 'Rastreamento'

