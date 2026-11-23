"""Direitos do titular (LGPD) no painel do joiner + página pública de privacidade."""
import json

from django.contrib import messages
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from apps.core.privacy import export_participant_data, request_deletion
from .session_auth import get_session_participant


class _ParticipantRequired(View):
    def dispatch(self, request, *args, **kwargs):
        self.participant = get_session_participant(request)
        if not self.participant:
            return redirect(f"/me/login/?next={request.path}")
        return super().dispatch(request, *args, **kwargs)


class ExportMyDataView(_ParticipantRequired):
    """Baixa em JSON todos os dados pessoais do joiner logado."""

    def get(self, request):
        from apps.cegs.models import AuditLog
        from apps.cegs.audit_service import AuditService

        data = export_participant_data(self.participant)
        AuditService.log_event(
            event_type=AuditLog.EventType.DATA_EXPORT,
            action_label="Joiner baixou seus dados pessoais (LGPD)",
            participant=self.participant,
        )
        filename = f"meus-dados-valcegs-{timezone.localdate():%Y%m%d}.json"
        response = HttpResponse(
            json.dumps(data, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2),
            content_type='application/json; charset=utf-8',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Cache-Control'] = 'no-store'
        return response


class RequestDataDeletionView(_ParticipantRequired):
    """Registra o pedido de exclusão e avisa a GOM (a anonimização é feita pelo staff)."""

    def post(self, request):
        if request.POST.get('confirmacao', '').strip().upper() != 'EXCLUIR':
            messages.error(request, 'Digite EXCLUIR para confirmar o pedido de exclusão.')
            return redirect('my_claims')
        if request_deletion(self.participant):
            messages.success(request, 'Pedido de exclusão enviado. A organização vai concluir as '
                                      'pendências e anonimizar sua conta.')
        else:
            messages.info(request, 'Seu pedido de exclusão já foi registrado e está em andamento.')
        return redirect('my_claims')


class PrivacyPolicyView(View):
    def get(self, request):
        from django.conf import settings
        return render(request, 'participants/privacidade.html', {
            'settings_pii_days': settings.PII_RETENTION_DAYS,
        })
