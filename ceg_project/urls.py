from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Personalização do cabeçalho do Django Admin
admin.site.site_header = "K-pop CEG Manager"
admin.site.site_title = "Painel do Organizador de CEGs"
admin.site.index_title = "Gestão de Compras em Grupo (K-pop)"

from django.http import HttpResponse

def health_check(request):
    return HttpResponse("OK", content_type="text/plain")

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('admin/whatsapp/', include('apps.auth_otp.urls')),
    path('admin/', admin.site.urls),
    path('me/', include('apps.participants.urls')),
    path('analytics/', include('apps.analytics.urls')),
    path('', include('apps.cegs.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
