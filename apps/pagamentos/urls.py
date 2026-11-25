from django.urls import path

from . import joiner_views

urlpatterns = [
    # Joiner (/me/pagar/...): sessão do joiner, respostas em JSON.
    path('me/pagar/gerar/', joiner_views.gerar, name='pix_gerar'),
    path('me/pagar/cobranca/<str:ref>/', joiner_views.ver, name='pix_ver'),
    path('me/pagar/cobranca/<str:ref>/paguei/', joiner_views.paguei, name='pix_paguei'),
    path('me/pagar/cobranca/<str:ref>/cancelar/', joiner_views.cancelar, name='pix_cancelar'),
]

from . import gom_views  # noqa: E402

urlpatterns += [
    # Equipe do GOM (permissão pag.confirmar).
    path('pagamentos/', gom_views.fila, name='pix_fila'),
    path('pagamentos/comprovante/<str:ref>/', gom_views.comprovante, name='pix_comprovante'),
    path('pagamentos/cobrar/<int:participant_id>/', gom_views.cobrar, name='pix_cobrar'),
]
