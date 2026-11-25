from django.urls import path

from . import two_factor_views

urlpatterns = [
    path('', two_factor_views.manage_view, name='staff_2fa_manage'),
    path('configurar/', two_factor_views.setup_view, name='staff_2fa_setup'),
    path('verificar/', two_factor_views.verify_view, name='staff_2fa_verify'),
]
