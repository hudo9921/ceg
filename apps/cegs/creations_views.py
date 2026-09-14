import json
import logging
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View

from apps.groups.models import KpopGroup, Era
from apps.cegs.models import Caixa, CEG, CEGItemDefinition, CEGSet, ItemSlot, ItemIndividual, TipoItem
from apps.cegs.services import ClaimService
from apps.participants.models import Participant, Claim

logger = logging.getLogger(__name__)


class StaffRequiredMixin(AccessMixin):
    """Garante que apenas usuários autenticados e com permissão de staff (admin/organizador) tenham acesso."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            messages.error(request, "Acesso restrito: Você precisa estar autenticado como Administrador/Organizador.")
            return redirect(f"/admin/login/?next={request.path}")
        return super().dispatch(request, *args, **kwargs)


def parse_local_datetime(val_str: str):
    """Converte valor de input datetime-local em datetime ciente de timezone."""
    if not val_str:
        return None
    try:
        dt = parse_datetime(val_str.strip())
        if dt and timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt
    except Exception:
        return None


class CreationsHubView(StaffRequiredMixin, View):
    """Página principal de criações e gerenciamento para o Organizador."""

    def get(self, request):
        groups = KpopGroup.objects.prefetch_related('eras').order_by('name')
        eras = Era.objects.select_related('group').order_by('group__name', 'name')
        cegs = CEG.objects.select_related('era__group', 'caixa').prefetch_related('sets', 'item_definitions').order_by('-created_at')
        caixas = Caixa.objects.all().order_by('-created_at')
        itens_individuais = ItemIndividual.objects.select_related('caixa', 'comprador').order_by('-created_at')

        # Dicionário de grupos e eras para seleção em cascata no Alpine.js
        groups_data = []
        for g in groups:
            groups_data.append({
                'id': g.id,
                'name': g.name,
                'slug': g.slug,
                'image_url': g.image_url,
                'eras': [
                    {'id': e.id, 'name': e.name, 'slug': e.slug}
                    for e in g.eras.all()
                ]
            })

        # Resumo de inventário para a aba de listagem
        cegs_summary = []
        for c in cegs:
            cegs_summary.append({
                'id': c.id,
                'title': c.title,
                'slug': c.slug,
                'group_name': c.era.group.name,
                'era_name': c.era.name,
                'status': c.status,
                'status_display': c.get_status_display(),
                'caixa_id': c.caixa.id if c.caixa else None,
                'caixa_nome': c.caixa.nome if c.caixa else None,
                'caixa_slug': c.caixa.slug if c.caixa else None,
                'caixa_origem': c.caixa.origem if c.caixa else None,
                'shipping_status_display': c.get_shipping_status_display(),
                'sets_count': len(c.sets.all()),
                'active_sets_count': sum(1 for s in c.sets.all() if s.is_active),
                'items_count': len(c.item_definitions.all()),
                'opens_at': c.opens_at.strftime('%d/%m/%Y %H:%M') if c.opens_at else None,
                'prazo_pagamento_item': c.prazo_pagamento_item.strftime('%d/%m/%Y %H:%M') if c.prazo_pagamento_item else None,
                'frete_inter': str(c.frete_inter) if c.frete_inter is not None else None,
                'taxa_aduaneira': str(c.taxa_aduaneira) if c.taxa_aduaneira is not None else None,
                'prazo_pagamento_frete_inter': c.prazo_pagamento_frete_inter.strftime('%d/%m/%Y %H:%M') if c.prazo_pagamento_frete_inter else None,
                'prazo_pagamento_taxa_aduaneira': c.prazo_pagamento_taxa_aduaneira.strftime('%d/%m/%Y %H:%M') if c.prazo_pagamento_taxa_aduaneira else None,
                'is_standby': c.is_standby,
                'pix_key': c.pix_key,
            })

        # Participantes cadastrados para pré-reserva de itens no cadastro da CEG
        participants = list(
            Participant.objects.all().order_by('name').values(
                'id', 'name', 'username', 'whatsapp', 'social_handle'
            )
        )

        # Itens Individuais (Mercari) serializados para modal de edição ágil
        itens_individuais_data = []
        for item in itens_individuais:
            itens_individuais_data.append({
                'id': item.id,
                'nome': item.nome,
                'tipo_item_id': item.tipo_item_id,
                'tipo_item_nome': item.tipo_item.nome if item.tipo_item else 'Item',
                'link_pedido': item.link_pedido,
                'quantidade': item.quantidade,
                'caixa_id': item.caixa_id,
                'caixa_nome': item.caixa.nome if item.caixa else None,
                'caixa_slug': item.caixa.slug if item.caixa else None,
                'caixa_origem': item.caixa.origem if item.caixa else None,
                'status': item.status,
                'status_display': item.get_status_display(),
                'comprador_id': item.comprador_id,
                'comprador_nome': item.comprador.display_name if item.comprador else '',
                'comprador_whatsapp': item.comprador.whatsapp if item.comprador else '',
                'comprador_username': item.comprador.username if item.comprador else '',
                'comprador_social': item.comprador.social_handle if item.comprador else '',
                'preco_produto': str(item.preco_produto) if item.preco_produto else '',
                'frete_inter': str(item.frete_inter) if item.frete_inter else '',
                'frete_inter_pago': item.frete_inter_pago,
                'prazo_frete_inter': item.prazo_frete_inter.strftime('%Y-%m-%dT%H:%M') if item.prazo_frete_inter else '',
                'taxa_aduaneira': str(item.taxa_aduaneira) if item.taxa_aduaneira else '',
                'taxa_aduaneira_paga': item.taxa_aduaneira_paga,
                'prazo_taxa_aduaneira': item.prazo_taxa_aduaneira.strftime('%Y-%m-%dT%H:%M') if item.prazo_taxa_aduaneira else '',
                'image_url': item.image_display_url,
                'observacoes': item.observacoes or '',
            })

        caixas_data = [
            {
                'id': cx.id,
                'nome': cx.nome,
                'slug': cx.slug,
                'origem': cx.origem,
                'origem_display': cx.get_origem_display(),
                'status': cx.status,
                'status_display': cx.get_status_display(),
                'is_mercari': cx.origem == 'JP',
            }
            for cx in caixas
        ]
        caixas_mercari = [cx for cx in caixas if cx.origem == 'JP']

        category_filter = request.GET.get('category', request.GET.get('tab', 'all'))
        if category_filter not in ['all', 'ceg', 'mercari']:
            category_filter = 'all'

        tipos_item = list(TipoItem.objects.all().order_by('nome'))
        tipos_item_data = [{'id': t.id, 'nome': t.nome} for t in tipos_item]

        context = {
            'groups': groups,
            'eras': eras,
            'cegs': cegs,
            'caixas': caixas,
            'caixas_mercari': caixas_mercari,
            'caixas_json': json.dumps(caixas_data),
            'groups_json': json.dumps(groups_data),
            'participants': participants,
            'participants_json': json.dumps(participants),
            'cegs_summary': cegs_summary,
            'item_types': CEGItemDefinition.ItemType.choices,
            'tipos_item': tipos_item,
            'tipos_item_json': json.dumps(tipos_item_data),
            'ceg_statuses': CEG.Status.choices,
            'active_tab': request.GET.get('tab', 'ceg'),
            'category_filter': category_filter,
            'category': category_filter,
            'preselected_caixa_id': int(request.GET.get('caixa_id')) if request.GET.get('caixa_id', '').isdigit() else '',
            'auto_open_modal': request.GET.get('open', ''),
            'total_groups': groups.count(),
            'total_eras': eras.count(),
            'total_cegs': cegs.count(),
            'open_cegs': cegs.filter(status=CEG.Status.OPEN).count(),
            'itens_individuais': itens_individuais,
            'itens_individuais_json': json.dumps(itens_individuais_data),
            'total_itens_individuais': itens_individuais.count(),
            'item_individual_statuses': ItemIndividual.Status.choices,
        }
        return render(request, 'cegs/creations.html', context)


class CreateGroupView(StaffRequiredMixin, View):
    """Cadastra um novo Grupo ou Solista de K-pop."""

    def post(self, request):
        name = request.POST.get('name', '').strip()
        image_url = request.POST.get('image_url', '').strip()
        description = request.POST.get('description', '').strip()

        if not name:
            messages.error(request, "O nome do grupo é obrigatório.")
            return redirect('/creations/?tab=group')

        try:
            group = KpopGroup.objects.create(
                name=name,
                image_url=image_url,
                description=description
            )
            messages.success(request, f"🎤 Grupo/Solista '{group.name}' cadastrado com sucesso! Agora você pode criar uma Era para ele.")
            return redirect('/creations/?tab=era')
        except Exception as e:
            logger.error(f"Erro ao criar grupo: {e}")
            messages.error(request, f"Erro ao cadastrar grupo: {e}")
            return redirect('/creations/?tab=group')


class CreateEraView(StaffRequiredMixin, View):
    """Cadastra uma nova Era / Álbum / Comeback vinculado a um grupo."""

    def post(self, request):
        group_id = request.POST.get('group_id')
        name = request.POST.get('name', '').strip()
        release_date = request.POST.get('release_date') or None
        banner_url = request.POST.get('banner_url', '').strip()
        description = request.POST.get('description', '').strip()

        if not group_id or not name:
            messages.error(request, "Selecione o Grupo e preencha o Nome da Era.")
            return redirect('/creations/?tab=era')

        group = get_object_or_404(KpopGroup, id=group_id)

        try:
            era = Era.objects.create(
                group=group,
                name=name,
                release_date=release_date,
                banner_url=banner_url,
                description=description
            )
            messages.success(request, f"💿 Era '{era.name}' ({group.name}) criada com sucesso! Você já pode abrir uma CEG para esta Era.")
            return redirect('/creations/?tab=ceg')
        except Exception as e:
            logger.error(f"Erro ao criar era: {e}")
            messages.error(request, f"Erro ao cadastrar era: {e}")
            return redirect('/creations/?tab=era')


class CreateCEGView(StaffRequiredMixin, View):
    """
    Cadastra uma nova CEG completa com:
    - Informações gerais (datas, status, chave pix, regras, prazos, taxas)
    - Construtor dinâmico de itens/photocards com valores
    - Geração automática do Set #1 e de seus slots físicos
    """

    def post(self, request):
        era_id = request.POST.get('era_id')
        caixa_id = request.POST.get('caixa_id', '').strip()
        title = request.POST.get('title', '').strip()
        status = request.POST.get('status', CEG.Status.OPEN)
        opens_at_str = request.POST.get('opens_at', '').strip()
        closes_at_str = request.POST.get('closes_at', '').strip()
        prazo_pagamento_item_str = request.POST.get('prazo_pagamento_item', '').strip()
        frete_inter_str = request.POST.get('frete_inter', '').strip()
        taxa_aduaneira_str = request.POST.get('taxa_aduaneira', '').strip()
        prazo_pagamento_frete_inter_str = request.POST.get('prazo_pagamento_frete_inter', '').strip()
        prazo_pagamento_taxa_aduaneira_str = request.POST.get('prazo_pagamento_taxa_aduaneira', '').strip()
        pix_key = request.POST.get('pix_key', '').strip()
        pix_instructions = request.POST.get('pix_instructions', '').strip()
        banner_url = request.POST.get('banner_url', '').strip()
        description = request.POST.get('description', '').strip()

        initial_sets_count = int(request.POST.get('initial_sets_count', 1) or 1)
        initial_sets_count = max(1, min(initial_sets_count, 10))

        if not era_id or not title:
            messages.error(request, "Por favor, selecione a Era e preencha o Título da CEG.")
            return redirect('/creations/?tab=ceg')

        era = get_object_or_404(Era, id=era_id)
        opens_at = parse_local_datetime(opens_at_str)
        closes_at = parse_local_datetime(closes_at_str)
        prazo_pagamento_item = parse_local_datetime(prazo_pagamento_item_str)
        prazo_pagamento_frete_inter = parse_local_datetime(prazo_pagamento_frete_inter_str)
        prazo_pagamento_taxa_aduaneira = parse_local_datetime(prazo_pagamento_taxa_aduaneira_str)

        def parse_optional_decimal(v_str):
            if not v_str:
                return None
            try:
                return Decimal(str(v_str).replace('R$', '').replace(' ', '').replace(',', '.').strip())
            except (InvalidOperation, ValueError):
                return None

        frete_inter = parse_optional_decimal(frete_inter_str)
        taxa_aduaneira = parse_optional_decimal(taxa_aduaneira_str)

        # Se tiver opens_at no futuro e status for OPEN, ajusta para SCHEDULED
        if opens_at and timezone.now() < opens_at and status == CEG.Status.OPEN:
            status = CEG.Status.SCHEDULED

        # Processamento dos itens/photocards definidos
        items_payload = []
        raw_items_json = request.POST.get('items_json', '').strip()
        if raw_items_json:
            try:
                items_payload = json.loads(raw_items_json)
            except Exception:
                items_payload = []

        # Fallback para campos tradicionais de formulário se items_json não estiver presente
        if not items_payload:
            item_names = request.POST.getlist('item_name[]')
            item_members = request.POST.getlist('item_member[]')
            item_types = request.POST.getlist('item_type[]')
            item_prices = request.POST.getlist('item_price[]')
            item_images = request.POST.getlist('item_image[]')
            item_tipos = request.POST.getlist('item_tipo_id[]')

            for idx, i_name in enumerate(item_names):
                if i_name.strip():
                    items_payload.append({
                        'name': i_name.strip(),
                        'member_name': item_members[idx].strip() if idx < len(item_members) else '',
                        'item_type': item_types[idx].strip() if idx < len(item_types) else CEGItemDefinition.ItemType.PHOTOCARD,
                        'tipo_item_id': item_tipos[idx].strip() if idx < len(item_tipos) else '',
                        'default_price': item_prices[idx].strip() if idx < len(item_prices) else '45.00',
                        'image_url': item_images[idx].strip() if idx < len(item_images) else '',
                        'order_index': idx + 1,
                    })

        # Atrela caixa existente se especificada
        caixa = None
        shipping_status = Caixa.Status.EM_CONSOLIDACAO
        if caixa_id:
            try:
                caixa = Caixa.objects.filter(id=int(caixa_id)).first()
                if caixa:
                    shipping_status = caixa.status
            except (ValueError, TypeError):
                caixa = None

        try:
            with transaction.atomic():
                # 1. Cria a CEG
                ceg = CEG.objects.create(
                    era=era,
                    caixa=caixa,
                    shipping_status=shipping_status,
                    title=title,
                    status=status,
                    opens_at=opens_at,
                    closes_at=closes_at,
                    prazo_pagamento_item=prazo_pagamento_item,
                    frete_inter=frete_inter,
                    taxa_aduaneira=taxa_aduaneira,
                    prazo_pagamento_frete_inter=prazo_pagamento_frete_inter,
                    prazo_pagamento_taxa_aduaneira=prazo_pagamento_taxa_aduaneira,
                    pix_key=pix_key,
                    pix_instructions=pix_instructions,
                    banner_url=banner_url,
                    description=description
                )

                # 2. Cria cada definição de item
                created_items_map = []
                for order_idx, item_data in enumerate(items_payload, start=1):
                    i_name = item_data.get('name', '').strip()
                    if not i_name:
                        continue

                    raw_price = str(item_data.get('default_price', '0.00')).replace(',', '.')
                    try:
                        price = Decimal(raw_price)
                    except (InvalidOperation, ValueError):
                        price = Decimal('0.00')

                    tipo_item_id = item_data.get('tipo_item_id')
                    tipo_item = None
                    if tipo_item_id:
                        try:
                            tipo_item = TipoItem.objects.filter(id=int(tipo_item_id)).first()
                        except (ValueError, TypeError):
                            tipo_item = None

                    item_def = CEGItemDefinition.objects.create(
                        ceg=ceg,
                        name=i_name,
                        member_name=item_data.get('member_name', '').strip(),
                        item_type=item_data.get('item_type', CEGItemDefinition.ItemType.PHOTOCARD),
                        tipo_item=tipo_item,
                        default_price=price,
                        image_url=item_data.get('image_url', '').strip(),
                        order_index=int(item_data.get('order_index', order_idx))
                    )
                    created_items_map.append((item_def, item_data))

                # 3. Cria os Sets iniciais e gera os slots para reserva
                generated_slots_count = 0
                pre_reserved_count = 0
                now = timezone.now()

                for set_num in range(1, initial_sets_count + 1):
                    ceg_set = CEGSet.objects.create(
                        ceg=ceg,
                        set_number=set_num,
                        is_active=True,
                        notes=f"Set #{set_num} inicial"
                    )
                    slots = ceg_set.generate_slots()
                    generated_slots_count += len(slots)

                    # No Set #1, se houver pré-reserva configurada para o item, vincula ao participante pré-existente
                    if set_num == 1:
                        item_data_by_def = {idef.id: idata for (idef, idata) in created_items_map}
                        for slot in slots:
                            idata = item_data_by_def.get(slot.item_definition_id)
                            p_id = idata.get('participant_id') or idata.get('pre_assigned_participant_id') if idata else None
                            if p_id:
                                try:
                                    participant = Participant.objects.get(id=int(p_id))
                                    slot.claimed_by = participant
                                    slot.status = ItemSlot.Status.RESERVED
                                    slot.claimed_at = now
                                    slot.save(update_fields=['claimed_by', 'status', 'claimed_at'])

                                    Claim.objects.create(
                                        slot=slot,
                                        participant=participant,
                                        status=Claim.Status.PENDING,
                                        total_price=slot.price,
                                        participant_notes="Pré-reservado pelo organizador na abertura da CEG",
                                        claimed_at=now
                                    )
                                    pre_reserved_count += 1
                                except (Participant.DoesNotExist, ValueError):
                                    pass

            pre_info = f", com {pre_reserved_count} item(ns) pré-reservado(s)" if pre_reserved_count > 0 else ""
            messages.success(
                request,
                f"🎉 CEG '{ceg.title}' criada com sucesso! "
                f"{len(created_items_map)} itens definidos{pre_info} e {initial_sets_count} Set(s) gerados "
                f"({generated_slots_count} slots prontos para reservas)."
            )
            return redirect('ceg_detail', slug=ceg.slug)

        except Exception as e:
            logger.error(f"Erro ao criar CEG completa: {e}")
            messages.error(request, f"Erro ao criar CEG: {e}")
            return redirect('/creations/?tab=ceg')


class CreateSetView(StaffRequiredMixin, View):
    """Adiciona um novo Set a uma CEG existente e gera os slots automaticamente."""

    def post(self, request):
        ceg_id = request.POST.get('ceg_id')
        set_number_input = request.POST.get('set_number', '').strip()
        notes = request.POST.get('notes', '').strip()
        is_active = request.POST.get('is_active') == 'on' or request.POST.get('is_active') == 'true'

        if not ceg_id:
            messages.error(request, "Selecione a CEG para a qual deseja adicionar o Set.")
            return redirect('/creations/?tab=sets')

        ceg = get_object_or_404(CEG, id=ceg_id)

        # Determina o próximo número do Set
        if set_number_input and set_number_input.isdigit():
            set_number = int(set_number_input)
        else:
            last_set = ceg.sets.order_by('-set_number').first()
            set_number = (last_set.set_number + 1) if last_set else 1

        if ceg.sets.filter(set_number=set_number).exists():
            messages.error(request, f"O Set #{set_number} já existe para a CEG '{ceg.title}'. Escolha outro número.")
            return redirect('/creations/?tab=sets')

        try:
            with transaction.atomic():
                new_set = CEGSet.objects.create(
                    ceg=ceg,
                    set_number=set_number,
                    is_active=is_active,
                    notes=notes or f"Set #{set_number}"
                )
                created_slots = new_set.generate_slots()
                promoted_count = ClaimService.allocate_waiting_list_for_slots(created_slots)

            msg = (
                f"📦 Set #{new_set.set_number} adicionado com sucesso à CEG '{ceg.title}'! "
                f"{len(created_slots)} slots físicos foram gerados."
            )
            if promoted_count > 0:
                msg += f" 🎯 {promoted_count} participante(s) da Lista de Espera foram alocados automaticamente nas vagas do novo set!"

            messages.success(request, msg)
            return redirect('ceg_detail', slug=ceg.slug)
        except Exception as e:
            logger.error(f"Erro ao criar set: {e}")
            messages.error(request, f"Erro ao adicionar Set: {e}")
            return redirect('/creations/?tab=sets')


class AddItemToCEGView(StaffRequiredMixin, View):
    """Adiciona uma nova definição de item/photocard a uma CEG existente."""

    def post(self, request):
        ceg_id = request.POST.get('ceg_id')
        name = request.POST.get('name', '').strip()
        member_name = request.POST.get('member_name', '').strip()
        item_type = request.POST.get('item_type', CEGItemDefinition.ItemType.PHOTOCARD)
        price_str = request.POST.get('default_price', '0.00').replace(',', '.').strip()
        image_url = request.POST.get('image_url', '').strip()
        sync_active_sets = request.POST.get('sync_active_sets') == 'on' or request.POST.get('sync_active_sets') == 'true'

        if not ceg_id or not name:
            messages.error(request, "Selecione a CEG e informe o Nome do Item.")
            return redirect('/creations/?tab=items')

        ceg = get_object_or_404(CEG, id=ceg_id)

        try:
            price = Decimal(price_str)
        except (InvalidOperation, ValueError):
            price = Decimal('0.00')

        try:
            with transaction.atomic():
                last_order = ceg.item_definitions.count()
                tipo_item_id = request.POST.get('tipo_item_id')
                tipo_item = None
                if tipo_item_id:
                    try:
                        tipo_item = TipoItem.objects.filter(id=int(tipo_item_id)).first()
                    except (ValueError, TypeError):
                        tipo_item = None

                item_def = CEGItemDefinition.objects.create(
                    ceg=ceg,
                    name=name,
                    member_name=member_name,
                    item_type=item_type,
                    tipo_item=tipo_item,
                    default_price=price,
                    image_url=image_url,
                    order_index=last_order + 1
                )

                synced_count = 0
                if sync_active_sets:
                    for s in ceg.sets.filter(is_active=True):
                        slot, created = ItemSlot.objects.get_or_create(
                            set=s,
                            item_definition=item_def,
                            defaults={'price': price}
                        )
                        if created:
                            synced_count += 1

            messages.success(
                request,
                f"✨ Item '{item_def.name}' adicionado à CEG '{ceg.title}'. "
                f"{f'{synced_count} novos slots gerados nos sets ativos.' if sync_active_sets else ''}"
            )
            return redirect('ceg_detail', slug=ceg.slug)
        except Exception as e:
            logger.error(f"Erro ao adicionar item à CEG: {e}")
            messages.error(request, f"Erro ao adicionar item: {e}")
            return redirect('/creations/?tab=items')
