from django.urls import path
from .views import (
    HomeView,
    CEGDetailView,
    ClaimSlotView,
    ToggleSlotPaymentView,
    UpdateCEGFeesView,
    UpdateCEGView,
    ManageSlotView,
    DeleteSetView,
    CEGLogsAndWaitingListView,
    BulkManageCEGItemsView,
)
from .creations_views import (
    CreationsHubView,
    CreateGroupView,
    CreateEraView,
    CreateCEGView,
    CreateSetView,
    AddItemToCEGView,
)
from .caixas_views import (
    CaixasDashboardView,
    CaixaDetailView,
    CaixaCreateView,
    CaixaUpdateView,
    CaixaUpdateStatusView,
    CaixaLinkCEGView,
    CaixaUnlinkCEGView,
    CaixaLinkItemIndividualView,
    CaixaUnlinkItemIndividualView,
    CaixaDistributeRatesView,
    TipoItemCreateView,
    TipoItemDeleteView,
)
from .itens_individuais_views import (
    CreateItemIndividualView,
    UpdateItemIndividualView,
    ToggleItemPaymentView,
    DeleteItemIndividualView,
    ParticipantLookupAPIView,
)
from .envios_views import (
    EnviosNacionaisView,
    EmpacotarItensView,
    MarcarPacoteEnviadoView,
    AtualizarPacoteView,
    DesempacotarItemView,
    ExcluirPacoteView,
)

from apps.participants.views import BulkParticipantCreateView

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('ceg/<slug:slug>/', CEGDetailView.as_view(), name='ceg_detail'),
    path('ceg/<slug:slug>/edit/', UpdateCEGView.as_view(), name='update_ceg'),
    path('ceg/<slug:slug>/update-fees/', UpdateCEGFeesView.as_view(), name='update_ceg_fees'),
    path('ceg/<slug:slug>/logs-espera/', CEGLogsAndWaitingListView.as_view(), name='ceg_logs_espera'),
    path('ceg/<slug:slug>/bulk-manage-items/', BulkManageCEGItemsView.as_view(), name='bulk_manage_ceg_items'),
    path('slots/<int:slot_id>/claim/', ClaimSlotView.as_view(), name='claim_slot'),
    path('slots/<int:slot_id>/toggle-payment/', ToggleSlotPaymentView.as_view(), name='toggle_slot_payment'),
    path('slots/<int:slot_id>/manage/', ManageSlotView.as_view(), name='manage_slot'),
    path('sets/<int:set_id>/delete/', DeleteSetView.as_view(), name='delete_set'),
    path('creations/', CreationsHubView.as_view(), name='creations_hub'),
    path('creations/participantes/em-massa/', BulkParticipantCreateView.as_view(), name='creations_bulk_participant'),
    path('creations/group/create/', CreateGroupView.as_view(), name='create_group'),
    path('creations/era/create/', CreateEraView.as_view(), name='create_era'),
    path('creations/ceg/create/', CreateCEGView.as_view(), name='create_ceg'),
    path('creations/set/create/', CreateSetView.as_view(), name='create_set'),
    path('creations/item/create/', AddItemToCEGView.as_view(), name='add_item_to_ceg'),

    # Consulta Joiner (Gestão de Envios Nacionais por Joiner / Empacotamento & Rastreio)
    path('consulta-joiner/', EnviosNacionaisView.as_view(), name='consulta_joiner'),
    path('envios/', EnviosNacionaisView.as_view(), name='envios_nacionais'),
    path('envios/empacotar/', EmpacotarItensView.as_view(), name='empacotar_itens'),
    path('envios/pacote/<int:pacote_id>/marcar-enviado/', MarcarPacoteEnviadoView.as_view(), name='marcar_pacote_enviado'),
    path('envios/pacote/<int:pacote_id>/atualizar/', AtualizarPacoteView.as_view(), name='atualizar_pacote'),
    path('envios/desempacotar/', DesempacotarItemView.as_view(), name='desempacotar_item'),
    path('envios/pacote/<int:pacote_id>/excluir/', ExcluirPacoteView.as_view(), name='excluir_pacote'),

    # Itens Individuais (Pedidos Mercari / JP / etc.)
    path('itens-individuais/create/', CreateItemIndividualView.as_view(), name='create_item_individual'),
    path('itens-individuais/<int:item_id>/update/', UpdateItemIndividualView.as_view(), name='update_item_individual'),
    path('itens-individuais/<int:item_id>/toggle-payment/', ToggleItemPaymentView.as_view(), name='toggle_item_payment'),
    path('itens-individuais/<int:item_id>/delete/', DeleteItemIndividualView.as_view(), name='delete_item_individual'),
    path('api/participants/lookup/', ParticipantLookupAPIView.as_view(), name='api_participant_lookup'),

    # Caixas (Remessas Internacionais KR / JP)
    path('caixas/', CaixasDashboardView.as_view(), name='caixas_dashboard'),
    path('caixas/create/', CaixaCreateView.as_view(), name='caixa_create'),
    path('caixas/<slug:slug>/', CaixaDetailView.as_view(), name='caixa_detail'),
    path('caixas/<slug:slug>/edit/', CaixaUpdateView.as_view(), name='caixa_update'),
    path('caixas/<slug:slug>/status/', CaixaUpdateStatusView.as_view(), name='caixa_update_status'),
    path('caixas/<slug:slug>/link-cegs/', CaixaLinkCEGView.as_view(), name='caixa_link_cegs'),
    path('caixas/<slug:slug>/unlink-ceg/<int:ceg_id>/', CaixaUnlinkCEGView.as_view(), name='caixa_unlink_ceg'),
    path('caixas/<slug:slug>/link-itens/', CaixaLinkItemIndividualView.as_view(), name='caixa_link_itens'),
    path('caixas/<slug:slug>/unlink-item/<int:item_id>/', CaixaUnlinkItemIndividualView.as_view(), name='caixa_unlink_item'),
    path('caixas/<slug:slug>/lancar-taxas/', CaixaDistributeRatesView.as_view(), name='caixa_distribute_rates'),
    path('tipos-item/criar/', TipoItemCreateView.as_view(), name='tipo_item_create'),
    path('tipos-item/<int:pk>/deletar/', TipoItemDeleteView.as_view(), name='tipo_item_delete'),
]
