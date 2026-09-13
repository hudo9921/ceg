import json
import logging
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View

from .models import Caixa, CEG, ItemIndividual, TipoItem, CaixaItemRate, ItemSlot, CEGItemDefinition
from .creations_views import StaffRequiredMixin

logger = logging.getLogger(__name__)


class CaixasDashboardView(StaffRequiredMixin, View):
    """
    Dashboard visual das Caixas / Remessas Internacionais (KR, JP, etc.).
    Acessível por todos para consulta e transparência de envios, com controles
    de gerenciamento ativos para Administradores / Organizadores.
    """

    def get(self, request):
        origem_filter = request.GET.get('origem', '').strip().upper()
        status_filter = request.GET.get('status', '').strip().upper()
        search_query = request.GET.get('q', '').strip()

        caixas_qs = Caixa.objects.prefetch_related(
            'cegs__era__group',
            'itens_individuais__comprador'
        ).annotate(
            cegs_count=Count('cegs', distinct=True),
            itens_count=Count('itens_individuais', distinct=True)
        ).order_by('-created_at')

        if origem_filter and origem_filter in Caixa.Origem.values:
            caixas_qs = caixas_qs.filter(origem=origem_filter)

        if status_filter and status_filter in Caixa.Status.values:
            caixas_qs = caixas_qs.filter(status=status_filter)

        if search_query:
            caixas_qs = caixas_qs.filter(
                Q(nome__icontains=search_query) |
                Q(codigo_rastreio__icontains=search_query) |
                Q(transportadora__icontains=search_query) |
                Q(cegs__title__icontains=search_query) |
                Q(itens_individuais__nome__icontains=search_query)
            ).distinct()

        # Métricas gerais
        all_caixas = Caixa.objects.all()
        total_caixas = all_caixas.count()
        caixas_kr = all_caixas.filter(origem=Caixa.Origem.KR).count()
        caixas_jp = all_caixas.filter(origem=Caixa.Origem.JP).count()

        transito_statuses = [
            Caixa.Status.ENVIADA,
            Caixa.Status.NO_BRASIL,
            Caixa.Status.TRIBUTADA,
            Caixa.Status.LIBERADA,
        ]
        caixas_em_transito = all_caixas.filter(status__in=transito_statuses).count()
        caixas_entregues = all_caixas.filter(status__in=[Caixa.Status.ENTREGUE, Caixa.Status.FINALIZADA]).count()
        total_cegs_vinculadas = CEG.objects.filter(caixa__isnull=False).count()

        # CEGs disponíveis sem caixa (para vincular pelo organizador)
        cegs_sem_caixa = CEG.objects.filter(caixa__isnull=True).select_related('era__group').order_by('-created_at')

        status_step_map = {
            Caixa.Status.EM_CONSOLIDACAO: 1,
            Caixa.Status.PRONTA_ENVIO: 2,
            Caixa.Status.ENVIADA: 3,
            Caixa.Status.NO_BRASIL: 4,
            Caixa.Status.TRIBUTADA: 4,
            Caixa.Status.LIBERADA: 5,
            Caixa.Status.ENTREGUE: 6,
            Caixa.Status.FINALIZADA: 7,
        }

        caixas_data = []
        for c in caixas_qs:
            step = status_step_map.get(c.status, 1)
            pct = int((step / 7) * 100)
            caixas_data.append({
                'caixa': c,
                'step': step,
                'progress_pct': min(pct, 100),
                'cegs': c.cegs.all(),
                'cegs_count': c.cegs.count(),
                'itens': c.itens_individuais.all(),
                'itens_count': c.itens_individuais.count(),
            })

        context = {
            'caixas_data': caixas_data,
            'total_caixas': total_caixas,
            'caixas_kr': caixas_kr,
            'caixas_jp': caixas_jp,
            'caixas_em_transito': caixas_em_transito,
            'caixas_entregues': caixas_entregues,
            'total_cegs_vinculadas': total_cegs_vinculadas,
            'cegs_sem_caixa': cegs_sem_caixa,
            'origem_choices': Caixa.Origem.choices,
            'status_choices': Caixa.Status.choices,
            'origem_filter': origem_filter,
            'status_filter': status_filter,
            'search_query': search_query,
            'is_staff_user': request.user.is_authenticated and request.user.is_staff,
        }
        return render(request, 'cegs/caixas_list.html', context)


class CaixaDetailView(StaffRequiredMixin, View):
    """
    Detalhes de uma Caixa / Remessa específica.
    Exibe informações de rastreio, linha do tempo dos status, CEGs atreladas,
    itens individuais atrelados e atalhos para atualização de envio em cascata.
    """

    def get(self, request, slug):
        caixa = get_object_or_404(
            Caixa.objects.prefetch_related(
                'cegs__era__group',
                'cegs__sets',
                'cegs__item_definitions',
                'itens_individuais__comprador'
            ),
            slug=slug
        )

        cegs = caixa.cegs.select_related('era__group').prefetch_related('sets').all()
        cegs_sem_caixa = CEG.objects.filter(caixa__isnull=True).select_related('era__group').order_by('-created_at')
        itens_individuais = caixa.itens_individuais.select_related('comprador', 'tipo_item').all().order_by('-created_at')
        itens_individuais_sem_caixa = ItemIndividual.objects.filter(caixa__isnull=True).select_related('comprador', 'tipo_item').order_by('-created_at')

        status_step_map = {
            Caixa.Status.EM_CONSOLIDACAO: 1,
            Caixa.Status.PRONTA_ENVIO: 2,
            Caixa.Status.ENVIADA: 3,
            Caixa.Status.NO_BRASIL: 4,
            Caixa.Status.TRIBUTADA: 4,
            Caixa.Status.LIBERADA: 5,
            Caixa.Status.ENTREGUE: 6,
            Caixa.Status.FINALIZADA: 7,
        }
        current_step = status_step_map.get(caixa.status, 1)

        total_slots_cegs = 0
        reserved_slots_cegs = 0
        for ceg in cegs:
            for s in ceg.sets.all():
                total_slots_cegs += s.slots.count()
                reserved_slots_cegs += s.slots.filter(status__in=[ItemSlot.Status.RESERVED, ItemSlot.Status.PAID]).count()

        # Detalhamento de taxas e rateios por Tipo de Item dinâmico nesta Caixa
        all_tipos = list(TipoItem.objects.all())
        item_rates_data = []
        configured_rates = []

        # Pré-carregar todas as taxas configuradas nesta caixa
        rates_by_tipo = {r.tipo_item_id: r for r in caixa.item_rates.select_related('tipo_item').all()}

        # Contagens reais de slots de CEGs e Itens Individuais nesta caixa agrupados por tipo
        ceg_slots_qs = ItemSlot.objects.filter(set__ceg__caixa=caixa)
        individual_items_qs = caixa.itens_individuais.all()

        import unicodedata

        def _normalize_name(name):
            return unicodedata.normalize('NFKD', name or '').encode('ASCII', 'ignore').decode('utf-8').lower()

        now = timezone.now()
        is_caixa_frete_expired = bool(caixa.prazo_frete and caixa.prazo_frete < now)
        is_caixa_taxa_expired = bool(caixa.prazo_taxa and caixa.prazo_taxa < now)

        for tipo in all_tipos:
            rate = rates_by_tipo.get(tipo.id)
            c_count = ceg_slots_qs.filter(item_definition__tipo_item=tipo).count()
            i_count = individual_items_qs.filter(tipo_item=tipo).count()
            tot = c_count + i_count

            # Garante formatação com ponto decimal (ex: "2.00") para inputs HTML5 number
            frete_str = ""
            if rate and rate.frete_unitario is not None and rate.frete_unitario > 0:
                frete_str = f"{rate.frete_unitario:.2f}"

            taxa_str = ""
            if rate and rate.taxa_unitaria is not None and rate.taxa_unitaria > 0:
                taxa_str = f"{rate.taxa_unitaria:.2f}"

            has_configured = rate is not None and (
                (rate.frete_unitario is not None and rate.frete_unitario > 0) or
                (rate.taxa_unitaria is not None and rate.taxa_unitaria > 0)
            )

            row_data = {
                'tipo': tipo,
                'ceg_count': c_count,
                'count_cegs': c_count,
                'individual_count': i_count,
                'count_mercari': i_count,
                'total_count': tot,
                'rate': rate,
                'frete_unitario': rate.frete_unitario if rate else None,
                'taxa_unitaria': rate.taxa_unitaria if rate else None,
                'frete_unitario_str': frete_str,
                'taxa_unitaria_str': taxa_str,
                'has_configured': has_configured,
            }
            item_rates_data.append(row_data)
            if has_configured:
                configured_rates.append(row_data)

        # Ordenação inteligente: tipos com itens na caixa ou taxas salvas vêm primeiro,
        # seguidos pelos demais tipos em ordem alfabética normalizada
        item_rates_data.sort(key=lambda x: (
            0 if (x['total_count'] > 0 or x['has_configured']) else 1,
            _normalize_name(x['tipo'].nome)
        ))

        itens_individuais_data = []
        for it in itens_individuais:
            itens_individuais_data.append({
                'id': it.id,
                'nome': it.nome,
                'tipo_item_id': it.tipo_item_id,
                'tipo_item_nome': it.tipo_item.nome if it.tipo_item else None,
                'quantidade': it.quantidade,
                'status': it.status,
                'status_display': it.get_status_display(),
                'comprador_id': it.comprador_id,
                'comprador_name': it.comprador.name,
                'comprador_display': it.comprador.display_name,
                'comprador_phone': it.comprador.whatsapp,
                'comprador_handle': it.comprador.social_handle or '',
                'caixa_id': it.caixa_id,
                'link_pedido': it.link_pedido or '',
                'image_url': it.image_display_url,
                'preco_produto': float(it.preco_produto) if it.preco_produto else None,
                'preco_produto_str': str(it.preco_produto) if it.preco_produto else '',
                'frete_inter': float(it.frete_inter) if it.frete_inter else None,
                'frete_inter_str': str(it.frete_inter) if it.frete_inter else '',
                'frete_inter_pago': it.frete_inter_pago,
                'prazo_frete_inter': it.prazo_frete_inter.strftime('%Y-%m-%dT%H:%M') if it.prazo_frete_inter else '',
                'taxa_aduaneira': float(it.taxa_aduaneira) if it.taxa_aduaneira else None,
                'taxa_aduaneira_str': str(it.taxa_aduaneira) if it.taxa_aduaneira else '',
                'taxa_aduaneira_paga': it.taxa_aduaneira_paga,
                'prazo_taxa_aduaneira': it.prazo_taxa_aduaneira.strftime('%Y-%m-%dT%H:%M') if it.prazo_taxa_aduaneira else '',
                'observacoes': it.observacoes or '',
            })

        context = {
            'caixa': caixa,
            'cegs': cegs,
            'cegs_sem_caixa': cegs_sem_caixa,
            'itens_individuais': itens_individuais,
            'itens_individuais_count': itens_individuais.count(),
            'itens_individuais_sem_caixa': itens_individuais_sem_caixa,
            'itens_individuais_data': itens_individuais_data,
            'itens_individuais_json': json.dumps(itens_individuais_data),
            'current_step': current_step,
            'status_choices': Caixa.Status.choices,
            'origem_choices': Caixa.Origem.choices,
            'total_slots_cegs': total_slots_cegs,
            'reserved_slots_cegs': reserved_slots_cegs,
            'item_rates_data': item_rates_data,
            'configured_rates': configured_rates,
            'configured_rates_count': len(configured_rates),
            'all_tipos_item': all_tipos,
            'tipos_item_json': json.dumps(list(TipoItem.objects.values('id', 'nome'))),
            'all_caixas': Caixa.objects.all().order_by('-created_at'),
            'item_individual_statuses': ItemIndividual.Status.choices,
            'is_staff_user': request.user.is_authenticated and request.user.is_staff,
            'is_caixa_frete_expired': is_caixa_frete_expired,
            'is_caixa_taxa_expired': is_caixa_taxa_expired,
        }
        return render(request, 'cegs/caixa_detail.html', context)


class CaixaCreateView(StaffRequiredMixin, View):
    """Criação de uma nova Caixa / Remessa internacional."""

    def get(self, request):
        cegs_sem_caixa = CEG.objects.filter(caixa__isnull=True).select_related('era__group').order_by('-created_at')
        return render(request, 'cegs/caixa_form.html', {
            'action': 'create',
            'origem_choices': Caixa.Origem.choices,
            'status_choices': Caixa.Status.choices,
            'cegs_sem_caixa': cegs_sem_caixa,
        })

    def post(self, request):
        nome = request.POST.get('nome', '').strip()
        origem = request.POST.get('origem', Caixa.Origem.KR).strip()
        status = request.POST.get('status', Caixa.Status.EM_CONSOLIDACAO).strip()
        codigo_rastreio = request.POST.get('codigo_rastreio', '').strip().upper()
        transportadora = request.POST.get('transportadora', '').strip()
        data_envio = parse_date(request.POST.get('data_envio', '') or '')
        data_previsao = parse_date(request.POST.get('data_previsao', '') or '')
        data_recebimento = parse_date(request.POST.get('data_recebimento', '') or '')
        observacoes = request.POST.get('observacoes', '').strip()

def parse_safe_decimal(val, field_label="Valor"):
    """Converte e valida valor decimal garantindo limites seguros para o banco de dados."""
    if not val:
        return None, None
    clean = str(val).replace('R$', '').replace(' ', '').replace(',', '.').strip()
    if not clean:
        return None, None
    try:
        d = Decimal(clean).quantize(Decimal('0.01'))
        if d < 0:
            return None, f"{field_label} não pode ser negativo."
        if d > Decimal('9999999999.99'):
            return None, f"{field_label} excede o limite máximo permitido (máximo R$ 9.999.999.999,99)."
        return d, None
    except (InvalidOperation, ValueError):
        return None, f"{field_label} possui formato numérico inválido."


class CaixaCreateView(StaffRequiredMixin, View):
    """Criação de uma nova Caixa / Remessa internacional."""

    def get(self, request):
        cegs_sem_caixa = CEG.objects.filter(caixa__isnull=True).select_related('era__group').order_by('-created_at')
        return render(request, 'cegs/caixa_form.html', {
            'action': 'create',
            'origem_choices': Caixa.Origem.choices,
            'status_choices': Caixa.Status.choices,
            'cegs_sem_caixa': cegs_sem_caixa,
        })

    def post(self, request):
        nome = request.POST.get('nome', '').strip()
        origem = request.POST.get('origem', Caixa.Origem.KR).strip()
        status = request.POST.get('status', Caixa.Status.EM_CONSOLIDACAO).strip()
        codigo_rastreio = request.POST.get('codigo_rastreio', '').strip().upper()
        transportadora = request.POST.get('transportadora', '').strip()
        data_envio = parse_date(request.POST.get('data_envio', '') or '')
        data_previsao = parse_date(request.POST.get('data_previsao', '') or '')
        data_recebimento = parse_date(request.POST.get('data_recebimento', '') or '')
        observacoes = request.POST.get('observacoes', '').strip()

        frete_inter_total, err_frete = parse_safe_decimal(request.POST.get('frete_inter_total'), "Frete Internacional")
        taxa_aduaneira_total, err_taxa = parse_safe_decimal(request.POST.get('taxa_aduaneira_total'), "Taxa Aduaneira")

        if err_frete or err_taxa:
            if err_frete:
                messages.error(request, err_frete)
            if err_taxa:
                messages.error(request, err_taxa)
            return redirect('caixa_create')

        if not nome:
            messages.error(request, "O nome da Caixa é obrigatório.")
            return redirect('caixa_create')

        try:
            with transaction.atomic():
                caixa = Caixa(
                    nome=nome,
                    origem=origem,
                    status=status,
                    codigo_rastreio=codigo_rastreio,
                    transportadora=transportadora,
                    data_envio=data_envio,
                    data_previsao=data_previsao,
                    data_recebimento=data_recebimento,
                    frete_inter_total=frete_inter_total,
                    taxa_aduaneira_total=taxa_aduaneira_total,
                    observacoes=observacoes,
                )
                caixa.full_clean()
                caixa.save()

                # Atrela CEGs selecionadas se houver
                ceg_ids = request.POST.getlist('ceg_ids')
                if ceg_ids:
                    CEG.objects.filter(id__in=ceg_ids).update(caixa=caixa, shipping_status=caixa.status)

            messages.success(request, f"Caixa '{caixa.nome}' criada com sucesso!")
            return redirect('caixa_detail', slug=caixa.slug)
        except Exception as e:
            logger.exception("Erro ao criar caixa")
            messages.error(request, f"Erro ao criar caixa: {str(e)}")
            return redirect('caixa_create')


class CaixaUpdateView(StaffRequiredMixin, View):
    """Edição dos dados cadastrais e financeiros de uma Caixa."""

    def get(self, request, slug):
        caixa = get_object_or_404(Caixa, slug=slug)
        cegs_sem_caixa = CEG.objects.filter(caixa__isnull=True).select_related('era__group').order_by('-created_at')
        return render(request, 'cegs/caixa_form.html', {
            'action': 'edit',
            'caixa': caixa,
            'origem_choices': Caixa.Origem.choices,
            'status_choices': Caixa.Status.choices,
            'cegs_sem_caixa': cegs_sem_caixa,
        })

    def post(self, request, slug):
        caixa = get_object_or_404(Caixa, slug=slug)

        nome = request.POST.get('nome', '').strip()
        origem = request.POST.get('origem', caixa.origem).strip()
        codigo_rastreio = request.POST.get('codigo_rastreio', '').strip().upper()
        transportadora = request.POST.get('transportadora', '').strip()
        data_envio = parse_date(request.POST.get('data_envio', '') or '')
        data_previsao = parse_date(request.POST.get('data_previsao', '') or '')
        data_recebimento = parse_date(request.POST.get('data_recebimento', '') or '')
        observacoes = request.POST.get('observacoes', '').strip()

        frete_inter_total, err_frete = parse_safe_decimal(request.POST.get('frete_inter_total'), "Frete Internacional")
        taxa_aduaneira_total, err_taxa = parse_safe_decimal(request.POST.get('taxa_aduaneira_total'), "Taxa Aduaneira")

        if err_frete or err_taxa:
            if err_frete:
                messages.error(request, err_frete)
            if err_taxa:
                messages.error(request, err_taxa)
            return redirect('caixa_update', slug=caixa.slug)

        if not nome:
            messages.error(request, "O nome da Caixa é obrigatório.")
            return redirect('caixa_update', slug=caixa.slug)

        try:
            caixa.nome = nome
            caixa.origem = origem
            caixa.codigo_rastreio = codigo_rastreio
            caixa.transportadora = transportadora
            caixa.data_envio = data_envio
            caixa.data_previsao = data_previsao
            caixa.data_recebimento = data_recebimento
            caixa.frete_inter_total = frete_inter_total
            caixa.taxa_aduaneira_total = taxa_aduaneira_total
            caixa.observacoes = observacoes

            prazo_frete_str = request.POST.get('prazo_frete', '').strip()
            if prazo_frete_str:
                try:
                    dt_f = timezone.datetime.fromisoformat(prazo_frete_str)
                    if timezone.is_naive(dt_f):
                        dt_f = timezone.make_aware(dt_f, timezone.get_current_timezone())
                    caixa.prazo_frete = dt_f
                except Exception:
                    pass

            prazo_taxa_str = request.POST.get('prazo_taxa', '').strip()
            if prazo_taxa_str:
                try:
                    dt_t = timezone.datetime.fromisoformat(prazo_taxa_str)
                    if timezone.is_naive(dt_t):
                        dt_t = timezone.make_aware(dt_t, timezone.get_current_timezone())
                    caixa.prazo_taxa = dt_t
                except Exception:
                    pass

            caixa.full_clean()
            caixa.save()

            # Propaga em cascata para CEGs e Itens Individuais atrelados
            caixa.propagar_taxas_e_prazos_em_cascata()

            messages.success(request, f"Caixa '{caixa.nome}' atualizada com sucesso!")
            return redirect('caixa_detail', slug=caixa.slug)
        except Exception as e:
            logger.exception("Erro ao atualizar caixa")
            messages.error(request, f"Erro ao atualizar caixa: {str(e)}")
            return redirect('caixa_update', slug=caixa.slug)


class CaixaUpdateStatusView(StaffRequiredMixin, View):
    """
    Ação rápida para avançar ou atualizar o status da Caixa.
    Ao atualizar, propaga automaticamente em cascata para todas as CEGs atreladas
    e gera notificações para os compradores.
    """

    def post(self, request, slug):
        caixa = get_object_or_404(Caixa, slug=slug)
        novo_status = request.POST.get('novo_status', '').strip()
        data_evento = parse_date(request.POST.get('data_evento', '') or '')

        if not novo_status or novo_status not in Caixa.Status.values:
            messages.error(request, f"Status inválido: {novo_status}")
            return redirect('caixa_detail', slug=caixa.slug)

        try:
            cegs_atualizadas = caixa.atualizar_status(
                novo_status=novo_status,
                data_evento=data_evento,
                notify_participants=True
            )
            status_label = caixa.get_status_display()
            messages.success(
                request,
                f"✅ Status da caixa '{caixa.nome}' atualizado para '{status_label}'! "
                f"{cegs_atualizadas} CEG(s) vinculadas foram sincronizadas e participantes notificados."
            )
        except Exception as e:
            logger.exception("Erro ao atualizar status da caixa")
            messages.error(request, f"Erro ao atualizar status: {str(e)}")

        # Permite retornar para onde veio (lista ou detalhe)
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
        if next_url:
            return redirect(next_url)
        return redirect('caixa_detail', slug=caixa.slug)


class CaixaLinkCEGView(StaffRequiredMixin, View):
    """Vincula uma ou mais CEGs a esta Caixa."""

    def post(self, request, slug):
        caixa = get_object_or_404(Caixa, slug=slug)
        ceg_ids = request.POST.getlist('ceg_ids')
        single_id = request.POST.get('ceg_id')
        if single_id and single_id not in ceg_ids:
            ceg_ids.append(single_id)

        if not ceg_ids:
            messages.warning(request, "Nenhuma CEG selecionada para vincular.")
            return redirect('caixa_detail', slug=caixa.slug)

        updated_count = CEG.objects.filter(id__in=ceg_ids).update(
            caixa=caixa,
            shipping_status=caixa.status
        )

        # Propaga em cascata taxas, prazos e status da Caixa para as novas CEGs vinculadas
        caixa.propagar_taxas_e_prazos_em_cascata()

        messages.success(
            request,
            f"🔗 {updated_count} CEG(s) vinculada(s) à caixa '{caixa.nome}' e sincronizadas com status '{caixa.get_status_display()}', taxas e prazos."
        )
        return redirect('caixa_detail', slug=caixa.slug)


class CaixaUnlinkCEGView(StaffRequiredMixin, View):
    """Desvincula uma CEG da Caixa."""

    def post(self, request, slug, ceg_id):
        caixa = get_object_or_404(Caixa, slug=slug)
        ceg = get_object_or_404(CEG, id=ceg_id, caixa=caixa)

        ceg.caixa = None
        ceg.shipping_status = Caixa.Status.EM_CONSOLIDACAO
        ceg.save(update_fields=['caixa', 'shipping_status'])

        messages.info(request, f"CEG '{ceg.title}' foi desvinculada da caixa '{caixa.nome}'.")
        return redirect('caixa_detail', slug=caixa.slug)


class CaixaLinkItemIndividualView(StaffRequiredMixin, View):
    """Vincula um ou mais Itens Individuais (Mercari) a esta Caixa."""

    def post(self, request, slug):
        caixa = get_object_or_404(Caixa, slug=slug)
        item_ids = request.POST.getlist('item_ids')
        single_id = request.POST.get('item_id')
        if single_id and single_id not in item_ids:
            item_ids.append(single_id)

        if not item_ids:
            messages.warning(request, "Nenhum item selecionado para vincular.")
            return redirect('caixa_detail', slug=caixa.slug)

        # Mapeia status da caixa para o status do item
        novo_status = caixa.status if caixa.status in ItemIndividual.Status.values else ItemIndividual.Status.COMPRADO
        updated_count = ItemIndividual.objects.filter(id__in=item_ids).update(
            caixa=caixa,
            status=novo_status
        )

        # Propaga em cascata taxas, prazos e status da Caixa para os novos itens vinculados
        caixa.propagar_taxas_e_prazos_em_cascata()

        messages.success(
            request,
            f"🔗 {updated_count} item(ns) Mercari vinculado(s) à caixa '{caixa.nome}' com sucesso!"
        )
        return redirect('caixa_detail', slug=caixa.slug)


class CaixaUnlinkItemIndividualView(StaffRequiredMixin, View):
    """Desvincula um Item Individual (Mercari) da Caixa."""

    def post(self, request, slug, item_id):
        caixa = get_object_or_404(Caixa, slug=slug)
        item = get_object_or_404(ItemIndividual, id=item_id, caixa=caixa)

        item.caixa = None
        item.status = ItemIndividual.Status.COMPRADO
        item.save(update_fields=['caixa', 'status'])

        messages.success(request, f"Item individual '{item.nome}' desvinculado da caixa '{caixa.nome}'.")
        return redirect('caixa_detail', slug=caixa.slug)


class CaixaDistributeRatesView(StaffRequiredMixin, View):
    """
    Recebe os valores de frete internacional, taxa aduaneira e prazos por tipo de item para uma Caixa,
    salva as configurações de taxa em CaixaItemRate e propaga em lote para todos os itens individuais
    e slots de CEGs vinculados a esta caixa.
    """

    def post(self, request, slug):
        caixa = get_object_or_404(Caixa, slug=slug)
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

        rates_to_process = []
        body_data = {}
        caixa_prazo_frete_str = None
        caixa_prazo_taxa_str = None

        if request.content_type == 'application/json':
            try:
                body_data = json.loads(request.body)
                rates_to_process = body_data.get('rates', [])
                caixa_prazo_frete_str = body_data.get('caixa_prazo_frete')
                caixa_prazo_taxa_str = body_data.get('caixa_prazo_taxa')
            except Exception:
                rates_to_process = []
        else:
            caixa_prazo_frete_str = request.POST.get('caixa_prazo_frete')
            caixa_prazo_taxa_str = request.POST.get('caixa_prazo_taxa')

            # Fallback de compatibilidade caso venha em formato antigo (prazo_frete_{id})
            if not caixa_prazo_frete_str:
                for k, v in request.POST.items():
                    if k.startswith('prazo_frete_') and v:
                        caixa_prazo_frete_str = v
                        break

            if not caixa_prazo_taxa_str:
                for k, v in request.POST.items():
                    if k.startswith('prazo_taxa_') and v:
                        caixa_prazo_taxa_str = v
                        break

            for tipo in TipoItem.objects.all():
                frete_str = request.POST.get(f"frete_unitario_{tipo.id}")
                if frete_str is None:
                    frete_str = request.POST.get(f"frete_unit_{tipo.id}")

                taxa_str = request.POST.get(f"taxa_unitaria_{tipo.id}")
                if taxa_str is None:
                    taxa_str = request.POST.get(f"taxa_unit_{tipo.id}")

                if frete_str is not None or taxa_str is not None:
                    rates_to_process.append({
                        'tipo_item_id': tipo.id,
                        'frete_unitario': frete_str or '0.00',
                        'taxa_unitaria': taxa_str or '0.00',
                    })

        # Fallback JSON
        if request.content_type == 'application/json':
            if not caixa_prazo_frete_str and rates_to_process:
                for r in rates_to_process:
                    if r.get('prazo_frete'):
                        caixa_prazo_frete_str = r.get('prazo_frete')
                        break
            if not caixa_prazo_taxa_str and rates_to_process:
                for r in rates_to_process:
                    if r.get('prazo_taxa'):
                        caixa_prazo_taxa_str = r.get('prazo_taxa')
                        break

        # Parsing dos prazos gerais da Caixa
        prazo_frete_caixa = None
        if caixa_prazo_frete_str:
            try:
                prazo_frete_caixa = timezone.datetime.fromisoformat(caixa_prazo_frete_str)
                if timezone.is_naive(prazo_frete_caixa):
                    prazo_frete_caixa = timezone.make_aware(prazo_frete_caixa)
            except (ValueError, TypeError):
                prazo_frete_caixa = None

        prazo_taxa_caixa = None
        if caixa_prazo_taxa_str:
            try:
                prazo_taxa_caixa = timezone.datetime.fromisoformat(caixa_prazo_taxa_str)
                if timezone.is_naive(prazo_taxa_caixa):
                    prazo_taxa_caixa = timezone.make_aware(prazo_taxa_caixa)
            except (ValueError, TypeError):
                prazo_taxa_caixa = None

        updated_items_count = 0
        updated_slots_count = 0
        saved_rates_map = {}

        with transaction.atomic():
            # Atualiza prazos no modelo da Caixa se foram submetidos no form
            caixa_fields = ['updated_at']
            if 'caixa_prazo_frete' in request.POST or (is_ajax and 'caixa_prazo_frete' in body_data) or prazo_frete_caixa is not None:
                caixa.prazo_frete = prazo_frete_caixa
                caixa_fields.append('prazo_frete')
            if 'caixa_prazo_taxa' in request.POST or (is_ajax and 'caixa_prazo_taxa' in body_data) or prazo_taxa_caixa is not None:
                caixa.prazo_taxa = prazo_taxa_caixa
                caixa_fields.append('prazo_taxa')

            if len(caixa_fields) > 1:
                caixa.save(update_fields=list(set(caixa_fields)))

            for r_data in rates_to_process:
                t_id = r_data.get('tipo_item_id')
                if not t_id:
                    continue
                tipo = TipoItem.objects.filter(id=t_id).first()
                if not tipo:
                    continue

                raw_frete = str(r_data.get('frete_unitario', '0.00')).replace(',', '.').strip()
                raw_taxa = str(r_data.get('taxa_unitaria', '0.00')).replace(',', '.').strip()

                try:
                    frete_val = max(Decimal('0.00'), Decimal(raw_frete)) if raw_frete else Decimal('0.00')
                except (InvalidOperation, ValueError):
                    frete_val = Decimal('0.00')

                try:
                    taxa_val = max(Decimal('0.00'), Decimal(raw_taxa)) if raw_taxa else Decimal('0.00')
                except (InvalidOperation, ValueError):
                    taxa_val = Decimal('0.00')

                rate_obj, _ = CaixaItemRate.objects.update_or_create(
                    caixa=caixa,
                    tipo_item=tipo,
                    defaults={
                        'frete_unitario': frete_val,
                        'taxa_unitaria': taxa_val,
                        'prazo_frete': caixa.prazo_frete,
                        'prazo_taxa': caixa.prazo_taxa,
                    }
                )
                saved_rates_map[tipo.id] = rate_obj

            # Propaga em cascata para todos os Itens Individuais, CEGs e slots da Caixa
            caixa.propagar_taxas_e_prazos_em_cascata()

            updated_items_count = caixa.itens_individuais.count()
            updated_slots_count = ItemSlot.objects.filter(set__ceg__caixa=caixa).count()

            # Dispara notificações aos participantes
            self._notificar_participantes_taxas(caixa)

        msg = (
            f"🚀 Fretes e taxas rateados com sucesso na remessa '{caixa.nome}'! "
            f"Atualizados {updated_items_count} item(ns) individuais e {updated_slots_count} slot(s) de CEGs."
        )

        if is_ajax:
            return JsonResponse({'success': True, 'message': msg})

        messages.success(request, msg)
        return redirect('caixa_detail', slug=caixa.slug)

    def _notificar_participantes_taxas(self, caixa):
        try:
            from apps.participants.models import Claim, ParticipantNotification
            claims = Claim.objects.filter(
                slot__set__ceg__caixa=caixa
            ).exclude(status=Claim.Status.CANCELLED).select_related('participant', 'slot__set__ceg')

            notified = set()
            for c in claims:
                p = c.participant
                if p.id in notified:
                    continue
                notified.add(p.id)
                ParticipantNotification.objects.create(
                    participant=p,
                    title=f"📦 Frete e/ou Taxa lançados: {caixa.nome}",
                    message=f"Os valores de frete internacional e/ou taxa aduaneira foram definidos para a remessa '{caixa.nome}'. Acesse suas reservas para conferir valores e prazos.",
                    notification_type=ParticipantNotification.NotificationType.CLAIM_UPDATE
                )

            for it in caixa.itens_individuais.select_related('comprador'):
                p = it.comprador
                if p.id in notified:
                    continue
                notified.add(p.id)
                ParticipantNotification.objects.create(
                    participant=p,
                    title=f"📦 Frete e/ou Taxa lançados: {caixa.nome}",
                    message=f"Os valores de frete internacional e/ou taxa aduaneira foram definidos para seu pedido '{it.nome}' na remessa '{caixa.nome}'. Acesse suas reservas para conferir valores e prazos.",
                    notification_type=ParticipantNotification.NotificationType.CLAIM_UPDATE
                )
        except Exception:
            pass


class TipoItemCreateView(StaffRequiredMixin, View):
    """Cria um novo TipoItem dinamicamente e retorna JSON."""

    def post(self, request):
        nome = request.POST.get('nome', '').strip()
        descricao = request.POST.get('descricao', '').strip()

        if not nome and request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                nome = data.get('nome', '').strip()
                descricao = data.get('descricao', '').strip()
            except Exception:
                pass

        if not nome:
            return JsonResponse({'success': False, 'message': 'Nome do tipo de item é obrigatório.'}, status=400)

        tipo = TipoItem.objects.filter(nome__iexact=nome).first()
        created = False
        if not tipo:
            tipo = TipoItem.objects.create(nome=nome.strip(), descricao=descricao)
            created = True

        return JsonResponse({
            'success': True,
            'id': tipo.id,
            'nome': tipo.nome,
            'tipo': {
                'id': tipo.id,
                'nome': tipo.nome,
                'descricao': tipo.descricao or ''
            },
            'created': created,
            'message': f"Tipo de item '{tipo.nome}' {'criado' if created else 'já existente'} com sucesso!"
        })


class TipoItemDeleteView(StaffRequiredMixin, View):
    """Exclui um TipoItem se não houver itens ou definições vinculadas a ele."""

    def post(self, request, pk):
        tipo = get_object_or_404(TipoItem, pk=pk)
        slots_count = ItemSlot.objects.filter(item_definition__tipo_item=tipo).count()
        itens_count = ItemIndividual.objects.filter(tipo_item=tipo).count()
        defs_count = CEGItemDefinition.objects.filter(tipo_item=tipo).count()
        total_linked = slots_count + itens_count + defs_count

        if total_linked > 0:
            return JsonResponse({
                'success': False,
                'message': f'Não é possível excluir "{tipo.nome}" pois existem {total_linked} item(ns) vinculados a este tipo.'
            }, status=400)

        nome = tipo.nome
        tipo.delete()
        return JsonResponse({
            'success': True,
            'message': f'Tipo de item "{nome}" excluído com sucesso!'
        })
