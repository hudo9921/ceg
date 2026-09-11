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
