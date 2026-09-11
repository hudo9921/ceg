from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
import urllib.parse
from .models import Participant, Claim


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ('name', 'formatted_phone', 'social_handle', 'active_claims_count', 'total_spent', 'created_at')
    search_fields = ('name', 'whatsapp', 'social_handle')
    ordering = ['name']

    def formatted_phone(self, obj):
        return obj.formatted_phone
    formatted_phone.short_description = 'WhatsApp'

    def active_claims_count(self, obj):
        return obj.claims.exclude(status=Claim.Status.CANCELLED).count()
    active_claims_count.short_description = 'Reservas Ativas'

    def total_spent(self, obj):
        paid_claims = obj.claims.filter(status=Claim.Status.PAID)
        total = sum(c.total_price for c in paid_claims)
        return f"R$ {total:.2f}"
    total_spent.short_description = 'Total Pago'


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'slot_info', 'participant_info', 'total_price',
        'status_badge', 'claimed_at', 'paid_at', 'whatsapp_contact_button'
    )
    list_filter = ('status', 'slot__set__ceg', 'slot__set__ceg__era__group')
    search_fields = (
        'participant__name', 'participant__whatsapp', 'participant__social_handle',
        'slot__item_definition__name', 'slot__set__ceg__title'
    )
    readonly_fields = ('claimed_at',)
    actions = ['mark_as_paid', 'cancel_claims']

    def slot_info(self, obj):
        return f"{obj.slot.set.ceg.title} | Set #{obj.slot.set.set_number} - {obj.slot.item_definition.name}"
    slot_info.short_description = 'Item Reservado'

    def participant_info(self, obj):
        p = obj.participant
        handle = f" ({p.social_handle})" if p.social_handle else ""
        return f"{p.name}{handle}"
    participant_info.short_description = 'Participante'

    def status_badge(self, obj):
        colors = {
            Claim.Status.PENDING: '#ffc107',
            Claim.Status.PAID: '#198754',
            Claim.Status.CANCELLED: '#dc3545',
        }
        color = colors.get(obj.status, '#333')
        text_color = '#000' if obj.status == Claim.Status.PENDING else '#fff'
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color, text_color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def whatsapp_contact_button(self, obj):
        phone = obj.participant.whatsapp
        ceg = obj.slot.set.ceg
        msg = (
            f"Olá {obj.participant.name}! Tudo bem?\n"
            f"Passando para falar sobre sua reserva na *{ceg.title}*:\n"
            f"📦 *Item:* {obj.slot.item_definition.name} (Set {obj.slot.set.set_number})\n"
            f"💰 *Valor:* R$ {obj.total_price:.2f}\n"
        )
        if obj.status == Claim.Status.PENDING and ceg.pix_key:
            msg += f"🔑 *Chave Pix:* {ceg.pix_key}\n"
            msg += f"Assim que fizer o Pix, por favor envie o comprovante por aqui!"
        elif obj.status == Claim.Status.PAID:
            msg += f"✅ Pagamento confirmado com sucesso!"

        encoded_msg = urllib.parse.quote(msg)
        wa_url = f"https://wa.me/{phone}?text={encoded_msg}"
        return format_html(
            '<a href="{}" target="_blank" style="background-color: #25D366; color: white; padding: 3px 8px; border-radius: 4px; text-decoration: none; font-size: 11px; font-weight: bold;">💬 Falar no WhatsApp</a>',
            wa_url
        )
    whatsapp_contact_button.short_description = 'Contato WhatsApp'

    @admin.action(description='Confirmar selecionados como PAGOS')
    def mark_as_paid(self, request, queryset):
        for claim in queryset:
            claim.mark_as_paid()
        self.message_user(request, f"{queryset.count()} reservas foram confirmadas como pagas com 1 clique.")

    @admin.action(description='Cancelar reservas selecionadas e liberar slots')
    def cancel_claims(self, request, queryset):
        for claim in queryset:
            claim.cancel()
        self.message_user(request, f"{queryset.count()} reservas foram canceladas e os slots liberados.")
