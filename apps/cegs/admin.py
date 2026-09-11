from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import CEG, CEGItemDefinition, CEGSet, ItemSlot, ClaimAttemptLog


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
    list_display = ('title', 'group_name', 'era', 'status_badge', 'opens_at', 'standby_badge', 'slots_progress', 'created_at')
    list_filter = ('status', 'era__group', 'era')
    search_fields = ('title', 'era__name', 'era__group__name')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [CEGItemDefinitionInline, CEGSetInline]
    actions = ['make_open', 'make_closed', 'generate_all_slots_for_ceg']

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
    list_display = ('id', 'set_info', 'item_name', 'price', 'status_badge', 'claimed_by_info', 'claimed_at')
    list_filter = ('status', 'set__ceg', 'set__set_number')
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
            ClaimAttemptLog.Result.LOST_RACE: '#dc3545',
            ClaimAttemptLog.Result.STANDBY_BLOCKED: '#ffc107',
            ClaimAttemptLog.Result.ERROR: '#6c757d',
        }
        text_color = '#000' if obj.result == ClaimAttemptLog.Result.STANDBY_BLOCKED else '#fff'
        color = colors.get(obj.result, '#333')
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color, text_color, obj.get_result_display()
        )
    result_badge.short_description = 'Resultado da Concorrência'
