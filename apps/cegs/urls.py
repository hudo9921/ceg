from django.urls import path
from .views import HomeView, CEGDetailView, ClaimSlotView
from .creations_views import (
    CreationsHubView,
    CreateGroupView,
    CreateEraView,
    CreateCEGView,
    CreateSetView,
    AddItemToCEGView,
)

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('ceg/<slug:slug>/', CEGDetailView.as_view(), name='ceg_detail'),
    path('slots/<int:slot_id>/claim/', ClaimSlotView.as_view(), name='claim_slot'),
    path('creations/', CreationsHubView.as_view(), name='creations_hub'),
    path('creations/group/create/', CreateGroupView.as_view(), name='create_group'),
    path('creations/era/create/', CreateEraView.as_view(), name='create_era'),
    path('creations/ceg/create/', CreateCEGView.as_view(), name='create_ceg'),
    path('creations/set/create/', CreateSetView.as_view(), name='create_set'),
    path('creations/item/create/', AddItemToCEGView.as_view(), name='add_item_to_ceg'),
]
