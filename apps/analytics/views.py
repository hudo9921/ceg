from django.shortcuts import render
from django.views import View
from django.http import JsonResponse
from .services import AnalyticsService


class AnalyticsDashboardView(View):
    def get(self, request):
        summary = AnalyticsService.get_summary_metrics()
        members = AnalyticsService.get_member_popularity()
        financials = AnalyticsService.get_era_financials()
        sets_near = AnalyticsService.get_sets_near_completion()

        return render(request, 'analytics/dashboard.html', {
            'summary': summary,
            'members': members,
            'financials': financials,
            'sets_near': sets_near,
        })


class AnalyticsApiView(View):
    def get(self, request):
        return JsonResponse({
            'summary': AnalyticsService.get_summary_metrics(),
            'members': AnalyticsService.get_member_popularity(),
            'financials': AnalyticsService.get_era_financials(),
            'sets_near': AnalyticsService.get_sets_near_completion(),
        })
