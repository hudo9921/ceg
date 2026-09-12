from django.urls import path
from .views import (
    CEGStatusView,
    SalesReportView,
    CEGStatusApiView,
    SalesReportApiView,
    AnalyticsDashboardView,
    AnalyticsApiView,
)

urlpatterns = [
    path('', CEGStatusView.as_view(), name='cegs_status'),
    path('cegs/', CEGStatusView.as_view(), name='cegs_status_tab'),
    path('vendas/', SalesReportView.as_view(), name='sales_report'),
    path('sales/', SalesReportView.as_view(), name='sales_report_alias'),
    path('dashboard/', AnalyticsDashboardView.as_view(), name='analytics_dashboard'),
    path('api/cegs/', CEGStatusApiView.as_view(), name='cegs_status_api'),
    path('api/sales/', SalesReportApiView.as_view(), name='sales_report_api'),
    path('api/', AnalyticsApiView.as_view(), name='analytics_api'),
]

