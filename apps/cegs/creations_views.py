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

from apps.groups.models import KpopGroup, Era, GroupMember
from apps.cegs.models import Caixa, CEG, CEGItemDefinition, CEGSet, ItemSlot, ItemIndividual, TipoItem
from apps.cegs.services import ClaimService
from .image_utils import process_image_upload
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
        groups = KpopGroup.objects.prefetch_related('eras', 'members').order_by('name')
        eras = Era.objects.select_related('group').order_by('group__name', 'name')
        cegs = CEG.objects.select_related('era__group').prefetch_related('sets').order_by('-created_at')
        caixas = Caixa.objects.all().order_by('-created_at')

        # Dicionário de grupos e eras para seleção em cascata e edição no Alpine.js
        groups_data = []
        for g in groups:
            members_list = list(g.members.all())
            groups_data.append({
                'id': g.id,
                'name': g.name,
                'slug': g.slug,
                'image_url': g.image_url,
                'color_hex': g.color_hex or '',
                'description': g.description or '',
                'members_count': len(members_list),
                'members': [
                    {'id': m.id, 'name': m.name, 'order': m.order}
                    for m in members_list
                ],
                'eras': [
                    {
                        'id': e.id,
                        'name': e.name,
                        'slug': e.slug,
                        'release_date': e.release_date.strftime('%Y-%m-%d') if e.release_date else '',
                        'banner_url': e.banner_url,
                        'color_hex': e.color_hex or '',
                        'description': e.description or '',
                        'group_id': g.id,
                        'group_name': g.name,
                    }
                    for e in g.eras.all()
                ]
            })

        # Participantes cadastrados para pré-reserva de itens no cadastro da CEG
        participants = list(
            Participant.objects.all().order_by('name').values(
                'id', 'name', 'username', 'whatsapp', 'social_handle'
            )
        )

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
            'open_cegs': sum(1 for c in cegs if c.status == CEG.Status.OPEN),
            'item_individual_statuses': ItemIndividual.Status.choices,
        }
        return render(request, 'cegs/creations.html', context)


def extract_member_names(request):
    """
    Extrai lista de nomes de integrantes de várias possíveis fontes no POST:
    - members_json (JSON string: '["Sakura", "Chaewon"]')
    - members[] ou member_names[] (getlist)
    - members_text (nomes separados por vírgula ou quebra de linha)
    """
    raw_names = []
    members_json = request.POST.get('members_json', '').strip()
    if members_json:
        try:
            parsed = json.loads(members_json)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        n = item.get('name', '').strip()
                    else:
                        n = str(item).strip()
                    if n:
                        raw_names.append(n)
        except Exception:
            pass

    if not raw_names:
        list_names = (
            request.POST.getlist('member_names') or
            request.POST.getlist('members[]') or
            request.POST.getlist('members')
        )
        for n in list_names:
            n_clean = str(n).strip()
            if n_clean:
                raw_names.append(n_clean)

    if not raw_names:
        text_names = request.POST.get('members_text', '').strip()
        if text_names:
            parts = [p.strip() for p in text_names.replace('\n', ',').replace(';', ',').split(',') if p.strip()]
            raw_names.extend(parts)

    # Se houver nome digitado pendente no input (caso o usuário aperte Atualizar diretamente)
    uncommitted = request.POST.get('editGroupMemberInput', '').strip() or request.POST.get('newGroupMemberInput', '').strip()
    if uncommitted:
        parts = [p.strip() for p in uncommitted.replace('\n', ',').replace(';', ',').split(',') if p.strip()]
        for p in parts:
            if p:
                raw_names.append(p)

    seen = set()
    unique_names = []
    for n in raw_names:
        n_norm = n.strip()
        if n_norm and n_norm.lower() not in seen:
            seen.add(n_norm.lower())
            unique_names.append(n_norm)
    return unique_names


class CreateGroupView(StaffRequiredMixin, View):
    """Cadastra um novo Grupo ou Solista de K-pop."""

    def post(self, request):
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        image_file = request.FILES.get('image_file')
        image_base64 = request.POST.get('image_base64', '').strip()
        image_url_input = request.POST.get('image_url', '').strip()

        color_hex = request.POST.get('color_hex', '').strip()

        if not name:
            messages.error(request, "O nome do grupo é obrigatório.")
            return redirect('/creations/?tab=group')

        try:
            image_url = process_image_upload(
                file_obj=image_file,
                base64_str=image_base64,
                folder='groups',
                fallback_url=image_url_input
            )
        except ValueError as e:
            messages.error(request, f"⚠️ {e}")
            return redirect('/creations/?tab=group')

        if color_hex:
            if not color_hex.startswith('#') and len(color_hex) in (3, 6):
                color_hex = f"#{color_hex}"
        elif image_url:
            try:
                from apps.groups.color_utils import extract_dominant_color
                color_hex = extract_dominant_color(image_url) or ''
            except Exception:
                color_hex = ''

        try:
            group = KpopGroup.objects.create(
                name=name,
                image_url=image_url,
                color_hex=color_hex,
                description=description
            )

            member_names = extract_member_names(request)
            for idx, m_name in enumerate(member_names):
                GroupMember.objects.create(group=group, name=m_name, order=idx)

            members_msg = f" com {len(member_names)} integrante(s)" if member_names else ""
            messages.success(request, f"🎤 Grupo/Solista '{group.name}' cadastrado{members_msg} com sucesso! Agora você pode criar uma Era para ele.")
            return redirect('/creations/?tab=era')
        except Exception as e:
            logger.error(f"Erro ao criar grupo: {e}")
            messages.error(request, f"Erro ao cadastrar grupo: {e}")
            return redirect('/creations/?tab=group')


class UpdateGroupView(StaffRequiredMixin, View):
    """Atualiza as informações de um Grupo ou Solista existente."""

    def post(self, request):
        group_id = request.POST.get('group_id')
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        image_file = request.FILES.get('image_file')
        image_base64 = request.POST.get('image_base64', '').strip()
        image_url_input = request.POST.get('image_url', '').strip()

        color_hex = request.POST.get('color_hex', '').strip()

        if not group_id:
            messages.error(request, "Selecione um grupo para atualizar.")
            return redirect('/creations/?tab=group')

        group = get_object_or_404(KpopGroup, id=group_id)

        if not name:
            messages.error(request, "O nome do grupo é obrigatório.")
            return redirect('/creations/?tab=group')

        try:
            if image_file or image_base64:
                image_url = process_image_upload(
                    file_obj=image_file,
                    base64_str=image_base64,
                    folder='groups',
                    fallback_url=''
                )
            elif 'image_url' in request.POST:
                image_url = process_image_upload(
                    file_obj=None,
                    base64_str=None,
                    folder='groups',
                    fallback_url=image_url_input
                )
            else:
                image_url = group.image_url
        except ValueError as e:
            messages.error(request, f"⚠️ {e}")
            return redirect('/creations/?tab=group')

        if color_hex:
            if not color_hex.startswith('#') and len(color_hex) in (3, 6):
                color_hex = f"#{color_hex}"
            group.color_hex = color_hex
        elif image_url:
            # Modo Auto: extrai ou re-extrai a cor da imagem do grupo
            try:
                from apps.groups.color_utils import extract_dominant_color
                group.color_hex = extract_dominant_color(image_url) or ''
            except Exception as e:
                logger.error(f"Erro ao extrair cor do grupo: {e}")
                group.color_hex = ''
        else:
            group.color_hex = ''

        try:
            group.name = name
            group.description = description
            group.image_url = image_url
            group.save()

            if any(k in request.POST for k in ('members_json', 'members_text', 'member_names', 'members[]', 'members', 'editGroupMemberInput', 'newGroupMemberInput')):
                member_names = extract_member_names(request)
                existing_members = {m.name.lower(): m for m in group.members.all()}
                kept_ids = []
                for idx, m_name in enumerate(member_names):
                    m_obj = existing_members.get(m_name.lower())
                    if m_obj:
                        m_obj.name = m_name
                        m_obj.order = idx
                        m_obj.save()
                        kept_ids.append(m_obj.id)
                    else:
                        new_m = GroupMember.objects.create(group=group, name=m_name, order=idx)
                        kept_ids.append(new_m.id)
                group.members.exclude(id__in=kept_ids).delete()

            messages.success(request, f"🎤 Grupo '{group.name}' atualizado com sucesso!")
            return redirect('/creations/?tab=group')
        except Exception as e:
            logger.error(f"Erro ao atualizar grupo: {e}")
            messages.error(request, f"Erro ao atualizar grupo: {e}")
            return redirect('/creations/?tab=group')


class CreateEraView(StaffRequiredMixin, View):
    """Cadastra uma nova Era / Álbum / Comeback vinculado a um grupo."""

    def post(self, request):
        group_id = request.POST.get('group_id')
        name = request.POST.get('name', '').strip()
        release_date = request.POST.get('release_date') or None
        banner_file = request.FILES.get('banner_file')
        banner_base64 = request.POST.get('banner_base64', '').strip()
        banner_url_input = request.POST.get('banner_url', '').strip()
        color_hex = request.POST.get('color_hex', '').strip()
        description = request.POST.get('description', '').strip()

        if not group_id or not name:
            messages.error(request, "Selecione o Grupo e preencha o Nome da Era.")
            return redirect('/creations/?tab=era')

        group = get_object_or_404(KpopGroup, id=group_id)

        try:
            banner_url = process_image_upload(
                file_obj=banner_file,
                base64_str=banner_base64,
                folder='eras',
                fallback_url=banner_url_input
            )
        except ValueError as e:
            messages.error(request, f"⚠️ {e}")
            return redirect('/creations/?tab=era')

        if color_hex:
            if not color_hex.startswith('#') and len(color_hex) in (3, 6):
                color_hex = f"#{color_hex}"
        elif banner_url:
            try:
                from apps.groups.color_utils import extract_dominant_color
                color_hex = extract_dominant_color(banner_url) or ''
            except Exception:
                color_hex = ''
        elif group and (getattr(group, 'color_hex', None) or getattr(group, 'image_url', None)):
            if getattr(group, 'color_hex', None):
                color_hex = group.color_hex
            elif getattr(group, 'image_url', None):
                try:
                    from apps.groups.color_utils import extract_dominant_color
                    color_hex = extract_dominant_color(group.image_url) or ''
                except Exception:
                    color_hex = ''
        else:
            color_hex = ''

        try:
            era = Era.objects.create(
                group=group,
                name=name,
                release_date=release_date,
                banner_url=banner_url,
                color_hex=color_hex,
                description=description
            )
            messages.success(request, f"CD Era '{era.name}' ({group.name}) criada com sucesso! Você já pode abrir uma CEG para esta Era.")
            return redirect('/creations/?tab=ceg')
        except Exception as e:
            logger.error(f"Erro ao criar era: {e}")
            messages.error(request, f"Erro ao cadastrar era: {e}")
            return redirect('/creations/?tab=era')


class UpdateEraView(StaffRequiredMixin, View):
    """Atualiza as informações de uma Era / Comeback existente."""

    def post(self, request):
        era_id = request.POST.get('era_id')
        group_id = request.POST.get('group_id')
        name = request.POST.get('name', '').strip()
        release_date = request.POST.get('release_date') or None
        banner_file = request.FILES.get('banner_file')
        banner_base64 = request.POST.get('banner_base64', '').strip()
        banner_url_input = request.POST.get('banner_url', '').strip()
        color_hex = request.POST.get('color_hex', '').strip()
        description = request.POST.get('description', '').strip()

        if not era_id:
            messages.error(request, "Selecione uma Era para atualizar.")
            return redirect('/creations/?tab=era')

        era = get_object_or_404(Era, id=era_id)

        if not group_id or not name:
            messages.error(request, "Selecione o Grupo e preencha o Nome da Era.")
            return redirect('/creations/?tab=era')

        group = get_object_or_404(KpopGroup, id=group_id)

        try:
            if banner_file or banner_base64:
                banner_url = process_image_upload(
                    file_obj=banner_file,
                    base64_str=banner_base64,
                    folder='eras',
                    fallback_url=''
                )
            elif 'banner_url' in request.POST:
                banner_url = process_image_upload(
                    file_obj=None,
                    base64_str=None,
                    folder='eras',
                    fallback_url=banner_url_input
                )
            else:
                banner_url = era.banner_url
        except ValueError as e:
            messages.error(request, f"⚠️ {e}")
            return redirect('/creations/?tab=era')

        if color_hex:
            if not color_hex.startswith('#') and len(color_hex) in (3, 6):
                color_hex = f"#{color_hex}"
            era.color_hex = color_hex
        elif banner_url:
            # Modo Auto: extrai ou re-extrai a cor predominante do banner
            try:
                from apps.groups.color_utils import extract_dominant_color
                extracted = extract_dominant_color(banner_url)
                era.color_hex = extracted or ''
            except Exception as e:
                logger.error(f"Erro ao extrair cor da era: {e}")
                era.color_hex = ''
        elif group and (getattr(group, 'color_hex', None) or getattr(group, 'image_url', None)):
            # Se a Era não possui banner próprio, herda a cor do Grupo
            if getattr(group, 'color_hex', None):
                era.color_hex = group.color_hex
            elif getattr(group, 'image_url', None):
                try:
                    from apps.groups.color_utils import extract_dominant_color
                    era.color_hex = extract_dominant_color(group.image_url) or ''
                except Exception:
                    era.color_hex = ''
        else:
            era.color_hex = ''

        try:
            era.group = group
            era.name = name
            era.release_date = release_date
            era.banner_url = banner_url
            era.description = description
            era.save()
            messages.success(request, f"CD Era '{era.name}' ({group.name}) atualizada com sucesso!")
            return redirect('/creations/?tab=era')
        except Exception as e:
            logger.error(f"Erro ao atualizar era: {e}")
            messages.error(request, f"Erro ao atualizar era: {e}")
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
        banner_file = request.FILES.get('banner_file')
        banner_base64 = request.POST.get('banner_base64', '').strip()
        banner_url_input = request.POST.get('banner_url', '').strip()
        description = request.POST.get('description', '').strip()

        if status == CEG.Status.POLLING:
            initial_sets_count = 0
        else:
            initial_sets_count = int(request.POST.get('initial_sets_count', 1) or 1)
            initial_sets_count = max(1, min(initial_sets_count, 10))

        if not era_id or not title:
            messages.error(request, "Por favor, selecione a Era e preencha o Título da CEG.")
            return redirect('/creations/?tab=ceg')

        era = get_object_or_404(Era, id=era_id)

        # Processa upload de banner da CEG (arquivo, base64 ou URL)
        try:
            banner_url = process_image_upload(
                file_obj=banner_file,
                base64_str=banner_base64,
                folder='cegs/banners',
                fallback_url=banner_url_input
            )
        except ValueError as e:
            messages.error(request, f"⚠️ {e}")
            return redirect('/creations/?tab=ceg')

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
            item_sub_cats = request.POST.getlist('item_sub_category[]')

            for idx, i_name in enumerate(item_names):
                if i_name.strip():
                    items_payload.append({
                        'name': i_name.strip(),
                        'member_name': item_members[idx].strip() if idx < len(item_members) else '',
                        'item_type': item_types[idx].strip() if idx < len(item_types) else CEGItemDefinition.ItemType.PHOTOCARD,
                        'tipo_item_id': item_tipos[idx].strip() if idx < len(item_tipos) else '',
                        'sub_category': item_sub_cats[idx].strip() if idx < len(item_sub_cats) else '',
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

                    is_av = bool(item_data.get('is_avulso', False))
                    qtd_av = max(1, int(item_data.get('quantidade_avulsa', 1) or 1)) if is_av else 1

                    item_def = CEGItemDefinition.objects.create(
                        ceg=ceg,
                        name=i_name,
                        member_name=item_data.get('member_name', '').strip(),
                        item_type=item_data.get('item_type', CEGItemDefinition.ItemType.PHOTOCARD),
                        tipo_item=tipo_item,
                        sub_category=item_data.get('sub_category', '').strip(),
                        default_price=price,
                        image_url=item_data.get('image_url', '').strip(),
                        is_avulso=is_av,
                        quantidade_avulsa=qtd_av,
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
                        item_data_by_def = {idef.id: idata for (idef, idata) in created_items_map if not idef.is_avulso}
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
                                    try:
                                        from apps.cegs.audit_service import AuditService
                                        AuditService.log_slot_assignment(
                                            slot=slot,
                                            participant=participant,
                                            action='assign',
                                            actor=request.user,
                                            metadata={'notes': 'Pré-reserva na criação da CEG'}
                                        )
                                    except Exception:
                                        pass
                                    pre_reserved_count += 1
                                except (Participant.DoesNotExist, ValueError):
                                    pass

                # 4. Se houver itens avulsos definidos, gera o set especial de avulsos e seus slots
                has_avulsos = any(idef.is_avulso for idef, _ in created_items_map)
                if has_avulsos:
                    avulso_set = ceg.get_or_create_avulso_set()
                    av_slots = avulso_set.generate_slots()
                    generated_slots_count += len(av_slots)

                    item_data_by_def = {idef.id: idata for (idef, idata) in created_items_map if idef.is_avulso}
                    for slot in av_slots:
                        if slot.unit_number == 1:
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
                                    try:
                                        from apps.cegs.audit_service import AuditService
                                        AuditService.log_slot_assignment(
                                            slot=slot,
                                            participant=participant,
                                            action='assign',
                                            actor=request.user,
                                            metadata={'notes': 'Pré-reserva de item avulso na criação da CEG'}
                                        )
                                    except Exception:
                                        pass
                                    pre_reserved_count += 1
                                except (Participant.DoesNotExist, ValueError):
                                    pass

            if ceg.status == CEG.Status.POLLING:
                messages.success(
                    request,
                    f"🗳️ CEG '{ceg.title}' criada em Modo de Enquete / Sondagem com {len(created_items_map)} item(ns) definidos! "
                    f"Os participantes já podem votar e demonstrar interesse."
                )
            else:
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
        next_url = request.POST.get('next')
        ceg_id = request.POST.get('ceg_id')
        set_number_input = request.POST.get('set_number', '').strip()
        notes = request.POST.get('notes', '').strip()
        is_active = request.POST.get('is_active') == 'on' or request.POST.get('is_active') == 'true'

        if not ceg_id:
            messages.error(request, "Selecione a CEG para a qual deseja adicionar o Set.")
            return redirect(next_url or '/creations/?tab=sets')

        ceg = get_object_or_404(CEG, id=ceg_id)

        # Determina o próximo número do Set (ignorando o set avulso #0)
        if set_number_input and set_number_input.isdigit():
            set_number = int(set_number_input)
        else:
            last_set = ceg.sets.filter(is_avulso=False).order_by('-set_number').first()
            set_number = (last_set.set_number + 1) if last_set else 1

        if ceg.sets.filter(set_number=set_number).exists():
            messages.error(request, f"O Set #{set_number} já existe para a CEG '{ceg.title}'. Escolha outro número.")
            return redirect(next_url or '/creations/?tab=sets')

        try:
            with transaction.atomic():
                new_set = CEGSet.objects.create(
                    ceg=ceg,
                    set_number=set_number,
                    is_active=is_active,
                    is_avulso=False,
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
            if next_url:
                return redirect(next_url)
            return redirect('ceg_detail', slug=ceg.slug)
        except Exception as e:
            logger.error(f"Erro ao criar set: {e}")
            messages.error(request, f"Erro ao adicionar Set: {e}")
            return redirect(next_url or '/creations/?tab=sets')


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
        is_avulso = request.POST.get('is_avulso') in ('on', 'true', '1')
        quantidade_avulsa_raw = request.POST.get('quantidade_avulsa', '1').strip()
        try:
            quantidade_avulsa = max(1, int(quantidade_avulsa_raw)) if is_avulso else 1
        except (ValueError, TypeError):
            quantidade_avulsa = 1

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
                    is_avulso=is_avulso,
                    quantidade_avulsa=quantidade_avulsa,
                    order_index=last_order + 1
                )

                synced_count = 0
                if is_avulso:
                    avulso_set = ceg.get_or_create_avulso_set()
                    for u in range(1, quantidade_avulsa + 1):
                        slot, created = ItemSlot.objects.get_or_create(
                            set=avulso_set,
                            item_definition=item_def,
                            unit_number=u,
                            defaults={'price': price}
                        )
                        if created:
                            synced_count += 1
                elif sync_active_sets:
                    for s in ceg.sets.filter(is_active=True, is_avulso=False):
                        slot, created = ItemSlot.objects.get_or_create(
                            set=s,
                            item_definition=item_def,
                            unit_number=1,
                            defaults={'price': price}
                        )
                        if created:
                            synced_count += 1

            if is_avulso:
                messages.success(
                    request,
                    f"🎁 Item Avulso '{item_def.name}' adicionado com sucesso à CEG '{ceg.title}'! "
                    f"({synced_count} vaga(s) gerada(s))."
                )
            else:
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
