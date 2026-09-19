import csv
import json
from datetime import datetime, time
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from apps.cegs.models import AuditLog, CEG, Caixa
from apps.groups.models import KpopGroup, Era
from apps.participants.models import Participant


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = '/admin/login/'
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class AuditDashboardView(StaffRequiredMixin, View):
    """
    Painel Central de Auditoria e Logs de Atividades.
    Permite filtrar e visualizar criação de contas, claims, pagamentos, envios e segmentações.
    """
    def get(self, request):
        qs = AuditLog.objects.select_related(
            'actor', 'participant', 'ceg', 'slot__item_definition',
            'slot__set__ceg', 'item_individual', 'pacote_nacional'
        ).all()

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
                Q(pacote_nacional__identificador__icontains=q) |
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
            elif event_type == 'PACKAGES_ALL':
                qs = qs.filter(event_type__in=[
                    AuditLog.EventType.PACKAGE_REQUESTED,
                    AuditLog.EventType.PACKAGE_SENT,
                    AuditLog.EventType.PACKAGE_DELIVERED,
                ])
            else:
                qs = qs.filter(event_type=event_type)

        # 3. Filtro por Grupo / Solista
        grupo_id = request.GET.get('grupo_id', '').strip()
        if grupo_id and grupo_id.isdigit():
            gid = int(grupo_id)
            qs = qs.filter(
                Q(ceg__era__group_id=gid) |
                Q(slot__set__ceg__era__group_id=gid) |
                Q(pacote_nacional__slots__set__ceg__era__group_id=gid)
            ).distinct()

        # 4. Filtro por Era / Comeback
        era_id = request.GET.get('era_id', '').strip()
        if era_id and era_id.isdigit():
            eid = int(era_id)
            qs = qs.filter(
                Q(ceg__era_id=eid) |
                Q(slot__set__ceg__era_id=eid) |
                Q(pacote_nacional__slots__set__ceg__era_id=eid)
            ).distinct()

        # 5. Filtro por CEG
        ceg_id = request.GET.get('ceg_id', '').strip()
        if ceg_id and ceg_id.isdigit():
            cid = int(ceg_id)
            qs = qs.filter(
                Q(ceg_id=cid) |
                Q(slot__set__ceg_id=cid) |
                Q(pacote_nacional__slots__set__ceg_id=cid)
            ).distinct()

        # 6. Filtro por Caixa / Remessa
        caixa_id = request.GET.get('caixa_id', '').strip()
        if caixa_id and caixa_id.isdigit():
            cx_id = int(caixa_id)
            qs = qs.filter(
                Q(ceg__caixa_id=cx_id) |
                Q(slot__set__ceg__caixa_id=cx_id) |
                Q(item_individual__caixa_id=cx_id) |
                Q(pacote_nacional__slots__set__ceg__caixa_id=cx_id) |
                Q(pacote_nacional__itens_individuais__caixa_id=cx_id)
            ).distinct()

        # 7. Filtro por Participante
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
                if log.pacote_nacional:
                    alvo = f"Pacote {log.pacote_nacional.identificador}"
                elif log.slot:
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
        cegs_qs = CEG.objects.select_related('era__group', 'caixa').only(
            'id', 'title', 'slug', 'era_id', 'era__group_id', 'era__group__name', 'era__name', 'caixa_id'
        ).order_by('title')
        caixas_qs = Caixa.objects.only('id', 'nome').order_by('nome')
        grupos_qs = KpopGroup.objects.only('id', 'name').order_by('name')
        eras_qs = Era.objects.select_related('group').only('id', 'name', 'group__name', 'group_id').order_by('group__name', 'name')
        event_choices = AuditLog.EventType.choices

        cegs_data = [
            {
                'id': c.id,
                'title': c.title,
                'caixa_id': c.caixa_id,
                'era_id': c.era_id,
                'group_id': c.era.group_id if c.era else None,
                'group_name': c.era.group.name if (c.era and c.era.group) else '',
                'era_name': c.era.name if c.era else '',
            }
            for c in cegs_qs
        ]
        eras_data = [
            {
                'id': e.id,
                'name': e.name,
                'group_id': e.group_id,
                'group_name': e.group.name if e.group else '',
            }
            for e in eras_qs
        ]
        grupos_data = [
            {
                'id': g.id,
                'name': g.name,
            }
            for g in grupos_qs
        ]
        caixas_data = [
            {
                'id': cx.id,
                'name': cx.nome,
            }
            for cx in caixas_qs
        ]

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
            'cegs': cegs_qs,
            'cegs_data': cegs_data,
            'caixas': caixas_qs,
            'grupos': grupos_qs,
            'eras': eras_qs,
            'cegs_json': json.dumps(cegs_data),
            'eras_json': json.dumps(eras_data),
            'grupos_json': json.dumps(grupos_data),
            'caixas_json': json.dumps(caixas_data),
            'event_choices': event_choices,
            'q': q,
            'event_type': event_type,
            'ceg_id': ceg_id,
            'caixa_id': caixa_id,
            'grupo_id': grupo_id,
            'era_id': era_id,
            'participant_id': participant_id,
            'date_from': date_from,
            'date_to': date_to,
            'status_filter': status_filter,
            'pagination_query': pagination_query,
        })
