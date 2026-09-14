import json
from django.shortcuts import render
from django.views import View
from django.http import JsonResponse
from apps.cegs.models import TipoItem, Caixa, ItemIndividual
from apps.cegs.creations_views import StaffRequiredMixin
from .services import AnalyticsService


class CEGStatusView(StaffRequiredMixin, View):
    """
    Página 1: Painel Operacional das CEGs, Sets e Itens Individuais (Mercari).
    Foco em status de CEGs, completude de sets (o que falta para fechar),
    sets completos porém pendentes (frete, taxa, pagamentos), valores das CEGs e fluxo Mercari.
    """
    def get(self, request):
        category = request.GET.get('category') or 'all'
        group_id = request.GET.get('group') or None
        era_id = request.GET.get('era') or None
        search = request.GET.get('search', '').strip()

        filter_options = AnalyticsService.get_filter_options()
        status_data = AnalyticsService.get_cegs_operational_status(
            group_id=group_id,
            era_id=era_id,
            category=category,
            search=search
        )

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

        tipos_item = list(TipoItem.objects.values('id', 'nome'))
        caixas = Caixa.objects.all().order_by('-created_at')

        return render(request, 'analytics/ceg_status.html', {
            'filter_options': filter_options,
            'filter_options_json': json.dumps(filter_options),
            'category': category,
            'selected_group': group_id or '',
            'selected_era': era_id or '',
            'selected_group_name': selected_group_name,
            'selected_era_name': selected_era_name,
            'search_query': search,
            'summary': status_data['summary'],
            'sets_fechados': status_data.get('sets_fechados', []),
            'sets_pagos': status_data.get('sets_pagos', []),
            'sets_terminados': status_data.get('sets_terminados', []),
            'sets_completed_pending': status_data['sets_completed_pending'],
            'sets_incomplete': status_data['sets_incomplete'],
            'cegs_overview': status_data['cegs_overview'],
            'mercari_status': status_data.get('mercari_status'),
            'tipos_item': tipos_item,
            'tipos_item_json': json.dumps(tipos_item),
            'caixas': caixas,
            'item_individual_statuses': ItemIndividual.Status.choices,
            'is_staff_user': request.user.is_authenticated and request.user.is_staff,
        })


class SalesReportView(StaffRequiredMixin, View):
    """
    Página 2: Relatório Financeiro e Análise de Vendas (Income & BI).
    Foco em faturamento, volume de claims/itens, gráficos temporais mês a mês
    (volume e valores em R$), ticket médio, ranking de itens e participantes.
    """
    def get(self, request):
        category = request.GET.get('category') or 'all'
        group_id = request.GET.get('group') or None
        era_id = request.GET.get('era') or None
        time_window = request.GET.get('window') or 'all'
        month = request.GET.get('month') or None

        filter_options = AnalyticsService.get_filter_options()
        sales_data = AnalyticsService.get_sales_analytics(
            group_id=group_id, era_id=era_id, time_window=time_window, month=month, category=category
        )

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

        from .services import MONTH_FULL
        window_labels = {
            '30d': 'Últimos 30 dias',
            '90d': 'Últimos 90 dias',
            '180d': 'Últimos 6 meses',
            'year': 'Este Ano',
            'all': 'Todo o Histórico',
        }
        window_label = window_labels.get(time_window, 'Todo o Histórico')
        if month:
            try:
                y, m = month.split('-')
                window_label = f"{MONTH_FULL.get(int(m), '')}/{y}"
            except Exception:
                pass

        # Estrutura de dados para os gráficos do Chart.js
        chart_data = {
            'monthly': {
                'labels': [m['label'] for m in sales_data['monthly_flow']],
                'full_labels': [m['full_label'] for m in sales_data['monthly_flow']],
                'total_sales': [m['total_sales'] for m in sales_data['monthly_flow']],
                'paid_sales': [m['paid_sales'] for m in sales_data['monthly_flow']],
                'pending_sales': [m['pending_sales'] for m in sales_data['monthly_flow']],
                'claims_count': [m['claims_count'] for m in sales_data['monthly_flow']],
            },
            'donut': {
                'labels': ['Pago (Confirmado)', 'Pendente (Aguardando Pix)'],
                'data': [
                    sales_data['summary']['total_paid'],
                    sales_data['summary']['total_pending']
                ],
            },
            'groups': {
                'labels': [g['group_name'] for g in sales_data['group_sales']],
                'sales': [g['total_sales'] for g in sales_data['group_sales']],
                'claims': [g['claims_count'] for g in sales_data['group_sales']],
            }
        }

        return render(request, 'analytics/sales_report.html', {
            'filter_options': filter_options,
            'filter_options_json': json.dumps(filter_options),
            'category': category,
            'selected_group': group_id or '',
            'selected_era': era_id or '',
            'selected_window': time_window,
            'selected_month': month or '',
            'selected_group_name': selected_group_name,
            'selected_era_name': selected_era_name,
            'window_label': window_label,
            'summary': sales_data['summary'],
            'monthly_flow': sales_data['monthly_flow'],
            'group_sales': sales_data['group_sales'],
            'top_items': sales_data['top_items'],
            'top_buyers': sales_data['top_buyers'],
            'chart_data': chart_data,
            'chart_data_json': json.dumps(chart_data),
        })


class CEGStatusApiView(View):
    def get(self, request):
        category = request.GET.get('category') or 'all'
        group_id = request.GET.get('group') or None
        era_id = request.GET.get('era') or None
        data = AnalyticsService.get_cegs_operational_status(group_id=group_id, era_id=era_id, category=category)
        return JsonResponse(data)


class SalesReportApiView(View):
    def get(self, request):
        category = request.GET.get('category') or 'all'
        group_id = request.GET.get('group') or None
        era_id = request.GET.get('era') or None
        time_window = request.GET.get('window') or 'all'
        month = request.GET.get('month') or None
        data = AnalyticsService.get_sales_analytics(
            group_id=group_id, era_id=era_id, time_window=time_window, month=month, category=category
        )
        return JsonResponse(data)


# Mantém compatibilidade com AnalyticsDashboardView e AnalyticsApiView antigos
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

        return render(request, 'analytics/dashboard.html', {
            'filter_options': filter_options,
            'filter_options_json': json.dumps(filter_options),
            'selected_group': group_id or '',
            'selected_era': era_id or '',
            'selected_month': month or '',
            'summary': summary,
            'monthly_flow': monthly_flow,
            'detailed_inventory': detailed_inventory,
            'group_comparison': group_comparison,
            'members': members[:12],
            'sets_near': sets_near,
            'chart_data_json': json.dumps(chart_data),
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

