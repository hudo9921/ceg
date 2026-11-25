from django.urls import path

from . import settings_views, views

urlpatterns = [
    path('entrar/', views.BackofficeLoginView.as_view(), name='backoffice_login'),
    path('painel/', views.backoffice_home, name='backoffice_home'),
    path('convite/<str:token>/', views.invite_accept, name='gom_invite_accept'),
    path('gom/equipe/', views.team, name='gom_team'),
    path('gom/trocar/', views.switch_gom, name='gom_switch'),
    path('gom/configuracoes/', settings_views.gom_settings_index, name='gom_settings'),
    path('gom/configuracoes/<slug:tab>/', settings_views.gom_settings, name='gom_settings_tab'),
    path('gom/perfil/', settings_views.old_profile_url, name='gom_profile'),  # link antigo
    path('plataforma/goms/', views.platform_goms, name='platform_goms'),
    # Depois das rotas fixas de /gom/ (equipe, trocar): slugs reservados em services.RESERVED_SLUGS.
    path('gom/<slug:slug>/', views.gom_public_page, name='gom_public'),
    path('gom/<slug:slug>/regras/aceitar/', views.accept_gom_rules, name='gom_rules_accept'),
]
