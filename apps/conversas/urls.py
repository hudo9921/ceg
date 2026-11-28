from django.urls import path

from . import views

urlpatterns = [
    # Joiner (sessão do joiner).
    path('me/mensagens/', views.joiner_lista, name='joiner_mensagens'),
    path('me/mensagens/nova/', views.joiner_nova, name='joiner_mensagem_nova'),
    path('me/mensagens/<int:conversa_id>/enviar/', views.joiner_enviar, name='joiner_mensagem_enviar'),
    path('me/mensagens/<int:conversa_id>/novas/', views.joiner_novas, name='joiner_mensagens_novas'),
    # Equipe do GOM (mensagens.responder).
    path('mensagens/', views.gom_lista, name='gom_mensagens'),
    path('mensagens/nova/', views.gom_nova, name='gom_mensagem_nova'),
    path('mensagens/respostas/', views.gom_respostas, name='gom_respostas'),
    path('mensagens/<int:conversa_id>/enviar/', views.gom_enviar, name='gom_mensagem_enviar'),
    path('mensagens/<int:conversa_id>/novas/', views.gom_novas, name='gom_mensagens_novas'),
    # Vitrine (S5b): joiner reserva/cancela; equipe cancela ou marca como pago (vitrine.reservar).
    path('vitrine/<slug:slug>/reservar/', views.vitrine_reservar, name='vitrine_reservar'),
    path('vitrine/<slug:slug>/comprar/', views.vitrine_comprar, name='vitrine_comprar'),
    path('me/reservas/<int:reserva_id>/cancelar/', views.joiner_reserva_cancelar, name='joiner_reserva_cancelar'),
    path('mensagens/reserva/<int:reserva_id>/<str:acao>/', views.gom_reserva_acao, name='gom_reserva_acao'),
]
