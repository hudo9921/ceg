from django.urls import path
from .views import (
    LoginOtpView, MyClaimsView, LogoutView, ProfileUpdateView,
    MarkNotificationReadView, MarkAllNotificationsReadView
)

urlpatterns = [
    path('login/', LoginOtpView.as_view(), name='login_otp'),
    path('profile/', ProfileUpdateView.as_view(), name='update_profile'),
    path('notifications/<int:notification_id>/read/', MarkNotificationReadView.as_view(), name='mark_notification_read'),
    path('notifications/read-all/', MarkAllNotificationsReadView.as_view(), name='mark_all_notifications_read'),
    path('', MyClaimsView.as_view(), name='my_claims'),
    path('logout/', LogoutView.as_view(), name='logout_participant'),
]

