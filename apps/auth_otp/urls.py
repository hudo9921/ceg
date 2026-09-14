from django.urls import path
from .views import WhatsAppManagerView, WhatsAppStatusAPIView

urlpatterns = [
    path('', WhatsAppManagerView.as_view(), name='admin_whatsapp'),
    path('status/', WhatsAppStatusAPIView.as_view(), name='admin_whatsapp_status'),
]
