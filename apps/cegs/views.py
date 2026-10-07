import json
import logging
import re
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db import transaction
from django.db.models import Q, Count, Prefetch
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from apps.groups.models import Era
from .models import Caixa, CEG, CEGSet, ItemSlot, ItemWaitingList, ClaimAttemptLog, CEGItemDefinition, TipoItem, HomeBannerConfig
from apps.participants.models import Participant, Claim
from .services import ClaimService, CEGError, AddedToWaitingListError, enrich_cegs_with_availability
from .creations_views import StaffRequiredMixin
from .image_utils import process_image_upload, crop_image_from_coordinates

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

        # CEGs abertas que passaram do encerramento SÓ passam para CLOSED se NÃO houverem mais vagas disponíveis
        expired_open_cegs = CEG.objects.filter(
            status=CEG.Status.OPEN,
            closes_at__lte=now
        )
        if expired_open_cegs.exists():
            cegs_with_available_slots = set(
                ItemSlot.objects.filter(
                    set__ceg__in=expired_open_cegs,
                    set__is_active=True,
                    status=ItemSlot.Status.AVAILABLE
                ).values_list('set__ceg_id', flat=True).distinct()
            )
            expired_open_cegs.exclude(
                id__in=cegs_with_available_slots
            ).update(status=CEG.Status.CLOSED)

        # 2. Busca CEGs abertas
        raw_open_cegs = list(
            CEG.objects.filter(
                Q(status=CEG.Status.OPEN) | Q(status=CEG.Status.SCHEDULED, opens_at__lte=now)
            ).select_related('era__group').order_by('-created_at')
        )
        enrich_cegs_with_availability(raw_open_cegs)

        # Filtra para mostrar apenas CEGs onde existem itens vagos nos sets (ao menos 1 item disponível em algum set)
        active_cegs = [c for c in raw_open_cegs if getattr(c, 'available_slots_count', 0) > 0]
        full_cegs = [c for c in raw_open_cegs if getattr(c, 'available_slots_count', 0) == 0]

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

        # 4. Agrupa os grupos, eras e integrantes presentes nas CEGs abertas para os filtros da Home
        open_groups_dict = {}
        open_eras_dict = {}
        open_members_set = set()

        for ceg in active_cegs:
            grp = ceg.era.group
            era = ceg.era

            # Grupos
            if grp.id not in open_groups_dict:
                open_groups_dict[grp.id] = {
                    'id': grp.id,
                    'name': grp.name,
                    'image_url': grp.image_url or '',
                    'color_hex': grp.color_hex or '',
                    'cegs_count': 0
                }
            open_groups_dict[grp.id]['cegs_count'] += 1

            # Eras
            if era.id not in open_eras_dict:
                open_eras_dict[era.id] = {
                    'id': era.id,
                    'name': era.name,
                    'group_id': grp.id,
                    'group_name': grp.name,
                    'cegs_count': 0
                }
            open_eras_dict[era.id]['cegs_count'] += 1

            # Integrantes disponíveis na CEG para busca/filtro
            ceg_members = []
            for item in getattr(ceg, 'grouped_available_items', []):
                m_name = item.get('member_name') or item.get('item_name')
                if m_name:
                    m_clean = m_name.strip()
                    open_members_set.add(m_clean)
                    ceg_members.append(m_clean.lower())
            ceg.available_members_str = ' '.join(ceg_members)

        open_groups = sorted(open_groups_dict.values(), key=lambda g: g['name'])
        open_eras = sorted(open_eras_dict.values(), key=lambda e: (e['group_name'], e['name']))
        open_members = sorted(open_members_set, key=lambda m: m.lower())

        # 5. Agrupa a pool de tipos de item (das caixas / TipoItem) presentes nas CEGs abertas
        all_tipos_pool = list(TipoItem.objects.all().order_by('nome'))
        count_mistas = sum(1 for c in active_cegs if getattr(c, 'is_mista', False))
        pool_tipos_item = []
        for t in all_tipos_pool:
            t.count_apenas = sum(1 for c in active_cegs if getattr(c, 'exclusive_tipo_id', None) == t.id)
            t.count_contem = sum(1 for c in active_cegs if t.id in getattr(c, 'tipo_ids_list', []))
            pool_tipos_item.append(t)

        ceg_share_map = {}
        if request.user.is_authenticated and request.user.is_staff:
            for c in list(active_cegs) + list(full_cegs) + list(scheduled_cegs):
                if hasattr(c, 'share_data'):
                    ceg_share_map[c.id] = c.share_data

        home_banner = HomeBannerConfig.get_active()

        return render(request, 'home.html', {
            'active_cegs': active_cegs,
            'full_cegs': full_cegs,
            'open_groups': open_groups,
            'open_eras': open_eras,
            'open_members': open_members,
            'pool_tipos_item': pool_tipos_item,
            'count_mistas': count_mistas,
            'scheduled_cegs': scheduled_cegs,
            'closed_cegs': closed_cegs,
            'ceg_share_map': ceg_share_map,
            'ceg_share_map_json': json.dumps(ceg_share_map),
            'home_banner': home_banner,
            'now': now,
        })


class UpdateHomeBannerView(StaffRequiredMixin, View):
    """Atualiza as imagens de banner da tela inicial (Modo Claro e Modo Escuro)."""
    def post(self, request):
        banner_config = HomeBannerConfig.objects.filter(is_active=True).first()
        if not banner_config:
            banner_config = HomeBannerConfig()

        # Banner Modo Claro
        light_file = request.FILES.get('banner_light_file')
        light_url = request.POST.get('banner_light_url', '').strip()
        light_b64 = request.POST.get('banner_light_b64', '').strip()
        if light_file or light_b64:
            try:
                banner_config.banner_light_url = process_image_upload(
                    file_obj=light_file,
                    base64_str=light_b64,
                    folder='banners',
                    fallback_url=light_url
                )
            except Exception as e:
                logger.error(f"Erro ao processar banner claro: {e}")
        elif light_url:
            banner_config.banner_light_url = light_url

        # Banner Modo Escuro
        dark_file = request.FILES.get('banner_dark_file')
        dark_url = request.POST.get('banner_dark_url', '').strip()
        dark_b64 = request.POST.get('banner_dark_b64', '').strip()
        if dark_file or dark_b64:
            try:
                banner_config.banner_dark_url = process_image_upload(
                    file_obj=dark_file,
                    base64_str=dark_b64,
                    folder='banners',
                    fallback_url=dark_url
                )
            except Exception as e:
                logger.error(f"Erro ao processar banner escuro: {e}")
        elif dark_url:
            banner_config.banner_dark_url = dark_url

        banner_config.is_active = True
        banner_config.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', ''):
            return JsonResponse({
                'success': True,
                'banner_light_url': banner_config.get_light_url(),
                'banner_dark_url': banner_config.get_dark_url(),
            })

        messages.success(request, 'Banners da Tela Inicial atualizados com sucesso!')
        return redirect('home')


class CEGDetailView(View):
    def get(self, request, slug):
        ceg = get_object_or_404(
            CEG.objects.select_related('era__group', 'caixa'),
            slug=slug
        )

        now = timezone.now()
        if ceg.status == CEG.Status.SCHEDULED and ceg.opens_at and ceg.opens_at <= now:
            ceg.status = CEG.Status.OPEN
            ceg.save(update_fields=['status'])

        # Carrega sets ativos com contadores anotados e prefetch otimizado (evita N+1 queries)
        slots_qs = ItemSlot.objects.select_related(
            'item_definition__tipo_item',
            'claimed_by'
        )

        active_sets = list(ceg.sets.filter(is_active=True).annotate(
            _annotated_slots_count=Count('slots', distinct=True),
            _annotated_reserved_count=Count(
                'slots',
                filter=Q(slots__status__in=[ItemSlot.Status.RESERVED, ItemSlot.Status.PAID]),
                distinct=True
            )
        ).prefetch_related(
            Prefetch('slots', queryset=slots_qs)
        ).order_by('set_number'))

        # Vincula contadores e instâncias em memória para evitar queries adicionais ao renderizar slots
        for s in active_sets:
            s._slots_count = s._annotated_slots_count
            s._reserved_count = s._annotated_reserved_count
            for slot in s.slots.all():
                slot.set = s
                slot.set.ceg = ceg

        # Separa sets regulares (Set 1, Set 2, Set 3...) do set especial de itens avulsos (set_number=0)
        regular_sets = [s for s in active_sets if not s.is_avulso]
        avulso_set = next((s for s in active_sets if s.is_avulso), None)
        avulso_slots = list(avulso_set.slots.all()) if avulso_set else []

        # Definições de itens avulsos da CEG
        avulso_definitions = list(
            ceg.item_definitions.filter(is_avulso=True)
            .select_related('tipo_item')
            .order_by('order_index', 'name')
        )
        has_avulsos = bool(avulso_slots or avulso_definitions)

        # Mapa estruturado de itens avulsos com seus slots para Alpine.js
        avulso_items_data = []
        for idef in avulso_definitions:
            matching_slots = [s for s in avulso_slots if s.item_definition_id == idef.id]
            idef.matching_slots = matching_slots
            idef.slots_count = len(matching_slots)
            idef.available_count = len([s for s in matching_slots if s.status == ItemSlot.Status.AVAILABLE])
            idef.first_slot = matching_slots[0] if matching_slots else None

            slots_data = []
            for s in matching_slots:
                slots_data.append({
                    'id': s.id,
                    'unit_number': s.unit_number,
                    'price': float(s.price),
                    'status': s.status,
                    'status_display': s.get_status_display(),
                    'is_item_paid': s.is_item_paid,
                    'is_frete_inter_paid': s.is_frete_inter_paid,
                    'is_taxa_aduaneira_paid': s.is_taxa_aduaneira_paid,
                    'is_frete_nacional_paid': s.is_frete_nacional_paid,
                    'frete_inter': float(s.frete_inter) if s.frete_inter is not None else None,
                    'taxa_aduaneira': float(s.taxa_aduaneira) if s.taxa_aduaneira is not None else None,
                    'claimed_by_id': s.claimed_by_id,
                    'claimed_by_name': s.claimed_by.display_name if s.claimed_by else '',
                    'claimed_by_whatsapp': s.claimed_by.whatsapp if s.claimed_by else '',
                    'claimed_by_social': s.claimed_by.social_handle if s.claimed_by else '',
                })
            avulso_items_data.append({
                'id': idef.id,
                'name': idef.name,
                'member_name': idef.member_name or '',
                'tipo_item_id': idef.tipo_item_id,
                'tipo_item_nome': idef.tipo_item_nome,
                'item_type': idef.item_type,
                'default_price': float(idef.default_price),
                'image_url': idef.image_url or '',
                'quantidade_avulsa': idef.quantidade_avulsa,
                'slots': slots_data,
                'slots_count': len(slots_data),
                'available_count': idef.available_count,
            })

        # Se o usuário for administrador/staff, carrega lista de participantes para seleção rápida e caixas
        all_participants = []
        all_caixas = []
        all_eras = []
        status_choices = []
        tipo_item_list = []
        item_type_choices = [
            {'code': code, 'label': label}
            for code, label in CEGItemDefinition.ItemType.choices
        ]
        if request.user.is_authenticated and request.user.is_staff:
            from apps.participants.models import Participant
            all_participants = list(
                Participant.objects.all().order_by('name').values(
                    'id', 'name', 'username', 'whatsapp', 'social_handle'
                )
            )
            all_caixas = Caixa.objects.all().order_by('-created_at')
            all_eras = list(Era.objects.select_related('group').all().order_by('group__name', 'name'))
            status_choices = CEG.Status.choices
            tipo_item_list = list(TipoItem.objects.all().order_by('nome').values('id', 'nome', 'descricao'))

            # Logs de claim por slot para exibição inline no template
            from apps.cegs.models import ClaimAttemptLog
            claim_logs_qs = ClaimAttemptLog.objects.filter(
                slot__set__ceg=ceg
            ).select_related('slot__item_definition', 'slot__set').order_by('slot_id', 'attempt_number')
            claim_logs_by_slot = {}
            for cl in claim_logs_qs:
                sid = cl.slot_id
                if sid not in claim_logs_by_slot:
                    claim_logs_by_slot[sid] = []
                claim_logs_by_slot[sid].append({
                    'id': cl.id,
                    'attempt_number': cl.attempt_number,
                    'participant_name': cl.participant_name,
                    'phone': cl.phone,
                    'social_handle': cl.social_handle or '',
                    'result': cl.result,
                    'result_display': cl.get_result_display(),
                    'details': cl.details or '',
                    'created_at': cl.created_at.strftime('%d/%m %H:%M:%S'),
                })
        else:
            claim_logs_by_slot = {}

        claim_logs_by_slot_json = json.dumps(claim_logs_by_slot)

        # Carrega participante logado via sessão ou usuário autenticado (para pré-preencher o formulário de reserva)
        logged_participant = None
        participant_id = request.session.get('participant_id')
        if participant_id:
            from apps.participants.models import Participant
            try:
                logged_participant = Participant.objects.get(id=participant_id)
            except Participant.DoesNotExist:
                request.session.pop('participant_id', None)
        if not logged_participant and request.user.is_authenticated:
            from apps.participants.models import Participant
            logged_participant = Participant.objects.filter(username=request.user.username).first()

        prefilled_name = ''
        prefilled_whatsapp = ''
        prefilled_social = ''
        prefilled_username = ''
        if logged_participant:
            prefilled_name = logged_participant.name
            prefilled_whatsapp = logged_participant.whatsapp or ''
            prefilled_social = logged_participant.social_handle or ''
            prefilled_username = logged_participant.username or ''
        elif request.user.is_authenticated:
            prefilled_name = request.user.get_full_name() or request.user.username
            prefilled_username = request.user.username

        # Polling / Sondagem de Demanda data
        polling_summary = None
        user_voted_def_ids = []
        polling_item_definitions = []
        if ceg.is_polling:
            from apps.cegs.polling_service import PollingDemandService
            from apps.cegs.models import CEGInterestVote
            polling_summary = PollingDemandService.get_polling_summary(ceg)
            polling_item_definitions = list(
                ceg.item_definitions.prefetch_related(
                    Prefetch(
                        'interest_votes',
                        queryset=CEGInterestVote.objects.select_related(
                            'participant',
                            'converted_slot__set'
                        ).order_by('created_at')
                    )
                ).select_related('tipo_item').order_by('order_index', 'name')
            )
            if logged_participant:
                user_voted_def_ids = list(
                    CEGInterestVote.objects.filter(
                        ceg=ceg,
                        participant=logged_participant
                    ).values_list('item_definition_id', flat=True)
                )

        # Agrupamento de vagas disponíveis por integrante/item para divulgação em redes sociais
        item_defs_dict = {}
        for item_def in ceg.item_definitions.all().order_by('order_index', 'name'):
            item_defs_dict[item_def.id] = {
                'id': item_def.id,
                'name': item_def.name,
                'member_name': item_def.member_name or '',
                'available_count': 0,
                'total_count': 0,
                'price': None,
            }

        slot_prices = set()
        for s_set in active_sets:
            for slot in s_set.slots.all():
                def_id = slot.item_definition_id
                if def_id in item_defs_dict:
                    item_defs_dict[def_id]['total_count'] += 1
                    if slot.status == ItemSlot.Status.AVAILABLE:
                        item_defs_dict[def_id]['available_count'] += 1
                    if item_defs_dict[def_id]['price'] is None and slot.price:
                        item_defs_dict[def_id]['price'] = float(slot.price)
                if slot.price and slot.price > 0:
                    slot_prices.add(slot.price)

        share_items = list(item_defs_dict.values())
        share_items_json = json.dumps(share_items)

        if len(slot_prices) == 1:
            ceg_price_display = f"R$ {list(slot_prices)[0]:.2f}"
        elif len(slot_prices) > 1:
            ceg_price_display = f"R$ {min(slot_prices):.2f} ~ R$ {max(slot_prices):.2f}"
        else:
            ceg_price_display = ""

        return render(request, 'cegs/detail.html', {
            'ceg': ceg,
            'sets': regular_sets,
            'avulso_set': avulso_set,
            'avulso_slots': avulso_slots,
            'avulso_definitions': avulso_definitions,
            'has_avulsos': has_avulsos,
            'avulso_items_data': avulso_items_data,
            'avulso_items_json': json.dumps(avulso_items_data),
            'countdown_seconds': ceg.countdown_seconds,
            'is_standby': ceg.is_standby,
            'is_open_for_claims': ceg.is_open_for_claims,
            'all_participants': all_participants,
            'all_participants_json': json.dumps(all_participants),
            'all_caixas': all_caixas,
            'all_eras': all_eras,
            'status_choices': status_choices,
            'tipo_item_list': tipo_item_list,
            'tipo_item_list_json': json.dumps(tipo_item_list),
            'item_type_choices': item_type_choices,
            'item_type_choices_json': json.dumps(item_type_choices),
            'logged_participant': logged_participant,
            'claim_logs_by_slot_json': claim_logs_by_slot_json,
            'polling_summary': polling_summary,
            'polling_summary_json': json.dumps(polling_summary, default=str),
            'user_voted_def_ids': user_voted_def_ids,
            'user_voted_def_ids_json': json.dumps(user_voted_def_ids),
            'polling_item_definitions': polling_item_definitions,
            'share_items': share_items,
            'share_items_json': share_items_json,
            'ceg_price_display': ceg_price_display,
            'prefilled_name': prefilled_name,
            'prefilled_whatsapp': prefilled_whatsapp,
            'prefilled_social': prefilled_social,
            'prefilled_username': prefilled_username,
        })



class ClaimSlotView(View):
    def post(self, request, slot_id):
        slot = get_object_or_404(ItemSlot.objects.select_related('set__ceg'), id=slot_id)
        ceg = slot.set.ceg

        # Detecta AJAX logo no início para garantir resposta JSON em todos os caminhos
        is_ajax = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.content_type == 'application/json'
        )

        logged_id = request.session.get('participant_id')
        is_staff = request.user.is_authenticated and request.user.is_staff

        # 1. Se não estiver logado via telefone e não for staff, bloqueia
        if not logged_id and not is_staff:
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
                if is_ajax:
                    return JsonResponse({
                        'success': False,
                        'requires_auth': True,
                        'redirect_url': f"/me/login/?next=/ceg/{ceg.slug}/",
                        'message': 'Sessão expirada. Por favor, autentique novamente.'
                    }, status=401)
                messages.error(request, 'Sessão expirada. Por favor, autentique novamente.')
                return redirect(f"/me/login/?next=/ceg/{ceg.slug}/")

        try:
            claim = ClaimService.claim_slot(
                slot_id=slot.id,
                name=name,
                phone=whatsapp,
                social_handle=social_handle,
                notes=notes,
                username=username,
                bypass_status_check=is_staff,  # Admin pode reservar em qualquer status de CEG
            )
            # Salva o participante na sessão se não for o admin realizando a reserva em nome de terceiro
            if not is_staff:
                request.session['participant_id'] = claim.participant.id

            if hasattr(claim, 'auto_fallback_from_set') and claim.auto_fallback_from_set:
                success_msg = (
                    f"🎉 Reserva realizada com sucesso via Auto-Fallback! "
                    f"O Set #{claim.auto_fallback_from_set} já havia esgotado, mas você garantiu sua vaga automaticamente no Set #{claim.slot.set.set_number} "
                    f"({claim.slot.item_definition.name}). Efetue o pagamento Pix para confirmar."
                )
            else:
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

        except AddedToWaitingListError as e:
            msg = str(e)
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'is_waiting_list': True,
                    'position': e.position,
                    'item_name': e.item_name,
                    'message': msg,
                })
            messages.warning(request, msg)
            return redirect('ceg_detail', slug=ceg.slug)

        except CEGError as e:
            err_msg = str(e)
            if is_ajax:
                return JsonResponse({'success': False, 'message': err_msg}, status=400)
            messages.error(request, err_msg)
            return redirect('ceg_detail', slug=ceg.slug)
        except Exception as e:
            import traceback
            err_msg = f"Erro inesperado ao processar reserva: {e}"
            if is_ajax:
                return JsonResponse({'success': False, 'message': err_msg}, status=500)
            messages.error(request, err_msg)
            return redirect('ceg_detail', slug=ceg.slug)


class BulkClaimView(View):
    """
    Endpoint para participantes darem claim em múltiplos slots de uma CEG de uma vez.
    Recebe JSON: {slot_ids: [...], name, whatsapp, social_handle}
    Retorna: {results: [{slot_id, item_name, set_number, success, is_waiting_list, position, message}, ...]}
    """
    def post(self, request, slug):
        ceg = get_object_or_404(CEG, slug=slug)
        logged_id = request.session.get('participant_id')
        is_staff = request.user.is_authenticated and request.user.is_staff

        if not logged_id and not is_staff:
            return JsonResponse({
                'success': False,
                'requires_auth': True,
                'redirect_url': f"/me/login/?next=/ceg/{ceg.slug}/",
                'message': 'Por favor, autentique com seu WhatsApp para realizar reservas.'
            }, status=401)

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'message': 'Requisição inválida.'}, status=400)

        slot_ids = body.get('slot_ids', [])
        avulso_claims = body.get('avulso_claims', [])
        name = body.get('name', '').strip()
        whatsapp = body.get('whatsapp', '').strip()
        social_handle = body.get('social_handle', '').strip()
        username = body.get('username', '').strip()
        notes = body.get('notes', '').strip()
        entrega_tipo = body.get('entrega_tipo', 'CAIXINHA').strip().upper()
        pref_label = "Guardar na Caixinha" if entrega_tipo == "CAIXINHA" else "Envio Imediato"
        if f"[Preferência: {pref_label}]" not in notes:
            notes = f"[Preferência: {pref_label}] {notes}".strip()

        if not slot_ids and not avulso_claims:
            return JsonResponse({'success': False, 'message': 'Nenhum slot ou item selecionado.'}, status=400)

        # Preenche com dados da sessão se for participante logado
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
                return JsonResponse({
                    'success': False,
                    'requires_auth': True,
                    'redirect_url': f"/me/login/?next=/ceg/{ceg.slug}/",
                    'message': 'Sessão expirada. Por favor, autentique novamente.'
                }, status=401)
        elif is_staff and not whatsapp:
            # Fallback para staff autenticado quando nenhum joiner for selecionado na lista
            from apps.participants.models import Participant
            p = Participant.objects.filter(username=request.user.username).first()
            if not p and request.user.email:
                p = Participant.objects.filter(email=request.user.email).first()
            if p and p.whatsapp:
                whatsapp = p.whatsapp
                name = name or p.name
                username = username or p.username
                social_handle = social_handle or p.social_handle
            else:
                staff_name = request.user.get_full_name() or request.user.username or "Admin Staff"
                staff_part, _ = Participant.objects.get_or_create(
                    whatsapp="5511999990000",
                    defaults={
                        'name': staff_name,
                        'username': request.user.username,
                        'social_handle': f"@{request.user.username}",
                    }
                )
                whatsapp = staff_part.whatsapp
                name = name or staff_part.name
                username = username or staff_part.username
                social_handle = social_handle or staff_part.social_handle

        results = []
        participant_saved = False

        # 1. Processa slots regulares por ID específico
        for slot_id in slot_ids:
            try:
                slot = ItemSlot.objects.select_related('set__ceg', 'item_definition').get(
                    id=slot_id, set__ceg=ceg
                )
            except ItemSlot.DoesNotExist:
                results.append({
                    'slot_id': slot_id,
                    'item_name': '?',
                    'set_number': '?',
                    'success': False,
                    'is_waiting_list': False,
                    'message': 'Slot não encontrado nesta CEG.',
                    'result': 'ERROR',
                })
                continue

            item_name = slot.item_definition.name
            set_number = slot.set.set_number

            try:
                claim = ClaimService.claim_slot(
                    slot_id=slot.id,
                    name=name,
                    phone=whatsapp,
                    social_handle=social_handle,
                    notes=notes,
                    username=username,
                    bypass_status_check=is_staff,
                )
                if not is_staff and not participant_saved:
                    request.session['participant_id'] = claim.participant.id
                    participant_saved = True

                results.append({
                    'slot_id': slot_id,
                    'item_name': item_name,
                    'set_number': set_number,
                    'success': True,
                    'is_waiting_list': False,
                    'message': f"🎉 Reservado com sucesso!",
                    'result': 'SUCCESS',
                    'total_price': str(claim.total_price),
                    'pix_key': ceg.pix_key,
                })

            except AddedToWaitingListError as e:
                results.append({
                    'slot_id': slot_id,
                    'item_name': item_name,
                    'set_number': set_number,
                    'success': False,
                    'is_waiting_list': True,
                    'position': e.position,
                    'message': str(e),
                    'result': 'WAITING_LIST',
                })

            except CEGError as e:
                results.append({
                    'slot_id': slot_id,
                    'item_name': item_name,
                    'set_number': set_number,
                    'success': False,
                    'is_waiting_list': False,
                    'message': str(e),
                    'result': 'FAILED',
                })

            except Exception as e:
                results.append({
                    'slot_id': slot_id,
                    'item_name': item_name,
                    'set_number': set_number,
                    'success': False,
                    'is_waiting_list': False,
                    'message': f"Erro inesperado: {e}",
                    'result': 'ERROR',
                })

        # 2. Processa solicitações de itens avulsos por quantidade e alocação dinâmica FIFO
        for av in avulso_claims:
            idef_id = av.get('item_def_id')
            try:
                qty = max(1, int(av.get('quantity', 1)))
            except (ValueError, TypeError):
                qty = 1

            try:
                idef = CEGItemDefinition.objects.get(id=idef_id, ceg=ceg)
            except CEGItemDefinition.DoesNotExist:
                results.append({
                    'slot_id': None,
                    'item_name': 'Item Avulso',
                    'set_number': 'Avulso',
                    'success': False,
                    'is_waiting_list': False,
                    'message': 'Item avulso não encontrado nesta CEG.',
                    'result': 'ERROR',
                })
                continue

            try:
                claims = ClaimService.claim_avulso_by_quantity(
                    ceg=ceg,
                    item_def_id=idef.id,
                    quantity=qty,
                    name=name,
                    phone=whatsapp,
                    social_handle=social_handle,
                    notes=notes,
                    username=username,
                    bypass_status_check=is_staff,
                )
                if not is_staff and not participant_saved and claims:
                    request.session['participant_id'] = claims[0].participant.id
                    participant_saved = True

                for c in claims:
                    results.append({
                        'slot_id': c.slot.id,
                        'item_name': f"{idef.name} (Unid. #{c.slot.unit_number})",
                        'name': f"{idef.name} (Unid. #{c.slot.unit_number})",
                        'set_number': 'Avulso',
                        'success': True,
                        'is_waiting_list': False,
                        'message': f"🎉 Unidade #{c.slot.unit_number} reservada com sucesso!",
                        'result': 'SUCCESS',
                        'total_price': str(c.total_price),
                        'pix_key': ceg.pix_key,
                    })

                if len(claims) < qty:
                    results.append({
                        'slot_id': None,
                        'item_name': idef.name,
                        'name': idef.name,
                        'set_number': 'Avulso',
                        'success': False,
                        'is_waiting_list': False,
                        'message': f"Estoque parcial: apenas {len(claims)} de {qty} unidade(s) estavam disponíveis.",
                        'result': 'PARTIAL',
                    })
            except CEGError as e:
                results.append({
                    'slot_id': None,
                    'item_name': idef.name,
                    'name': idef.name,
                    'set_number': 'Avulso',
                    'success': False,
                    'is_waiting_list': False,
                    'message': str(e),
                    'result': 'FAILED',
                })
            except Exception as e:
                results.append({
                    'slot_id': None,
                    'item_name': idef.name,
                    'name': idef.name,
                    'set_number': 'Avulso',
                    'success': False,
                    'is_waiting_list': False,
                    'message': f"Erro inesperado: {e}",
                    'result': 'ERROR',
                })

        successes = sum(1 for r in results if r['success'])
        waiting = sum(1 for r in results if r.get('is_waiting_list'))
        return JsonResponse({
            'success': True,
            'results': results,
            'summary': {
                'total': len(results),
                'succeeded': successes,
                'waiting_list': waiting,
                'failed': len(results) - successes - waiting,
                'pix_key': ceg.pix_key,
            }
        })



@method_decorator(csrf_exempt, name='dispatch')
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

            new_val = slot.toggle_payment(field, value=value, actor=request.user)

            field_labels = {
                'item': 'Item',
                'is_item_paid': 'Item',
                'inter': 'Frete Internacional',
                'frete_inter': 'Frete Internacional',
                'taxa': 'Taxa Aduaneira',
                'taxa_aduaneira': 'Taxa Aduaneira',
                'nacional': 'Frete Nacional',
                'frete_nacional': 'Frete Nacional',
            }
            label = field_labels.get(field, field)
            status_text = "Pago ✔" if new_val else "Pendente"
            msg = f"{label} marcado como: {status_text}."

            return JsonResponse({
                'success': True,
                'message': msg,
                'slot_id': slot.id,
                'field': field,
                'new_value': new_val,
                'is_item_paid': slot.is_item_paid,
                'is_frete_inter_paid': slot.is_frete_inter_paid,
                'is_taxa_aduaneira_paid': slot.is_taxa_aduaneira_paid,
                'is_frete_nacional_paid': slot.is_frete_nacional_paid,
                'status': slot.status,
                'status_display': slot.get_status_display(),
                'pode_empacotar': slot.pode_empacotar,
                'motivo_bloqueio': slot.motivo_bloqueio,
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

        update_fields = [
            'prazo_pagamento_item',
            'frete_inter',
            'taxa_aduaneira',
            'prazo_pagamento_frete_inter',
            'prazo_pagamento_taxa_aduaneira',
        ]

        caixa_id = request.POST.get('caixa_id')
        if caixa_id is not None:
            if caixa_id.strip():
                try:
                    caixa = Caixa.objects.filter(id=int(caixa_id.strip())).first()
                    ceg.caixa = caixa
                    if caixa:
                        ceg.shipping_status = caixa.status
                    update_fields.extend(['caixa', 'shipping_status'])
                except (ValueError, TypeError):
                    pass
            else:
                ceg.caixa = None
                update_fields.append('caixa')

        ceg.save(update_fields=update_fields)

        # Propagação em cascata
        if ceg.caixa:
            # Se vinculada a uma caixa, propaga os rates e prazos da caixa para a CEG e seus slots
            ceg.caixa.propagar_taxas_e_prazos_em_cascata()
        else:
            # Se não tiver caixa, mas tiver prazos ou valores definidos na CEG, propaga para os slots
            slots_to_update = []
            for slot in ItemSlot.objects.filter(set__ceg=ceg):
                changed = False
                if ceg.frete_inter is not None and slot.frete_inter_valor != ceg.frete_inter:
                    slot.frete_inter_valor = ceg.frete_inter
                    changed = True
                if ceg.taxa_aduaneira is not None and slot.taxa_aduaneira_valor != ceg.taxa_aduaneira:
                    slot.taxa_aduaneira_valor = ceg.taxa_aduaneira
                    changed = True
                if ceg.prazo_pagamento_frete_inter and slot.prazo_frete_inter != ceg.prazo_pagamento_frete_inter:
                    slot.prazo_frete_inter = ceg.prazo_pagamento_frete_inter
                    changed = True
                if ceg.prazo_pagamento_taxa_aduaneira and slot.prazo_taxa_aduaneira != ceg.prazo_pagamento_taxa_aduaneira:
                    slot.prazo_taxa_aduaneira = ceg.prazo_pagamento_taxa_aduaneira
                    changed = True
                if changed:
                    slots_to_update.append(slot)
            if slots_to_update:
                ItemSlot.objects.bulk_update(
                    slots_to_update,
                    ['frete_inter_valor', 'taxa_aduaneira_valor', 'prazo_frete_inter', 'prazo_taxa_aduaneira']
                )

        messages.success(request, f"💰 Taxas, prazos e remessa da CEG '{ceg.title}' atualizados com sucesso!")
        return redirect('ceg_detail', slug=ceg.slug)


class UpdateCEGView(StaffRequiredMixin, View):
    """
    Permite ao organizador (admin/staff) editar as informações completas da CEG:
    - Título, Era / Grupo, Caixa vinculada
    - Banner / Foto da CEG (Upload direto de arquivo de imagem ou URL externa)
    - Status (Aberta, Agendada/Standby, Rascunho, Fechada, Cancelada)
    - Prazos e Datas (Abertura/Standby, Encerramento, Prazo do item)
    - Regras / Descrição e Chave Pix / Instruções
    """
    def post(self, request, slug):
        ceg = get_object_or_404(CEG, slug=slug)

        try:
            title = request.POST.get('title', '').strip()
            era_id = request.POST.get('era_id')
            caixa_id = request.POST.get('caixa_id')
            status = request.POST.get('status', '').strip()
            opens_at_str = request.POST.get('opens_at', '').strip()
            closes_at_str = request.POST.get('closes_at', '').strip()
            prazo_item_str = request.POST.get('prazo_pagamento_item', '').strip()
            pix_key = request.POST.get('pix_key', '').strip()
            pix_instructions = request.POST.get('pix_instructions', '').strip()
            pix_key_frete = request.POST.get('pix_key_frete', '').strip()
            pix_instructions_frete = request.POST.get('pix_instructions_frete', '').strip()
            pix_key_taxa = request.POST.get('pix_key_taxa', '').strip()
            pix_instructions_taxa = request.POST.get('pix_instructions_taxa', '').strip()
            description = request.POST.get('description', '').strip()
            banner_url_input = request.POST.get('banner_url', '').strip()
            remove_banner = request.POST.get('remove_banner') in ('1', 'true', 'on')

            if title:
                ceg.title = title

            if era_id:
                try:
                    ceg.era = Era.objects.get(id=int(era_id))
                except (Era.DoesNotExist, ValueError):
                    pass

            if caixa_id is not None:
                if caixa_id.strip():
                    try:
                        caixa = Caixa.objects.filter(id=int(caixa_id.strip())).first()
                        ceg.caixa = caixa
                        if caixa:
                            ceg.shipping_status = caixa.status
                    except (ValueError, TypeError):
                        pass
                else:
                    ceg.caixa = None

            if status in CEG.Status.values:
                ceg.status = status

            def parse_local_dt(dt_str):
                if not dt_str:
                    return None
                try:
                    dt = parse_datetime(dt_str)
                    if dt and timezone.is_naive(dt):
                        dt = timezone.make_aware(dt, timezone.get_current_timezone())
                    return dt
                except Exception:
                    return None

            ceg.opens_at = parse_local_dt(opens_at_str)
            ceg.closes_at = parse_local_dt(closes_at_str)
            ceg.prazo_pagamento_item = parse_local_dt(prazo_item_str)

            # Se tiver opens_at no futuro e status estiver como OPEN, converte para SCHEDULED automaticamente
            if ceg.opens_at and timezone.now() < ceg.opens_at and ceg.status == CEG.Status.OPEN:
                ceg.status = CEG.Status.SCHEDULED

            ceg.pix_key = pix_key
            ceg.pix_instructions = pix_instructions
            ceg.pix_key_frete = pix_key_frete
            ceg.pix_instructions_frete = pix_instructions_frete
            ceg.pix_key_taxa = pix_key_taxa
            ceg.pix_instructions_taxa = pix_instructions_taxa
            ceg.description = description

            # Upload de Imagem / Foto de Banner (Arquivo, Ctrl+V Base64 ou URL)
            banner_file = request.FILES.get('banner_file')
            banner_base64 = request.POST.get('banner_base64', '').strip()

            if remove_banner:
                ceg.banner_url = ''
            elif banner_file or banner_base64 or banner_url_input:
                new_banner = process_image_upload(
                    file_obj=banner_file,
                    base64_str=banner_base64,
                    folder='cegs/banners',
                    fallback_url=banner_url_input
                )
                if new_banner:
                    ceg.banner_url = new_banner
                elif 'banner_url' in request.POST and not banner_file and not banner_base64:
                    ceg.banner_url = ''

            ceg.save()

            messages.success(request, f"✨ Informações e foto da CEG '{ceg.title}' foram atualizadas com sucesso!")
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect('ceg_detail', slug=ceg.slug)
        except Exception as e:
            logger.exception(f"Erro ao atualizar informações da CEG {slug}: {e}")
            messages.error(request, f"Erro ao atualizar informações da CEG: {e}")
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
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
        promote_waiting = data.get('promote_waiting', False) or action == 'promote_waiting'
        participant_id = data.get('participant_id')

        msg_text = 'Slot atualizado com sucesso!'

        with transaction.atomic():
            # 0. Ações de Exclusão de Slot ou Definição do Item
            if action == 'delete_item_definition':
                item_def = slot.item_definition
                item_name = item_def.name
                item_def.delete()
                return JsonResponse({
                    'success': True,
                    'message': f"Item '{item_name}' e todas as suas vagas na CEG foram excluídos com sucesso!",
                    'deleted_item_definition': True
                })

            if action == 'delete_slot':
                slot_name = slot.item_definition.name
                set_num = slot.set.set_number
                slot.delete()
                return JsonResponse({
                    'success': True,
                    'message': f"Vaga do item '{slot_name}' no Set #{set_num} foi excluída com sucesso!",
                    'deleted_slot': True
                })

            # 1. Atualização de Tipo de Item, Nome e Integrante
            item_type = data.get('item_type')
            tipo_item_id = data.get('tipo_item_id')
            name = data.get('name')
            member_name = data.get('member_name')

            item_def = slot.item_definition
            item_def_changed = False

            if tipo_item_id is not None:
                if str(tipo_item_id).strip() == '':
                    item_def.tipo_item = None
                else:
                    try:
                        tipo_obj = TipoItem.objects.filter(id=int(tipo_item_id)).first()
                        item_def.tipo_item = tipo_obj
                        if tipo_obj:
                            item_def.item_type = CEGItemDefinition.resolve_item_type_from_tipo_item(tipo_obj)
                    except (ValueError, TypeError):
                        pass
                item_def_changed = True
            elif item_type and item_type in CEGItemDefinition.ItemType.values:
                item_def.item_type = item_type
                item_def_changed = True


            if name and str(name).strip():
                item_def.name = str(name).strip()
                item_def_changed = True

            if member_name is not None:
                item_def.member_name = str(member_name).strip()
                item_def_changed = True

            if item_def_changed:
                item_def.save()

            # 2. Atualização de Preço
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

            # 3. Remover Reserva / Desistência (repassa automaticamente para o 1º da fila se houver)
            if remove_claim or action == 'remove_claim':
                old_p = slot.claimed_by
                if hasattr(slot, 'claim') and slot.claim:
                    slot.claim.delete()
                promoted_entry = ClaimService.promote_from_waiting_list_on_slot_released(slot)
                if old_p:
                    try:
                        from apps.cegs.audit_service import AuditService
                        AuditService.log_slot_assignment(
                            slot=slot,
                            participant=old_p,
                            action='release',
                            actor=request.user,
                            metadata={'promoted_waiting': bool(promoted_entry)}
                        )
                    except Exception:
                        pass
                if promoted_entry:
                    msg_text = (
                        f"Reserva cancelada. O slot foi repassado com prioridade para o 1º da fila de espera: "
                        f"{promoted_entry.name} ({promoted_entry.social_handle or promoted_entry.phone})!"
                    )
                else:
                    msg_text = "Reserva removida. O slot voltou a ficar disponível."

            # 4. Promover manualmente da fila de espera
            elif promote_waiting:
                promoted_entry = ClaimService.promote_from_waiting_list_on_slot_released(slot)
                if promoted_entry:
                    msg_text = f"Participante {promoted_entry.name} promovido da fila de espera para o slot com sucesso!"
                else:
                    return JsonResponse({'success': False, 'message': 'Não há participantes aguardando na lista de espera para este item.'}, status=400)

            # 5. Trocar ou Atribuir Participante
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

                    try:
                        from apps.cegs.audit_service import AuditService
                        AuditService.log_slot_assignment(
                            slot=slot,
                            participant=new_participant,
                            action='assign',
                            actor=request.user,
                        )
                    except Exception:
                        pass
                except Participant.DoesNotExist:
                    return JsonResponse({'success': False, 'message': 'Participante não encontrado.'}, status=404)

            slot.save()

        return JsonResponse({
            'success': True,
            'message': msg_text,
            'slot': {
                'id': slot.id,
                'name': slot.item_definition.name,
                'member_name': slot.item_definition.member_name,
                'item_type': slot.item_definition.item_type,
                'item_type_display': slot.item_definition.get_item_type_display(),
                'tipo_item_id': slot.item_definition.tipo_item_id,
                'tipo_item_nome': slot.item_definition.tipo_item_nome,
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


class BulkManageCEGItemsView(View):
    """
    Permite ao organizador (staff) realizar alterações e exclusões em massa de itens de uma CEG:
    - Alterar tipo de múltiplos itens (item_type / tipo_item) com atualização opcional de prefixo
    - Alterar preço de múltiplos itens
    - Excluir múltiplos itens da CEG (CEGItemDefinition e seus slots)
    - Excluir múltiplos slots específicos de sets
    """
    def post(self, request, slug):
        if not request.user.is_authenticated or not request.user.is_staff:
            return JsonResponse({'success': False, 'message': 'Acesso restrito ao organizador.'}, status=403)

        ceg = get_object_or_404(CEG, slug=slug)

        try:
            if request.content_type == 'application/json':
                data = json.loads(request.body.decode('utf-8') or '{}')
            else:
                data = request.POST
        except Exception:
            data = request.POST

        action = data.get('action')
        slot_ids = data.get('slot_ids', [])
        item_def_ids = data.get('item_def_ids', [])

        # Se passou slot_ids mas não item_def_ids, obtém as definições correspondentes
        if slot_ids and not item_def_ids:
            item_def_ids = list(ItemSlot.objects.filter(id__in=slot_ids, set__ceg=ceg).values_list('item_definition_id', flat=True).distinct())

        with transaction.atomic():
            if action == 'update_type':
                new_item_type = data.get('new_item_type')
                new_tipo_item_id = data.get('new_tipo_item_id')
                update_prefix = data.get('update_prefix', True)
                if isinstance(update_prefix, str):
                    update_prefix = update_prefix.lower() in ('true', '1', 'yes', 'on')

                if not new_tipo_item_id and not new_item_type:
                    return JsonResponse({'success': False, 'message': 'Selecione o novo tipo de item a ser aplicado.'}, status=400)

                target_tipo = None
                if new_tipo_item_id:
                    try:
                        target_tipo = TipoItem.objects.filter(id=int(new_tipo_item_id)).first()
                    except (ValueError, TypeError):
                        pass

                if target_tipo:
                    new_prefix = target_tipo.nome
                    derived_item_type = CEGItemDefinition.resolve_item_type_from_tipo_item(target_tipo)
                else:
                    prefix_map = {
                        'PHOTOCARD': 'Photocard',
                        'POB': 'POB',
                        'ALBUM': 'Álbum',
                        'INCLUSION': 'Inclusão',
                        'OTHER': 'Item'
                    }
                    new_prefix = prefix_map.get(new_item_type, 'Item')
                    derived_item_type = new_item_type if new_item_type in CEGItemDefinition.ItemType.values else CEGItemDefinition.ItemType.OTHER

                prefix_pattern = r'^(Photocard|POB|Pre-Order Benefit|Álbum|Album|Compact ver\.|Lucky Draw|Fansign|Inclusão|Lightstick|Item)\s*'

                item_defs = CEGItemDefinition.objects.filter(id__in=item_def_ids, ceg=ceg)
                count = 0
                for item_def in item_defs:
                    if target_tipo:
                        item_def.tipo_item = target_tipo
                        item_def.item_type = derived_item_type
                    elif new_item_type:
                        item_def.item_type = derived_item_type

                    if update_prefix and new_prefix:
                        cur_name = item_def.name
                        if re.search(prefix_pattern, cur_name, re.IGNORECASE):
                            item_def.name = re.sub(prefix_pattern, f'{new_prefix} ', cur_name, flags=re.IGNORECASE).strip()
                        elif item_def.member_name:
                            item_def.name = f"{new_prefix} {item_def.member_name}"
                        else:
                            item_def.name = f"{new_prefix} {cur_name}"

                    item_def.save()
                    count += 1

                return JsonResponse({
                    'success': True,
                    'message': f"Tipo atualizado para '{new_prefix}' em {count} item(ns) da CEG com sucesso!"
                })


            elif action == 'update_price':
                price_val = data.get('new_price')
                apply_all_sets = data.get('apply_all_sets', True)
                if price_val is None or str(price_val).strip() == '':
                    return JsonResponse({'success': False, 'message': 'Informe o novo preço.'}, status=400)
                try:
                    new_price = Decimal(str(price_val).replace('R$', '').replace(' ', '').replace(',', '.').strip())
                    if new_price < 0:
                        return JsonResponse({'success': False, 'message': 'O preço não pode ser negativo.'}, status=400)
                except (InvalidOperation, ValueError):
                    return JsonResponse({'success': False, 'message': 'Valor de preço inválido.'}, status=400)

                if apply_all_sets:
                    slots = ItemSlot.objects.filter(set__ceg=ceg, item_definition_id__in=item_def_ids)
                    CEGItemDefinition.objects.filter(id__in=item_def_ids, ceg=ceg).update(default_price=new_price)
                else:
                    slots = ItemSlot.objects.filter(id__in=slot_ids, set__ceg=ceg)

                updated_count = slots.update(price=new_price)
                Claim.objects.filter(slot__in=slots).update(total_price=new_price)

                return JsonResponse({
                    'success': True,
                    'message': f"Preço atualizado para R$ {new_price:.2f} em {updated_count} vaga(s)!"
                })

            elif action == 'delete_items':
                item_defs = CEGItemDefinition.objects.filter(id__in=item_def_ids, ceg=ceg)
                count = item_defs.count()
                item_defs.delete()
                return JsonResponse({
                    'success': True,
                    'message': f"{count} item(ns) e todas as suas vagas foram excluídos da CEG com sucesso!"
                })

            elif action == 'delete_slots':
                slots = ItemSlot.objects.filter(id__in=slot_ids, set__ceg=ceg)
                count = slots.count()
                slots.delete()
                return JsonResponse({
                    'success': True,
                    'message': f"{count} vaga(s) selecionada(s) foram excluídas com sucesso!"
                })

            elif action == 'bulk_payment':
                field = str(data.get('field', '')).strip()
                val_raw = data.get('value', True)
                if isinstance(val_raw, str):
                    value = val_raw.lower() in ('true', '1', 'yes', 'on')
                elif val_raw is None:
                    value = True
                else:
                    value = bool(val_raw)

                if not field:
                    return JsonResponse({'success': False, 'message': 'Informe a etapa de pagamento (item, inter, taxa).'}, status=400)

                valid_fields = [
                    'item', 'is_item_paid',
                    'inter', 'frete_inter', 'is_frete_inter_paid',
                    'taxa', 'taxa_aduaneira', 'is_taxa_aduaneira_paid',
                    'nacional', 'frete_nacional', 'is_frete_nacional_paid'
                ]
                if field not in valid_fields:
                    return JsonResponse({'success': False, 'message': f'Campo de pagamento "{field}" inválido.'}, status=400)

                if not slot_ids:
                    return JsonResponse({'success': False, 'message': 'Nenhuma vaga foi selecionada.'}, status=400)

                slots = ItemSlot.objects.filter(id__in=slot_ids, set__ceg=ceg).select_related('set', 'item_definition', 'claimed_by')
                count = 0
                slots_data = []
                for slot in slots:
                    slot.toggle_payment(field, value=value, actor=request.user)
                    count += 1
                    slots_data.append({
                        'id': slot.id,
                        'status': slot.status,
                        'is_item_paid': slot.is_item_paid,
                        'is_frete_inter_paid': slot.is_frete_inter_paid,
                        'is_taxa_aduaneira_paid': slot.is_taxa_aduaneira_paid,
                        'is_frete_nacional_paid': slot.is_frete_nacional_paid,
                    })

                field_labels = {
                    'item': 'Item',
                    'is_item_paid': 'Item',
                    'inter': 'Frete Internacional',
                    'frete_inter': 'Frete Internacional',
                    'is_frete_inter_paid': 'Frete Internacional',
                    'taxa': 'Taxa Aduaneira',
                    'taxa_aduaneira': 'Taxa Aduaneira',
                    'is_taxa_aduaneira_paid': 'Taxa Aduaneira',
                    'nacional': 'Frete Nacional',
                    'frete_nacional': 'Frete Nacional',
                    'is_frete_nacional_paid': 'Frete Nacional',
                }
                label = field_labels.get(field, field)
                status_label = "Pago ✔" if value else "Pendente"

                return JsonResponse({
                    'success': True,
                    'message': f"{count} vaga(s) marcada(s) com {label} como {status_label}!",
                    'count': count,
                    'field': field,
                    'value': value,
                    'slots': slots_data,
                })

            else:
                return JsonResponse({'success': False, 'message': 'Ação em massa não reconhecida.'}, status=400)


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

        # Suporte a FormData ou JSON
        password = ''
        if request.content_type == 'application/json':
            try:
                import json
                body = json.loads(request.body.decode('utf-8'))
                password = body.get('password', '')
                notify_participants = bool(body.get('notify_participants', True))
                custom_message = str(body.get('custom_message', '')).strip()
            except Exception:
                notify_participants = True
                custom_message = ''
        else:
            password = request.POST.get('password', '')
            notify_participants = request.POST.get('notify_participants', 'true').lower() in ('true', '1', 'on', 'yes')
            custom_message = request.POST.get('custom_message', '').strip()

        if not password or not request.user.check_password(password):
            return JsonResponse({'success': False, 'message': 'Senha de administrador incorreta. Ação não autorizada.'}, status=403)

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


class CEGLogsAndWaitingListView(View):
    """
    Endpoint JSON para o organizador visualizar os Logs de Disputa / Concorrência
    e a Lista de Espera por Item na interface da CEG.
    """
    def get(self, request, slug):
        if not request.user.is_authenticated or not request.user.is_staff:
            return JsonResponse({'success': False, 'message': 'Acesso restrito ao organizador.'}, status=403)

        ceg = get_object_or_404(CEG, slug=slug)

        # 1. Logs de tentativas nos slots desta CEG
        logs_qs = ClaimAttemptLog.objects.filter(
            slot__set__ceg=ceg
        ).select_related('slot__item_definition', 'slot__set').order_by('-created_at')[:150]

        logs_data = []
        for l in logs_qs:
            logs_data.append({
                'id': l.id,
                'slot_id': l.slot_id,
                'item_name': l.slot.item_definition.name,
                'set_number': l.slot.set.set_number,
                'attempt_number': l.attempt_number,
                'participant_name': l.participant_name,
                'phone': l.phone,
                'social_handle': l.social_handle or '',
                'result': l.result,
                'result_display': l.get_result_display(),
                'details': l.details,
                'created_at': l.created_at.strftime('%d/%m/%Y %H:%M:%S.%f')[:-3],
            })

        # 2. Fila de Espera dos itens desta CEG
        waiting_qs = ItemWaitingList.objects.filter(
            item_definition__ceg=ceg
        ).select_related('item_definition', 'participant', 'allocated_slot__set').order_by('item_definition__name', 'position')

        waiting_data = []
        for w in waiting_qs:
            waiting_data.append({
                'id': w.id,
                'item_definition_id': w.item_definition_id,
                'item_name': w.item_definition.name,
                'participant_id': w.participant_id,
                'participant_name': w.name,
                'phone': w.phone,
                'social_handle': w.social_handle or '',
                'position': w.position,
                'status': w.status,
                'status_display': w.get_status_display(),
                'allocated_slot': f"Set #{w.allocated_slot.set.set_number}" if w.allocated_slot else None,
                'created_at': w.created_at.strftime('%d/%m/%Y %H:%M'),
            })

        return JsonResponse({
            'success': True,
            'ceg_title': ceg.title,
            'logs': logs_data,
            'waiting_list': waiting_data,
            'total_logs': len(logs_data),
            'total_waiting': len([w for w in waiting_data if w['status'] == 'WAITING']),
        })

class DeleteCEGView(StaffRequiredMixin, View):
    """
    Permite ao organizador (staff) excluir permanentemente uma CEG inteira,
    incluindo todos os seus sets, slots, claims, fila de espera e votos.
    Requer autenticação de segurança com a senha do administrador logado.
    """
    def post(self, request, slug):
        ceg = get_object_or_404(CEG, slug=slug)
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

        password = ''
        if request.content_type == 'application/json':
            try:
                import json
                body = json.loads(request.body.decode('utf-8'))
                password = body.get('password', '')
            except Exception:
                pass
        else:
            password = request.POST.get('password', '')

        if not password or not request.user.check_password(password):
            error_msg = 'Senha de administrador incorreta. Ação de exclusão não autorizada.'
            if is_ajax:
                return JsonResponse({'success': False, 'message': error_msg}, status=403)
            messages.error(request, error_msg)
            return redirect('ceg_detail', slug=slug)

        ceg_title = ceg.title
        with transaction.atomic():
            ceg.delete()

        success_msg = f'CEG "{ceg_title}" foi excluída permanentemente.'
        if is_ajax:
            return JsonResponse({'success': True, 'message': success_msg, 'redirect_url': reverse('home')})

        messages.success(request, success_msg)
        return redirect('home')


class CreateAvulsoItemView(StaffRequiredMixin, View):
    """
    Permite à admin adicionar um novo item avulso diretamente na página da CEG:
    - Nome do item, tipo de item (dropdown compartilhado), categoria, preço, quantidade, integrante (opcional)
    - Foto do item (Upload de arquivo, base64 ou URL)
    - Gera os ItemSlots no container de avulsos da CEG (set_number=0)
    - Pré-reserva opcional de participante
    """
    def post(self, request, slug):
        ceg = get_object_or_404(CEG, slug=slug)
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

        name = request.POST.get('name', '').strip()
        member_name = (request.POST.get('member_name') or request.POST.get('member') or '').strip()
        item_type = request.POST.get('item_type', CEGItemDefinition.ItemType.OTHER)
        tipo_item_id = request.POST.get('tipo_item_id')
        price_str = (request.POST.get('default_price') or request.POST.get('price') or '0.00').replace(',', '.').strip()
        quantidade_str = str(request.POST.get('quantidade') or request.POST.get('quantity') or '1').strip()
        participant_id = request.POST.get('participant_id', '').strip()

        image_file = request.FILES.get('image_file')
        image_base64 = request.POST.get('image_base64', '').strip()
        image_url_input = request.POST.get('image_url', '').strip()

        if not name:
            msg = 'O nome do item avulso é obrigatório.'
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect('ceg_detail', slug=slug)

        try:
            price = Decimal(price_str)
        except (InvalidOperation, ValueError):
            price = Decimal('0.00')

        try:
            quantidade = max(1, int(quantidade_str))
        except (ValueError, TypeError):
            quantidade = 1

        try:
            image_url = process_image_upload(
                file_obj=image_file,
                base64_str=image_base64,
                folder='cegs/items',
                fallback_url=image_url_input
            )
        except ValueError as e:
            msg = str(e)
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect('ceg_detail', slug=slug)

        tipo_item = None
        if tipo_item_id:
            try:
                tipo_item = TipoItem.objects.filter(id=int(tipo_item_id)).first()
            except (ValueError, TypeError):
                pass

        try:
            with transaction.atomic():
                avulso_set = ceg.get_or_create_avulso_set()
                order_index = ceg.item_definitions.count() + 1

                item_def = CEGItemDefinition.objects.create(
                    ceg=ceg,
                    name=name,
                    member_name=member_name,
                    item_type=item_type,
                    tipo_item=tipo_item,
                    default_price=price,
                    image_url=image_url,
                    is_avulso=True,
                    quantidade_avulsa=quantidade,
                    order_index=order_index
                )

                created_slots = []
                for u in range(1, quantidade + 1):
                    slot = ItemSlot.objects.create(
                        set=avulso_set,
                        item_definition=item_def,
                        unit_number=u,
                        price=price
                    )
                    created_slots.append(slot)

                # Se houver pré-reserva selecionada, vincula ao primeiro slot
                if participant_id and created_slots:
                    try:
                        participant = Participant.objects.get(id=int(participant_id))
                        first_slot = created_slots[0]
                        now = timezone.now()
                        first_slot.claimed_by = participant
                        first_slot.status = ItemSlot.Status.RESERVED
                        first_slot.claimed_at = now
                        first_slot.save(update_fields=['claimed_by', 'status', 'claimed_at'])

                        Claim.objects.create(
                            slot=first_slot,
                            participant=participant,
                            status=Claim.Status.PENDING,
                            total_price=first_slot.price,
                            participant_notes="Pré-reservado pela administração ao cadastrar item avulso",
                            claimed_at=now
                        )
                        try:
                            from .models import AuditLog
                            AuditLog.objects.create(
                                event_type=AuditLog.EventType.SLOT_ASSIGNED,
                                actor=request.user,
                                actor_name=request.user.get_full_name() or request.user.username,
                                participant=participant,
                                participant_name=participant.name,
                                participant_phone=participant.whatsapp,
                                ceg=ceg,
                                slot=first_slot,
                                action_label=f"Pré-reserva de Item Avulso #{item_def.name} para {participant.display_name}"
                            )
                        except Exception:
                            pass
                    except (Participant.DoesNotExist, ValueError):
                        pass

            success_msg = f"🎁 Item Avulso '{item_def.name}' ({quantidade} unidade(s)) adicionado com sucesso!"
            if is_ajax:
                return JsonResponse({'success': True, 'message': success_msg})
            messages.success(request, success_msg)
            return redirect('ceg_detail', slug=slug)

        except Exception as e:
            logger.error(f"Erro ao criar item avulso: {e}")
            err_msg = f"Erro ao adicionar item avulso: {e}"
            if is_ajax:
                return JsonResponse({'success': False, 'message': err_msg}, status=500)
            messages.error(request, err_msg)
            return redirect('ceg_detail', slug=slug)


class UpdateAvulsoItemView(StaffRequiredMixin, View):
    """
    Permite à admin editar um item avulso existente:
    - Nome, membro, tipo_item, preço padrão, imagem
    - Quantidade de unidades (expande adicionando slots ou contrai removendo apenas slots vagos)
    """
    def post(self, request, slug, item_def_id):
        ceg = get_object_or_404(CEG, slug=slug)
        item_def = get_object_or_404(CEGItemDefinition, id=item_def_id, ceg=ceg, is_avulso=True)
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

        name = request.POST.get('name', '').strip()
        member_name = (request.POST.get('member_name') or request.POST.get('member') or '').strip()
        item_type = request.POST.get('item_type', item_def.item_type)
        tipo_item_id = request.POST.get('tipo_item_id')
        price_str = (request.POST.get('default_price') or request.POST.get('price') or '').replace(',', '.').strip()
        quantidade_str = str(request.POST.get('quantidade') or request.POST.get('quantity') or '').strip()

        image_file = request.FILES.get('image_file')
        image_base64 = request.POST.get('image_base64', '').strip()
        image_url_input = request.POST.get('image_url', '').strip()

        if name:
            item_def.name = name
        item_def.member_name = member_name

        if tipo_item_id:
            try:
                item_def.tipo_item = TipoItem.objects.filter(id=int(tipo_item_id)).first()
            except (ValueError, TypeError):
                pass
        elif tipo_item_id == '':
            item_def.tipo_item = None

        if item_type in CEGItemDefinition.ItemType.values:
            item_def.item_type = item_type

        price = None
        if price_str:
            try:
                price = Decimal(price_str)
                item_def.default_price = price
            except (InvalidOperation, ValueError):
                pass

        if image_file or image_base64:
            try:
                item_def.image_url = process_image_upload(
                    file_obj=image_file,
                    base64_str=image_base64,
                    folder='cegs/items',
                    fallback_url=''
                )
            except ValueError as e:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': str(e)}, status=400)
                messages.error(request, str(e))
                return redirect('ceg_detail', slug=slug)
        elif image_url_input:
            item_def.image_url = image_url_input

        try:
            with transaction.atomic():
                avulso_set = ceg.get_or_create_avulso_set()
                existing_slots = list(ItemSlot.objects.filter(set=avulso_set, item_definition=item_def).order_by('unit_number'))
                current_count = len(existing_slots)

                if quantidade_str:
                    try:
                        new_quantidade = max(1, int(quantidade_str))
                    except (ValueError, TypeError):
                        new_quantidade = current_count

                    if new_quantidade > current_count:
                        # Gera novas unidades
                        for u in range(current_count + 1, new_quantidade + 1):
                            ItemSlot.objects.create(
                                set=avulso_set,
                                item_definition=item_def,
                                unit_number=u,
                                price=item_def.default_price
                            )
                        item_def.quantidade_avulsa = new_quantidade
                    elif new_quantidade < current_count:
                        # Verifica se as unidades a serem removidas estão disponíveis
                        slots_to_remove = [s for s in existing_slots if s.unit_number > new_quantidade]
                        blocked = [s for s in slots_to_remove if s.status != ItemSlot.Status.AVAILABLE]
                        if blocked:
                            err_msg = f"Não é possível reduzir para {new_quantidade} unidade(s) porque a(s) unidade(s) #{', #'.join(str(s.unit_number) for s in blocked)} já possuem reserva ativa."
                            if is_ajax:
                                return JsonResponse({'success': False, 'message': err_msg}, status=400)
                            messages.error(request, err_msg)
                            return redirect('ceg_detail', slug=slug)
                        # Deleta com segurança as unidades excedentes
                        ItemSlot.objects.filter(id__in=[s.id for s in slots_to_remove]).delete()
                        item_def.quantidade_avulsa = new_quantidade

                # Se o preço mudou, atualiza nos slots disponíveis
                if price is not None:
                    ItemSlot.objects.filter(
                        set=avulso_set,
                        item_definition=item_def,
                        status=ItemSlot.Status.AVAILABLE
                    ).update(price=price)

                item_def.save()

            success_msg = f"🎁 Item Avulso '{item_def.name}' atualizado com sucesso!"
            if is_ajax:
                return JsonResponse({'success': True, 'message': success_msg})
            messages.success(request, success_msg)
            return redirect('ceg_detail', slug=slug)

        except Exception as e:
            logger.error(f"Erro ao atualizar item avulso: {e}")
            err_msg = f"Erro ao atualizar item avulso: {e}"
            if is_ajax:
                return JsonResponse({'success': False, 'message': err_msg}, status=500)
            messages.error(request, err_msg)
            return redirect('ceg_detail', slug=slug)


class DeleteAvulsoItemView(StaffRequiredMixin, View):
    """
    Permite à admin excluir um item avulso de uma CEG:
    - Impede exclusão se houver pagamentos confirmados (is_item_paid=True)
    - Deleta com segurança slots e a definição do item
    """
    def post(self, request, slug, item_def_id):
        ceg = get_object_or_404(CEG, slug=slug)
        item_def = get_object_or_404(CEGItemDefinition, id=item_def_id, ceg=ceg, is_avulso=True)
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

        slots = ItemSlot.objects.filter(item_definition=item_def)
        paid_slots = slots.filter(Q(is_item_paid=True) | Q(status=ItemSlot.Status.PAID))
        if paid_slots.exists():
            err_msg = f"Não é possível excluir o item '{item_def.name}' pois existem {paid_slots.count()} unidade(s) com pagamento já confirmado. Cancele/estorne os pagamentos antes."
            if is_ajax:
                return JsonResponse({'success': False, 'message': err_msg}, status=400)
            messages.error(request, err_msg)
            return redirect('ceg_detail', slug=slug)

        try:
            with transaction.atomic():
                item_name = item_def.name
                slots.delete()
                item_def.delete()

                # Se o set avulso ficou vazio, remove-o
                avulso_set = ceg.sets.filter(is_avulso=True).first()
                if avulso_set and avulso_set.slots.count() == 0:
                    avulso_set.delete()

            success_msg = f"🗑️ Item Avulso '{item_name}' foi excluído com sucesso."
            if is_ajax:
                return JsonResponse({'success': True, 'message': success_msg})
            messages.success(request, success_msg)
            return redirect('ceg_detail', slug=slug)

        except Exception as e:
            logger.error(f"Erro ao excluir item avulso: {e}")
            err_msg = f"Erro ao excluir item avulso: {e}"
            if is_ajax:
                return JsonResponse({'success': False, 'message': err_msg}, status=500)
            messages.error(request, err_msg)
            return redirect('ceg_detail', slug=slug)


class CropCEGItemPhotoView(View):
    """
    Endpoint AJAX para salvar a foto recortada de um item da CEG (CEGItemDefinition).
    Suporta:
    1. Base64 gerado pelo Cropper.js no browser (image_base64 / base64_data).
    2. Coordenadas {x, y, width, height} para recorte via Pillow no backend.
    """
    def post(self, request, slug, item_def_id):
        if not request.user.is_authenticated or not request.user.is_staff:
            return JsonResponse({'success': False, 'message': 'Acesso restrito ao organizador.'}, status=403)

        ceg = get_object_or_404(CEG, slug=slug)
        item_def = get_object_or_404(CEGItemDefinition, id=item_def_id, ceg=ceg)

        try:
            if request.content_type == 'application/json':
                data = json.loads(request.body.decode('utf-8') or '{}')
            else:
                data = request.POST
        except Exception:
            data = request.POST

        base64_data = data.get('base64_data') or data.get('image_base64')
        source_url = data.get('source_url') or (ceg.get_banner_image() if hasattr(ceg, 'get_banner_image') else '') or ceg.banner_url or ''
        x = data.get('x')
        y = data.get('y')
        width = data.get('width')
        height = data.get('height')

        new_image_url = ''

        # 1. Base64 exportado pelo Cropper.js no cliente
        if base64_data:
            try:
                new_image_url = process_image_upload(base64_str=base64_data, folder='items')
            except Exception as e:
                logger.error(f"Erro ao salvar Base64 do recorte de item: {e}")

        # 2. Coordenadas para corte no backend com Pillow
        elif x is not None and y is not None and width and height:
            try:
                new_image_url = crop_image_from_coordinates(
                    source_url_or_path=source_url,
                    x=float(x),
                    y=float(y),
                    width=float(width),
                    height=float(height),
                    folder='items'
                )
            except Exception as e:
                logger.error(f"Erro ao recortar via coordenadas Pillow: {e}")

        if new_image_url:
            item_def.image_url = new_image_url
            item_def.save(update_fields=['image_url'])
            return JsonResponse({
                'success': True,
                'image_url': new_image_url,
                'item_def_id': item_def.id,
                'item_name': item_def.name,
                'message': f"Foto de {item_def.name} recortada e salva com sucesso!"
            })

        return JsonResponse({
            'success': False,
            'message': 'Não foi possível processar a imagem recortada. Forneça dados Base64 ou coordenadas válidas.'
        }, status=400)

