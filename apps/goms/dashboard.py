"""
Início do painel do GOM (P5): o que fazer hoje e os números do mês, só com o que a pessoa pode ver
(apps.goms.permissions). Tudo filtrado pelo GOM ativo (for_gom).
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone


def _sum(qs, field):
    return qs.aggregate(v=Sum(field))['v'] or Decimal('0.00')


def brl(value):
    """R$ no formato brasileiro: 1.234,56."""
    return 'R$ ' + f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def ago(when, now):
    """Tempo curto: agora, há 5 min, há 3 h, há 2 d."""
    secs = max(0, int((now - when).total_seconds()))
    if secs < 60:
        return 'agora'
    if secs < 3600:
        return f'há {secs // 60} min'
    if secs < 86400:
        return f'há {secs // 3600} h'
    return f'há {secs // 86400} d'


def _tasks(request, granted, pending, upcoming, now):
    from apps.cegs.models import PacoteNacional

    tasks = []
    if granted & {'pag.confirmar', 'pedidos.ver'}:
        n = pending.count()
        tasks.append({'tag': 'Pagamentos', 'cls': 'ui-danger' if n else 'ui-ok', 'n': n,
                      'what': 'item a pagar' if n == 1 else 'itens a pagar',
                      'hint': (f'{brl(_sum(pending, "total_price"))} em aberto. Confira os comprovantes e marque como pago.'
                               if n else 'Nada em aberto.'),
                      'cta': 'Ver CEGs', 'url': reverse('cegs_status')})
    if 'envios.pacotes' in granted:
        n = PacoteNacional.objects.for_gom(request.active_gom).filter(status=PacoteNacional.Status.SOLICITADO).count()
        tasks.append({'tag': 'Envios', 'cls': 'ui-warn' if n else 'ui-ok', 'n': n,
                      'what': 'pedido de envio' if n == 1 else 'pedidos de envio',
                      'hint': 'Cote o frete nacional e embale.' if n else 'Nenhum pedido esperando.',
                      'cta': 'Ver envios', 'url': reverse('envios_nacionais')})
    if 'ceg.editar' in granted:
        today = [c for c in upcoming if timezone.localtime(c.opens_at).date() == timezone.localtime(now).date()]
        tasks.append({'tag': 'CEGs', 'cls': 'ui-ok', 'n': len(today), 'what': 'abre hoje' if len(today) == 1 else 'abrem hoje',
                      'hint': (f'{today[0].title} abre às {timezone.localtime(today[0].opens_at):%H:%M}.' if today
                               else 'Nenhuma abertura hoje. Que tal criar a próxima CEG?'),
                      'cta': 'Ver CEGs' if today else 'Criar CEG', 'url': reverse('cegs_status' if today else 'creations_hub')})
    return tasks


def build_dashboard(request, granted):
    from apps.cegs.models import AuditLog, CEG
    from apps.participants.models import Claim

    gom = request.active_gom
    now = timezone.now()
    month_start = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    claims = Claim.objects.for_gom(gom)
    pending = claims.filter(status=Claim.Status.PENDING)
    upcoming = list(CEG.objects.for_gom(gom).filter(status=CEG.Status.SCHEDULED, opens_at__gte=now,
                                                     opens_at__lte=now + timedelta(days=14))
                    .select_related('era__group').order_by('opens_at')[:5])

    kpis, activity = [], []
    if 'analytics.ver' in granted:
        month_claims = claims.filter(claimed_at__gte=month_start).exclude(status=Claim.Status.CANCELLED)
        joiners = claims.filter(claimed_at__gte=now - timedelta(days=30)).values('participant').distinct().count()
        kpis = [
            {'label': 'Vendido no mês', 'value': brl(_sum(month_claims, 'total_price')), 'sub': f'{month_claims.count()} photocards'},
            {'label': 'A receber', 'value': brl(_sum(pending, 'total_price')), 'sub': f'{pending.count()} itens a pagar'},
            {'label': 'Joiners ativos', 'value': str(joiners), 'sub': 'nos últimos 30 dias'},
            {'label': 'CEGs abertas', 'value': str(CEG.objects.for_gom(gom).filter(status=CEG.Status.OPEN).count()),
             'sub': f'{len(upcoming)} agendada{"s" if len(upcoming) != 1 else ""} (14 dias)'},
        ]
        activity = [{'text': log.action_label, 'when': ago(log.created_at, now)}
                    for log in AuditLog.objects.for_gom(gom).order_by('-created_at')[:6]]
    return {'tasks': _tasks(request, granted, pending, upcoming, now), 'kpis': kpis,
            'upcoming': upcoming if 'ceg.editar' in granted or 'analytics.ver' in granted else [], 'activity': activity}
