from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from .models import CEG, CEGSet, ItemSlot
from .services import ClaimService, CEGError


class HomeView(View):
    def get(self, request):
        now = timezone.now()
        active_cegs = CEG.objects.filter(status=CEG.Status.OPEN).select_related('era__group')
        scheduled_cegs = CEG.objects.filter(
            status=CEG.Status.SCHEDULED
        ).select_related('era__group').order_by('opens_at')
        closed_cegs = CEG.objects.filter(
            status__in=[CEG.Status.CLOSED, CEG.Status.COMPLETED]
        ).select_related('era__group')[:6]

        return render(request, 'home.html', {
            'active_cegs': active_cegs,
            'scheduled_cegs': scheduled_cegs,
            'closed_cegs': closed_cegs,
            'now': now,
        })


class CEGDetailView(View):
    def get(self, request, slug):
        ceg = get_object_or_404(
            CEG.objects.select_related('era__group'),
            slug=slug
        )

        # Carrega sets ativos com seus respectivos slots ordenados
        active_sets = ceg.sets.filter(is_active=True).prefetch_related(
            'slots__item_definition',
            'slots__claimed_by'
        ).order_by('set_number')

        return render(request, 'cegs/detail.html', {
            'ceg': ceg,
            'sets': active_sets,
            'countdown_seconds': ceg.countdown_seconds,
            'is_standby': ceg.is_standby,
            'is_open_for_claims': ceg.is_open_for_claims,
        })


class ClaimSlotView(View):
    def post(self, request, slot_id):
        slot = get_object_or_404(ItemSlot.objects.select_related('set__ceg'), id=slot_id)
        ceg = slot.set.ceg

        name = request.POST.get('name', '').strip()
        whatsapp = request.POST.get('whatsapp', '').strip()
        social_handle = request.POST.get('social_handle', '').strip()
        notes = request.POST.get('notes', '').strip()

        # Se o participante já estiver logado via OTP na sessão, aproveita os dados se não fornecidos
        logged_id = request.session.get('participant_id')
        if logged_id and not whatsapp:
            from apps.participants.models import Participant
            try:
                p = Participant.objects.get(id=logged_id)
                whatsapp = p.whatsapp
                if not name:
                    name = p.name
                if not social_handle:
                    social_handle = p.social_handle
            except Participant.DoesNotExist:
                pass

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json'

        try:
            claim = ClaimService.claim_slot(
                slot_id=slot.id,
                name=name,
                phone=whatsapp,
                social_handle=social_handle,
                notes=notes
            )
            # Salva o participante na sessão para que ele possa acompanhar os claims sem ter que logar de novo
            request.session['participant_id'] = claim.participant.id

            success_msg = (
                f"🎉 Reserva realizada com sucesso! Você pegou: {claim.slot.item_definition.name} "
                f"(Set {claim.slot.set.set_number}). Efetue o pagamento Pix para confirmar."
            )

            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': success_msg,
                    'claim_id': claim.id,
                    'total_price': str(claim.total_price),
                    'pix_key': ceg.pix_key,
                })

            messages.success(request, success_msg)
            return redirect('ceg_detail', slug=ceg.slug)

        except CEGError as e:
            err_msg = str(e)
            if is_ajax:
                return JsonResponse({'success': False, 'message': err_msg}, status=400)
            messages.error(request, err_msg)
            return redirect('ceg_detail', slug=ceg.slug)
        except Exception as e:
            err_msg = f"Erro inesperado ao processar reserva: {e}"
            if is_ajax:
                return JsonResponse({'success': False, 'message': err_msg}, status=500)
            messages.error(request, err_msg)
            return redirect('ceg_detail', slug=ceg.slug)
