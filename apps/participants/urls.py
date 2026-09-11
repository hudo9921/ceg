from django.urls import path
from .views import LoginOtpView, MyClaimsView, LogoutView

urlpatterns = [
    path('login/', LoginOtpView.as_view(), name='login_otp'),
    path('', MyClaimsView.as_view(), name='my_claims'),
    path('logout/', LogoutView.as_view(), name='logout_participant'),
]
