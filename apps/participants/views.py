import json
from django.shortcuts import render, redirect
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.http import JsonResponse
from django.utils import timezone
from .models import Participant, Claim, ParticipantNotification, clean_phone_number
from .services import BulkParticipantService
from apps.auth_otp.services import OTPService


class StaffRequiredMixin(AccessMixin):
    """Garante que apenas usuários autenticados e com permissão de staff (admin/organizador) tenham acesso."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': 'Acesso restrito ao organizador.'}, status=403)
            messages.error(request, "Acesso restrito: Você precisa estar autenticado como Administrador/Organizador.")
            return redirect(f"/admin/login/?next={request.path}")
        return super().dispatch(request, *args, **kwargs)


class BulkParticipantCreateView(StaffRequiredMixin, View):
    """
    Interface para cadastro de participantes em massa.
    Permite colar linhas (Excel, Sheets, CSV, TSV) ou usar grade dinâmica interativa,
    com suporte robusto a números brasileiros (DDD 9 dígitos) e internacionais (+DDI).
    """

    def get(self, request):
        recent_participants = Participant.objects.all().order_by('-created_at')[:25]
        total_participants = Participant.objects.count()
        with_twitter = Participant.objects.exclude(social_handle='').count()

        return render(request, 'participants/bulk_create.html', {
            'recent_participants': recent_participants,
            'total_participants': total_participants,
            'with_twitter': with_twitter,
        })

    def post(self, request):
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json'

        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body.decode('utf-8'))
            except Exception:
                return JsonResponse({'success': False, 'message': 'JSON inválido.'}, status=400)
            action = data.get('action', 'save')
            raw_text = data.get('raw_text', '')
            items = data.get('items', [])
            default_ddi = str(data.get('default_ddi', '55')).strip() or '55'
            update_existing = bool(data.get('update_existing', True))
        else:
            action = request.POST.get('action', 'save')
            raw_text = request.POST.get('raw_text', '')
            items_json = request.POST.get('items_json', '')
            items = json.loads(items_json) if items_json else []
            default_ddi = str(request.POST.get('default_ddi', '55')).strip() or '55'
            update_existing = request.POST.get('update_existing', 'true').lower() in ('true', '1', 'yes', 'on')

        # Ação 1: Apenas pré-visualizar / parsear linhas coladas
        if action == 'parse':
            parsed_items = BulkParticipantService.parse_pasted_text(raw_text, default_ddi=default_ddi)
            # Verifica quais já existem no banco
            for item in parsed_items:
                if item.get('whatsapp'):
                    existing = Participant.objects.filter(whatsapp=item['whatsapp']).first()
                    item['already_exists'] = bool(existing)
                    item['existing_name'] = existing.name if existing else ''
                    item['existing_handle'] = existing.social_handle if existing else ''
                else:
                    item['already_exists'] = False
                    item['existing_name'] = ''
                    item['existing_handle'] = ''
            return JsonResponse({'success': True, 'items': parsed_items, 'total': len(parsed_items)})

        # Ação 2: Salvar no banco (direto do texto colado ou do array de itens)
        if not items and raw_text:
            items = BulkParticipantService.parse_pasted_text(raw_text, default_ddi=default_ddi)

        if not items:
            msg = "Nenhum participante válido foi informado para cadastro."
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect('bulk_participant_create')

        report = BulkParticipantService.bulk_create_or_update(
            items=items,
            update_existing=update_existing,
            default_ddi=default_ddi,
        )

        created_c = report['created_count']
        updated_c = report['updated_count']
        errors_c = report['errors_count']

        success_msg = f"Sucesso: {created_c} novo(s) participante(s) cadastrado(s)"
        if updated_c:
            success_msg += f" e {updated_c} atualizado(s)"
        success_msg += "."

        if errors_c:
            success_msg += f" ({errors_c} linha(s) ignorada(s) por dados incompletos)."

        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': success_msg,
                'created_count': created_c,
                'updated_count': updated_c,
                'errors_count': errors_c,
                'errors': report['errors'],
            })

        messages.success(request, success_msg)
        return redirect('bulk_participant_create')




class LoginOtpView(View):
    def get(self, request):
        next_url = request.GET.get('next', '').strip()
        if request.session.get('participant_id'):
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect('my_claims')
        phone = request.GET.get('phone', '').strip()
        step = request.GET.get('step', 'phone')

        formatted_phone_display = ""
        if phone:
            cleaned = clean_phone_number(phone)
            dummy = Participant(whatsapp=cleaned)
            formatted_phone_display = dummy.formatted_phone

        return render(request, 'participants/login_otp.html', {
            'phone': phone,
            'formatted_phone': formatted_phone_display,
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
            'slot__set__ceg__caixa',
            'slot__item_definition',
            'slot__pacote_nacional'
        ).order_by('-claimed_at')

        claims_list = list(claims)
        total_claims_count = len(claims_list)
        pending_claims_count = sum(1 for c in claims_list if c.status == Claim.Status.PENDING)
        paid_claims_count = sum(1 for c in claims_list if c.status == Claim.Status.PAID)

        # Itens Individuais (Mercari) vinculados ao participante
        itens_individuais = participant.itens_individuais.select_related('caixa', 'pacote_nacional').order_by('-created_at')
        itens_individuais_list = list(itens_individuais)
        itens_individuais_count = len(itens_individuais_list)

        # Pacotes Nacionais de envio do participante
        pacotes_nacionais = list(participant.pacotes_nacionais.prefetch_related(
            'slots__item_definition',
            'slots__set__ceg',
            'itens_individuais'
        ).order_by('-created_at'))
        itens_frete_unpaid_count = sum(1 for it in itens_individuais_list if it.frete_inter and it.frete_inter > 0 and not it.frete_inter_pago)
        itens_taxa_unpaid_count = sum(1 for it in itens_individuais_list if it.taxa_aduaneira and it.taxa_aduaneira > 0 and not it.taxa_aduaneira_paga)

        # Contagens de frete inter e taxa não pagos (apenas quando o valor cadastrado na CEG for > 0)
        inter_unpaid_count = sum(
            1 for c in claims_list
            if c.slot.set.ceg.frete_inter and c.slot.set.ceg.frete_inter > 0 and not c.slot.is_frete_inter_paid
        )
        taxa_unpaid_count = sum(
            1 for c in claims_list
            if c.slot.set.ceg.taxa_aduaneira and c.slot.set.ceg.taxa_aduaneira > 0 and not c.slot.is_taxa_aduaneira_paid
        )

        # Agrupamento de reservas por CEG para facilitar o pagamento e visualização
        cegs_dict = {}
        groups_dict = {}
        caixas_dict = {}
        itens_sem_caixa_count = 0

        for claim in claims_list:
            ceg = claim.slot.set.ceg
            group = ceg.era.group

            if ceg.caixa:
                c = ceg.caixa
                if c.id not in caixas_dict:
                    caixas_dict[c.id] = {
                        'id': c.id,
                        'nome': c.nome,
                        'slug': c.slug,
                        'origem': c.origem,
                        'origem_display': c.get_origem_display(),
                        'status': c.status,
                        'status_display': c.get_status_display(),
                        'codigo_rastreio': c.codigo_rastreio,
                        'tracking_url': c.tracking_url,
                        'prazo_frete': c.prazo_frete,
                        'prazo_taxa': c.prazo_taxa,
                        'items_count': 0,
                        'cegs_ids': set(),
                        'mercari_count': 0,
                    }
                caixas_dict[c.id]['items_count'] += 1
                caixas_dict[c.id]['cegs_ids'].add(ceg.id)
            else:
                itens_sem_caixa_count += 1

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
                    'caixa': ceg.caixa,
                    'caixa_id': str(ceg.caixa_id) if ceg.caixa_id else '',
                    'claims': [],
                    'total_pending': 0,
                    'total_paid': 0,
                    'count_pending': 0,
                    'count_paid': 0,
                    'count_inter_unpaid': 0,
                    'count_taxa_unpaid': 0,
                }
            cegs_dict[ceg.id]['claims'].append(claim)
            if claim.status == Claim.Status.PENDING:
                cegs_dict[ceg.id]['total_pending'] += claim.total_price
                cegs_dict[ceg.id]['count_pending'] += 1
            elif claim.status == Claim.Status.PAID:
                cegs_dict[ceg.id]['total_paid'] += claim.total_price
                cegs_dict[ceg.id]['count_paid'] += 1

            if ceg.frete_inter and ceg.frete_inter > 0 and not claim.slot.is_frete_inter_paid:
                cegs_dict[ceg.id]['count_inter_unpaid'] += 1
            if ceg.taxa_aduaneira and ceg.taxa_aduaneira > 0 and not claim.slot.is_taxa_aduaneira_paid:
                cegs_dict[ceg.id]['count_taxa_unpaid'] += 1

        for item in itens_individuais_list:
            qtd = item.quantidade or 1
            if item.caixa:
                c = item.caixa
                if c.id not in caixas_dict:
                    caixas_dict[c.id] = {
                        'id': c.id,
                        'nome': c.nome,
                        'slug': c.slug,
                        'origem': c.origem,
                        'origem_display': c.get_origem_display(),
                        'status': c.status,
                        'status_display': c.get_status_display(),
                        'codigo_rastreio': c.codigo_rastreio,
                        'tracking_url': c.tracking_url,
                        'prazo_frete': c.prazo_frete,
                        'prazo_taxa': c.prazo_taxa,
                        'items_count': 0,
                        'cegs_ids': set(),
                        'mercari_count': 0,
                    }
                caixas_dict[c.id]['items_count'] += qtd
                caixas_dict[c.id]['mercari_count'] += qtd
            else:
                itens_sem_caixa_count += qtd

        caixas_list = []
        for c_id, c_data in caixas_dict.items():
            c_data['cegs_count'] = len(c_data['cegs_ids'])
            caixas_list.append(c_data)

        caixas_list.sort(key=lambda x: x['nome'])

        total_pending_all = sum(c['total_pending'] for c in cegs_dict.values())
        total_paid_all = sum(c['total_paid'] for c in cegs_dict.values())

        cegs_filter_list = [
            {
                'id': c_data['ceg'].id,
                'title': c_data['ceg'].title,
                'group_id': c_data['group'].id,
                'group_name': c_data['group'].name,
                'caixa_id': c_data['caixa_id'],
                'items_count': len(c_data['claims']),
                'count_pending': c_data['count_pending'],
                'count_paid': c_data['count_paid'],
                'count_inter_unpaid': c_data['count_inter_unpaid'],
                'count_taxa_unpaid': c_data['count_taxa_unpaid'],
            }
            for c_data in cegs_dict.values()
        ]
        groups_filter_list = sorted(groups_dict.values(), key=lambda g: g['name'])

        mercari_filter_list = [
            {
                'id': it.id,
                'caixa_id': str(it.caixa_id) if it.caixa_id else '',
                'status': it.status,
                'frete_inter': float(it.frete_inter or 0),
                'frete_inter_pago': it.frete_inter_pago,
                'taxa_aduaneira': float(it.taxa_aduaneira or 0),
                'taxa_aduaneira_paga': it.taxa_aduaneira_paga,
            }
            for it in itens_individuais_list
        ]

        is_placeholder_name = participant.name.startswith('Participante ')

        # Notificações do participante
        notifications = list(participant.notifications.all()[:25])
        unread_notifications_count = sum(1 for n in notifications if not n.is_read)

        itens_frete_unpaid_total = sum(it.frete_inter for it in itens_individuais_list if it.frete_inter and not it.frete_inter_pago)
        itens_taxa_unpaid_total = sum(it.taxa_aduaneira for it in itens_individuais_list if it.taxa_aduaneira and not it.taxa_aduaneira_paga)

        return render(request, 'participants/my_claims.html', {
            'participant': participant,
            'cegs_groups': list(cegs_dict.values()),
            'groups_filter_list': groups_filter_list,
            'cegs_filter_list': cegs_filter_list,
            'mercari_filter_list': mercari_filter_list,
            'caixas_list': caixas_list,
            'itens_sem_caixa_count': itens_sem_caixa_count,
            'total_claims_count': total_claims_count,
            'pending_claims_count': pending_claims_count,
            'paid_claims_count': paid_claims_count,
            'inter_unpaid_count': inter_unpaid_count,
            'taxa_unpaid_count': taxa_unpaid_count,
            'total_pending_all': total_pending_all,
            'total_paid_all': total_paid_all,
            'itens_individuais': itens_individuais_list,
            'itens_individuais_count': itens_individuais_count,
            'itens_frete_unpaid_count': itens_frete_unpaid_count,
            'itens_taxa_unpaid_count': itens_taxa_unpaid_count,
            'itens_frete_unpaid_total': itens_frete_unpaid_total,
            'itens_taxa_unpaid_total': itens_taxa_unpaid_total,
            'is_placeholder_name': is_placeholder_name,
            'notifications': notifications,
            'unread_notifications_count': unread_notifications_count,
            'pacotes_nacionais': pacotes_nacionais,
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

