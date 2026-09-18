import csv
from datetime import datetime, time
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from apps.cegs.models import AuditLog, CEG
from apps.participants.models import Participant


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class AuditDashboardView(StaffRequiredMixin, View):
    """
    Painel Central de Auditoria e Logs de Atividades.
    Permite filtrar e visualizar criação de contas, claims e alterações de pagamentos.
    """
    def get(self, request):
        qs = AuditLog.objects.select_related('actor', 'participant', 'ceg', 'slot__item_definition', 'slot__set', 'item_individual').all()

        # 1. Busca textual
        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(participant_name__icontains=q) |
                Q(participant_phone__icontains=q) |
                Q(action_label__icontains=q) |
                Q(ceg__title__icontains=q) |
                Q(slot__item_definition__name__icontains=q) |
                Q(item_individual__nome__icontains=q) |
                Q(actor_name__icontains=q)
            )

        # 2. Filtro por tipo de evento
        event_type = request.GET.get('event_type', '').strip()
        if event_type:
            if event_type == 'PAYMENTS_ALL':
                qs = qs.filter(event_type__in=[
                    AuditLog.EventType.PAYMENT_ITEM,
                    AuditLog.EventType.PAYMENT_FRETE_INTER,
                    AuditLog.EventType.PAYMENT_TAXA,
                    AuditLog.EventType.PAYMENT_FRETE_NACIONAL,
                ])
            elif event_type == 'CLAIMS_ALL':
                qs = qs.filter(event_type__in=[
                    AuditLog.EventType.CLAIM_ATTEMPT,
                    AuditLog.EventType.CLAIM_SUCCESS,
                    AuditLog.EventType.CLAIM_CANCELLED,
                ])
            else:
                qs = qs.filter(event_type=event_type)

        # 3. Filtro por CEG
        ceg_id = request.GET.get('ceg_id', '').strip()
        if ceg_id and ceg_id.isdigit():
            qs = qs.filter(ceg_id=int(ceg_id))

        # 4. Filtro por Participante
        participant_id = request.GET.get('participant_id', '').strip()
        if participant_id and participant_id.isdigit():
            qs = qs.filter(participant_id=int(participant_id))

        # 5. Filtro por Intervalo de Datas
        date_from = request.GET.get('date_from', '').strip()
        if date_from:
            try:
                dt_from = datetime.strptime(date_from, '%Y-%m-%d')
                dt_from = timezone.make_aware(datetime.combine(dt_from.date(), time.min))
                qs = qs.filter(created_at__gte=dt_from)
            except ValueError:
                pass

        date_to = request.GET.get('date_to', '').strip()
        if date_to:
            try:
                dt_to = datetime.strptime(date_to, '%Y-%m-%d')
                dt_to = timezone.make_aware(datetime.combine(dt_to.date(), time.max))
                qs = qs.filter(created_at__lte=dt_to)
            except ValueError:
                pass

        # 6. Filtro por Status / Novo Valor
        status_filter = request.GET.get('status', '').strip()
        if status_filter == 'pago':
            qs = qs.filter(new_value__icontains='pago')
        elif status_filter == 'pendente':
            qs = qs.filter(new_value__icontains='pendente')

        # Exportação CSV
        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            filename = f"auditoria_logs_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'

            # Escreve BOM UTF-8 para Excel abrir acentos perfeitamente
            response.write('\ufeff'.encode('utf8'))
            writer = csv.writer(response, delimiter=';')
            writer.writerow([
                'ID', 'Data e Hora', 'Tipo de Evento', 'Ação / Detalhes',
                'Operador', 'Participante', 'WhatsApp', 'CEG', 'Alvo',
                'Valor Anterior', 'Novo Valor'
            ])

            for log in qs[:5000]:
                alvo = ""
                if log.slot:
                    alvo = f"Slot #{log.slot.id} ({log.slot.item_definition.name})"
                elif log.item_individual:
                    alvo = f"Mercari #{log.item_individual.id} ({log.item_individual.nome})"

                writer.writerow([
                    log.id,
                    log.created_at.strftime('%d/%m/%Y %H:%M:%S'),
                    log.get_event_type_display(),
                    log.action_label,
                    log.actor_name or 'Sistema',
                    log.participant_name,
                    log.participant_phone,
                    log.ceg.title if log.ceg else '',
                    alvo,
                    log.old_value,
                    log.new_value,
                ])
            return response

        # KPIs Rápidos
        total_logs = AuditLog.objects.count()
        total_accounts = AuditLog.objects.filter(event_type=AuditLog.EventType.ACCOUNT_CREATED).count()
        total_claims = AuditLog.objects.filter(
            event_type__in=[AuditLog.EventType.CLAIM_ATTEMPT, AuditLog.EventType.CLAIM_SUCCESS]
        ).count()
        total_payments = AuditLog.objects.filter(
            event_type__in=[
                AuditLog.EventType.PAYMENT_ITEM,
                AuditLog.EventType.PAYMENT_FRETE_INTER,
                AuditLog.EventType.PAYMENT_TAXA,
                AuditLog.EventType.PAYMENT_FRETE_NACIONAL,
            ]
        ).count()

        # Paginação
        paginator = Paginator(qs, 40)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        # Dados auxiliares para filtros
        cegs = CEG.objects.only('id', 'title', 'slug').order_by('-created_at')[:50]
        event_choices = AuditLog.EventType.choices

        # Preserva query string para paginação
        get_params = request.GET.copy()
        if 'page' in get_params:
            del get_params['page']
        pagination_query = get_params.urlencode()

        return render(request, 'cegs/auditoria.html', {
            'logs': page_obj,
            'page_obj': page_obj,
            'total_filtered': qs.count(),
            'total_logs': total_logs,
            'total_accounts': total_accounts,
            'total_claims': total_claims,
            'total_payments': total_payments,
            'cegs': cegs,
            'event_choices': event_choices,
            'q': q,
            'event_type': event_type,
            'ceg_id': ceg_id,
            'participant_id': participant_id,
            'date_from': date_from,
            'date_to': date_to,
            'status_filter': status_filter,
            'pagination_query': pagination_query,
        })
