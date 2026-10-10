from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views import View

from apps.cegs.models import GOMNotification
from apps.cegs.audit_service import AuditService


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = '/admin/login/'

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

    def handle_no_permission(self):
        is_ajax = (
            self.request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or 'application/json' in self.request.headers.get('accept', '')
            or self.request.content_type == 'application/json'
        )
        if is_ajax:
            if not self.request.user.is_authenticated:
                return JsonResponse({'success': False, 'error': 'Autenticação necessária.'}, status=401)
            return JsonResponse({'success': False, 'error': 'Acesso restrito à equipe GOM.'}, status=403)
        return super().handle_no_permission()


class GOMNotificationsView(StaffRequiredMixin, View):
    """
    Central de Notificações Operacionais da GOM.
    Exibe feed filtrável por tipo de ação (Claims, Solicitações de Envio, Pagamentos, Enquetes e Cadastros).
    """
    def get(self, request):
        # Auto-sincronização de eventos retroativos caso ainda não existam notificações
        AuditService.sync_recent_gom_notifications(50)

        qs = GOMNotification.objects.select_related(
            'participant',
            'ceg__era__group',
            'slot__item_definition',
            'pacote_nacional',
        ).all()

        # 1. Filtro por tipo de ação
        action_type = request.GET.get('action_type', 'all').strip().lower()
        if action_type == 'claims':
            qs = qs.filter(notification_type__in=[
                GOMNotification.NotificationType.CLAIM,
                GOMNotification.NotificationType.CLAIM_CANCELLED,
            ])
        elif action_type == 'solicitacoes':
            qs = qs.filter(notification_type=GOMNotification.NotificationType.PACKAGE_REQUEST)
        elif action_type == 'pagamentos':
            qs = qs.filter(notification_type=GOMNotification.NotificationType.PAYMENT)
        elif action_type == 'enquetes':
            qs = qs.filter(notification_type=GOMNotification.NotificationType.POLLING)
        elif action_type == 'cadastros':
            qs = qs.filter(notification_type=GOMNotification.NotificationType.ACCOUNT)

        # 2. Filtro por lida / não lida
        unread_only = request.GET.get('unread', '').strip().lower() in ('true', '1')
        if unread_only:
            qs = qs.filter(is_read=False)

        # 3. Busca textual
        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q) |
                Q(message__icontains=q) |
                Q(participant__name__icontains=q) |
                Q(ceg__title__icontains=q)
            )

        # Contadores para as abas
        all_notifs = GOMNotification.objects.all()
        total_notifications = all_notifs.count()
        total_unread = all_notifs.filter(is_read=False).count()
        count_claims = all_notifs.filter(notification_type__in=[
            GOMNotification.NotificationType.CLAIM,
            GOMNotification.NotificationType.CLAIM_CANCELLED,
        ]).count()
        count_solicitacoes = all_notifs.filter(notification_type=GOMNotification.NotificationType.PACKAGE_REQUEST).count()
        count_pagamentos = all_notifs.filter(notification_type=GOMNotification.NotificationType.PAYMENT).count()
        count_enquetes = all_notifs.filter(notification_type=GOMNotification.NotificationType.POLLING).count()
        count_cadastros = all_notifs.filter(notification_type=GOMNotification.NotificationType.ACCOUNT).count()

        # Paginação (25 notificações por página)
        paginator = Paginator(qs, 25)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        # Preserva query string para paginação
        get_params = request.GET.copy()
        if 'page' in get_params:
            del get_params['page']
        pagination_query = get_params.urlencode()

        return render(request, 'cegs/notificacoes.html', {
            'notifications': page_obj,
            'page_obj': page_obj,
            'total_filtered': qs.count(),
            'total_notifications': total_notifications,
            'total_unread': total_unread,
            'count_claims': count_claims,
            'count_solicitacoes': count_solicitacoes,
            'count_pagamentos': count_pagamentos,
            'count_enquetes': count_enquetes,
            'count_cadastros': count_cadastros,
            'action_type': action_type,
            'unread_only': unread_only,
            'q': q,
            'pagination_query': pagination_query,
        })


@method_decorator(csrf_exempt, name='dispatch')
class MarkGOMNotificationReadView(StaffRequiredMixin, View):
    """Marca uma notificação individual como lida via AJAX."""
    def post(self, request, notification_id):
        notif = get_object_or_404(GOMNotification, id=notification_id)
        notif.mark_as_read()
        unread_count = GOMNotification.objects.filter(is_read=False).count()
        return JsonResponse({
            'success': True,
            'notification_id': notif.id,
            'is_read': True,
            'unread_count': unread_count,
        })

    def get(self, request, notification_id):
        return self.post(request, notification_id)


@method_decorator(csrf_exempt, name='dispatch')
class MarkAllGOMNotificationsReadView(StaffRequiredMixin, View):
    """Marca todas as notificações (ou filtradas por tipo) como lidas via AJAX."""
    def post(self, request):
        action_type = (request.POST.get('action_type') or request.GET.get('action_type', 'all')).strip().lower()
        qs = GOMNotification.objects.filter(is_read=False)

        if action_type == 'claims':
            qs = qs.filter(notification_type__in=[
                GOMNotification.NotificationType.CLAIM,
                GOMNotification.NotificationType.CLAIM_CANCELLED,
            ])
        elif action_type == 'solicitacoes':
            qs = qs.filter(notification_type=GOMNotification.NotificationType.PACKAGE_REQUEST)
        elif action_type == 'pagamentos':
            qs = qs.filter(notification_type=GOMNotification.NotificationType.PAYMENT)
        elif action_type == 'enquetes':
            qs = qs.filter(notification_type=GOMNotification.NotificationType.POLLING)
        elif action_type == 'cadastros':
            qs = qs.filter(notification_type=GOMNotification.NotificationType.ACCOUNT)

        updated_count = qs.update(is_read=True, read_at=timezone.now())
        remaining_unread = GOMNotification.objects.filter(is_read=False).count()

        return JsonResponse({
            'success': True,
            'updated_count': updated_count,
            'unread_count': remaining_unread,
        })

    def get(self, request):
        return self.post(request)
