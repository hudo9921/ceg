import json
import logging
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View

from apps.cegs.models import Caixa, ItemSlot, TipoItem, ItemVitrine
from apps.groups.models import KpopGroup, Era
from .image_utils import process_image_upload

logger = logging.getLogger(__name__)


class StaffRequiredMixin(AccessMixin):
    """Garante que apenas usuários autenticados e com permissão de staff tenham acesso."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            messages.error(request, "Acesso restrito: Você precisa estar autenticado como Administrador/Organizador.")
            return redirect(f"/admin/login/?next={request.path}")
        return super().dispatch(request, *args, **kwargs)


class VitrineListView(View):
    """
    Vitrine pública de pronta entrega da ValCegs.
    Exibe itens cadastrados pela GOM (photocards, álbuns, POBs, etc.)
    com busca por texto, filtro de categorias, grupos, eras e faixa de preço.
    """

    def get(self, request):
        queryset = ItemVitrine.objects.select_related('tipo_item', 'group', 'era', 'origem_caixa')

        # 1. Filtro de Status (padrão: apenas DISPONIVEL)
        status_filter = request.GET.get('status', 'DISPONIVEL').strip().upper()
        if status_filter == 'ALL':
            pass
        elif status_filter in [ItemVitrine.Status.DISPONIVEL, ItemVitrine.Status.RESERVADO, ItemVitrine.Status.VENDIDO]:
            queryset = queryset.filter(status=status_filter)
        else:
            status_filter = 'DISPONIVEL'
            queryset = queryset.filter(status=ItemVitrine.Status.DISPONIVEL)

        # 2. Busca por texto
        q = request.GET.get('q', '').strip()
        if q:
            queryset = queryset.filter(
                Q(titulo__icontains=q) |
                Q(integrante__icontains=q) |
                Q(descricao__icontains=q) |
                Q(group__name__icontains=q) |
                Q(era__name__icontains=q)
            )

        # 3. Filtro por Tipo de Item (Categoria)
        tipo_id = request.GET.get('tipo', '').strip()
        if tipo_id and tipo_id.isdigit():
            queryset = queryset.filter(tipo_item_id=int(tipo_id))

        # 4. Filtro por Grupo
        group_id = request.GET.get('group', '').strip()
        if group_id and group_id.isdigit():
            queryset = queryset.filter(group_id=int(group_id))

        # 5. Filtro por Era
        era_id = request.GET.get('era', '').strip()
        if era_id and era_id.isdigit():
            queryset = queryset.filter(era_id=int(era_id))

        # 6. Filtro por Membro / Integrante
        member = request.GET.get('member', '').strip()
        if member:
            queryset = queryset.filter(
                Q(integrante__iexact=member) | Q(titulo__icontains=member)
            )

        # 7. Filtro por Subcategoria / Tipo de Photocard
        sub_category = request.GET.get('sub_category', '').strip()
        if sub_category:
            queryset = queryset.filter(
                Q(sub_category__iexact=sub_category) | Q(titulo__icontains=sub_category)
            )

        # 8. Ordenação
        sort_by = request.GET.get('sort', 'destaque').strip()
        if sort_by == 'menor_preco':
            queryset = queryset.order_by('preco', '-destaque', '-created_at')
        elif sort_by == 'maior_preco':
            queryset = queryset.order_by('-preco', '-destaque', '-created_at')
        elif sort_by == 'nome':
            queryset = queryset.order_by('titulo')
        elif sort_by == 'recentes':
            queryset = queryset.order_by('-created_at')
        else:
            sort_by = 'destaque'
            queryset = queryset.order_by('-destaque', '-created_at')

        # Contadores gerais
        total_disponiveis = ItemVitrine.objects.filter(status=ItemVitrine.Status.DISPONIVEL).count()
        total_reservados = ItemVitrine.objects.filter(status=ItemVitrine.Status.RESERVADO).count()
        total_vendidos = ItemVitrine.objects.filter(status=ItemVitrine.Status.VENDIDO).count()

        # Itens para renderização no template (suporta filtragem instantânea no client-side)
        itens = queryset

        tipos_item = TipoItem.objects.all().order_by('nome')
        groups = KpopGroup.objects.prefetch_related('members').all().order_by('name')
        eras = Era.objects.select_related('group').order_by('group__name', 'name')
        is_staff_user = bool(request.user.is_authenticated and request.user.is_staff)

        eras_by_group = {}
        for e in eras:
            eras_by_group.setdefault(e.group_id, []).append({'id': e.id, 'name': e.name})

        members_by_group = {}
        all_members_set = set()
        for g in groups:
            m_list = list(g.members.values_list('name', flat=True))
            members_by_group[g.id] = m_list
            all_members_set.update(m_list)

        vitrine_members = ItemVitrine.objects.exclude(integrante='').values_list('integrante', flat=True).distinct()
        for vm in vitrine_members:
            if vm and vm.strip():
                all_members_set.add(vm.strip())
        all_members = sorted(list(all_members_set))

        photocard_subcategories = ['Regulares', 'POB', 'Lucky Draw', 'Fansign', 'Broadcast', 'Inclusão', 'Outro']
        is_photocard_selected = False
        photocard_tipo_id = None
        for t in tipos_item:
            if 'photocard' in t.nome.lower():
                photocard_tipo_id = str(t.id)
                if str(tipo_id) == str(t.id):
                    is_photocard_selected = True

        context = {
            'itens': itens,
            'tipos_item': tipos_item,
            'groups': groups,
            'eras': eras,
            'eras_by_group_json': json.dumps(eras_by_group),
            'members_by_group_json': json.dumps(members_by_group),
            'all_members': all_members,
            'all_members_json': json.dumps(all_members),
            'photocard_subcategories': photocard_subcategories,
            'photocard_tipo_id': photocard_tipo_id,
            'is_photocard_selected': is_photocard_selected,
            'selected_tipo': tipo_id,
            'selected_group': group_id,
            'selected_era': era_id,
            'selected_member': member,
            'selected_sub_category': sub_category,
            'selected_status': status_filter,
            'selected_sort': sort_by,
            'search_query': q,
            'total_disponiveis': total_disponiveis,
            'total_reservados': total_reservados,
            'total_vendidos': total_vendidos,
            'total_encontrados': queryset.count(),
            'is_staff_user': is_staff_user,
        }
        return render(request, 'cegs/vitrine.html', context)


class VitrineItemCreateView(StaffRequiredMixin, View):
    """Permite à GOM adicionar um novo item diretamente na Vitrine."""

    def get(self, request):
        tipos_item = TipoItem.objects.all().order_by('nome')
        groups = KpopGroup.objects.prefetch_related('members').all().order_by('name')
        eras = Era.objects.select_related('group').order_by('group__name', 'name')
        caixas = Caixa.objects.all().order_by('-created_at')

        eras_by_group = {}
        for e in eras:
            eras_by_group.setdefault(e.group_id, []).append({
                'id': e.id,
                'name': e.name,
            })

        members_by_group = {}
        for g in groups:
            members_by_group[g.id] = list(g.members.values_list('name', flat=True))

        photocard_subcategories = ['Regulares', 'POB', 'Lucky Draw', 'Fansign', 'Broadcast', 'Inclusão', 'Outro']

        context = {
            'action': 'create',
            'tipos_item': tipos_item,
            'groups': groups,
            'eras': eras,
            'caixas': caixas,
            'eras_by_group_json': json.dumps(eras_by_group),
            'members_by_group_json': json.dumps(members_by_group),
            'photocard_subcategories': photocard_subcategories,
            'status_choices': ItemVitrine.Status.choices,
        }
        return render(request, 'cegs/vitrine_form.html', context)

    def post(self, request):
        titulo = request.POST.get('titulo', '').strip()
        if not titulo:
            messages.error(request, "O título do item é obrigatório.")
            return redirect('vitrine_create')

        descricao = request.POST.get('descricao', '').strip()
        integrante = request.POST.get('integrante', '').strip()
        sub_category = request.POST.get('sub_category', '').strip()
        status = request.POST.get('status', ItemVitrine.Status.DISPONIVEL)
        destaque = request.POST.get('destaque') == 'on' or request.POST.get('destaque') == 'true'

        try:
            preco_raw = request.POST.get('preco', '0').replace(',', '.').strip()
            preco = Decimal(preco_raw)
            if preco < 0:
                raise InvalidOperation()
        except (InvalidOperation, TypeError):
            preco = Decimal('0.00')

        try:
            quantidade = max(1, int(request.POST.get('quantidade', '1')))
        except (ValueError, TypeError):
            quantidade = 1

        tipo_item_id = request.POST.get('tipo_item')
        tipo_item = TipoItem.objects.filter(pk=tipo_item_id).first() if tipo_item_id else None

        group_id = request.POST.get('group')
        group = KpopGroup.objects.filter(pk=group_id).first() if group_id else None

        era_id = request.POST.get('era')
        era = Era.objects.filter(pk=era_id).first() if era_id else None

        caixa_id = request.POST.get('origem_caixa')
        origem_caixa = Caixa.objects.filter(pk=caixa_id).first() if caixa_id else None

        # Upload de Imagem ou URL direta
        raw_image_url = request.POST.get('image_url', '').strip()
        uploaded_file = request.FILES.get('foto_arquivo')
        base64_img = request.POST.get('foto_base64', '').strip()

        final_image_url = raw_image_url
        if uploaded_file or base64_img:
            saved_url = process_image_upload(
                file_obj=uploaded_file,
                base64_str=base64_img,
                folder='vitrine',
                fallback_url=raw_image_url
            )
            if saved_url:
                final_image_url = saved_url

        item = ItemVitrine.objects.create(
            titulo=titulo,
            descricao=descricao,
            tipo_item=tipo_item,
            group=group,
            era=era,
            integrante=integrante,
            sub_category=sub_category,
            preco=preco,
            quantidade=quantidade,
            status=status,
            destaque=destaque,
            image_url=final_image_url,
            origem_caixa=origem_caixa
        )

        messages.success(request, f"✨ Item '{item.titulo}' adicionado com sucesso à Vitrine!")
        return redirect('vitrine_list')


class VitrineItemUpdateView(StaffRequiredMixin, View):
    """Permite à GOM editar dados de um item existente na Vitrine."""

    def get(self, request, slug):
        item = get_object_or_404(ItemVitrine, slug=slug)
        tipos_item = TipoItem.objects.all().order_by('nome')
        groups = KpopGroup.objects.prefetch_related('members').all().order_by('name')
        eras = Era.objects.select_related('group').order_by('group__name', 'name')
        caixas = Caixa.objects.all().order_by('-created_at')

        eras_by_group = {}
        for e in eras:
            eras_by_group.setdefault(e.group_id, []).append({
                'id': e.id,
                'name': e.name,
            })

        members_by_group = {}
        for g in groups:
            members_by_group[g.id] = list(g.members.values_list('name', flat=True))

        photocard_subcategories = ['Regulares', 'POB', 'Lucky Draw', 'Fansign', 'Broadcast', 'Inclusão', 'Outro']

        context = {
            'action': 'update',
            'item': item,
            'tipos_item': tipos_item,
            'groups': groups,
            'eras': eras,
            'caixas': caixas,
            'eras_by_group_json': json.dumps(eras_by_group),
            'members_by_group_json': json.dumps(members_by_group),
            'photocard_subcategories': photocard_subcategories,
            'status_choices': ItemVitrine.Status.choices,
        }
        return render(request, 'cegs/vitrine_form.html', context)

    def post(self, request, slug):
        item = get_object_or_404(ItemVitrine, slug=slug)

        titulo = request.POST.get('titulo', '').strip()
        if not titulo:
            messages.error(request, "O título do item é obrigatório.")
            return redirect('vitrine_edit', slug=slug)

        item.titulo = titulo
        item.descricao = request.POST.get('descricao', '').strip()
        item.integrante = request.POST.get('integrante', '').strip()
        item.sub_category = request.POST.get('sub_category', '').strip()
        item.status = request.POST.get('status', item.status)
        item.destaque = request.POST.get('destaque') == 'on' or request.POST.get('destaque') == 'true'

        try:
            preco_raw = request.POST.get('preco', '0').replace(',', '.').strip()
            item.preco = Decimal(preco_raw)
        except (InvalidOperation, TypeError):
            pass

        try:
            item.quantidade = max(0, int(request.POST.get('quantidade', '1')))
        except (ValueError, TypeError):
            pass

        tipo_item_id = request.POST.get('tipo_item')
        item.tipo_item = TipoItem.objects.filter(pk=tipo_item_id).first() if tipo_item_id else None

        group_id = request.POST.get('group')
        item.group = KpopGroup.objects.filter(pk=group_id).first() if group_id else None

        era_id = request.POST.get('era')
        item.era = Era.objects.filter(pk=era_id).first() if era_id else None

        caixa_id = request.POST.get('origem_caixa')
        item.origem_caixa = Caixa.objects.filter(pk=caixa_id).first() if caixa_id else None

        # Imagem
        raw_image_url = request.POST.get('image_url', '').strip()
        uploaded_file = request.FILES.get('foto_arquivo')
        base64_img = request.POST.get('foto_base64', '').strip()

        if uploaded_file or base64_img:
            saved_url = process_image_upload(
                file_obj=uploaded_file,
                base64_str=base64_img,
                folder='vitrine',
                fallback_url=raw_image_url or item.image_url
            )
            if saved_url:
                item.image_url = saved_url
        elif raw_image_url:
            item.image_url = raw_image_url

        item.save()
        messages.success(request, f"💾 Item '{item.titulo}' atualizado com sucesso!")
        return redirect('vitrine_list')


class VitrineItemDeleteView(StaffRequiredMixin, View):
    """Exclui um item da Vitrine."""

    def post(self, request, slug):
        item = get_object_or_404(ItemVitrine, slug=slug)
        titulo = item.titulo
        item.delete()
        messages.success(request, f"🗑️ Item '{titulo}' excluído da Vitrine.")
        return redirect('vitrine_list')


class VitrineToggleStatusView(StaffRequiredMixin, View):
    """Alterna rapidamente o status de um item (Disponível, Reservado, Vendido)."""

    def post(self, request, slug):
        item = get_object_or_404(ItemVitrine, slug=slug)
        novo_status = request.POST.get('status', '').strip().upper()

        if novo_status in [ItemVitrine.Status.DISPONIVEL, ItemVitrine.Status.RESERVADO, ItemVitrine.Status.VENDIDO]:
            item.status = novo_status
            if novo_status == ItemVitrine.Status.VENDIDO:
                item.quantidade = 0
            elif novo_status == ItemVitrine.Status.DISPONIVEL and item.quantidade == 0:
                item.quantidade = 1
            item.save(update_fields=['status', 'quantidade', 'updated_at'])
            messages.success(request, f"Status de '{item.titulo}' alterado para {item.get_status_display()}.")

        return redirect(request.META.get('HTTP_REFERER', 'vitrine_list'))


class CaixaTransferUnclaimedToVitrineView(StaffRequiredMixin, View):
    """
    Permite à GOM transferir todos os itens não claimados (slots livres)
    de uma Caixa entregue ('Chegou na casa da GOM') diretamente para a Vitrine.
    """

    def get(self, request, slug):
        caixa = get_object_or_404(Caixa, slug=slug)

        # Localiza todos os slots em CEGs vinculadas a esta Caixa que estejam disponíveis/não claimados
        # e que ainda não tenham sido transferidos para a Vitrine
        unclaimed_slots = ItemSlot.objects.filter(
            set__ceg__caixa=caixa,
            status=ItemSlot.Status.AVAILABLE,
            claimed_by__isnull=True
        ).exclude(
            item_vitrine__isnull=False
        ).select_related(
            'item_definition',
            'item_definition__tipo_item',
            'item_definition__ceg',
            'item_definition__ceg__era',
            'item_definition__ceg__era__group'
        ).order_by('item_definition__ceg__title', 'item_definition__name')

        context = {
            'caixa': caixa,
            'unclaimed_slots': unclaimed_slots,
            'unclaimed_count': unclaimed_slots.count(),
        }
        return render(request, 'cegs/caixa_transfer_vitrine.html', context)

    def post(self, request, slug):
        caixa = get_object_or_404(Caixa, slug=slug)

        unclaimed_slots = ItemSlot.objects.filter(
            set__ceg__caixa=caixa,
            status=ItemSlot.Status.AVAILABLE,
            claimed_by__isnull=True
        ).exclude(
            item_vitrine__isnull=False
        ).select_related(
            'item_definition',
            'item_definition__tipo_item',
            'item_definition__ceg',
            'item_definition__ceg__era',
            'item_definition__ceg__era__group'
        )

        selected_slot_ids = request.POST.getlist('selected_slots')
        transfer_all = request.POST.get('transfer_all') == 'true'

        if transfer_all or not selected_slot_ids:
            slots_to_transfer = list(unclaimed_slots)
        else:
            try:
                ids_int = [int(i) for i in selected_slot_ids if i.isdigit()]
                slots_to_transfer = list(unclaimed_slots.filter(id__in=ids_int))
            except Exception:
                slots_to_transfer = []

        if not slots_to_transfer:
            messages.warning(request, "Nenhum item válido selecionado para transferência.")
            return redirect('caixa_detail', slug=caixa.slug)

        transferred_count = 0
        with transaction.atomic():
            for slot in slots_to_transfer:
                item_def = slot.item_definition
                ceg = item_def.ceg
                era = ceg.era
                group = era.group if era else None

                # Preço sugerido ou customizado via formulário
                preco_custom = request.POST.get(f'preco_{slot.id}', '').replace(',', '.').strip()
                try:
                    preco = Decimal(preco_custom) if preco_custom else (slot.price or item_def.default_price or Decimal('0.00'))
                except (InvalidOperation, TypeError):
                    preco = slot.price or item_def.default_price or Decimal('0.00')

                # Título descritivo do item
                nome_item = item_def.name
                if item_def.member_name:
                    titulo_final = f"{nome_item} - {item_def.member_name}"
                else:
                    titulo_final = nome_item

                # Criação do ItemVitrine
                ItemVitrine.objects.create(
                    titulo=titulo_final,
                    descricao=f"Item de pronta entrega transferido da remessa '{caixa.nome}' (CEG: {ceg.title}).",
                    tipo_item=item_def.tipo_item,
                    group=group,
                    era=era,
                    integrante=item_def.member_name or '',
                    sub_category=getattr(item_def, 'sub_category', '') or '',
                    preco=preco,
                    quantidade=1,
                    status=ItemVitrine.Status.DISPONIVEL,
                    image_url=item_def.image_url or '',
                    origem_caixa=caixa,
                    origem_slot=slot,
                    destaque=False
                )

                # Marca o slot na CEG como cancelado para não ficar disponível para reservas públicas antigas
                slot.status = ItemSlot.Status.CANCELLED
                slot.save(update_fields=['status'])
                transferred_count += 1

        messages.success(
            request,
            f"🎉 Sucesso! {transferred_count} item(ns) não claimados da caixa '{caixa.nome}' foram transferidos para a Vitrine."
        )
        return redirect('vitrine_list')
