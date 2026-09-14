from django.urls import path
from .views import (
    LoginOtpView, MyClaimsView, LogoutView, ProfileUpdateView,
    MarkNotificationReadView, MarkAllNotificationsReadView,
    BulkParticipantCreateView
)

urlpatterns = [
    path('login/', LoginOtpView.as_view(), name='login_otp'),
    path('profile/', ProfileUpdateView.as_view(), name='update_profile'),
    path('participantes/em-massa/', BulkParticipantCreateView.as_view(), name='bulk_participant_create'),
    path('cadastros-em-massa/', BulkParticipantCreateView.as_view(), name='bulk_participant_create_alias'),
    path('notifications/<int:notification_id>/read/', MarkNotificationReadView.as_view(), name='mark_notification_read'),
    path('notifications/read-all/', MarkAllNotificationsReadView.as_view(), name='mark_all_notifications_read'),
    path('', MyClaimsView.as_view(), name='my_claims'),
    path('logout/', LogoutView.as_view(), name='logout_participant'),
]

