from django.contrib import admin

from .models import Cobranca, CobrancaLinha


class LinhaInline(admin.TabularInline):
    model = CobrancaLinha
    extra = 0
    readonly_fields = ('tipo', 'descricao', 'valor', 'slot', 'item_individual', 'pacote')
    can_delete = False


@admin.register(Cobranca)
class CobrancaAdmin(admin.ModelAdmin):
    list_display = ('referencia', 'gom', 'participant', 'valor_total', 'status', 'criada_em')
    list_filter = ('status', 'gom')
    search_fields = ('referencia', 'participant__name', 'participant__whatsapp')
    readonly_fields = ('referencia', 'copia_e_cola', 'criada_em', 'informada_em', 'resolvida_em')
    inlines = [LinhaInline]
