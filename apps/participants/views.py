from django.shortcuts import render, redirect
from django.views import View
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from .models import Participant, Claim, ParticipantNotification, clean_phone_number
from apps.auth_otp.services import OTPService



class LoginOtpView(View):
    def get(self, request):
        next_url = request.GET.get('next', '').strip()
        if request.session.get('participant_id'):
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect('my_claims')
        phone = request.GET.get('phone', '')
        step = request.GET.get('step', 'phone')
        return render(request, 'participants/login_otp.html', {
            'phone': phone,
            'step': step,
            'next_url': next_url,
        })

    def post(self, request):
        action = request.POST.get('action')
        phone = request.POST.get('phone', '').strip()
        next_url = request.POST.get('next', '').strip() or request.GET.get('next', '').strip()
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if action == 'send_otp':
            success, msg, dev_code = OTPService.send_otp(phone)
            if is_ajax:
                return JsonResponse({'success': success, 'message': msg, 'dev_code': dev_code})
            if success:
                messages.success(request, msg)
                query = f"step=verify&phone={clean_phone_number(phone)}"
                if next_url:
                    from urllib.parse import quote
                    query += f"&next={quote(next_url)}"
                return redirect(f"/me/login/?{query}")
            else:
                messages.error(request, msg)
                return render(request, 'participants/login_otp.html', {'phone': phone, 'step': 'phone', 'next_url': next_url})

        elif action == 'verify_otp':
            code = request.POST.get('code', '').strip()
            success, msg, participant = OTPService.verify_otp(phone, code)

            target_redirect = next_url if (next_url and next_url.startswith('/')) else '/me/'

            if is_ajax:
                if success and participant:
                    request.session['participant_id'] = participant.id
                    return JsonResponse({'success': True, 'message': msg, 'redirect_url': target_redirect})
                return JsonResponse({'success': False, 'message': msg})

            if success and participant:
                request.session['participant_id'] = participant.id
                messages.success(request, f"Bem-vindo(a), {participant.display_name}!")
                if next_url and next_url.startswith('/'):
                    return redirect(next_url)
                return redirect('my_claims')
            else:
                messages.error(request, msg)
                return render(request, 'participants/login_otp.html', {
                    'phone': phone,
                    'step': 'verify',
                    'next_url': next_url
                })

        return redirect('login_otp')


class ProfileUpdateView(View):
    def post(self, request):
        participant_id = request.session.get('participant_id')
        if not participant_id:
            return redirect('login_otp')

        try:
            participant = Participant.objects.get(id=participant_id)
        except Participant.DoesNotExist:
            request.session.pop('participant_id', None)
            return redirect('login_otp')

        name = request.POST.get('name', '').strip()
        username = request.POST.get('username', '').strip()
        social_handle = request.POST.get('social_handle', '').strip()

        if not name:
            messages.error(request, "O nome do participante é obrigatório.")
            return redirect('my_claims')

        # Se informou o @ sem o prefixo '@', adiciona automaticamente para padronização
        if social_handle and not social_handle.startswith('@'):
            social_handle = f"@{social_handle}"

        participant.name = name
        participant.username = username
        participant.social_handle = social_handle
        participant.save(update_fields=['name', 'username', 'social_handle'])

        messages.success(request, f"✨ Perfil atualizado com sucesso, {participant.display_name}!")
        return redirect('my_claims')


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

        claims_list = list(claims)
        total_claims_count = len(claims_list)
        pending_claims_count = sum(1 for c in claims_list if c.status == Claim.Status.PENDING)
        paid_claims_count = sum(1 for c in claims_list if c.status == Claim.Status.PAID)

        # Agrupamento de reservas por CEG para facilitar o pagamento e visualização
        cegs_dict = {}
        groups_dict = {}

        for claim in claims_list:
            ceg = claim.slot.set.ceg
            group = ceg.era.group

            if group.id not in groups_dict:
                groups_dict[group.id] = {
                    'id': group.id,
                    'name': group.name,
                    'total_items': 0,
                }
            groups_dict[group.id]['total_items'] += 1

            if ceg.id not in cegs_dict:
                cegs_dict[ceg.id] = {
                    'ceg': ceg,
                    'group': group,
                    'claims': [],
                    'total_pending': 0,
                    'total_paid': 0,
                    'count_pending': 0,
                    'count_paid': 0,
                }
            cegs_dict[ceg.id]['claims'].append(claim)
            if claim.status == Claim.Status.PENDING:
                cegs_dict[ceg.id]['total_pending'] += claim.total_price
                cegs_dict[ceg.id]['count_pending'] += 1
            elif claim.status == Claim.Status.PAID:
                cegs_dict[ceg.id]['total_paid'] += claim.total_price
                cegs_dict[ceg.id]['count_paid'] += 1

        total_pending_all = sum(c['total_pending'] for c in cegs_dict.values())
        total_paid_all = sum(c['total_paid'] for c in cegs_dict.values())

        cegs_filter_list = [
            {
                'id': c_data['ceg'].id,
                'title': c_data['ceg'].title,
                'group_id': c_data['group'].id,
                'group_name': c_data['group'].name,
                'items_count': len(c_data['claims']),
                'count_pending': c_data['count_pending'],
                'count_paid': c_data['count_paid'],
            }
            for c_data in cegs_dict.values()
        ]
        groups_filter_list = sorted(groups_dict.values(), key=lambda g: g['name'])

        is_placeholder_name = participant.name.startswith('Participante ')

        # Notificações do participante
        notifications = list(participant.notifications.all()[:25])
        unread_notifications_count = sum(1 for n in notifications if not n.is_read)

        return render(request, 'participants/my_claims.html', {
            'participant': participant,
            'cegs_groups': list(cegs_dict.values()),
            'groups_filter_list': groups_filter_list,
            'cegs_filter_list': cegs_filter_list,
            'total_claims_count': total_claims_count,
            'pending_claims_count': pending_claims_count,
            'paid_claims_count': paid_claims_count,
            'total_pending_all': total_pending_all,
            'total_paid_all': total_paid_all,
            'is_placeholder_name': is_placeholder_name,
            'notifications': notifications,
            'unread_notifications_count': unread_notifications_count,
        })

    def post(self, request):
        return ProfileUpdateView.as_view()(request)


class MarkNotificationReadView(View):
    """Marca uma notificação como lida pelo participante."""
    def post(self, request, notification_id):
        participant_id = request.session.get('participant_id')
        if not participant_id:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Não autenticado'}, status=401)
            return redirect('login_otp')

        try:
            notif = ParticipantNotification.objects.get(id=notification_id, participant_id=participant_id)
            notif.mark_as_read()
        except ParticipantNotification.DoesNotExist:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Notificação não encontrada'}, status=404)
            return redirect('my_claims')

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            unread_count = ParticipantNotification.objects.filter(participant_id=participant_id, is_read=False).count()
            return JsonResponse({'success': True, 'unread_count': unread_count})

        messages.success(request, "Aviso marcado como lido.")
        return redirect('my_claims')


class MarkAllNotificationsReadView(View):
    """Marca todas as notificações do participante como lidas."""
    def post(self, request):
        participant_id = request.session.get('participant_id')
        if not participant_id:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Não autenticado'}, status=401)
            return redirect('login_otp')

        ParticipantNotification.objects.filter(participant_id=participant_id, is_read=False).update(
            is_read=True,
            read_at=timezone.now()
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'unread_count': 0})

        messages.success(request, "Todos os avisos foram marcados como lidos.")
        return redirect('my_claims')


class LogoutView(View):
    def get(self, request):
        request.session.pop('participant_id', None)
        messages.info(request, "Você encerrou sua sessão com sucesso.")
        return redirect('home')

