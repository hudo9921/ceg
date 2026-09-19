from django.urls import path
from .views import (
    HomeView,
    CEGDetailView,
    ClaimSlotView,
    BulkClaimView,
    ToggleSlotPaymentView,
    UpdateCEGFeesView,
    UpdateCEGView,
    ManageSlotView,
    DeleteSetView,
    DeleteCEGView,
    CEGLogsAndWaitingListView,
    BulkManageCEGItemsView,
)
from .creations_views import (
    CreationsHubView,
    CreateGroupView,
    UpdateGroupView,
    CreateEraView,
    UpdateEraView,
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
    ConsultaJoinerView,
    EnviosNacionaisDashboardView,
    EmpacotarItensView,
    MarcarPacoteEnviadoView,
    MarcarPacoteEntregueAdminView,
    AtualizarPacoteView,
    DesempacotarItemView,
    ExcluirPacoteView,
    AtualizarConfiguracaoEnvioView,
)

from .allocator_views import (
    CEGBulkAllocatorView,
    CEGBulkAllocatorAPIView,
)
from .audit_views import AuditDashboardView
from .vitrine_views import (
    VitrineListView,
    VitrineItemCreateView,
    VitrineItemUpdateView,
    VitrineItemDeleteView,
    VitrineToggleStatusView,
    CaixaTransferUnclaimedToVitrineView,
)
from apps.participants.views import BulkParticipantCreateView

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('cegs/alocar-joiners/', CEGBulkAllocatorView.as_view(), name='bulk_joiner_allocator_global'),
    path('ceg/<slug:slug>/', CEGDetailView.as_view(), name='ceg_detail'),
    path('ceg/<slug:slug>/edit/', UpdateCEGView.as_view(), name='update_ceg'),
    path('ceg/<slug:slug>/update-fees/', UpdateCEGFeesView.as_view(), name='update_ceg_fees'),
    path('ceg/<slug:slug>/logs-espera/', CEGLogsAndWaitingListView.as_view(), name='ceg_logs_espera'),
    path('ceg/<slug:slug>/bulk-manage-items/', BulkManageCEGItemsView.as_view(), name='bulk_manage_ceg_items'),
    path('ceg/<slug:slug>/delete/', DeleteCEGView.as_view(), name='delete_ceg'),
    path('ceg/<slug:slug>/alocar-massa/', CEGBulkAllocatorView.as_view(), name='ceg_bulk_allocator'),
    path('ceg/<slug:slug>/alocar-massa/api/', CEGBulkAllocatorAPIView.as_view(), name='ceg_bulk_allocator_api'),
    path('slots/<int:slot_id>/claim/', ClaimSlotView.as_view(), name='claim_slot'),
    path('ceg/<slug:slug>/bulk-claim/', BulkClaimView.as_view(), name='bulk_claim'),
    path('slots/<int:slot_id>/toggle-payment/', ToggleSlotPaymentView.as_view(), name='toggle_slot_payment'),
    path('slots/<int:slot_id>/manage/', ManageSlotView.as_view(), name='manage_slot'),
    path('sets/<int:set_id>/delete/', DeleteSetView.as_view(), name='delete_set'),
    path('creations/', CreationsHubView.as_view(), name='creations_hub'),
    path('creations/participantes/em-massa/', BulkParticipantCreateView.as_view(), name='creations_bulk_participant'),
    path('creations/group/create/', CreateGroupView.as_view(), name='create_group'),
    path('creations/group/update/', UpdateGroupView.as_view(), name='update_group'),
    path('creations/era/create/', CreateEraView.as_view(), name='create_era'),
    path('creations/era/update/', UpdateEraView.as_view(), name='update_era'),
    path('creations/ceg/create/', CreateCEGView.as_view(), name='create_ceg'),
    path('creations/set/create/', CreateSetView.as_view(), name='create_set'),
    path('creations/item/create/', AddItemToCEGView.as_view(), name='add_item_to_ceg'),

    # 1. Consulta Joiner (Visão 360º de itens, pagamentos e envios de cada participante)
    path('consulta-joiner/', ConsultaJoinerView.as_view(), name='consulta_joiner'),

    # 2. Envios Nacionais & Pacotes (Dashboard Global com todos os envios, filtros e feedbacks)
    path('envios/', EnviosNacionaisDashboardView.as_view(), name='envios_nacionais'),
    path('envios/empacotar/', EmpacotarItensView.as_view(), name='empacotar_itens'),
    path('envios/pacote/<int:pacote_id>/marcar-enviado/', MarcarPacoteEnviadoView.as_view(), name='marcar_pacote_enviado'),
    path('envios/pacote/<int:pacote_id>/marcar-entregue/', MarcarPacoteEntregueAdminView.as_view(), name='marcar_pacote_entregue'),
    path('envios/pacote/<int:pacote_id>/atualizar/', AtualizarPacoteView.as_view(), name='atualizar_pacote'),
    path('envios/desempacotar/', DesempacotarItemView.as_view(), name='desempacotar_item'),
    path('envios/pacote/<int:pacote_id>/excluir/', ExcluirPacoteView.as_view(), name='excluir_pacote'),
    path('envios/configuracao/', AtualizarConfiguracaoEnvioView.as_view(), name='atualizar_configuracao_envio'),

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

    # Auditoria e Logs de Atividades
    path('auditoria/', AuditDashboardView.as_view(), name='auditoria_logs'),
    path('logs/', AuditDashboardView.as_view(), name='auditoria_logs_alias'),

    # Vitrine de Pronta Entrega
    path('vitrine/', VitrineListView.as_view(), name='vitrine_list'),
    path('vitrine/novo/', VitrineItemCreateView.as_view(), name='vitrine_create'),
    path('vitrine/<slug:slug>/editar/', VitrineItemUpdateView.as_view(), name='vitrine_edit'),
    path('vitrine/<slug:slug>/excluir/', VitrineItemDeleteView.as_view(), name='vitrine_delete'),
    path('vitrine/<slug:slug>/status/', VitrineToggleStatusView.as_view(), name='vitrine_toggle_status'),
    path('caixas/<slug:slug>/transferir-vitrine/', CaixaTransferUnclaimedToVitrineView.as_view(), name='caixa_transfer_unclaimed_vitrine'),
]
