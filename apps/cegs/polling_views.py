import json
import logging
from django.views import View
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.cegs.models import CEG
from apps.cegs.polling_service import PollingDemandService, PollingError
from apps.participants.models import Participant

logger = logging.getLogger(__name__)


class CEGVoteView(View):
    """Endpoint público para envio de votos / pré-claims em uma CEG em status POLLING."""
    def post(self, request, slug):
        ceg = get_object_or_404(CEG, slug=slug)

        if ceg.status != CEG.Status.POLLING:
            return JsonResponse({
                'success': False,
                'message': f"Esta CEG não está em fase de Enquete (status: {ceg.get_status_display()})."
            }, status=400)

        if ceg.is_standby:
            prazo = ceg.opens_at.strftime('%d/%m/%Y às %H:%M:%S') if ceg.opens_at else 'em breve'
            return JsonResponse({
                'success': False,
                'message': f"A votação desta enquete ainda não abriu! Abertura oficial agendada para {prazo}."
            }, status=400)

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'message': 'Requisição JSON inválida.'}, status=400)

        item_def_ids = body.get('item_def_ids') or body.get('item_definition_ids') or []
        name = body.get('name', '').strip()
        whatsapp = body.get('whatsapp', '').strip()
        username = body.get('username', '').strip()
        social_handle = body.get('social_handle', '').strip()
        notes = body.get('notes', '').strip()

        # Se houver participante autenticado na sessão, preenche dados ausentes
        logged_id = request.session.get('participant_id')
        if logged_id:
            try:
                p = Participant.objects.get(id=logged_id)
                if not whatsapp:
                    whatsapp = p.whatsapp
                if not name:
                    name = p.name
                if not username:
                    username = p.username
                if not social_handle:
                    social_handle = p.social_handle
            except Participant.DoesNotExist:
                request.session.pop('participant_id', None)

        if not whatsapp:
            return JsonResponse({
                'success': False,
                'message': 'Por favor, informe seu número de WhatsApp para confirmar os votos.'
            }, status=400)

        if not item_def_ids:
            return JsonResponse({
                'success': False,
                'message': 'Selecione pelo menos 1 integrante/item para votar.'
            }, status=400)

        try:
            result = PollingDemandService.record_votes(
                ceg=ceg,
                item_def_ids=item_def_ids,
                name=name,
                phone=whatsapp,
                username=username,
                social_handle=social_handle,
                notes=notes,
                actor=request.user if request.user.is_authenticated else None,
            )

            # Salva na sessão o participante
            if not request.user.is_staff:
                request.session['participant_id'] = result['participant'].id

            summary = PollingDemandService.get_polling_summary(ceg)

            return JsonResponse({
                'success': True,
                'message': result['message'],
                'votes_registered': result['votes_registered'],
                'recorded_count': result['votes_registered'],
                'participant_name': result['participant'].display_name,
                'summary': summary,
            })

        except PollingError as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
        except Exception as e:
            logger.error(f"Erro ao processar votos na CEG {ceg.slug}: {e}", exc_info=True)
            return JsonResponse({'success': False, 'message': f"Erro interno: {e}"}, status=500)


class ConsolidatePollingView(LoginRequiredMixin, View):
    """Endpoint administrativo para consolidar a enquete e gerar N sets físicos com alocação."""
    def post(self, request, slug):
        if not request.user.is_staff:
            return HttpResponseForbidden("Apenas administradores podem consolidar enquetes.")

        ceg = get_object_or_404(CEG, slug=slug)

        is_json = request.content_type == 'application/json'
        if is_json:
            try:
                body = json.loads(request.body)
            except (json.JSONDecodeError, ValueError):
                return JsonResponse({'success': False, 'message': 'JSON inválido.'}, status=400)
            num_sets_str = body.get('num_sets', '1')
            notify_wa = body.get('notify_whatsapp', True)
        else:
            num_sets_str = request.POST.get('num_sets', '1')
            notify_wa = request.POST.get('notify_whatsapp') in ['true', '1', 'on', True]

        try:
            num_sets = int(num_sets_str)
            if num_sets < 1:
                raise ValueError()
        except (ValueError, TypeError):
            msg = "A quantidade de sets deve ser um número inteiro positivo maior que zero."
            if is_json:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect('ceg_detail', slug=ceg.slug)

        try:
            result = PollingDemandService.consolidate_polling_to_sets(
                ceg=ceg,
                num_sets=num_sets,
                actor=request.user,
                notify_whatsapp=notify_wa,
            )

            if is_json:
                return JsonResponse(result)

            messages.success(request, result['message'])
            return redirect('ceg_detail', slug=ceg.slug)

        except PollingError as e:
            if is_json:
                return JsonResponse({'success': False, 'message': str(e)}, status=400)
            messages.error(request, str(e))
            return redirect('ceg_detail', slug=ceg.slug)
        except Exception as e:
            logger.error(f"Erro ao consolidar CEG {ceg.slug}: {e}", exc_info=True)
            msg = f"Erro interno ao consolidar: {e}"
            if is_json:
                return JsonResponse({'success': False, 'message': msg}, status=500)
            messages.error(request, msg)
            return redirect('ceg_detail', slug=ceg.slug)


class CEGPollingSummaryAPIView(View):
    """Retorna o resumo da enquete de demanda (contagem de votos por item e status)."""
    def get(self, request, slug):
        ceg = get_object_or_404(CEG, slug=slug)
        summary = PollingDemandService.get_polling_summary(ceg)
        return JsonResponse(summary)
