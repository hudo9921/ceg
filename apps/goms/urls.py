from django.urls import path

from . import views

urlpatterns = [
    path('entrar/', views.BackofficeLoginView.as_view(), name='backoffice_login'),
    path('painel/', views.backoffice_home, name='backoffice_home'),
    path('convite/<str:token>/', views.invite_accept, name='gom_invite_accept'),
    path('gom/equipe/', views.team, name='gom_team'),
    path('gom/trocar/', views.switch_gom, name='gom_switch'),
    path('plataforma/goms/', views.platform_goms, name='platform_goms'),
    # Depois das rotas fixas de /gom/ (equipe, trocar): slugs reservados em services.RESERVED_SLUGS.
    path('gom/<slug:slug>/', views.gom_public_page, name='gom_public'),
]
