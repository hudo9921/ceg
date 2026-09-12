from datetime import timedelta
from django.db.models import Count, Sum, Q, F
from django.db.models.functions import TruncMonth
from django.utils import timezone
from apps.cegs.models import CEG, CEGSet, ItemSlot, CEGItemDefinition
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
            groups_data.append({
                'id': str(g.id),
                'name': g.name,
                'eras': [{'id': str(e.id), 'name': e.name} for e in g.eras.all().order_by('name')]
            })

        eras = Era.objects.select_related('group').all().order_by('group__name', 'name')
        eras_data = [{
            'id': str(e.id),
            'name': e.name,
            'group_id': str(e.group_id),
            'group_name': e.group.name
        } for e in eras]

        # Meses com claims registrados
        month_dates = Claim.objects.annotate(
            m=TruncMonth('claimed_at')
        ).values_list('m', flat=True).distinct().order_by('-m')

        months_data = []
        seen_months = set()
        for dt in month_dates:
            if dt:
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

        table_rows = []
        for c in cegs:
            total_slots = ItemSlot.objects.filter(set__ceg=c, set__is_active=True).count()
            sold_slots = ItemSlot.objects.filter(
                set__ceg=c, set__is_active=True,
                status__in=[ItemSlot.Status.RESERVED, ItemSlot.Status.PAID]
            ).count()
            available_slots = ItemSlot.objects.filter(
                set__ceg=c, set__is_active=True, status=ItemSlot.Status.AVAILABLE
            ).count()

            paid_sum = float(Claim.objects.filter(
                slot__set__ceg=c, status=Claim.Status.PAID
            ).aggregate(s=Sum('total_price'))['s'] or 0)

            pending_sum = float(Claim.objects.filter(
                slot__set__ceg=c, status=Claim.Status.PENDING
            ).aggregate(s=Sum('total_price'))['s'] or 0)

            sold_sum = paid_sum + pending_sum

            available_sum = float(ItemSlot.objects.filter(
                set__ceg=c, set__is_active=True, status=ItemSlot.Status.AVAILABLE
            ).aggregate(s=Sum('price'))['s'] or 0)

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
        """Compara o faturamento e capacidade entre os grupos para gráficos"""
        groups = KpopGroup.objects.all().order_by('name')
        results = []
        for g in groups:
            paid = float(Claim.objects.filter(
                slot__set__ceg__era__group=g, status=Claim.Status.PAID
            ).aggregate(s=Sum('total_price'))['s'] or 0)

            pending = float(Claim.objects.filter(
                slot__set__ceg__era__group=g, status=Claim.Status.PENDING
            ).aggregate(s=Sum('total_price'))['s'] or 0)

            available = float(ItemSlot.objects.filter(
                set__ceg__era__group=g, set__is_active=True, status=ItemSlot.Status.AVAILABLE
            ).aggregate(s=Sum('price'))['s'] or 0)

            claims_cnt = Claim.objects.filter(
                slot__set__ceg__era__group=g
            ).exclude(status=Claim.Status.CANCELLED).count()

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
        """Retorna sets com suporte a filtros de grupo e era."""
        active_sets = CEGSet.objects.filter(
            is_active=True,
            ceg__status__in=[CEG.Status.OPEN, CEG.Status.SCHEDULED]
        ).select_related('ceg', 'ceg__era', 'ceg__era__group')

        if group_id:
            active_sets = active_sets.filter(ceg__era__group_id=group_id)
        if era_id:
            active_sets = active_sets.filter(ceg__era_id=era_id)

        sets_info = []
        for s in active_sets:
            total = s.slots_count
            reserved = s.reserved_count
            if total > 0:
                pct = int((reserved / total) * 100)
                sets_info.append({
                    'set_id': s.id,
                    'set_number': s.set_number,
                    'ceg_title': s.ceg.title,
                    'group_name': s.ceg.era.group.name,
                    'total_slots': total,
                    'reserved_slots': reserved,
                    'remaining_slots': total - reserved,
                    'fill_percentage': pct,
                    'is_full': s.is_full,
                })

        return sorted(sets_info, key=lambda x: x['fill_percentage'], reverse=True)

    # Mantém compatibilidade com código legado que chama get_era_financials
    @staticmethod
    def get_era_financials():
        return AnalyticsService.get_detailed_inventory_table()

    @staticmethod
    def get_cegs_operational_status(group_id=None, era_id=None):
        """
        Retorna o status operacional detalhado das CEGs e Sets:
        - sets_completed_pending: Sets 100% preenchidos, porém ainda não finalizados
          (ex: aguardando cotação de frete inter, taxa aduaneira, ou com pagamentos de item/taxas pendentes).
        - sets_incomplete: Sets que ainda NÃO estão 100% preenchidos, com detalhes exatos
          do que falta para completá-los (membros/itens vagos, slots restantes, valor restante).
        - cegs_overview: Tabela consolidada de valores das CEGs em si (valores totais de itens, frete, taxa, status, prazos).
        """
        cegs_qs = CEG.objects.select_related('era__group', 'era').prefetch_related(
            'sets__slots__item_definition',
            'sets__slots__claimed_by'
        ).all()

        if group_id:
            cegs_qs = cegs_qs.filter(era__group_id=group_id)
        if era_id:
            cegs_qs = cegs_qs.filter(era_id=era_id)

        sets_completed_pending = []
        sets_incomplete = []
        cegs_overview = []

        total_sets_count = 0
        total_slots_count = 0
        total_reserved_slots_count = 0

        for ceg in cegs_qs:
            for cset in ceg.sets.filter(is_active=True).order_by('set_number'):
                total_sets_count += 1
                slots = list(cset.slots.all().order_by('item_definition__name'))
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
                    if items_unpaid:
                        pending_reasons.append({
                            'code': 'UNPAID_ITEMS',
                            'title': f"{len(items_unpaid)} item(ns) aguardando pagamento",
                            'type': 'warning'
                        })

                    # 2. Frete Internacional
                    # Quando não existir valor (> 0) para frete, consideramos que ele não existe na CEG (não flagar pendência)
                    has_frete = (ceg.frete_inter is not None and ceg.frete_inter > 0)
                    if has_frete:
                        unpaid_frete = [s for s in slots if not s.is_frete_inter_paid]
                        if unpaid_frete:
                            pending_reasons.append({
                                'code': 'FRETE_INTER_UNPAID',
                                'title': f"{len(unpaid_frete)} frete(s) inter pendente(s)",
                                'type': 'warning'
                            })

                    # 3. Taxa Aduaneira
                    # Quando não existir valor (> 0) para taxa, consideramos que ela não existe na CEG (não flagar pendência)
                    has_taxa = (ceg.taxa_aduaneira is not None and ceg.taxa_aduaneira > 0)
                    if has_taxa:
                        unpaid_taxa = [s for s in slots if not s.is_taxa_aduaneira_paid]
                        if unpaid_taxa:
                            pending_reasons.append({
                                'code': 'TAXA_UNPAID',
                                'title': f"{len(unpaid_taxa)} taxa(s) aduaneira(s) pendente(s)",
                                'type': 'warning'
                            })

                    # Apenas inclui em sets_completed_pending se houver de fato pendências ativas
                    if pending_reasons:
                        sets_completed_pending.append({
                            'set_id': cset.id,
                            'set_number': cset.set_number,
                            'ceg_id': ceg.id,
                            'ceg_title': ceg.title,
                            'ceg_slug': ceg.slug,
                            'group_name': ceg.era.group.name,
                            'era_name': ceg.era.name,
                            'ceg_status': ceg.status,
                            'ceg_status_display': ceg.get_status_display(),
                            'total_slots': tot,
                            'set_total_value': set_total_value,
                            'set_paid_value': set_paid_value,
                            'set_pending_value': set_pending_value,
                            'has_frete': has_frete,
                            'has_taxa': has_taxa,
                            'frete_inter': float(ceg.frete_inter) if has_frete else None,
                            'taxa_aduaneira': float(ceg.taxa_aduaneira) if has_taxa else None,
                            'pending_reasons': pending_reasons,
                            'is_fully_paid': False
                        })

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
                        'ceg_slug': ceg.slug,
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

            # Estatísticas da CEG individual para cegs_overview
            ceg_slots = ItemSlot.objects.filter(set__ceg=ceg, set__is_active=True)
            ceg_total_slots_cnt = ceg_slots.count()
            ceg_sold_slots_cnt = ceg_slots.filter(status__in=[ItemSlot.Status.RESERVED, ItemSlot.Status.PAID]).count()
            ceg_avail_slots_cnt = ceg_slots.filter(status=ItemSlot.Status.AVAILABLE).count()

            ceg_paid_val = float(Claim.objects.filter(slot__set__ceg=ceg, status=Claim.Status.PAID).aggregate(s=Sum('total_price'))['s'] or 0)
            ceg_pending_val = float(Claim.objects.filter(slot__set__ceg=ceg, status=Claim.Status.PENDING).aggregate(s=Sum('total_price'))['s'] or 0)
            ceg_avail_val = float(ceg_slots.filter(status=ItemSlot.Status.AVAILABLE).aggregate(s=Sum('price'))['s'] or 0)
            ceg_pot_val = ceg_paid_val + ceg_pending_val + ceg_avail_val
            ceg_fill_pct = int((ceg_sold_slots_cnt / ceg_total_slots_cnt) * 100) if ceg_total_slots_cnt > 0 else 0

            # Contadores de frete e taxa na CEG (apenas quando existirem com valor > 0)
            has_ceg_frete = (ceg.frete_inter is not None and ceg.frete_inter > 0)
            has_ceg_taxa = (ceg.taxa_aduaneira is not None and ceg.taxa_aduaneira > 0)
            frete_inter_paid_slots = ceg_slots.filter(is_frete_inter_paid=True).count() if has_ceg_frete else 0
            taxa_paid_slots = ceg_slots.filter(is_taxa_aduaneira_paid=True).count() if has_ceg_taxa else 0

            ceg_completed_cnt = sum(1 for s in sets_completed_pending if s['ceg_id'] == ceg.id)
            ceg_incomplete_cnt = sum(1 for s in sets_incomplete if s['ceg_id'] == ceg.id)

            cegs_overview.append({
                'ceg_id': ceg.id,
                'title': ceg.title,
                'slug': ceg.slug,
                'status': ceg.status,
                'status_display': ceg.get_status_display(),
                'group_name': ceg.era.group.name,
                'era_name': ceg.era.name,
                'total_sets': ceg.sets.filter(is_active=True).count(),
                'total_slots': ceg_total_slots_cnt,
                'sold_slots': ceg_sold_slots_cnt,
                'available_slots': ceg_avail_slots_cnt,
                'fill_percentage': ceg_fill_pct,
                'completed_pending_sets': ceg_completed_cnt,
                'incomplete_sets': ceg_incomplete_cnt,
                'has_completed_sets': ceg_completed_cnt > 0 or (ceg_sold_slots_cnt == ceg_total_slots_cnt and ceg_total_slots_cnt > 0),
                'has_incomplete_sets': ceg_incomplete_cnt > 0 or ceg_avail_slots_cnt > 0,
                'paid_amount': ceg_paid_val,
                'pending_amount': ceg_pending_val,
                'available_amount': ceg_avail_val,
                'total_potential': ceg_pot_val,
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

        # Ordenações convenientes
        sets_completed_pending.sort(key=lambda x: (x['group_name'], x['era_name'], x['set_number']))
        sets_incomplete.sort(key=lambda x: (x['remaining_slots'], -x['fill_percentage']))
        cegs_overview.sort(key=lambda x: (x['status'] != CEG.Status.OPEN, -x['total_potential']))

        global_occupancy = int((total_reserved_slots_count / total_slots_count) * 100) if total_slots_count > 0 else 0

        return {
            'sets_completed_pending': sets_completed_pending,
            'sets_incomplete': sets_incomplete,
            'cegs_overview': cegs_overview,
            'summary': {
                'total_cegs': cegs_qs.count(),
                'open_cegs': cegs_qs.filter(status=CEG.Status.OPEN).count(),
                'scheduled_cegs': cegs_qs.filter(status=CEG.Status.SCHEDULED).count(),
                'total_sets': total_sets_count,
                'completed_pending_sets_count': len(sets_completed_pending),
                'incomplete_sets_count': len(sets_incomplete),
                'total_slots': total_slots_count,
                'reserved_slots': total_reserved_slots_count,
                'available_slots': total_slots_count - total_reserved_slots_count,
                'global_occupancy': global_occupancy,
            }
        }

    @staticmethod
    def get_sales_analytics(group_id=None, era_id=None, time_window=None, month=None):
        """
        Retorna o relatório analítico completo de vendas, faturamento e BI:
        - time_window: '30d', '90d', '180d', 'year', 'all'
        - month: 'YYYY-MM'
        - monthly_sales: agregação mensal com claims_count (volume) e valores monetários (R$)
        - group_sales: faturamento e volume por grupo
        - top_items: ranking de photocards/itens mais vendidos
        - top_buyers: participantes com maior volume de compras
        """
        claims = Claim.objects.exclude(status=Claim.Status.CANCELLED).select_related(
            'participant', 'slot__set__ceg__era__group', 'slot__item_definition'
        )

        if group_id:
            claims = claims.filter(slot__set__ceg__era__group_id=group_id)
        if era_id:
            claims = claims.filter(slot__set__ceg__era_id=era_id)

        now = timezone.now()
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

        total_paid = float(claims.filter(status=Claim.Status.PAID).aggregate(s=Sum('total_price'))['s'] or 0)
        total_pending = float(claims.filter(status=Claim.Status.PENDING).aggregate(s=Sum('total_price'))['s'] or 0)
        total_sales = total_paid + total_pending
        claims_count = claims.count()
        unique_participants = claims.values('participant_id').distinct().count()
        avg_ticket = float(total_sales / unique_participants) if unique_participants > 0 else 0.0

        # Agregação temporal mês a mês
        monthly_qs = claims.annotate(
            month=TruncMonth('claimed_at')
        ).values('month').annotate(
            total_amount=Sum('total_price'),
            paid_amount=Sum('total_price', filter=Q(status=Claim.Status.PAID)),
            pending_amount=Sum('total_price', filter=Q(status=Claim.Status.PENDING)),
            claims_count=Count('id')
        ).order_by('month')

        monthly_flow = []
        for row in monthly_qs:
            dt = row['month']
            if dt:
                monthly_flow.append({
                    'month_key': dt.strftime('%Y-%m'),
                    'label': f"{MONTH_ABBR.get(dt.month, '')}/{str(dt.year)[2:]}",
                    'full_label': f"{MONTH_FULL.get(dt.month, '')}/{dt.year}",
                    'total_sales': float(row['total_amount'] or 0),
                    'paid_sales': float(row['paid_amount'] or 0),
                    'pending_sales': float(row['pending_amount'] or 0),
                    'claims_count': row['claims_count'],
                })

        if not monthly_flow:
            monthly_flow.append({
                'month_key': now.strftime('%Y-%m'),
                'label': f"{MONTH_ABBR.get(now.month, '')}/{str(now.year)[2:]}",
                'full_label': f"{MONTH_FULL.get(now.month, '')}/{now.year}",
                'total_sales': 0.0,
                'paid_sales': 0.0,
                'pending_sales': 0.0,
                'claims_count': 0,
            })

        # Vendas por Grupo
        group_sales_map = {}
        for c in claims:
            grp = c.slot.set.ceg.era.group.name
            if grp not in group_sales_map:
                group_sales_map[grp] = {'group_name': grp, 'total_sales': 0.0, 'claims_count': 0}
            group_sales_map[grp]['total_sales'] += float(c.total_price)
            group_sales_map[grp]['claims_count'] += 1
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
                    'item_name': name,
                    'member_name': member,
                    'group_name': grp,
                    'count': 0,
                    'total_amount': 0.0
                }
            item_sales_map[key]['count'] += 1
            item_sales_map[key]['total_amount'] += float(c.total_price)
        top_items = sorted(item_sales_map.values(), key=lambda x: (x['count'], x['total_amount']), reverse=True)[:15]

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
        top_buyers = sorted(buyer_map.values(), key=lambda x: (x['total_spent'], x['claims_count']), reverse=True)[:10]

        return {
            'summary': {
                'total_paid': total_paid,
                'total_pending': total_pending,
                'total_sales': total_sales,
                'claims_count': claims_count,
                'unique_participants': unique_participants,
                'avg_ticket': avg_ticket,
            },
            'monthly_flow': monthly_flow,
            'group_sales': group_sales,
            'top_items': top_items,
            'top_buyers': top_buyers,
        }

