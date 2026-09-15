import json
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from .creations_views import StaffRequiredMixin
from apps.participants.models import Participant, ParticipantNotification
from .models import PacoteNacional, ItemSlot, ItemIndividual, Caixa
from apps.groups.models import KpopGroup, Era


def parse_decimal(val_str, default=None):
    if not val_str:
        return default
    try:
        val_str = str(val_str).replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
        d = Decimal(val_str)
        return d if d >= 0 else default
    except (InvalidOperation, ValueError):
        return default


@method_decorator(ensure_csrf_cookie, name='dispatch')
class EnviosNacionaisView(StaffRequiredMixin, View):
    """
    Aba onde o admin pode escolher um joiner e com isso ver todas as CEGs/itens individuais dessa pessoa,
    ver os status de pagamento (item, inter, taxa), filtrar por múltiplos critérios, selecionar itens
    e empacotá-los para envio nacional.
    """

    def get(self, request):
        participant_id = request.GET.get('participant_id', '').strip()

        # Participantes ativos que têm slots ou compras avulsas
        participants_with_counts = Participant.objects.annotate(
            total_slots=Count('reserved_slots', distinct=True),
            total_mercari=Count('itens_individuais', distinct=True),
            unpacked_slots=Count('reserved_slots', filter=Q(reserved_slots__pacote_nacional__isnull=True), distinct=True),
            unpacked_mercari=Count('itens_individuais', filter=Q(itens_individuais__pacote_nacional__isnull=True), distinct=True),
        ).filter(Q(total_slots__gt=0) | Q(total_mercari__gt=0)).order_by('name')

        all_participants = Participant.objects.all().order_by('name')

        selected_participant = None
        items_data = []
        pacotes = []
        groups_list = []
        eras_list = []
        caixas_list = []

        # Contadores gerais do joiner
        stats = {
            'total_items': 0,
            'unpacked_count': 0,
            'packed_count': 0,
            'enviados_count': 0,
            'item_paid_count': 0,
            'item_unpaid_count': 0,
            'inter_unpaid_count': 0,
            'taxa_unpaid_count': 0,
        }

        if participant_id:
            selected_participant = Participant.objects.filter(id=participant_id).first()

            if selected_participant:
                # 1. Busca slots de CEG
                slots = ItemSlot.objects.filter(claimed_by=selected_participant).select_related(
                    'set__ceg__era__group',
                    'set__ceg__caixa',
                    'item_definition__tipo_item',
                    'pacote_nacional'
                ).order_by('-id')

                # 2. Busca itens individuais Mercari / JP
                itens_individuais = ItemIndividual.objects.filter(comprador=selected_participant).select_related(
                    'caixa',
                    'tipo_item',
                    'pacote_nacional'
                ).order_by('-created_at')

                # 3. Busca pacotes nacionais deste joiner
                pacotes = list(PacoteNacional.objects.filter(participant=selected_participant).prefetch_related(
                    'slots__item_definition',
                    'slots__set__ceg',
                    'itens_individuais'
                ).order_by('-created_at'))

                groups_map = {}
                eras_map = {}
                caixas_map = {}

                # Montagem uniforme dos itens de CEG
                for slot in slots:
                    ceg = slot.set.ceg
                    group = ceg.era.group
                    era = ceg.era
                    caixa = ceg.caixa

                    groups_map[group.id] = {'id': group.id, 'nome': group.name}
                    eras_map[era.id] = {'id': era.id, 'nome': era.name, 'group_id': group.id}
                    if caixa:
                        caixas_map[caixa.id] = {
                            'id': caixa.id,
                            'nome': caixa.nome,
                            'origem': caixa.origem,
                            'origem_display': caixa.get_origem_display(),
                        }

                    is_item_paid = slot.is_item_paid or slot.status == ItemSlot.Status.PAID
                    is_frete_inter_paid = slot.is_frete_inter_paid
                    is_taxa_aduaneira_paid = slot.is_taxa_aduaneira_paid
                    frete_inter_val = float(slot.frete_inter or 0)
                    taxa_aduaneira_val = float(slot.taxa_aduaneira or 0)

                    stats['total_items'] += 1
                    if slot.pacote_nacional:
                        if slot.pacote_nacional.status in (PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE):
                            stats['enviados_count'] += 1
                        else:
                            stats['packed_count'] += 1
                    else:
                        stats['unpacked_count'] += 1

                    if is_item_paid:
                        stats['item_paid_count'] += 1
                    else:
                        stats['item_unpaid_count'] += 1

                    if frete_inter_val > 0 and not is_frete_inter_paid:
                        stats['inter_unpaid_count'] += 1

                    if taxa_aduaneira_val > 0 and not is_taxa_aduaneira_paid:
                        stats['taxa_unpaid_count'] += 1

                    items_data.append({
                        'uid': f"slot_{slot.id}",
                        'type': 'slot',
                        'id': slot.id,
                        'nome': slot.item_definition.name,
                        'integrante': slot.item_definition.member_name or '',
                        'tipo_item': slot.item_definition.tipo_item_nome,
                        'ceg_titulo': ceg.title,
                        'ceg_slug': ceg.slug,
                        'link_pedido': '',
                        'group_id': group.id,
                        'group_name': group.name,
                        'era_id': era.id,
                        'era_name': era.name,
                        'caixa_id': caixa.id if caixa else '',
                        'caixa_nome': caixa.nome if caixa else 'Sem Caixa Atrelada',
                        'caixa_origem': caixa.origem if caixa else '',
                        'caixa_status': caixa.get_status_display() if caixa else '',
                        'image_url': slot.item_definition.image_url or ceg.banner_url or '',
                        'preco': float(slot.price),
                        'is_item_paid': is_item_paid,
                        'frete_inter_valor': frete_inter_val,
                        'is_frete_inter_paid': is_frete_inter_paid,
                        'taxa_aduaneira_valor': taxa_aduaneira_val,
                        'is_taxa_aduaneira_paid': is_taxa_aduaneira_paid,
                        'is_frete_nacional_paid': slot.is_frete_nacional_paid,
                        'pacote_id': slot.pacote_nacional.id if slot.pacote_nacional else None,
                        'pacote_identificador': slot.pacote_nacional.identificador if slot.pacote_nacional else '',
                        'pacote_status': slot.pacote_nacional.status if slot.pacote_nacional else '',
                        'pacote_status_display': slot.pacote_nacional.get_status_display() if slot.pacote_nacional else '',
                        'pacote_rastreio': slot.pacote_nacional.codigo_rastreio if slot.pacote_nacional else '',
                    })

                # Montagem uniforme dos itens individuais Mercari / JP
                for item in itens_individuais:
                    caixa = item.caixa
                    if caixa:
                        caixas_map[caixa.id] = {
                            'id': caixa.id,
                            'nome': caixa.nome,
                            'origem': caixa.origem,
                            'origem_display': caixa.get_origem_display(),
                        }

                    # Mercari entra na categoria especial de grupo
                    groups_map['mercari'] = {'id': 'mercari', 'nome': 'Mercari / Avulsos (JP)'}

                    is_item_paid = item.produto_pago
                    is_frete_inter_paid = item.frete_inter_pago
                    is_taxa_aduaneira_paid = item.taxa_aduaneira_paga
                    frete_inter_val = float(item.frete_inter or 0)
                    taxa_aduaneira_val = float(item.taxa_aduaneira or 0)

                    stats['total_items'] += 1
                    if item.pacote_nacional:
                        if item.pacote_nacional.status in (PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE):
                            stats['enviados_count'] += 1
                        else:
                            stats['packed_count'] += 1
                    else:
                        stats['unpacked_count'] += 1

                    if is_item_paid:
                        stats['item_paid_count'] += 1
                    else:
                        stats['item_unpaid_count'] += 1

                    if frete_inter_val > 0 and not is_frete_inter_paid:
                        stats['inter_unpaid_count'] += 1

                    if taxa_aduaneira_val > 0 and not is_taxa_aduaneira_paid:
                        stats['taxa_unpaid_count'] += 1

                    items_data.append({
                        'uid': f"mercari_{item.id}",
                        'type': 'mercari',
                        'id': item.id,
                        'nome': item.nome,
                        'integrante': '',
                        'tipo_item': item.tipo_item_nome,
                        'ceg_titulo': 'Pedido Mercari / Individual',
                        'ceg_slug': '',
                        'link_pedido': item.link_pedido or '',
                        'group_id': 'mercari',
                        'group_name': 'Mercari / Avulsos (JP)',
                        'era_id': '',
                        'era_name': '',
                        'caixa_id': caixa.id if caixa else '',
                        'caixa_nome': caixa.nome if caixa else 'Sem Caixa Atrelada',
                        'caixa_origem': caixa.origem if caixa else 'JP',
                        'caixa_status': caixa.get_status_display() if caixa else '',
                        'image_url': item.image_display_url,
                        'preco': float(item.preco_produto or 0),
                        'is_item_paid': is_item_paid,
                        'frete_inter_valor': frete_inter_val,
                        'is_frete_inter_paid': is_frete_inter_paid,
                        'taxa_aduaneira_valor': taxa_aduaneira_val,
                        'is_taxa_aduaneira_paid': is_taxa_aduaneira_paid,
                        'is_frete_nacional_paid': False,
                        'pacote_id': item.pacote_nacional.id if item.pacote_nacional else None,
                        'pacote_identificador': item.pacote_nacional.identificador if item.pacote_nacional else '',
                        'pacote_status': item.pacote_nacional.status if item.pacote_nacional else '',
                        'pacote_status_display': item.pacote_nacional.get_status_display() if item.pacote_nacional else '',
                        'pacote_rastreio': item.pacote_nacional.codigo_rastreio if item.pacote_nacional else '',
                    })

                groups_list = sorted(groups_map.values(), key=lambda x: str(x['nome']))
                eras_list = sorted(eras_map.values(), key=lambda x: str(x['nome']))
                caixas_list = sorted(caixas_map.values(), key=lambda x: str(x['nome']))

        return render(request, 'cegs/envios_nacionais.html', {
            'selected_participant': selected_participant,
            'participants_with_counts': participants_with_counts,
            'all_participants': all_participants,
            'items_data': items_data,
            'items_data_json': json.dumps(items_data),
            'pacotes': pacotes,
            'groups_list': groups_list,
            'eras_list': eras_list,
            'caixas_list': caixas_list,
            'stats': stats,
        })


class EmpacotarItensView(StaffRequiredMixin, View):
    """
    Agrupa itens selecionados de um participante em um PacoteNacional (novo ou existente).
    """

    def post(self, request):
        participant_id = request.POST.get('participant_id', '').strip()
        participant = get_object_or_404(Participant, id=participant_id)

        action_type = request.POST.get('action_type', 'novo_pacote').strip()
        selected_uids = [u.strip() for u in request.POST.get('selected_uids', '').split(',') if u.strip()]

        if not selected_uids:
            messages.error(request, "Nenhum item foi selecionado para empacotamento.")
            return redirect(f"/consulta-joiner/?participant_id={participant.id}")

        pacote = None

        if action_type == 'adicionar_existente':
            pacote_id = request.POST.get('pacote_id', '').strip()
            pacote = get_object_or_404(PacoteNacional, id=pacote_id, participant=participant)
            if pacote.status in [PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE]:
                messages.error(request, "Não é possível adicionar itens a um pacote que já foi enviado nacionalmente ou entregue.")
                return redirect(f"/consulta-joiner/?participant_id={participant.id}")
        else:
            # Cria novo pacote
            identificador = request.POST.get('identificador', '').strip()
            transportadora = request.POST.get('transportadora', 'Correios').strip()
            codigo_rastreio = request.POST.get('codigo_rastreio', '').strip().upper()
            valor_frete_str = request.POST.get('valor_frete_nacional', '').strip()
            is_frete_pago = request.POST.get('is_frete_pago') == 'on' or request.POST.get('is_frete_pago') == 'true'
            observacoes = request.POST.get('observacoes', '').strip()

            valor_frete = parse_decimal(valor_frete_str, default=None)

            pacote = PacoteNacional.objects.create(
                participant=participant,
                identificador=identificador,
                transportadora=transportadora or 'Correios',
                codigo_rastreio=codigo_rastreio,
                valor_frete_nacional=valor_frete,
                is_frete_pago=is_frete_pago,
                observacoes=observacoes,
                status=PacoteNacional.Status.EM_PREPARACAO
            )

        slots_vinculados = 0
        mercari_vinculados = 0

        for uid in selected_uids:
            if uid.startswith('slot_'):
                slot_id = uid.replace('slot_', '')
                try:
                    slot = ItemSlot.objects.get(id=slot_id, claimed_by=participant)
                    # Bloqueio: item já enviado nacionalmente não pode ser empacotado novamente!
                    if slot.pacote_nacional and slot.pacote_nacional.status in [PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE]:
                        continue
                    slot.pacote_nacional = pacote
                    slot.save(update_fields=['pacote_nacional'])
                    slots_vinculados += 1
                except ItemSlot.DoesNotExist:
                    continue
            elif uid.startswith('mercari_'):
                item_id = uid.replace('mercari_', '')
                try:
                    item = ItemIndividual.objects.get(id=item_id, comprador=participant)
                    # Bloqueio: item já enviado nacionalmente não pode ser empacotado novamente!
                    if item.pacote_nacional and item.pacote_nacional.status in [PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE]:
                        continue
                    item.pacote_nacional = pacote
                    item.save(update_fields=['pacote_nacional'])
                    mercari_vinculados += 1
                except ItemIndividual.DoesNotExist:
                    continue

        total = slots_vinculados + mercari_vinculados

        if total == 0:
            if action_type != 'adicionar_existente':
                # Remove pacote vazio recém-criado
                pacote.delete()
            messages.error(request, "Nenhum dos itens selecionados pôde ser empacotado (itens já enviados ou inválidos).")
            return redirect(f"/consulta-joiner/?participant_id={participant.id}")

        # Se o admin marcou a flag "Marcar como Enviado Imediatamente"
        marcar_enviado = request.POST.get('marcar_enviado') in ('1', 'on', 'true')
        if marcar_enviado:
            rastreio = request.POST.get('codigo_rastreio', '').strip().upper()
            transp = request.POST.get('transportadora', '').strip()
            pacote.marcar_como_enviado(codigo_rastreio=rastreio, transportadora=transp)
            messages.success(
                request,
                f"✨ Pacote {pacote.identificador} criado com {total} item(ns) e marcado como ENVIADO NACIONALMENTE!"
            )
        else:
            messages.success(
                request,
                f"📦 {total} item(ns) empacotados com sucesso no pacote {pacote.identificador}!"
            )

        return redirect(f"/consulta-joiner/?participant_id={participant.id}")


class MarcarPacoteEnviadoView(StaffRequiredMixin, View):
    """
    Marca um pacote como enviado nacionalmente, preenche/atualiza o código de rastreio
    e envia notificação ao participante.
    """

    def post(self, request, pacote_id):
        pacote = get_object_or_404(PacoteNacional, id=pacote_id)
        codigo_rastreio = request.POST.get('codigo_rastreio', '').strip().upper()
        transportadora = request.POST.get('transportadora', '').strip()

        pacote.marcar_como_enviado(codigo_rastreio=codigo_rastreio, transportadora=transportadora)

        messages.success(
            request,
            f"🚀 Pacote {pacote.identificador} despachado com sucesso! O comprador {pacote.participant.display_name} foi notificado."
        )
        return redirect(f"/consulta-joiner/?participant_id={pacote.participant_id}")


class AtualizarPacoteView(StaffRequiredMixin, View):
    """
    Atualiza detalhes do pacote nacional (código de rastreio, frete, transportadora, status e notas).
    """

    def post(self, request, pacote_id):
        pacote = get_object_or_404(PacoteNacional, id=pacote_id)

        status = request.POST.get('status', pacote.status).strip()
        codigo_rastreio = request.POST.get('codigo_rastreio', '').strip().upper()
        transportadora = request.POST.get('transportadora', pacote.transportadora).strip()
        valor_frete_str = request.POST.get('valor_frete_nacional', '').strip()
        is_frete_pago = request.POST.get('is_frete_pago') in ('1', 'on', 'true')
        observacoes = request.POST.get('observacoes', '').strip()

        pacote.status = status
        pacote.codigo_rastreio = codigo_rastreio
        pacote.transportadora = transportadora or 'Correios'
        pacote.valor_frete_nacional = parse_decimal(valor_frete_str, default=pacote.valor_frete_nacional)
        pacote.is_frete_pago = is_frete_pago
        pacote.observacoes = observacoes

        if status == PacoteNacional.Status.ENVIADO and not pacote.data_envio:
            pacote.data_envio = timezone.now()
        elif status == PacoteNacional.Status.ENTREGUE and not pacote.data_entrega:
            pacote.data_entrega = timezone.now()

        pacote.save()

        messages.success(request, f"Detalhes do pacote {pacote.identificador} atualizados com sucesso.")
        return redirect(f"/consulta-joiner/?participant_id={pacote.participant_id}")


class DesempacotarItemView(StaffRequiredMixin, View):
    """
    Remove um item (slot ou individual) de seu pacote nacional.
    """

    def post(self, request):
        item_uid = request.POST.get('item_uid', '').strip()
        participant_id = request.POST.get('participant_id', '').strip()

        if item_uid.startswith('slot_'):
            slot_id = item_uid.replace('slot_', '')
            slot = get_object_or_404(ItemSlot, id=slot_id)
            if slot.pacote_nacional and slot.pacote_nacional.status in [PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE]:
                messages.error(request, "Não é possível desempacotar um item que já foi enviado nacionalmente.")
                return redirect(f"/consulta-joiner/?participant_id={participant_id}")
            slot.pacote_nacional = None
            slot.save(update_fields=['pacote_nacional'])
            messages.success(request, f"Item '{slot.item_definition.name}' removido do pacote.")
        elif item_uid.startswith('mercari_'):
            item_id = item_uid.replace('mercari_', '')
            item = get_object_or_404(ItemIndividual, id=item_id)
            if item.pacote_nacional and item.pacote_nacional.status in [PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE]:
                messages.error(request, "Não é possível desempacotar um item que já foi enviado nacionalmente.")
                return redirect(f"/consulta-joiner/?participant_id={participant_id}")
            item.pacote_nacional = None
            item.save(update_fields=['pacote_nacional'])
            messages.success(request, f"Item '{item.nome}' removido do pacote.")

        return redirect(f"/consulta-joiner/?participant_id={participant_id}")


class ExcluirPacoteView(StaffRequiredMixin, View):
    """
    Exclui um pacote nacional e desassocia todos os itens contidos nele.
    """

    def post(self, request, pacote_id):
        pacote = get_object_or_404(PacoteNacional, id=pacote_id)
        participant_id = pacote.participant_id
        identificador = pacote.identificador

        if pacote.status in [PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE]:
            messages.error(request, "Não é possível excluir um pacote que já foi enviado nacionalmente.")
            return redirect(f"/consulta-joiner/?participant_id={participant_id}")

        pacote.slots.update(pacote_nacional=None)
        pacote.itens_individuais.update(pacote_nacional=None)
        pacote.delete()

        messages.success(request, f"Pacote {identificador} excluído com sucesso. Os itens retornaram para a fila.")
        return redirect(f"/consulta-joiner/?participant_id={participant_id}")
