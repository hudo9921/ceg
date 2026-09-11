import json
from django.shortcuts import render
from django.views import View
from django.http import JsonResponse
from .services import AnalyticsService


class AnalyticsDashboardView(View):
    def get(self, request):
        group_id = request.GET.get('group') or None
        era_id = request.GET.get('era') or None
        month = request.GET.get('month') or None

        filter_options = AnalyticsService.get_filter_options()
        summary = AnalyticsService.get_summary_metrics(group_id=group_id, era_id=era_id, month=month)
        monthly_flow = AnalyticsService.get_monthly_sales_flow(group_id=group_id, era_id=era_id)
        detailed_inventory = AnalyticsService.get_detailed_inventory_table(group_id=group_id, era_id=era_id)
        group_comparison = AnalyticsService.get_group_comparison()
        members = AnalyticsService.get_member_popularity(group_id=group_id, era_id=era_id)
        sets_near = AnalyticsService.get_sets_near_completion(group_id=group_id, era_id=era_id)

        # Prepara dados para os gráficos do Chart.js
        chart_data = {
            'monthly': {
                'labels': [m['label'] for m in monthly_flow],
                'paid': [m['paid_sales'] for m in monthly_flow],
                'pending': [m['pending_sales'] for m in monthly_flow],
                'claims': [m['claims_count'] for m in monthly_flow],
            },
            'donut': {
                'labels': ['Faturado (Pago)', 'Falta Pagar (Pendente)', 'Para Vender (Livre)'],
                'data': [
                    summary['total_paid'],
                    summary['total_pending'],
                    summary['total_remaining_to_sell']
                ],
            },
            'groups': {
                'labels': [g['group_name'] for g in group_comparison],
                'sold': [g['sold_amount'] for g in group_comparison],
                'available': [g['available_amount'] for g in group_comparison],
            }
        }

        # Objeto ou nome do grupo e era selecionados para exibição
        selected_group_name = None
        if group_id:
            for g in filter_options['groups']:
                if g['id'] == str(group_id):
                    selected_group_name = g['name']
                    break

        selected_era_name = None
        if era_id:
            for e in filter_options['eras']:
                if e['id'] == str(era_id):
                    selected_era_name = e['name']
                    break

        return render(request, 'analytics/dashboard.html', {
            'filter_options': filter_options,
            'filter_options_json': json.dumps(filter_options),
            'selected_group': group_id or '',
            'selected_era': era_id or '',
            'selected_month': month or '',
            'selected_group_name': selected_group_name,
            'selected_era_name': selected_era_name,
            'summary': summary,
            'monthly_flow': monthly_flow,
            'detailed_inventory': detailed_inventory,
            'group_comparison': group_comparison,
            'members': members[:12],  # Top 12 integrantes
            'sets_near': sets_near,
            'chart_data_json': json.dumps(chart_data),
            # Para manter retrocompatibilidade com código existente:
            'financials': detailed_inventory,
        })


class AnalyticsApiView(View):
    def get(self, request):
        group_id = request.GET.get('group') or None
        era_id = request.GET.get('era') or None
        month = request.GET.get('month') or None

        return JsonResponse({
            'summary': AnalyticsService.get_summary_metrics(group_id=group_id, era_id=era_id, month=month),
            'monthly_flow': AnalyticsService.get_monthly_sales_flow(group_id=group_id, era_id=era_id),
            'detailed_inventory': AnalyticsService.get_detailed_inventory_table(group_id=group_id, era_id=era_id),
            'group_comparison': AnalyticsService.get_group_comparison(),
            'members': AnalyticsService.get_member_popularity(group_id=group_id, era_id=era_id),
            'sets_near': AnalyticsService.get_sets_near_completion(group_id=group_id, era_id=era_id),
            'filter_options': AnalyticsService.get_filter_options(),
        })

