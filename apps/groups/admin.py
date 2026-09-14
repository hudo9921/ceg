from django.contrib import admin
from .models import KpopGroup, Era


@admin.register(KpopGroup)
class KpopGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'eras_count', 'created_at')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}

    def eras_count(self, obj):
        return obj.eras.count()
    eras_count.short_description = 'Eras Cadastradas'


@admin.register(Era)
class EraAdmin(admin.ModelAdmin):
    list_display = ('name', 'group', 'release_date', 'cegs_count', 'created_at')
    list_filter = ('group',)
    search_fields = ('name', 'group__name')
    prepopulated_fields = {'slug': ('name',)}

    def cegs_count(self, obj):
        return obj.cegs.count()
    cegs_count.short_description = 'CEGs da Era'
