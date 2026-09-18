from collections import defaultdict
from datetime import timedelta
from django.db.models import Count, Sum, Q, F
from django.db.models.functions import TruncMonth
from django.utils import timezone
from apps.cegs.models import CEG, CEGSet, ItemSlot, CEGItemDefinition, ItemIndividual
from apps.groups.models import KpopGroup, Era
from apps.participants.models import Claim, Participant

MONTH_ABBR = {
    1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun',
    7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'
}

MONTH_FULL = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril', 5: 'Maio', 6: 'Junho',
    7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
}


class AnalyticsService:

    @staticmethod
    def get_filter_options():
        """Retorna os grupos, eras e meses disponíveis para alimentar os filtros do painel."""
        groups = KpopGroup.objects.prefetch_related('eras').all().order_by('name')
        groups_data = []
        for g in groups:
            sorted_eras = sorted(g.eras.all(), key=lambda e: e.name.lower())
            groups_data.append({
                'id': str(g.id),
                'name': g.name,
                'eras': [{'id': str(e.id), 'name': e.name} for e in sorted_eras]
            })

        eras = Era.objects.select_related('group').all().order_by('group__name', 'name')
        eras_data = [{
            'id': str(e.id),
            'name': e.name,
            'group_id': str(e.group_id),
            'group_name': e.group.name
        } for e in eras]

        # Meses com claims ou itens individuais registrados
        claim_months = list(Claim.objects.annotate(
            m=TruncMonth('claimed_at')
        ).values_list('m', flat=True).distinct())

        item_months = list(ItemIndividual.objects.annotate(
            m=TruncMonth('created_at')
        ).values_list('m', flat=True).distinct())

        all_month_dates = [d for d in set(claim_months + item_months) if d]
        all_month_dates.sort(reverse=True)

        months_data = []
        seen_months = set()
        for dt in all_month_dates:
            key = dt.strftime('%Y-%m')
            if key not in seen_months:
                seen_months.add(key)
                label = f"{MONTH_FULL.get(dt.month, '')}/{dt.year}"
                months_data.append({'value': key, 'label': label})

        # Se não houver meses, adiciona pelo menos o mês atual
        if not months_data:
            now = timezone.now()
            key = now.strftime('%Y-%m')
            months_data.append({
                'value': key,
                'label': f"{MONTH_FULL.get(now.month, '')}/{now.year}"
            })

        return {
            'groups': groups_data,
            'eras': eras_data,
            'months': months_data,
        }

    @staticmethod
    def get_summary_metrics(group_id=None, era_id=None, month=None):
        """
        Calcula as métricas financeiras e operacionais com filtros opcionais:
        - total_paid: Faturamento Confirmado (Pix aprovado)
        - total_pending: Falta Pagar (Aguardando Pix)
        - total_sold: Já Vendido (Pago + Pendente)
        - total_remaining_to_sell: Para Vender (Valor dos slots livres)
        - total_inventory_value: Potencial Total (Já Vendido + Para Vender)
        - total_slots, reserved_slots, available_slots, occupancy_percentage
        - unique_participants, avg_ticket
        """
        claims = Claim.objects.exclude(status=Claim.Status.CANCELLED)
        slots = ItemSlot.objects.filter(set__is_active=True)
        cegs = CEG.objects.all()

        if group_id:
            claims = claims.filter(slot__set__ceg__era__group_id=group_id)
            slots = slots.filter(set__ceg__era__group_id=group_id)
            cegs = cegs.filter(era__group_id=group_id)

        if era_id:
            claims = claims.filter(slot__set__ceg__era_id=era_id)
            slots = slots.filter(set__ceg__era_id=era_id)
            cegs = cegs.filter(era_id=era_id)

        if month:
            try:
                y, m = month.split('-')
                claims = claims.filter(claimed_at__year=int(y), claimed_at__month=int(m))
            except (ValueError, TypeError):
                pass

        total_paid = float(claims.filter(status=Claim.Status.PAID).aggregate(s=Sum('total_price'))['s'] or 0)
        total_pending = float(claims.filter(status=Claim.Status.PENDING).aggregate(s=Sum('total_price'))['s'] or 0)
        total_sold = total_paid + total_pending

        total_remaining_to_sell = float(
            slots.filter(status=ItemSlot.Status.AVAILABLE).aggregate(s=Sum('price'))['s'] or 0
        )
        total_inventory_value = total_sold + total_remaining_to_sell

        total_slots = slots.count()
        reserved_slots = slots.filter(status__in=[ItemSlot.Status.RESERVED, ItemSlot.Status.PAID]).count()
        available_slots = slots.filter(status=ItemSlot.Status.AVAILABLE).count()
        occupancy_pct = int((reserved_slots / total_slots) * 100) if total_slots > 0 else 0

        unique_participants = claims.values('participant_id').distinct().count()
        avg_ticket = float(total_sold / unique_participants) if unique_participants > 0 else 0.0

        return {
            'total_paid': total_paid,
            'total_pending': total_pending,
            'total_sold': total_sold,
            'total_remaining_to_sell': total_remaining_to_sell,
            'total_inventory_value': total_inventory_value,
            'total_slots': total_slots,
            'reserved_slots': reserved_slots,
            'available_slots': available_slots,
            'occupancy_percentage': occupancy_pct,
            'total_participants': unique_participants,
            'avg_ticket': avg_ticket,
            'total_claims_count': claims.count(),
            'total_cegs': cegs.count(),
            'active_cegs': cegs.filter(status__in=[CEG.Status.OPEN, CEG.Status.SCHEDULED]).count(),
        }

    @staticmethod
    def get_monthly_sales_flow(group_id=None, era_id=None):
        """
        Retorna agregação de vendas mês a mês para o gráfico de fluxo temporal (Chart.js).
        """
        claims = Claim.objects.exclude(status=Claim.Status.CANCELLED)
        if group_id:
            claims = claims.filter(slot__set__ceg__era__group_id=group_id)
        if era_id:
            claims = claims.filter(slot__set__ceg__era_id=era_id)

        monthly_qs = claims.annotate(
            month=TruncMonth('claimed_at')
        ).values('month').annotate(
            total_sales=Sum('total_price'),
            paid_sales=Sum('total_price', filter=Q(status=Claim.Status.PAID)),
            pending_sales=Sum('total_price', filter=Q(status=Claim.Status.PENDING)),
            claims_count=Count('id')
        ).order_by('month')

        results = []
        for row in monthly_qs:
            dt = row['month']
            if dt:
                results.append({
                    'month_key': dt.strftime('%Y-%m'),
                    'label': f"{MONTH_ABBR.get(dt.month, '')}/{str(dt.year)[2:]}",
                    'full_label': f"{MONTH_FULL.get(dt.month, '')}/{dt.year}",
                    'total_sales': float(row['total_sales'] or 0),
                    'paid_sales': float(row['paid_sales'] or 0),
                    'pending_sales': float(row['pending_sales'] or 0),
                    'claims_count': row['claims_count'],
                })

        if not results:
            now = timezone.now()
            results.append({
                'month_key': now.strftime('%Y-%m'),
                'label': f"{MONTH_ABBR.get(now.month, '')}/{str(now.year)[2:]}",
                'full_label': f"{MONTH_FULL.get(now.month, '')}/{now.year}",
                'total_sales': 0.0,
                'paid_sales': 0.0,
                'pending_sales': 0.0,
                'claims_count': 0,
            })

        return results

    @staticmethod
    def get_detailed_inventory_table(group_id=None, era_id=None):
        """
        Retorna a tabela consolidada de cada CEG com:
        Aberto/Status, Faturado, Falta Pagar, Já Vendido, Para Vender e Total Potencial.
        """
        cegs = CEG.objects.select_related('era__group', 'era').all()
        if group_id:
            cegs = cegs.filter(era__group_id=group_id)
        if era_id:
            cegs = cegs.filter(era_id=era_id)

        cegs_list = list(cegs)
        ceg_ids = [c.id for c in cegs_list]

        all_slots = list(
            ItemSlot.objects.filter(set__ceg_id__in=ceg_ids, set__is_active=True)
            .select_related('set')
        )
        slots_by_ceg = defaultdict(list)
        for s in all_slots:
            slots_by_ceg[s.set.ceg_id].append(s)

        claim_aggregates = Claim.objects.filter(
            slot__set__ceg_id__in=ceg_ids
        ).values('slot__set__ceg_id', 'status').annotate(
            total_val=Sum('total_price')
        )
        paid_val_by_ceg = defaultdict(float)
        pending_val_by_ceg = defaultdict(float)
        for row in claim_aggregates:
            cid = row['slot__set__ceg_id']
            val = float(row['total_val'] or 0)
            if row['status'] == Claim.Status.PAID:
                paid_val_by_ceg[cid] += val
            elif row['status'] == Claim.Status.PENDING:
                pending_val_by_ceg[cid] += val

        table_rows = []
        for c in cegs_list:
            ceg_slots = slots_by_ceg.get(c.id, [])
            total_slots = len(ceg_slots)
            sold_slots = sum(1 for s in ceg_slots if s.status in [ItemSlot.Status.RESERVED, ItemSlot.Status.PAID])
            available_slots = sum(1 for s in ceg_slots if s.status == ItemSlot.Status.AVAILABLE)

            paid_sum = paid_val_by_ceg.get(c.id, 0.0)
            pending_sum = pending_val_by_ceg.get(c.id, 0.0)
            sold_sum = paid_sum + pending_sum
            available_sum = sum(float(s.price) for s in ceg_slots if s.status == ItemSlot.Status.AVAILABLE)
            total_potential = sold_sum + available_sum
            fill_pct = int((sold_slots / total_slots) * 100) if total_slots > 0 else 0

            table_rows.append({
                'ceg_id': c.id,
                'title': c.title,
                'slug': c.slug,
                'status': c.status,
                'status_display': c.get_status_display(),
                'group_name': c.era.group.name,
                'group_id': str(c.era.group.id),
                'era_name': c.era.name,
                'era_id': str(c.era.id),
                'total_slots': total_slots,
                'sold_slots': sold_slots,
                'available_slots': available_slots,
                'fill_percentage': fill_pct,
                'paid_amount': paid_sum,
                'pending_amount': pending_sum,
                'sold_amount': sold_sum,
                'available_amount': available_sum,
                'total_potential': total_potential,
            })

        return sorted(table_rows, key=lambda x: (x['total_potential'], x['sold_amount']), reverse=True)

    @staticmethod
    def get_group_comparison():
        """Compara o faturamento e capacidade entre os grupos para gráficos (0 queries N+1)"""
        groups = list(KpopGroup.objects.all().order_by('name'))
        
        claim_aggs = Claim.objects.exclude(status=Claim.Status.CANCELLED).values(
            'slot__set__ceg__era__group_id', 'status'
        ).annotate(
            total_val=Sum('total_price'),
            claims_count=Count('id')
        )
        paid_by_group = defaultdict(float)
        pending_by_group = defaultdict(float)
        claims_cnt_by_group = defaultdict(int)
        for row in claim_aggs:
            gid = row['slot__set__ceg__era__group_id']
            if not gid:
                continue
            claims_cnt_by_group[gid] += row['claims_count']
            val = float(row['total_val'] or 0)
            if row['status'] == Claim.Status.PAID:
                paid_by_group[gid] += val
            elif row['status'] == Claim.Status.PENDING:
                pending_by_group[gid] += val

        slot_aggs = ItemSlot.objects.filter(
            set__is_active=True, status=ItemSlot.Status.AVAILABLE
        ).values('set__ceg__era__group_id').annotate(
            avail_val=Sum('price')
        )
        avail_by_group = {row['set__ceg__era__group_id']: float(row['avail_val'] or 0) for row in slot_aggs}

        results = []
        for g in groups:
            paid = paid_by_group.get(g.id, 0.0)
            pending = pending_by_group.get(g.id, 0.0)
            available = avail_by_group.get(g.id, 0.0)
            claims_cnt = claims_cnt_by_group.get(g.id, 0)
            if (paid + pending + available) > 0 or claims_cnt > 0:
                results.append({
                    'group_name': g.name,
                    'paid_amount': paid,
                    'pending_amount': pending,
                    'sold_amount': paid + pending,
                    'available_amount': available,
                    'total_amount': paid + pending + available,
                    'claims_count': claims_cnt
                })
        return sorted(results, key=lambda x: x['total_amount'], reverse=True)

    @staticmethod
    def get_member_popularity(group_id=None, era_id=None):
        """Calcula integrantes mais disputados, com suporte a filtros de grupo e era."""
        qs = ItemSlot.objects.filter(
            item_definition__member_name__isnull=False
        ).exclude(
            item_definition__member_name=''
        )

        if group_id:
            qs = qs.filter(set__ceg__era__group_id=group_id)
        if era_id:
            qs = qs.filter(set__ceg__era_id=era_id)

        member_stats = qs.values(
            'item_definition__member_name',
            'set__ceg__era__group__name'
        ).annotate(
            total_slots=Count('id'),
            claimed_slots=Count('id', filter=Q(status__in=[ItemSlot.Status.RESERVED, ItemSlot.Status.PAID])),
            paid_slots=Count('id', filter=Q(status=ItemSlot.Status.PAID)),
        ).order_by('-claimed_slots')

        results = []
        for stat in member_stats:
            member = stat['item_definition__member_name']
            group = stat['set__ceg__era__group__name']
            total = stat['total_slots']
            claimed = stat['claimed_slots']
            pct = int((claimed / total) * 100) if total > 0 else 0
            results.append({
                'member_name': member,
                'group_name': group,
                'total_slots': total,
                'claimed_slots': claimed,
                'claim_percentage': pct,
                'paid_slots': stat['paid_slots']
            })

        return sorted(results, key=lambda x: (x['claim_percentage'], x['claimed_slots']), reverse=True)

    @staticmethod
    def get_sets_near_completion(group_id=None, era_id=None):
        """Retorna sets com suporte a filtros de grupo e era (em memória, sem N+1)."""
        active_sets = CEGSet.objects.filter(
            is_active=True,
            ceg__status__in=[CEG.Status.OPEN, CEG.Status.SCHEDULED]
        ).select_related('ceg', 'ceg__era', 'ceg__era__group').prefetch_related('slots')

        if group_id:
            active_sets = active_sets.filter(ceg__era__group_id=group_id)
        if era_id:
            active_sets = active_sets.filter(ceg__era_id=era_id)

        sets_info = []
        for s in active_sets:
            slots = list(s.slots.all())
            total = len(slots)
            reserved = sum(1 for sl in slots if sl.status in [ItemSlot.Status.RESERVED, ItemSlot.Status.PAID])
            if total > 0:
                pct = int((reserved / total) * 100)
                sets_info.append({
                    'set_id': s.id,
                    'set_number': s.set_number,
                    'ceg_title': s.ceg.title,
                    'ceg_clean_title': s.ceg.clean_title(s.ceg.era.group.name),
                    'group_name': s.ceg.era.group.name,
                    'total_slots': total,
                    'reserved_slots': reserved,
                    'remaining_slots': total - reserved,
                    'fill_percentage': pct,
                    'is_full': reserved == total,
                })

        return sorted(sets_info, key=lambda x: x['fill_percentage'], reverse=True)

    # Mantém compatibilidade com código legado que chama get_era_financials
    @staticmethod
    def get_era_financials():
        return AnalyticsService.get_detailed_inventory_table()

    @staticmethod
    def get_cegs_operational_status(group_id=None, era_id=None, category='all', search=None):
        """
        Retorna o status operacional detalhado das CEGs, Sets e Itens Individuais (Mercari):
        - sets_completed_pending: Sets 100% preenchidos, porém ainda não finalizados
        - sets_incomplete: Sets que ainda NÃO estão 100% preenchidos
        - sets_overview: Tabela consolidada de valores das CEGs em si
        - mercari_status: Painel consolidado de itens individuais (Mercari) por status e pendências
        """
        sets_fechados = []
        sets_pagos = []
        sets_terminados = []
        sets_completed_pending = []
        sets_incomplete = []
        cegs_overview = []
        total_sets_count = 0
        total_slots_count = 0
        total_reserved_slots_count = 0
        cegs_qs = CEG.objects.none()

        if category in ['all', 'ceg']:
            cegs_qs = CEG.objects.select_related('era__group', 'era', 'caixa').all()

            if group_id:
                cegs_qs = cegs_qs.filter(era__group_id=group_id)
            if era_id:
                cegs_qs = cegs_qs.filter(era_id=era_id)
            if search and search.strip():
                s_term = search.strip()
                cegs_qs = cegs_qs.filter(
                    Q(title__icontains=s_term) |
                    Q(era__name__icontains=s_term) |
                    Q(era__group__name__icontains=s_term) |
                    Q(sets__slots__item_definition__name__icontains=s_term)
                ).distinct()

            cegs_list = list(cegs_qs)
            ceg_ids = [c.id for c in cegs_list]

            # 1. Carrega todos os sets ativos de uma vez
            active_sets = list(
                CEGSet.objects.filter(ceg_id__in=ceg_ids, is_active=True).order_by('set_number')
            )
            sets_by_ceg = defaultdict(list)
            for s in active_sets:
                sets_by_ceg[s.ceg_id].append(s)

            # 2. Carrega todos os slots dos sets ativos de uma vez
            all_slots = list(
                ItemSlot.objects.filter(set__ceg_id__in=ceg_ids, set__is_active=True)
                .select_related('set', 'item_definition')
                .order_by('item_definition__name')
            )
            slots_by_set = defaultdict(list)
            slots_by_ceg = defaultdict(list)
            for slot in all_slots:
                slots_by_set[slot.set_id].append(slot)
                slots_by_ceg[slot.set.ceg_id].append(slot)

            # 3. Agrega valores de Claims em 1 única query
            claim_aggregates = Claim.objects.filter(
                slot__set__ceg_id__in=ceg_ids
            ).values('slot__set__ceg_id', 'status').annotate(
                total_val=Sum('total_price')
            )
            paid_val_by_ceg = defaultdict(float)
            pending_val_by_ceg = defaultdict(float)
            for row in claim_aggregates:
                cid = row['slot__set__ceg_id']
                val = float(row['total_val'] or 0)
                if row['status'] == Claim.Status.PAID:
                    paid_val_by_ceg[cid] += val
                elif row['status'] == Claim.Status.PENDING:
                    pending_val_by_ceg[cid] += val

            for ceg in cegs_list:
                for cset in sets_by_ceg.get(ceg.id, []):
                    total_sets_count += 1
                    slots = slots_by_set.get(cset.id, [])
                    tot = len(slots)
                    total_slots_count += tot

                    claimed_slots = [s for s in slots if s.status in [ItemSlot.Status.RESERVED, ItemSlot.Status.PAID]]
                    available_slots = [s for s in slots if s.status == ItemSlot.Status.AVAILABLE]
                    res_count = len(claimed_slots)
                    total_reserved_slots_count += res_count

                    fill_pct = int((res_count / tot) * 100) if tot > 0 else 0
                    set_is_full = (res_count == tot and tot > 0)

                    # Valores do set
                    set_total_value = sum(float(s.price) for s in slots)
                    set_paid_value = sum(float(s.price) for s in slots if s.is_item_paid)
                    set_pending_value = sum(float(s.price) for s in claimed_slots if not s.is_item_paid)
                    set_missing_value = sum(float(s.price) for s in available_slots)

                    # Checagem de pendências operacionais (se set_is_full)
                    if set_is_full:
                        pending_reasons = []
                        # 1. Pagamento de itens
                        items_unpaid = [s for s in slots if not s.is_item_paid]
                        paid_items_count = tot - len(items_unpaid)
                        if items_unpaid:
                            pending_reasons.append({
                                'code': 'UNPAID_ITEMS',
                                'title': f"{len(items_unpaid)} item(ns) aguardando pagamento",
                                'type': 'warning'
                            })

                        # 2. Frete Internacional
                        has_frete = (ceg.frete_inter is not None and ceg.frete_inter > 0)
                        actual_frete_paid = sum(1 for s in slots if s.is_frete_inter_paid)
                        unpaid_frete = [s for s in slots if not s.is_frete_inter_paid] if has_frete else []
                        frete_paid_slots = (tot - len(unpaid_frete)) if has_frete else actual_frete_paid
                        frete_inter_paid = bool(has_frete and len(unpaid_frete) == 0)
                        frete_inter_pending = bool(has_frete and len(unpaid_frete) > 0)

                        if has_frete and unpaid_frete:
                            pending_reasons.append({
                                'code': 'FRETE_INTER_UNPAID',
                                'title': f"{len(unpaid_frete)} frete(s) inter pendente(s)",
                                'type': 'warning'
                            })

                        # 3. Taxa Aduaneira
                        has_taxa = (ceg.taxa_aduaneira is not None and ceg.taxa_aduaneira > 0)
                        actual_taxa_paid = sum(1 for s in slots if s.is_taxa_aduaneira_paid)
                        unpaid_taxa = [s for s in slots if not s.is_taxa_aduaneira_paid] if has_taxa else []
                        taxa_paid_slots = (tot - len(unpaid_taxa)) if has_taxa else actual_taxa_paid
                        taxa_aduaneira_paid = bool(has_taxa and len(unpaid_taxa) == 0)
                        taxa_aduaneira_pending = bool(has_taxa and len(unpaid_taxa) > 0)

                        if has_taxa and unpaid_taxa:
                            pending_reasons.append({
                                'code': 'TAXA_UNPAID',
                                'title': f"{len(unpaid_taxa)} taxa(s) aduaneira(s) pendente(s)",
                                'type': 'warning'
                            })

                        is_fully_paid = (len(items_unpaid) == 0)
                        frete_ok = (not has_frete) or (len(unpaid_frete) == 0)
                        taxa_ok = (not has_taxa) or (len(unpaid_taxa) == 0)
                        is_terminado = is_fully_paid and frete_ok and taxa_ok

                        set_dict = {
                            'set_id': cset.id,
                            'set_number': cset.set_number,
                            'ceg_id': ceg.id,
                            'ceg_title': ceg.title,
                            'ceg_clean_title': ceg.clean_title(ceg.era.group.name),
                            'ceg_slug': ceg.slug,
                            'banner_url': ceg.banner_url or '',
                            'image_url': ceg.banner_url or (ceg.era.banner_url if (ceg.era and ceg.era.banner_url) else '') or (ceg.era.group.image_url if (ceg.era and ceg.era.group and ceg.era.group.image_url) else '') or '',
                            'group_name': ceg.era.group.name,
                            'era_name': ceg.era.name,
                            'ceg_status': ceg.status,
                            'ceg_status_display': ceg.get_status_display(),
                            'total_slots': tot,
                            'reserved_slots': res_count,
                            'paid_items_count': paid_items_count,
                            'unpaid_items_count': len(items_unpaid),
                            'set_total_value': set_total_value,
                            'set_paid_value': set_paid_value,
                            'set_pending_value': set_pending_value,
                            'has_frete': has_frete,
                            'has_taxa': has_taxa,
                            'frete_inter': float(ceg.frete_inter) if has_frete else None,
                            'frete_inter_paid': frete_inter_paid,
                            'frete_inter_pending': frete_inter_pending,
                            'frete_inter_paid_slots': frete_paid_slots,
                            'frete_status_display': 'Pago' if frete_inter_paid else (f"{frete_paid_slots}/{tot} pagos" if has_frete else "Sem frete"),
                            'taxa_aduaneira': float(ceg.taxa_aduaneira) if has_taxa else None,
                            'taxa_aduaneira_paid': taxa_aduaneira_paid,
                            'taxa_aduaneira_pending': taxa_aduaneira_pending,
                            'taxa_paid_slots': taxa_paid_slots,
                            'taxa_status_display': 'Paga' if taxa_aduaneira_paid else (f"{taxa_paid_slots}/{tot} pagas" if has_taxa else "Sem taxa"),
                            'pending_reasons': pending_reasons,
                            'is_fully_paid': is_fully_paid,
                            'is_terminado': is_terminado,
                        }

                        if not is_fully_paid:
                            sets_fechados.append(set_dict)
                        else:
                            sets_pagos.append(set_dict)
                            if is_terminado:
                                sets_terminados.append(set_dict)

                        if pending_reasons:
                            sets_completed_pending.append(set_dict)

                    else:
                        # Set Incompleto: detalhar exatamente o que falta para fechar
                        missing_items = []
                        for s in available_slots:
                            missing_items.append({
                                'slot_id': s.id,
                                'item_name': s.item_definition.name,
                                'member_name': s.item_definition.member_name or s.item_definition.get_item_type_display(),
                                'price': float(s.price)
                            })

                        sets_incomplete.append({
                            'set_id': cset.id,
                            'set_number': cset.set_number,
                            'ceg_id': ceg.id,
                            'ceg_title': ceg.title,
                            'ceg_clean_title': ceg.clean_title(ceg.era.group.name),
                            'ceg_slug': ceg.slug,
                            'banner_url': ceg.banner_url or '',
                            'image_url': ceg.banner_url or (ceg.era.banner_url if (ceg.era and ceg.era.banner_url) else '') or (ceg.era.group.image_url if (ceg.era and ceg.era.group and ceg.era.group.image_url) else '') or '',
                            'group_name': ceg.era.group.name,
                            'era_name': ceg.era.name,
                            'ceg_status': ceg.status,
                            'ceg_status_display': ceg.get_status_display(),
                            'total_slots': tot,
                            'reserved_slots': res_count,
                            'remaining_slots': len(available_slots),
                            'fill_percentage': fill_pct,
                            'set_total_value': set_total_value,
                            'set_sold_value': set_paid_value + set_pending_value,
                            'missing_value': set_missing_value,
                            'missing_items': missing_items,
                        })

                # Estatísticas da CEG individual em memória (0 queries adicionais!)
                ceg_slots = slots_by_ceg.get(ceg.id, [])
                ceg_total_slots_cnt = len(ceg_slots)
                ceg_sold_slots_cnt = sum(1 for s in ceg_slots if s.status in [ItemSlot.Status.RESERVED, ItemSlot.Status.PAID])
                ceg_avail_slots_cnt = sum(1 for s in ceg_slots if s.status == ItemSlot.Status.AVAILABLE)

                ceg_paid_val = paid_val_by_ceg.get(ceg.id, 0.0)
                ceg_pending_val = pending_val_by_ceg.get(ceg.id, 0.0)
                ceg_avail_val = sum(float(s.price) for s in ceg_slots if s.status == ItemSlot.Status.AVAILABLE)
                ceg_pot_val = ceg_paid_val + ceg_pending_val + ceg_avail_val
                ceg_fill_pct = int((ceg_sold_slots_cnt / ceg_total_slots_cnt) * 100) if ceg_total_slots_cnt > 0 else 0

                has_ceg_frete = (ceg.frete_inter is not None and ceg.frete_inter > 0)
                has_ceg_taxa = (ceg.taxa_aduaneira is not None and ceg.taxa_aduaneira > 0)
                frete_inter_paid_slots = sum(1 for s in ceg_slots if s.is_frete_inter_paid) if has_ceg_frete else 0
                taxa_paid_slots = sum(1 for s in ceg_slots if s.is_taxa_aduaneira_paid) if has_ceg_taxa else 0

                ceg_closed_cnt = sum(1 for s in sets_fechados if s['ceg_id'] == ceg.id)
                ceg_paid_sets_cnt = sum(1 for s in sets_pagos if s['ceg_id'] == ceg.id)
                ceg_finished_cnt = sum(1 for s in sets_terminados if s['ceg_id'] == ceg.id)
                ceg_incomplete_cnt = sum(1 for s in sets_incomplete if s['ceg_id'] == ceg.id)
                ceg_completed_pending_cnt = sum(1 for s in sets_completed_pending if s['ceg_id'] == ceg.id)

                is_ceg_ativa = (ceg_avail_slots_cnt > 0)

                cegs_overview.append({
                    'ceg_id': ceg.id,
                    'title': ceg.title,
                    'clean_title': ceg.clean_title(ceg.era.group.name),
                    'slug': ceg.slug,
                    'banner_url': ceg.banner_url or '',
                    'image_url': ceg.banner_url or (ceg.era.banner_url if (ceg.era and ceg.era.banner_url) else '') or (ceg.era.group.image_url if (ceg.era and ceg.era.group and ceg.era.group.image_url) else '') or '',
                    'status': ceg.status,
                    'status_display': ceg.get_status_display(),
                    'group_name': ceg.era.group.name,
                    'era_name': ceg.era.name,
                    'total_sets': len(sets_by_ceg.get(ceg.id, [])),
                    'total_slots': ceg_total_slots_cnt,
                    'sold_slots': ceg_sold_slots_cnt,
                    'available_slots': ceg_avail_slots_cnt,
                    'fill_percentage': ceg_fill_pct,
                    'is_ativa': is_ceg_ativa,
                    'has_open_slots': is_ceg_ativa,
                    'closed_sets_count': ceg_closed_cnt,
                    'paid_sets_count': ceg_paid_sets_cnt,
                    'finished_sets_count': ceg_finished_cnt,
                    'completed_pending_sets_count': ceg_completed_pending_cnt,
                    'incomplete_sets_count': ceg_incomplete_cnt,
                    'completed_pending_sets': ceg_completed_pending_cnt,
                    'incomplete_sets': ceg_incomplete_cnt,
                    'has_completed_sets': ceg_closed_cnt > 0 or (ceg_sold_slots_cnt == ceg_total_slots_cnt and ceg_total_slots_cnt > 0),
                    'has_incomplete_sets': is_ceg_ativa,
                    'has_paid_sets': ceg_paid_sets_cnt > 0,
                    'has_finished_sets': ceg_finished_cnt > 0,
                    'paid_amount': ceg_paid_val,
                    'pending_amount': ceg_pending_val,
                    'available_amount': ceg_avail_val,
                    'total_potential': ceg_pot_val,
                    'caixa_id': ceg.caixa_id,
                    'caixa_nome': ceg.caixa.nome if ceg.caixa else None,
                    'caixa_origem': ceg.caixa.origem if ceg.caixa else None,
                    'caixa_origem_display': ceg.caixa.get_origem_display() if ceg.caixa else None,
                    'caixa_slug': ceg.caixa.slug if ceg.caixa else None,
                    'shipping_status': ceg.shipping_status,
                    'shipping_status_display': ceg.get_shipping_status_display(),
                    'tracking_code': ceg.caixa.codigo_rastreio if (ceg.caixa and ceg.caixa.codigo_rastreio) else '',
                    'tracking_url': ceg.caixa.tracking_url if ceg.caixa else '',
                    'has_frete': has_ceg_frete,
                    'has_taxa': has_ceg_taxa,
                    'frete_inter': float(ceg.frete_inter) if has_ceg_frete else None,
                    'frete_inter_paid_slots': frete_inter_paid_slots,
                    'prazo_frete_inter': ceg.prazo_pagamento_frete_inter if has_ceg_frete else None,
                    'taxa_aduaneira': float(ceg.taxa_aduaneira) if has_ceg_taxa else None,
                    'taxa_paid_slots': taxa_paid_slots,
                    'prazo_taxa': ceg.prazo_pagamento_taxa_aduaneira if has_ceg_taxa else None,
                    'prazo_item': ceg.prazo_pagamento_item,
                })

            sets_fechados.sort(key=lambda x: (x['group_name'], x['era_name'], x['set_number']))
            sets_pagos.sort(key=lambda x: (not x['is_terminado'], x['group_name'], x['era_name'], x['set_number']))
            sets_terminados.sort(key=lambda x: (x['group_name'], x['era_name'], x['set_number']))
            sets_completed_pending.sort(key=lambda x: (x['group_name'], x['era_name'], x['set_number']))
            sets_incomplete.sort(key=lambda x: (x['remaining_slots'], -x['fill_percentage']))
            cegs_overview.sort(key=lambda x: (not x['is_ativa'], -x['total_potential']))

        global_occupancy = int((total_reserved_slots_count / total_slots_count) * 100) if total_slots_count > 0 else 0

        # Estatísticas de Itens Individuais (Mercari)
        mercari_status = None
        total_mercari_items = 0
        mercari_frete_unpaid_count = 0
        mercari_taxa_unpaid_count = 0

        if category in ['all', 'mercari']:
            mercari_qs = ItemIndividual.objects.select_related('caixa', 'comprador', 'tipo_item').all()
            if (group_id or era_id) and category != 'mercari':
                mercari_items_list = []
            else:
                mercari_items_list = list(mercari_qs)

            total_mercari_items = len(mercari_items_list)
            status_counts = {
                'COMPRADO': 0, 'WAREHOUSE': 0, 'EM_CONSOLIDACAO': 0,
                'ENVIADO': 0, 'NO_BRASIL': 0, 'TRIBUTADO': 0,
                'LIBERADO': 0, 'NA_GOM': 0, 'FINALIZADO': 0
            }
            mercari_frete_unpaid_amount = 0.0
            mercari_taxa_unpaid_amount = 0.0
            mercari_total_product_value = 0.0
            serialized_mercari_items = []

            for it in mercari_items_list:
                st = it.status
                if st in status_counts:
                    status_counts[st] += it.quantidade
                else:
                    status_counts[st] = status_counts.get(st, 0) + it.quantidade

                if it.preco_produto:
                    mercari_total_product_value += float(it.preco_produto)

                if it.frete_inter and it.frete_inter > 0 and not it.frete_inter_pago:
                    mercari_frete_unpaid_count += 1
                    mercari_frete_unpaid_amount += float(it.frete_inter)

                if it.taxa_aduaneira and it.taxa_aduaneira > 0 and not it.taxa_aduaneira_paga:
                    mercari_taxa_unpaid_count += 1
                    mercari_taxa_unpaid_amount += float(it.taxa_aduaneira)

                serialized_mercari_items.append({
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
                    'comprador_phone_clean': it.comprador.whatsapp,
                    'comprador_handle': it.comprador.social_handle or '',
                    'caixa_id': it.caixa_id,
                    'caixa_nome': it.caixa.nome if it.caixa else None,
                    'caixa_slug': it.caixa.slug if it.caixa else None,
                    'caixa_status': it.caixa.status if it.caixa else None,
                    'caixa_status_display': it.caixa.get_status_display() if it.caixa else None,
                    'tracking_code': it.caixa.codigo_rastreio if (it.caixa and it.caixa.codigo_rastreio) else '',
                    'tracking_url': it.caixa.tracking_url if it.caixa else '',
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
                    'created_at': it.created_at,
                })

            mercari_status = {
                'total_itens': total_mercari_items,
                'total_unidades': sum(it.quantidade for it in mercari_items_list),
                'by_status': status_counts,
                'frete_unpaid_count': mercari_frete_unpaid_count,
                'frete_unpaid_amount': mercari_frete_unpaid_amount,
                'taxa_unpaid_count': mercari_taxa_unpaid_count,
                'taxa_unpaid_amount': mercari_taxa_unpaid_amount,
                'total_product_value': mercari_total_product_value,
                'items': serialized_mercari_items,
            }

        active_cegs_count = sum(1 for c in cegs_overview if c['is_ativa']) if category in ['all', 'ceg'] else 0

        return {
            'category': category,
            'sets_fechados': sets_fechados,
            'sets_pagos': sets_pagos,
            'sets_terminados': sets_terminados,
            'sets_completed_pending': sets_completed_pending,
            'sets_incomplete': sets_incomplete,
            'cegs_overview': cegs_overview,
            'mercari_status': mercari_status,
            'summary': {
                'total_cegs': cegs_qs.count() if category in ['all', 'ceg'] else 0,
                'open_cegs': active_cegs_count,
                'active_cegs': active_cegs_count,
                'active_cegs_count': active_cegs_count,
                'scheduled_cegs': cegs_qs.filter(status=CEG.Status.SCHEDULED).count() if category in ['all', 'ceg'] else 0,
                'total_sets': total_sets_count,
                'closed_sets_count': len(sets_fechados),
                'paid_sets_count': len(sets_pagos),
                'finished_sets_count': len(sets_terminados),
                'completed_pending_sets_count': len(sets_fechados),
                'incomplete_sets_count': len(sets_incomplete),
                'paid_frete_sets_count': sum(1 for s in sets_pagos if s['frete_inter_paid']),
                'pending_frete_sets_count': sum(1 for s in sets_pagos if s['frete_inter_pending']),
                'unlaunched_frete_sets_count': sum(1 for s in sets_pagos if not s['has_frete']),
                'paid_taxa_sets_count': sum(1 for s in sets_pagos if s['taxa_aduaneira_paid']),
                'pending_taxa_sets_count': sum(1 for s in sets_pagos if s['taxa_aduaneira_pending']),
                'unlaunched_taxa_sets_count': sum(1 for s in sets_pagos if not s['has_taxa']),
                'total_slots': total_slots_count,
                'reserved_slots': total_reserved_slots_count,
                'available_slots': total_slots_count - total_reserved_slots_count,
                'global_occupancy': global_occupancy,
                'total_mercari_items': total_mercari_items,
                'mercari_frete_unpaid': mercari_frete_unpaid_count,
                'mercari_taxa_unpaid': mercari_taxa_unpaid_count,
            }
        }

    @staticmethod
    def get_sales_analytics(group_id=None, era_id=None, time_window=None, month=None, category='all'):
        """
        Retorna o relatório analítico completo de vendas, faturamento e BI com suporte a categorias:
        - category: 'all' (Geral: CEGs + Mercari), 'ceg' (Apenas CEGs), 'mercari' (Apenas Caixa Mercari)
        - time_window: '30d', '90d', '180d', 'year', 'all'
        - month: 'YYYY-MM'
        - monthly_flow: agregação temporal contínua mês a mês
        - group_sales: faturamento e volume por grupo (incluindo Mercari)
        - top_items: ranking de itens mais vendidos
        - top_buyers: participantes com maior volume de compras
        """
        now = timezone.now()

        # 1. CEGs Claims
        claims = Claim.objects.none()
        if category in ['all', 'ceg']:
            claims = Claim.objects.exclude(status=Claim.Status.CANCELLED).select_related(
                'participant', 'slot__set__ceg__era__group', 'slot__item_definition'
            )
            if group_id:
                claims = claims.filter(slot__set__ceg__era__group_id=group_id)
            if era_id:
                claims = claims.filter(slot__set__ceg__era_id=era_id)

            if time_window == '30d':
                claims = claims.filter(claimed_at__gte=now - timedelta(days=30))
            elif time_window == '90d':
                claims = claims.filter(claimed_at__gte=now - timedelta(days=90))
            elif time_window == '180d':
                claims = claims.filter(claimed_at__gte=now - timedelta(days=180))
            elif time_window == 'year':
                claims = claims.filter(claimed_at__year=now.year)
            elif month:
                try:
                    y, m = month.split('-')
                    claims = claims.filter(claimed_at__year=int(y), claimed_at__month=int(m))
                except (ValueError, TypeError):
                    pass

        ceg_paid = float(claims.filter(status=Claim.Status.PAID).aggregate(s=Sum('total_price'))['s'] or 0)
        ceg_pending = float(claims.filter(status=Claim.Status.PENDING).aggregate(s=Sum('total_price'))['s'] or 0)
        ceg_claims_count = claims.count()

        # Agregação temporal de claims por mês
        claims_by_month = {}
        if claims.exists():
            monthly_qs = claims.annotate(
                month=TruncMonth('claimed_at')
            ).values('month').annotate(
                total_amount=Sum('total_price'),
                paid_amount=Sum('total_price', filter=Q(status=Claim.Status.PAID)),
                pending_amount=Sum('total_price', filter=Q(status=Claim.Status.PENDING)),
                claims_count=Count('id')
            ).order_by('month')

            for row in monthly_qs:
                dt = row['month']
                if dt:
                    key = dt.strftime('%Y-%m')
                    claims_by_month[key] = {
                        'total_sales': float(row['total_amount'] or 0),
                        'paid_sales': float(row['paid_amount'] or 0),
                        'pending_sales': float(row['pending_amount'] or 0),
                        'claims_count': row['claims_count'],
                    }

        # 2. Itens Individuais (Mercari)
        mercari_items = ItemIndividual.objects.none()
        if category in ['all', 'mercari']:
            if not ((group_id or era_id) and category != 'mercari'):
                mercari_items = ItemIndividual.objects.select_related('comprador', 'caixa').all()
                if time_window == '30d':
                    mercari_items = mercari_items.filter(created_at__gte=now - timedelta(days=30))
                elif time_window == '90d':
                    mercari_items = mercari_items.filter(created_at__gte=now - timedelta(days=90))
                elif time_window == '180d':
                    mercari_items = mercari_items.filter(created_at__gte=now - timedelta(days=180))
                elif time_window == 'year':
                    mercari_items = mercari_items.filter(created_at__year=now.year)
                elif month:
                    try:
                        y, m = month.split('-')
                        mercari_items = mercari_items.filter(created_at__year=int(y), created_at__month=int(m))
                    except (ValueError, TypeError):
                        pass

        mercari_paid = 0.0
        mercari_pending = 0.0
        mercari_by_month = {}
        mercari_items_count = 0
        mercari_buyers = {}
        mercari_item_counts = {}

        for it in mercari_items:
            prod_price = float(it.preco_produto or 0)
            frete = float(it.frete_inter or 0)
            taxa = float(it.taxa_aduaneira or 0)

            paid_val = prod_price + (frete if it.frete_inter_pago else 0.0) + (taxa if it.taxa_aduaneira_paga else 0.0)
            pending_val = (frete if not it.frete_inter_pago else 0.0) + (taxa if not it.taxa_aduaneira_paga else 0.0)
            tot_val = paid_val + pending_val

            mercari_paid += paid_val
            mercari_pending += pending_val
            mercari_items_count += it.quantidade

            m_key = it.created_at.strftime('%Y-%m')
            if m_key not in mercari_by_month:
                mercari_by_month[m_key] = {
                    'total_sales': 0.0,
                    'paid_sales': 0.0,
                    'pending_sales': 0.0,
                    'claims_count': 0
                }
            mercari_by_month[m_key]['total_sales'] += tot_val
            mercari_by_month[m_key]['paid_sales'] += paid_val
            mercari_by_month[m_key]['pending_sales'] += pending_val
            mercari_by_month[m_key]['claims_count'] += it.quantidade

            bp = it.comprador
            if bp.id not in mercari_buyers:
                mercari_buyers[bp.id] = {
                    'id': bp.id,
                    'name': bp.name,
                    'display_name': bp.display_name,
                    'whatsapp': bp.whatsapp,
                    'social_handle': bp.social_handle or '',
                    'claims_count': 0,
                    'total_spent': 0.0
                }
            mercari_buyers[bp.id]['claims_count'] += it.quantidade
            mercari_buyers[bp.id]['total_spent'] += tot_val

            item_key = (it.nome, 'Caixas Mercari (JP)')
            if item_key not in mercari_item_counts:
                mercari_item_counts[item_key] = {
                    'name': it.nome,
                    'item_name': it.nome,
                    'member_name': 'Mercari JP',
                    'group_name': 'Caixas Mercari (JP)',
                    'count': 0,
                    'total_claims': 0,
                    'total_amount': 0.0,
                    'total_revenue': 0.0,
                }
            mercari_item_counts[item_key]['count'] += it.quantidade
            mercari_item_counts[item_key]['total_claims'] += it.quantidade
            mercari_item_counts[item_key]['total_amount'] += tot_val
            mercari_item_counts[item_key]['total_revenue'] += tot_val

        # Consolidação Geral
        total_paid = ceg_paid + mercari_paid
        total_pending = ceg_pending + mercari_pending
        total_sales = total_paid + total_pending
        claims_count = ceg_claims_count + mercari_items_count

        claim_participant_ids = set(claims.values_list('participant_id', flat=True)) if claims.exists() else set()
        mercari_participant_ids = set(mercari_buyers.keys())
        unique_participants = len(claim_participant_ids.union(mercari_participant_ids))

        avg_ticket_per_buyer = float(total_sales / unique_participants) if unique_participants > 0 else 0.0
        avg_ticket_per_claim = float(total_sales / claims_count) if claims_count > 0 else 0.0
        collection_rate = round((total_paid / total_sales) * 100, 1) if total_sales > 0 else 0

        # Construção da linha do tempo contínua
        timeline_months = []
        if month:
            try:
                y, m = month.split('-')
                timeline_months = [(int(y), int(m))]
            except (ValueError, TypeError):
                timeline_months = [(now.year, now.month)]
        elif time_window == 'year':
            cur_y, cur_m = now.year, 1
            while (cur_y < now.year) or (cur_y == now.year and cur_m <= now.month):
                timeline_months.append((cur_y, cur_m))
                cur_m += 1
                if cur_m > 12:
                    cur_m = 1
                    cur_y += 1
        elif time_window == '180d':
            start_m = now.month - 5
            start_y = now.year
            while start_m <= 0:
                start_m += 12
                start_y -= 1
            cur_y, cur_m = start_y, start_m
            while (cur_y < now.year) or (cur_y == now.year and cur_m <= now.month):
                timeline_months.append((cur_y, cur_m))
                cur_m += 1
                if cur_m > 12:
                    cur_m = 1
                    cur_y += 1
        elif time_window == '90d':
            start_m = now.month - 2
            start_y = now.year
            while start_m <= 0:
                start_m += 12
                start_y -= 1
            cur_y, cur_m = start_y, start_m
            while (cur_y < now.year) or (cur_y == now.year and cur_m <= now.month):
                timeline_months.append((cur_y, cur_m))
                cur_m += 1
                if cur_m > 12:
                    cur_m = 1
                    cur_y += 1
        elif time_window == '30d':
            start_m = now.month - 1
            start_y = now.year
            while start_m <= 0:
                start_m += 12
                start_y -= 1
            cur_y, cur_m = start_y, start_m
            while (cur_y < now.year) or (cur_y == now.year and cur_m <= now.month):
                timeline_months.append((cur_y, cur_m))
                cur_m += 1
                if cur_m > 12:
                    cur_m = 1
                    cur_y += 1
        else:
            six_m_ago_m = now.month - 5
            six_m_ago_y = now.year
            while six_m_ago_m <= 0:
                six_m_ago_m += 12
                six_m_ago_y -= 1

            all_month_keys = list(claims_by_month.keys()) + list(mercari_by_month.keys())
            if all_month_keys:
                min_key = min(all_month_keys)
                min_y, min_m = int(min_key[:4]), int(min_key[5:7])
                if (min_y, min_m) < (six_m_ago_y, six_m_ago_m):
                    start_y, start_m = min_y, min_m
                else:
                    start_y, start_m = six_m_ago_y, six_m_ago_m
            else:
                start_y, start_m = six_m_ago_y, six_m_ago_m

            cur_y, cur_m = start_y, start_m
            while (cur_y < now.year) or (cur_y == now.year and cur_m <= now.month):
                timeline_months.append((cur_y, cur_m))
                cur_m += 1
                if cur_m > 12:
                    cur_m = 1
                    cur_y += 1

        monthly_flow = []
        for y, m in timeline_months:
            key = f"{y:04d}-{m:02d}"
            cdata = claims_by_month.get(key, {
                'total_sales': 0.0,
                'paid_sales': 0.0,
                'pending_sales': 0.0,
                'claims_count': 0
            })
            mdata = mercari_by_month.get(key, {
                'total_sales': 0.0,
                'paid_sales': 0.0,
                'pending_sales': 0.0,
                'claims_count': 0
            })
            monthly_flow.append({
                'month_key': key,
                'label': f"{MONTH_ABBR.get(m, '')}/{str(y)[2:]}",
                'full_label': f"{MONTH_FULL.get(m, '')}/{y}",
                'total_sales': cdata['total_sales'] + mdata['total_sales'],
                'paid_sales': cdata['paid_sales'] + mdata['paid_sales'],
                'pending_sales': cdata['pending_sales'] + mdata['pending_sales'],
                'claims_count': cdata['claims_count'] + mdata['claims_count'],
            })

        # Vendas por Grupo
        group_sales_map = {}
        for c in claims:
            grp = c.slot.set.ceg.era.group.name
            if grp not in group_sales_map:
                group_sales_map[grp] = {'group_name': grp, 'total_sales': 0.0, 'claims_count': 0}
            group_sales_map[grp]['total_sales'] += float(c.total_price)
            group_sales_map[grp]['claims_count'] += 1

        if (mercari_paid + mercari_pending) > 0 or mercari_items_count > 0:
            group_sales_map['Caixas Mercari (JP)'] = {
                'group_name': 'Caixas Mercari (JP)',
                'total_sales': mercari_paid + mercari_pending,
                'claims_count': mercari_items_count
            }

        group_sales = sorted(group_sales_map.values(), key=lambda x: x['total_sales'], reverse=True)

        # Top Itens mais vendidos
        item_sales_map = {}
        for c in claims:
            name = c.slot.item_definition.name
            member = c.slot.item_definition.member_name or ''
            grp = c.slot.set.ceg.era.group.name
            key = (name, grp)
            if key not in item_sales_map:
                item_sales_map[key] = {
                    'name': name,
                    'item_name': name,
                    'member_name': member,
                    'group_name': grp,
                    'count': 0,
                    'total_claims': 0,
                    'total_amount': 0.0,
                    'total_revenue': 0.0,
                }
            item_sales_map[key]['count'] += 1
            item_sales_map[key]['total_claims'] += 1
            item_sales_map[key]['total_amount'] += float(c.total_price)
            item_sales_map[key]['total_revenue'] += float(c.total_price)

        for m_key, m_val in mercari_item_counts.items():
            if m_key not in item_sales_map:
                item_sales_map[m_key] = m_val
            else:
                item_sales_map[m_key]['count'] += m_val['count']
                item_sales_map[m_key]['total_claims'] += m_val['total_claims']
                item_sales_map[m_key]['total_amount'] += m_val['total_amount']
                item_sales_map[m_key]['total_revenue'] += m_val['total_revenue']

        top_items = sorted(item_sales_map.values(), key=lambda x: (x['total_claims'], x['total_revenue']), reverse=True)[:15]

        # Top compradores
        buyer_map = {}
        for c in claims:
            p = c.participant
            if p.id not in buyer_map:
                buyer_map[p.id] = {
                    'id': p.id,
                    'name': p.name,
                    'display_name': p.display_name,
                    'whatsapp': p.whatsapp,
                    'social_handle': p.social_handle or '',
                    'claims_count': 0,
                    'total_spent': 0.0
                }
            buyer_map[p.id]['claims_count'] += 1
            buyer_map[p.id]['total_spent'] += float(c.total_price)

        for mb_id, mb_data in mercari_buyers.items():
            if mb_id not in buyer_map:
                buyer_map[mb_id] = mb_data
            else:
                buyer_map[mb_id]['claims_count'] += mb_data['claims_count']
                buyer_map[mb_id]['total_spent'] += mb_data['total_spent']

        top_buyers = sorted(buyer_map.values(), key=lambda x: (x['total_spent'], x['claims_count']), reverse=True)[:10]

        return {
            'category': category,
            'summary': {
                'total_paid': total_paid,
                'total_pending': total_pending,
                'total_sales': total_sales,
                'total_claims': claims_count,
                'claims_count': claims_count,
                'total_participants': unique_participants,
                'unique_participants': unique_participants,
                'avg_ticket': avg_ticket_per_buyer,
                'avg_ticket_per_buyer': avg_ticket_per_buyer,
                'avg_ticket_per_claim': avg_ticket_per_claim,
                'collection_rate': collection_rate,
            },
            'monthly_flow': monthly_flow,
            'group_sales': group_sales,
            'top_items': top_items,
            'top_buyers': top_buyers,
        }

