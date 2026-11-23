from django.contrib import admin

from .models import Gom, GomInvite, GomMembership


class GomMembershipInline(admin.TabularInline):
    model = GomMembership
    fk_name = 'gom'
    extra = 0
    autocomplete_fields = ['user']
    readonly_fields = ['created_at']
    exclude = ['invited_by']


@admin.register(Gom)
class GomAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'slug']
    inlines = [GomMembershipInline]


@admin.register(GomMembership)
class GomMembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'gom', 'role', 'is_active', 'created_at']
    list_filter = ['gom', 'role', 'is_active']
    search_fields = ['user__username', 'gom__name']
    autocomplete_fields = ['user', 'gom']


@admin.register(GomInvite)
class GomInviteAdmin(admin.ModelAdmin):
    """Somente leitura: convites são criados pelas telas (o token não fica no banco)."""
    list_display = ['gom', 'role', 'name', 'status', 'expires_at', 'created_by']
    list_filter = ['gom', 'role']
    readonly_fields = [f.name for f in GomInvite._meta.fields]

    def has_add_permission(self, request):
        return False
