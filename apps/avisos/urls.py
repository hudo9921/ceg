from django.urls import path

from . import views

urlpatterns = [
    path('sw.js', views.service_worker, name='service_worker'),
    path('manifest.webmanifest', views.manifesto, name='webmanifest'),
    path('push/chave/', views.chave, name='push_chave'),
    path('push/inscrever/', views.inscrever, name='push_inscrever'),
    path('push/cancelar/', views.cancelar, name='push_cancelar'),
    path('push/testar/', views.testar, name='push_testar'),
]
