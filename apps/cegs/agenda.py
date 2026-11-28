"""
Agenda de aberturas (/agenda/, pública): CEGs agendadas de todos os GOMs ativos, por dia, com contagem para o
Segundo Zero. Quem segue grupos/integrantes vê as dela destacadas e pode filtrar "Só quem eu sigo".
/agenda/<slug>.ics: o evento da abertura para o calendário do celular (lembrete 15 min antes). Nada é enviado.
"""
from collections import OrderedDict
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from apps.participants.seguindo import marcar, preferencias
from apps.participants.session_auth import get_session_participant

from .models import CEG

DIAS = 60


def _agendadas():
    now = timezone.now()
    return (CEG.objects.filter(status=CEG.Status.SCHEDULED, opens_at__gt=now, opens_at__lte=now + timedelta(days=DIAS),
                               gom__is_active=True)
            .select_related('era__group', 'gom').prefetch_related('item_definitions').order_by('opens_at'))


def agenda(request):
    cegs = list(_agendadas())
    prefs = preferencias(get_session_participant(request))
    marcar(cegs, prefs)
    so_sigo = bool(prefs) and request.GET.get('seguindo') == '1'
    if so_sigo:
        cegs = [c for c in cegs if c.para_voce]
    hoje = timezone.localdate()
    dias = OrderedDict()
    for c in cegs:
        dia = timezone.localtime(c.opens_at).date()
        dias.setdefault(dia, []).append(c)
    return render(request, 'cegs/agenda.html', {
        'dias': [{'data': d, 'hoje': d == hoje, 'amanha': d == hoje + timedelta(days=1), 'cegs': lista}
                 for d, lista in dias.items()],
        'tem_prefs': bool(prefs), 'so_sigo': so_sigo, 'nav_agenda': True, 'total': len(cegs),
    })


def _ics_texto(valor):
    return str(valor).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def agenda_ics(request, slug):
    ceg = get_object_or_404(CEG.objects.select_related('gom', 'era__group'), slug=slug, gom__is_active=True)
    if ceg.status != CEG.Status.SCHEDULED or not ceg.opens_at:
        raise Http404('Esta CEG não está agendada.')
    inicio = ceg.opens_at.astimezone(dt_timezone.utc)
    url = request.build_absolute_uri(reverse('ceg_detail', args=[ceg.slug]))
    fmt = '%Y%m%dT%H%M%SZ'
    linhas = [
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//CegManager//Agenda//PT', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        f'UID:ceg-{ceg.id}-{int(inicio.timestamp())}@cegmanager',
        f'DTSTAMP:{timezone.now().astimezone(dt_timezone.utc).strftime(fmt)}',
        f'DTSTART:{inicio.strftime(fmt)}',
        f'DTEND:{(inicio + timedelta(minutes=30)).strftime(fmt)}',
        f'SUMMARY:{_ics_texto("Abre: " + ceg.title)}',
        f'DESCRIPTION:{_ics_texto(f"CEG de {ceg.gom.name}. Entre antes para estar pronto(a) no Segundo Zero: {url}")}',
        f'URL:{url}',
        'BEGIN:VALARM', 'ACTION:DISPLAY', 'TRIGGER:-PT15M', f'DESCRIPTION:{_ics_texto("Em 15 min abre " + ceg.title)}', 'END:VALARM',
        'END:VEVENT', 'END:VCALENDAR',
    ]
    resposta = HttpResponse('\r\n'.join(linhas) + '\r\n', content_type='text/calendar; charset=utf-8')
    resposta['Content-Disposition'] = f'attachment; filename="abertura-{ceg.slug[:60]}.ics"'
    return resposta
