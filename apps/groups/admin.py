from django.contrib import admin
from .models import KpopGroup, Era, GroupMember


class GroupMemberInline(admin.TabularInline):
    model = GroupMember
    extra = 1
    fields = ('name', 'order')


@admin.register(KpopGroup)
class KpopGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'members_count_display', 'eras_count', 'created_at')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}
    inlines = [GroupMemberInline]

    def members_count_display(self, obj):
        return obj.members.count()
    members_count_display.short_description = 'Integrantes'

    def eras_count(self, obj):
        return obj.eras.count()
    eras_count.short_description = 'Eras Cadastradas'


@admin.register(GroupMember)
class GroupMemberAdmin(admin.ModelAdmin):
    list_display = ('name', 'group', 'order', 'created_at')
    list_filter = ('group',)
    search_fields = ('name', 'group__name')
    ordering = ('group__name', 'order', 'name')


@admin.register(Era)
class EraAdmin(admin.ModelAdmin):
    list_display = ('name', 'group', 'release_date', 'cegs_count', 'created_at')
    list_filter = ('group',)
    search_fields = ('name', 'group__name')
    prepopulated_fields = {'slug': ('name',)}

    def cegs_count(self, obj):
        return obj.cegs.count()
    cegs_count.short_description = 'CEGs da Era'
