from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Personalização do cabeçalho do Django Admin
admin.site.site_header = "K-pop CEG Manager"
admin.site.site_title = "Painel do Organizador de CEGs"
admin.site.index_title = "Gestão de Compras em Grupo (K-pop)"

from django.http import HttpResponse
from apps.participants.privacy_views import PrivacyPolicyView

def health_check(request):
    """Usado pelo deploy para confirmar que a nova versão subiu e alcança o banco."""
    from django.db import connection
    try:
        connection.ensure_connection()
    except Exception:
        return HttpResponse("DB indisponivel", status=503, content_type="text/plain")
    return HttpResponse("OK", content_type="text/plain")

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('admin/whatsapp/', include('apps.auth_otp.urls')),
    path('admin/seguranca/2fa/', include('apps.core.urls')),
    path('admin/', admin.site.urls),
    path('me/', include('apps.participants.urls')),
    path('privacidade/', PrivacyPolicyView.as_view(), name='privacy_policy'),
    path('', include('apps.goms.urls')),
    path('analytics/', include('apps.analytics.urls')),
    path('', include('apps.cegs.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
