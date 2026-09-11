from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from .models import WhatsAppOTP


@admin.register(WhatsAppOTP)
class WhatsAppOTPAdmin(admin.ModelAdmin):
    list_display = ('phone', 'code', 'expires_at', 'status_badge', 'attempts', 'created_at')
    list_filter = ('is_used',)
    search_fields = ('phone', 'code')
    readonly_fields = ('created_at',)

    def status_badge(self, obj):
        if obj.is_used:
            return format_html('<span style="color: green; font-weight: bold;">✔ Utilizado</span>')
        if timezone.now() > obj.expires_at:
            return format_html('<span style="color: red; font-weight: bold;">✖ Expirado</span>')
        return format_html('<span style="color: blue; font-weight: bold;">⏳ Ativo</span>')
    status_badge.short_description = 'Status'
