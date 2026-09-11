from django.db.models import Count, Sum, Q, F
from django.utils import timezone
from apps.cegs.models import CEG, CEGSet, ItemSlot, CEGItemDefinition
from apps.groups.models import Era
from apps.participants.models import Claim, Participant


class AnalyticsService:
    @staticmethod
    def get_summary_metrics():
        """Métricas gerais do sistema"""
        total_cegs = CEG.objects.count()
        active_cegs = CEG.objects.filter(status__in=[CEG.Status.OPEN, CEG.Status.SCHEDULED]).count()
        total_participants = Participant.objects.count()

        total_paid = Claim.objects.filter(status=Claim.Status.PAID).aggregate(
            total=Sum('total_price')
        )['total'] or 0

        total_pending = Claim.objects.filter(status=Claim.Status.PENDING).aggregate(
            total=Sum('total_price')
        )['total'] or 0

        total_claims_count = Claim.objects.exclude(status=Claim.Status.CANCELLED).count()

        return {
            'total_cegs': total_cegs,
            'active_cegs': active_cegs,
            'total_participants': total_participants,
            'total_paid': float(total_paid),
            'total_pending': float(total_pending),
            'total_revenue_potential': float(total_paid + total_pending),
            'total_claims_count': total_claims_count,
        }

    @staticmethod
    def get_member_popularity():
        """
        Calcula quais integrantes esgotam mais e mais rápido.
        """
        # Itens que têm member_name definido e já foram reservados
        member_stats = ItemSlot.objects.filter(
            item_definition__member_name__isnull=False
        ).exclude(
            item_definition__member_name=''
        ).values(
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
    def get_era_financials():
        """Faturamento consolidado por Era/Comeback"""
        eras = Era.objects.all().select_related('group')
        era_data = []

        for era in eras:
            paid_sum = Claim.objects.filter(
                slot__set__ceg__era=era,
                status=Claim.Status.PAID
            ).aggregate(s=Sum('total_price'))['s'] or 0

            pending_sum = Claim.objects.filter(
                slot__set__ceg__era=era,
                status=Claim.Status.PENDING
            ).aggregate(s=Sum('total_price'))['s'] or 0

            claims_count = Claim.objects.filter(
                slot__set__ceg__era=era
            ).exclude(status=Claim.Status.CANCELLED).count()

            if paid_sum > 0 or pending_sum > 0 or claims_count > 0:
                era_data.append({
                    'era_name': era.name,
                    'group_name': era.group.name,
                    'paid_amount': float(paid_sum),
                    'pending_amount': float(pending_sum),
                    'total_amount': float(paid_sum + pending_sum),
                    'claims_count': claims_count,
                })

        return sorted(era_data, key=lambda x: x['total_amount'], reverse=True)

    @staticmethod
    def get_sets_near_completion():
        """
        Retorna sets ativos ordenados pela taxa de fechamento
        para ajudar o organizador a identificar quais fechar com o fornecedor.
        """
        active_sets = CEGSet.objects.filter(
            is_active=True,
            ceg__status__in=[CEG.Status.OPEN, CEG.Status.SCHEDULED]
        ).select_related('ceg', 'ceg__era', 'ceg__era__group')

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

        # Ordena dos mais cheios para os menos cheios
        return sorted(sets_info, key=lambda x: x['fill_percentage'], reverse=True)
