from django.urls import path
from .views import LoginOtpView, MyClaimsView, LogoutView, ProfileUpdateView

urlpatterns = [
    path('login/', LoginOtpView.as_view(), name='login_otp'),
    path('profile/', ProfileUpdateView.as_view(), name='update_profile'),
    path('', MyClaimsView.as_view(), name='my_claims'),
    path('logout/', LogoutView.as_view(), name='logout_participant'),
]
