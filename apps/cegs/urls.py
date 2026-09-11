from django.urls import path
from .views import HomeView, CEGDetailView, ClaimSlotView

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('ceg/<slug:slug>/', CEGDetailView.as_view(), name='ceg_detail'),
    path('slots/<int:slot_id>/claim/', ClaimSlotView.as_view(), name='claim_slot'),
]
