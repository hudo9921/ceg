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
    avisados = 0
    if 'pag.confirmar' in granted:
        from apps.pagamentos.models import Cobranca
        avisados = Cobranca.objects.for_gom(request.active_gom).filter(status=Cobranca.Status.INFORMADA).count()
    if avisados:
        tasks.append({'tag': 'Pagamentos', 'cls': 'ui-danger', 'n': avisados,
                      'what': 'Pix para confirmar',
                      'hint': 'Joiners avisaram que pagaram. Confira no banco e toque em Recebi.',
                      'cta': 'Ver pagamentos', 'url': reverse('pix_fila')})
    elif granted & {'pag.confirmar', 'pedidos.ver'}:
        n = pending.count()
        tasks.append({'tag': 'Pagamentos', 'cls': 'ui-danger' if n else 'ui-ok', 'n': n,
                      'what': 'item a pagar' if n == 1 else 'itens a pagar',
                      'hint': (f'{brl(_sum(pending, "total_price"))} em aberto. Confira os comprovantes e marque como pago.'
                               if n else 'Nada em aberto.'),
                      'cta': 'Ver CEGs', 'url': reverse('cegs_status')})
    if 'pedidos.editar' in granted:  # só aparece quando há repasse esperando
        from apps.repasses.models import Repasse
        n = Repasse.objects.for_gom(request.active_gom).filter(status=Repasse.Status.AGUARDANDO_GOM).count()
        if n:
            tasks.append({'tag': 'Repasses', 'cls': 'ui-warn', 'n': n,
                          'what': 'repasse para aprovar' if n == 1 else 'repasses para aprovar',
                          'hint': 'Joiners passando a vaga para outra pessoa; quem recebe já aceitou.',
                          'cta': 'Ver repasses', 'url': reverse('gom_repasses')})
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


def _links(log, granted):
    """Para onde o GOM vai a partir de um evento: o painel do joiner (com permissão) e a página da CEG."""
    links = {'url': '', 'ceg_url': '', 'ceg_title': ''}
    if log.participant_id and 'pedidos.ver' in granted:
        links['url'] = f"{reverse('consulta_joiner')}?participant_id={log.participant_id}"
    elif log.pacote_nacional_id and 'envios.pacotes' in granted:
        links['url'] = reverse('envios_nacionais')
    if log.ceg_id and log.ceg:
        ceg_url = reverse('ceg_detail', kwargs={'slug': log.ceg.slug})
        if links['url']:
            links.update(ceg_url=ceg_url, ceg_title=log.ceg.title)
        else:
            links['url'] = ceg_url
    return links


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
        logs = AuditLog.objects.for_gom(gom).select_related('ceg').order_by('-created_at')[:6]
        activity = [{'text': log.action_label, 'when': ago(log.created_at, now), **_links(log, granted)} for log in logs]
    return {'tasks': _tasks(request, granted, pending, upcoming, now), 'kpis': kpis,
            'upcoming': upcoming if 'ceg.editar' in granted or 'analytics.ver' in granted else [], 'activity': activity}
