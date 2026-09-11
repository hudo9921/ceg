from django.shortcuts import render, redirect
from django.views import View
from django.contrib import messages
from django.http import JsonResponse
from .models import Participant, Claim, clean_phone_number
from apps.auth_otp.services import OTPService


class LoginOtpView(View):
    def get(self, request):
        if request.session.get('participant_id'):
            return redirect('my_claims')
        phone = request.GET.get('phone', '')
        step = request.GET.get('step', 'phone')
        return render(request, 'participants/login_otp.html', {
            'phone': phone,
            'step': step,
        })

    def post(self, request):
        action = request.POST.get('action')
        phone = request.POST.get('phone', '').strip()
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if action == 'send_otp':
            success, msg, dev_code = OTPService.send_otp(phone)
            if is_ajax:
                return JsonResponse({'success': success, 'message': msg, 'dev_code': dev_code})
            if success:
                messages.success(request, msg)
                return redirect(f"/me/login/?step=verify&phone={clean_phone_number(phone)}")
            else:
                messages.error(request, msg)
                return render(request, 'participants/login_otp.html', {'phone': phone, 'step': 'phone'})

        elif action == 'verify_otp':
            code = request.POST.get('code', '').strip()
            success, msg, participant = OTPService.verify_otp(phone, code)

            if is_ajax:
                if success and participant:
                    request.session['participant_id'] = participant.id
                    return JsonResponse({'success': True, 'message': msg, 'redirect_url': '/me/'})
                return JsonResponse({'success': False, 'message': msg})

            if success and participant:
                request.session['participant_id'] = participant.id
                messages.success(request, f"Bem-vindo(a), {participant.name}!")
                return redirect('my_claims')
            else:
                messages.error(request, msg)
                return render(request, 'participants/login_otp.html', {
                    'phone': phone,
                    'step': 'verify'
                })

        return redirect('login_otp')


class MyClaimsView(View):
    def get(self, request):
        participant_id = request.session.get('participant_id')
        if not participant_id:
            return redirect('login_otp')

        try:
            participant = Participant.objects.get(id=participant_id)
        except Participant.DoesNotExist:
            request.session.pop('participant_id', None)
            return redirect('login_otp')

        claims = participant.claims.select_related(
            'slot__set__ceg__era__group',
            'slot__item_definition'
        ).order_by('-claimed_at')

        # Agrupamento de reservas por CEG para facilitar o pagamento e visualização
        cegs_dict = {}
        for claim in claims:
            ceg = claim.slot.set.ceg
            if ceg.id not in cegs_dict:
                cegs_dict[ceg.id] = {
                    'ceg': ceg,
                    'claims': [],
                    'total_pending': 0,
                    'total_paid': 0,
                }
            cegs_dict[ceg.id]['claims'].append(claim)
            if claim.status == Claim.Status.PENDING:
                cegs_dict[ceg.id]['total_pending'] += claim.total_price
            elif claim.status == Claim.Status.PAID:
                cegs_dict[ceg.id]['total_paid'] += claim.total_price

        total_pending_all = sum(c['total_pending'] for c in cegs_dict.values())
        total_paid_all = sum(c['total_paid'] for c in cegs_dict.values())

        return render(request, 'participants/my_claims.html', {
            'participant': participant,
            'cegs_groups': list(cegs_dict.values()),
            'total_claims_count': claims.count(),
            'total_pending_all': total_pending_all,
            'total_paid_all': total_paid_all,
        })


class LogoutView(View):
    def get(self, request):
        request.session.pop('participant_id', None)
        messages.info(request, "Você encerrou sua sessão com sucesso.")
        return redirect('home')
