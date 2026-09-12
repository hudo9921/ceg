import json
import logging
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db import transaction
from django.db.models import Q
from .models import CEG, CEGSet, ItemSlot
from apps.participants.models import Participant, Claim
from .services import ClaimService, CEGError, enrich_cegs_with_availability

logger = logging.getLogger(__name__)


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
        enrich_cegs_with_availability(active_cegs)

        # 3. Busca apenas as agendadas cujo horário AINDA está no futuro
        scheduled_cegs = list(
            CEG.objects.filter(
                status=CEG.Status.SCHEDULED,
                opens_at__gt=now
            ).select_related('era__group').order_by('opens_at')
        )
        enrich_cegs_with_availability(scheduled_cegs)

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


class ManageSlotView(View):
    """
    Permite ao organizador (staff) gerenciar um ItemSlot:
    - Editar o preço do slot (com opção de aplicar a todos os sets do item na CEG)
    - Remover claim / reserva (liberar slot)
    - Trocar participante do claim ou atribuir a um novo participante
    """
    def post(self, request, slot_id):
        if not request.user.is_authenticated or not request.user.is_staff:
            return JsonResponse({'success': False, 'message': 'Acesso restrito ao organizador.'}, status=403)

        slot = get_object_or_404(ItemSlot.objects.select_related('set__ceg', 'item_definition', 'claimed_by'), id=slot_id)

        try:
            if request.content_type == 'application/json':
                data = json.loads(request.body.decode('utf-8') or '{}')
            else:
                data = request.POST
        except Exception:
            data = request.POST

        action = data.get('action')
        price_val = data.get('price')
        apply_all_sets = data.get('apply_to_all_sets', False)
        if isinstance(apply_all_sets, str):
            apply_all_sets = apply_all_sets.lower() in ('true', '1', 'yes', 'on')
        remove_claim = data.get('remove_claim', False)
        if isinstance(remove_claim, str):
            remove_claim = remove_claim.lower() in ('true', '1', 'yes', 'on')
        participant_id = data.get('participant_id')

        with transaction.atomic():
            # 1. Atualização de Preço
            if price_val is not None and str(price_val).strip() != '':
                val_clean = str(price_val).replace('R$', '').replace(' ', '').replace(',', '.').strip()
                try:
                    new_price = Decimal(val_clean)
                    if new_price < 0:
                        return JsonResponse({'success': False, 'message': 'O preço não pode ser negativo.'}, status=400)
                    slot.price = new_price
                    if hasattr(slot, 'claim') and slot.claim:
                        slot.claim.total_price = new_price
                        slot.claim.save(update_fields=['total_price'])

                    if apply_all_sets:
                        ItemSlot.objects.filter(
                            set__ceg=slot.set.ceg,
                            item_definition=slot.item_definition
                        ).update(price=new_price)
                        slot.item_definition.default_price = new_price
                        slot.item_definition.save(update_fields=['default_price'])
                        Claim.objects.filter(
                            slot__set__ceg=slot.set.ceg,
                            slot__item_definition=slot.item_definition
                        ).update(total_price=new_price)
                except (InvalidOperation, ValueError):
                    return JsonResponse({'success': False, 'message': 'Valor de preço inválido.'}, status=400)

            # 2. Remover Reserva
            if remove_claim or action == 'remove_claim':
                if hasattr(slot, 'claim') and slot.claim:
                    slot.claim.delete()
                slot.claimed_by = None
                slot.claimed_at = None
                slot.status = ItemSlot.Status.AVAILABLE
                slot.is_item_paid = False
                slot.is_frete_inter_paid = False
                slot.is_taxa_aduaneira_paid = False
                slot.is_frete_nacional_paid = False

            # 3. Trocar ou Atribuir Participante
            elif participant_id:
                try:
                    new_participant = Participant.objects.get(id=participant_id)
                    slot.claimed_by = new_participant
                    if not slot.claimed_at:
                        slot.claimed_at = timezone.now()
                    if slot.status == ItemSlot.Status.AVAILABLE:
                        slot.status = ItemSlot.Status.RESERVED

                    if hasattr(slot, 'claim') and slot.claim:
                        slot.claim.participant = new_participant
                        slot.claim.save(update_fields=['participant'])
                    else:
                        Claim.objects.create(
                            slot=slot,
                            participant=new_participant,
                            total_price=slot.price,
                            status=Claim.Status.PAID if slot.is_item_paid else Claim.Status.PENDING
                        )
                except Participant.DoesNotExist:
                    return JsonResponse({'success': False, 'message': 'Participante não encontrado.'}, status=404)

            slot.save()

        return JsonResponse({
            'success': True,
            'message': 'Slot atualizado com sucesso!',
            'slot': {
                'id': slot.id,
                'price': f"{slot.price:.2f}",
                'status': slot.status,
                'status_display': slot.get_status_display(),
                'is_item_paid': slot.is_item_paid,
                'is_frete_inter_paid': slot.is_frete_inter_paid,
                'is_taxa_aduaneira_paid': slot.is_taxa_aduaneira_paid,
                'claimed_by': {
                    'id': slot.claimed_by.id,
                    'name': slot.claimed_by.name,
                    'display_name': slot.claimed_by.display_name,
                    'social_handle': slot.claimed_by.social_handle or '',
                    'whatsapp': slot.claimed_by.whatsapp or '',
                } if slot.claimed_by else None,
            }
        })


class DeleteSetView(View):
    """
    Permite ao organizador (staff) excluir um Set da CEG (por exemplo, quando o Set não fechou).
    Ao excluir o Set, todos os seus slots e eventuais reservas são permanentemente removidos.
    Além disso, notifica os participantes que estavam no set via WhatsApp Gateway.
    """
    def post(self, request, set_id):
        if not request.user.is_authenticated or not request.user.is_staff:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': 'Acesso restrito ao organizador.'}, status=403)
            messages.error(request, "Acesso restrito ao organizador.")
            return redirect(f"/admin/login/?next={request.path}")

        ceg_set = get_object_or_404(CEGSet.objects.select_related('ceg'), id=set_id)
        ceg = ceg_set.ceg
        set_number = ceg_set.set_number

        notify_participants = request.POST.get('notify_participants', 'true').lower() in ('true', '1', 'on', 'yes')
        custom_message = request.POST.get('custom_message', '').strip()

        # 1. Coleta participantes e itens reservados neste set ANTES de deletar
        claimed_slots = list(
            ceg_set.slots.filter(claimed_by__isnull=False)
            .select_related('claimed_by', 'item_definition')
        )

        # Agrupa por participante para enviar 1 mensagem consolidada por pessoa
        participants_data = {}
        for slot in claimed_slots:
            p = slot.claimed_by
            if p.id not in participants_data:
                participants_data[p.id] = {
                    'participant': p,
                    'items': [],
                    'has_paid': False,
                }
            participants_data[p.id]['items'].append({
                'name': slot.item_definition.name,
                'price': slot.price,
                'is_paid': slot.is_item_paid,
            })
            if slot.is_item_paid:
                participants_data[p.id]['has_paid'] = True

        # 2. Deleta o set em transação atômica
        with transaction.atomic():
            ceg_set.delete()

        # 3. Cria Notificações Internas no Painel do Participante (sempre persistido no banco)
        from apps.participants.models import ParticipantNotification
        for p_id, p_info in participants_data.items():
            p = p_info['participant']
            items_text_app = "\n".join(
                f"• {item['name']} — R$ {item['price']:.2f} ({'Pago ✔' if item['is_paid'] else 'Pendente'})"
                for item in p_info['items']
            )
            if p_info['has_paid']:
                payment_note_app = "⚠️ Importante: Como você já havia efetuado o pagamento deste item, entre em contato para estorno/reembolso via Pix ou transferência de crédito."
            else:
                payment_note_app = "ℹ️ Nenhuma cobrança foi efetuada para este item."
            extra_note_app = f"\n\n💬 Recado do organizador:\n{custom_message}" if custom_message else ""

            notification_message = (
                f"O Set #{set_number} da compra em grupo '{ceg.title}' infelizmente não atingiu o fechamento e precisou ser cancelado.\n\n"
                f"📦 Item(ns) que você tinha neste set:\n{items_text_app}\n\n"
                f"{payment_note_app}{extra_note_app}"
            )

            ParticipantNotification.objects.create(
                participant=p,
                title=f"Set #{set_number} Cancelado — {ceg.title}",
                message=notification_message,
                notification_type=ParticipantNotification.NotificationType.SET_CANCELLED,
            )

        # 4. Envia notificações via WhatsApp Gateway se solicitado
        notified_names = []
        if notify_participants and participants_data:
            from apps.auth_otp.providers import get_whatsapp_provider
            provider = get_whatsapp_provider()

            for p_id, p_info in participants_data.items():
                p = p_info['participant']
                if not p.whatsapp:
                    continue

                items_text = "\n".join(
                    f"• {item['name']} — R$ {item['price']:.2f} ({'Pago ✔' if item['is_paid'] else 'Pendente'})"
                    for item in p_info['items']
                )

                if p_info['has_paid']:
                    payment_note = "⚠️ *Importante:* Como você já havia efetuado o pagamento deste item, entre em contato para estorno/reembolso via Pix ou transferência de crédito."
                else:
                    payment_note = "ℹ️ Nenhuma cobrança foi efetuada para este item."

                extra_note = f"\n\n💬 *Recado do organizador:*\n{custom_message}" if custom_message else ""

                msg = (
                    f"Olá, {p.display_name}! 📢\n\n"
                    f"Informamos que o *Set #{set_number}* da compra em grupo *{ceg.title}* infelizmente não atingiu o fechamento e precisou ser cancelado.\n\n"
                    f"📦 *Item(ns) que você tinha neste set:*\n"
                    f"{items_text}\n\n"
                    f"{payment_note}"
                    f"{extra_note}\n\n"
                    f"Agradecemos muito pelo seu apoio e compreensão!"
                )

                try:
                    sent = provider.send_message(p.whatsapp, msg)
                    if sent:
                        notified_names.append(p.display_name)
                except Exception as e:
                    logger.error(f"Erro ao enviar notificação WhatsApp para {p.whatsapp}: {e}")

        # Mensagem de feedback
        msg = f"🗑️ Set #{set_number} excluído com sucesso da CEG '{ceg.title}'."
        if claimed_slots:
            msg += f" {len(claimed_slots)} reserva(s) foram canceladas e notificadas no painel de {len(participants_data)} participante(s)."
        if notified_names:
            msg += f" 📢 WhatsApp enviado para {len(notified_names)} participante(s): {', '.join(notified_names)}."


        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({
                'success': True,
                'message': msg,
                'set_number': set_number,
                'notified_count': len(notified_names),
                'notified_names': notified_names,
            })

        messages.success(request, msg)
        return redirect('ceg_detail', slug=ceg.slug)




