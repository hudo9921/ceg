from django.urls import path
from .views import AnalyticsDashboardView, AnalyticsApiView

urlpatterns = [
    path('', AnalyticsDashboardView.as_view(), name='analytics_dashboard'),
    path('api/', AnalyticsApiView.as_view(), name='analytics_api'),
]
