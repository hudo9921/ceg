import json
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db.models import Q
from .models import CEG, CEGSet, ItemSlot
from .services import ClaimService, CEGError


class HomeView(View):
    def get(self, request):
        now = timezone.now()

        # 1. Transição Automática de Status:
        # CEGs agendadas cujo horário de abertura já chegou passam para OPEN
        CEG.objects.filter(
            status=CEG.Status.SCHEDULED,
            opens_at__lte=now
        ).update(status=CEG.Status.OPEN)

        # CEGs abertas que passaram do encerramento passam para CLOSED
        CEG.objects.filter(
            status=CEG.Status.OPEN,
            closes_at__lte=now
        ).update(status=CEG.Status.CLOSED)

        # 2. Busca CEGs abertas
        active_cegs = list(
            CEG.objects.filter(
                Q(status=CEG.Status.OPEN) | Q(status=CEG.Status.SCHEDULED, opens_at__lte=now)
            ).select_related('era__group').order_by('-created_at')
        )

        # 3. Busca apenas as agendadas cujo horário AINDA está no futuro
        scheduled_cegs = CEG.objects.filter(
            status=CEG.Status.SCHEDULED,
            opens_at__gt=now
        ).select_related('era__group').order_by('opens_at')

        closed_cegs = CEG.objects.filter(
            status__in=[CEG.Status.CLOSED, CEG.Status.COMPLETED]
        ).select_related('era__group')[:6]

        # 4. Agrupa os grupos presentes nas CEGs abertas para o filtro de grupos da Home
        open_groups_dict = {}
        for ceg in active_cegs:
            grp = ceg.era.group
            if grp.id not in open_groups_dict:
                open_groups_dict[grp.id] = {
                    'id': grp.id,
                    'name': grp.name,
                    'cegs_count': 0
                }
            open_groups_dict[grp.id]['cegs_count'] += 1

        open_groups = sorted(open_groups_dict.values(), key=lambda g: g['name'])

        return render(request, 'home.html', {
            'active_cegs': active_cegs,
            'open_groups': open_groups,
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

        now = timezone.now()
        if ceg.status == CEG.Status.SCHEDULED and ceg.opens_at and ceg.opens_at <= now:
            ceg.status = CEG.Status.OPEN
            ceg.save(update_fields=['status'])

        # Carrega sets ativos com seus respectivos slots ordenados
        active_sets = ceg.sets.filter(is_active=True).prefetch_related(
            'slots__item_definition',
            'slots__claimed_by'
        ).order_by('set_number')

        # Se o usuário for administrador/staff, carrega lista de participantes para seleção rápida
        all_participants = []
        if request.user.is_authenticated and request.user.is_staff:
            from apps.participants.models import Participant
            all_participants = list(
                Participant.objects.all().order_by('name').values(
                    'id', 'name', 'username', 'whatsapp', 'social_handle'
                )
            )

        return render(request, 'cegs/detail.html', {
            'ceg': ceg,
            'sets': active_sets,
            'countdown_seconds': ceg.countdown_seconds,
            'is_standby': ceg.is_standby,
            'is_open_for_claims': ceg.is_open_for_claims,
            'all_participants': all_participants,
            'all_participants_json': json.dumps(all_participants),
        })


class ClaimSlotView(View):
    def post(self, request, slot_id):
        slot = get_object_or_404(ItemSlot.objects.select_related('set__ceg'), id=slot_id)
        ceg = slot.set.ceg

        logged_id = request.session.get('participant_id')
        is_staff = request.user.is_authenticated and request.user.is_staff

        # 1. Se não estiver logado via telefone e não for staff, bloqueia e redireciona para login OTP
        if not logged_id and not is_staff:
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json'
            if is_ajax:
                return JsonResponse({
                    'success': False,
                    'requires_auth': True,
                    'redirect_url': f"/me/login/?next=/ceg/{ceg.slug}/",
                    'message': 'Por favor, autentique com seu WhatsApp para realizar reservas.'
                }, status=401)
            messages.error(request, 'Você precisa autenticar com seu WhatsApp para realizar reservas.')
            return redirect(f"/me/login/?next=/ceg/{ceg.slug}/")

        name = request.POST.get('name', '').strip()
        username = request.POST.get('username', '').strip()
        whatsapp = request.POST.get('whatsapp', '').strip()
        social_handle = request.POST.get('social_handle', '').strip()
        notes = request.POST.get('notes', '').strip()

        # 2. Se for participante comum logado, aproveita os dados cadastrados na sessão
        if logged_id:
            from apps.participants.models import Participant
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
                messages.error(request, 'Sessão expirada. Por favor, autentique novamente.')
                return redirect(f"/me/login/?next=/ceg/{ceg.slug}/")

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json'

        try:
            claim = ClaimService.claim_slot(
                slot_id=slot.id,
                name=name,
                phone=whatsapp,
                social_handle=social_handle,
                notes=notes,
                username=username
            )
            # Salva o participante na sessão se não for o admin realizando a reserva em nome de terceiro
            if not is_staff:
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


class ToggleSlotPaymentView(View):
    """
    Endpoint para o Organizador (Staff) alternar check marks de pagamento por item:
    - Item pago (is_item_paid)
    - Frete Inter pago (is_frete_inter_paid)
    - Taxa Aduaneira paga (is_taxa_aduaneira_paid)
    - Frete Nacional pago (is_frete_nacional_paid)
    """
    def post(self, request, slot_id):
        if not request.user.is_authenticated or not request.user.is_staff:
            return JsonResponse({
                'success': False,
                'message': 'Acesso restrito: apenas o organizador pode alterar status de pagamento.'
            }, status=403)

        slot = get_object_or_404(ItemSlot.objects.select_related('set__ceg', 'claimed_by'), id=slot_id)

        try:
            if request.content_type == 'application/json':
                body = json.loads(request.body.decode('utf-8') or '{}')
                field = body.get('field', '').strip()
                value = body.get('value')
            else:
                field = request.POST.get('field', '').strip()
                val_raw = request.POST.get('value')
                value = val_raw.lower() in ('true', '1', 'yes') if val_raw is not None else None

            if not field:
                return JsonResponse({'success': False, 'message': 'Parâmetro "field" é obrigatório.'}, status=400)

            new_val = slot.toggle_payment(field, value=value)

            return JsonResponse({
                'success': True,
                'slot_id': slot.id,
                'field': field,
                'new_value': new_val,
                'is_item_paid': slot.is_item_paid,
                'is_frete_inter_paid': slot.is_frete_inter_paid,
                'is_taxa_aduaneira_paid': slot.is_taxa_aduaneira_paid,
                'is_frete_nacional_paid': slot.is_frete_nacional_paid,
                'status': slot.status,
                'status_display': slot.get_status_display(),
            })
        except ValueError as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Erro ao atualizar status: {e}'}, status=500)


class UpdateCEGFeesView(View):
    """
    Permite ao organizador atualizar valores e prazos da CEG:
    - Prazo Pagamento Item
    - Frete Internacional (R$)
    - Taxa Aduaneira (R$)
    - Prazo Pagamento Frete Inter
    - Prazo Pagamento Taxa Aduaneira
    """
    def post(self, request, slug):
        if not request.user.is_authenticated or not request.user.is_staff:
            messages.error(request, "Acesso restrito ao organizador.")
            return redirect(f"/admin/login/?next={request.path}")

        ceg = get_object_or_404(CEG, slug=slug)

        def parse_dt(dt_str):
            if not dt_str:
                return None
            try:
                dt = parse_datetime(dt_str.strip())
                if dt and timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
                return dt
            except Exception:
                return None

        def parse_decimal(val_str):
            if val_str is None or val_str == '':
                return None
            val_clean = str(val_str).replace('R$', '').replace(' ', '').replace(',', '.').strip()
            if not val_clean:
                return None
            try:
                return Decimal(val_clean)
            except (InvalidOperation, ValueError):
                return None

        # Dados do form
        prazo_item_str = request.POST.get('prazo_pagamento_item', '').strip()
        frete_inter_str = request.POST.get('frete_inter', '').strip()
        taxa_aduaneira_str = request.POST.get('taxa_aduaneira', '').strip()
        prazo_frete_str = request.POST.get('prazo_pagamento_frete_inter', '').strip()
        prazo_taxa_str = request.POST.get('prazo_pagamento_taxa_aduaneira', '').strip()

        ceg.prazo_pagamento_item = parse_dt(prazo_item_str) if prazo_item_str else None
        ceg.frete_inter = parse_decimal(frete_inter_str)
        ceg.taxa_aduaneira = parse_decimal(taxa_aduaneira_str)
        ceg.prazo_pagamento_frete_inter = parse_dt(prazo_frete_str) if prazo_frete_str else None
        ceg.prazo_pagamento_taxa_aduaneira = parse_dt(prazo_taxa_str) if prazo_taxa_str else None

        ceg.save(update_fields=[
            'prazo_pagamento_item',
            'frete_inter',
            'taxa_aduaneira',
            'prazo_pagamento_frete_inter',
            'prazo_pagamento_taxa_aduaneira',
        ])

        messages.success(request, f"💰 Taxas e prazos da CEG '{ceg.title}' atualizados com sucesso!")
        return redirect('ceg_detail', slug=ceg.slug)

