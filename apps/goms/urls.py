from django.urls import path

from apps.groups import plataforma_views

from . import busca, settings_views, views

urlpatterns = [
    path('entrar/', views.BackofficeLoginView.as_view(), name='backoffice_login'),
    path('painel/', views.backoffice_home, name='backoffice_home'),
    path('painel/busca/', busca.busca, name='painel_busca'),
    path('convite/<str:token>/', views.invite_accept, name='gom_invite_accept'),
    path('gom/equipe/', views.team, name='gom_team'),
    path('gom/trocar/', views.switch_gom, name='gom_switch'),
    path('gom/configuracoes/', settings_views.gom_settings_index, name='gom_settings'),
    path('gom/configuracoes/<slug:tab>/', settings_views.gom_settings, name='gom_settings_tab'),
    path('gom/perfil/', settings_views.old_profile_url, name='gom_profile'),  # link antigo
    path('plataforma/goms/', views.platform_goms, name='platform_goms'),
    path('plataforma/catalogo/', plataforma_views.catalogo, name='platform_catalogo'),
    path('plataforma/catalogo/<int:pk>/', plataforma_views.catalogo_grupo, name='platform_catalogo_grupo'),
    path('plataforma/catalogo/<int:pk>/salvar/', plataforma_views.catalogo_grupo_salvar, name='platform_catalogo_grupo_salvar'),
    path('plataforma/catalogo/era/<int:pk>/salvar/', plataforma_views.catalogo_era_salvar, name='platform_catalogo_era_salvar'),
    path('plataforma/catalogo/era/<int:pk>/juntar/', plataforma_views.catalogo_era_juntar, name='platform_catalogo_era_juntar'),
    path('goms/', views.gom_directory, name='gom_directory'),
    # Depois das rotas fixas de /gom/ (equipe, trocar): slugs reservados em services.RESERVED_SLUGS.
    path('gom/<slug:slug>/', views.gom_public_page, name='gom_public'),
    path('gom/<slug:slug>/regras/aceitar/', views.accept_gom_rules, name='gom_rules_accept'),
]
