from django.urls import path

from . import views

urlpatterns = [
    # Joiner (sessão do joiner, JSON).
    path('me/repasses/criar/', views.criar, name='repasse_criar'),
    path('me/repasses/<int:pk>/responder/', views.responder, name='repasse_responder'),
    path('me/repasses/<int:pk>/cancelar/', views.cancelar, name='repasse_cancelar'),
    path('repasses/<int:pk>/pedir/', views.pedir, name='repasse_pedir'),
    # Público.
    path('repasses/', views.lista_publica, name='repasses_disponiveis'),
    # Equipe do GOM (pedidos.editar).
    path('gom/repasses/', views.gom_fila, name='gom_repasses'),
]
