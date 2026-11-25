"""
Equipe do GOM: fila de Pagamentos (Recebi / Não recebi), comprovante e "Cobrar no WhatsApp" para joiners que ainda
não usam o site (gera o Pix em nome do joiner e abre o WhatsApp do próprio GOM com a mensagem pronta).
"""
from urllib.parse import quote

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.core.permissions import staff_required
from apps.participants.models import Participant

from . import services
from .models import Cobranca
from .pix import qr_svg

PERM = 'pag.confirmar'
ORDER = {Cobranca.Status.INFORMADA: 0, Cobranca.Status.AGUARDANDO: 1, Cobranca.Status.RECUSADA: 2}


def _queue(gom, tab):
    qs = Cobranca.objects.for_gom(gom).select_related('participant')
    if tab == 'recebidos':
        return list(qs.filter(status=Cobranca.Status.CONFIRMADA).order_by('-resolvida_em')[:60])
    items = list(qs.filter(status__in=Cobranca.OPEN).prefetch_related('linhas'))
    return sorted(items, key=lambda c: (ORDER[c.status], -(c.informada_em or c.criada_em).timestamp()))


@never_cache
@staff_required(PERM)
@require_http_methods(['GET', 'POST'])
def fila(request):
    gom = request.active_gom
    if request.method == 'POST':
        cob = get_object_or_404(Cobranca.objects.for_gom(gom), referencia=request.POST.get('ref', ''))
        try:
            if request.POST.get('action') == 'recebi':
                services.confirmar(cob, request.user)
                messages.success(request, f'Pix {cob.referencia} confirmado. {cob.participant.display_name} foi avisado(a).')
            else:
                services.recusar(cob, request.user, request.POST.get('recado', ''))
                messages.success(request, f'Pix {cob.referencia} marcado como não recebido.')
        except services.CobrancaError as exc:
            messages.error(request, str(exc))
        return redirect('pix_fila')
    tab = 'recebidos' if request.GET.get('tab') == 'recebidos' else 'confirmar'
    items = _queue(gom, tab)
    cur = next((c for c in items if c.referencia == request.GET.get('ref')), items[0] if items else None)
    return render(request, 'pagamentos/fila.html', {
        'tab': tab, 'items': items, 'cur': cur,
        'informadas': sum(1 for c in items if c.status == Cobranca.Status.INFORMADA) if tab == 'confirmar' else 0,
    })


@never_cache
@staff_required(PERM)
def comprovante(request, ref):
    cob = get_object_or_404(Cobranca.objects.for_gom(request.active_gom), referencia=ref)
    proof = getattr(cob, 'comprovante', None)
    if proof is None:
        raise Http404
    response = HttpResponse(bytes(proof.conteudo), content_type=proof.content_type)
    response['Content-Disposition'] = f'inline; filename="comprovante-{cob.referencia}"'
    response['Cache-Control'] = 'private, no-store'
    return response


def whatsapp_link(cob, request):
    """Link wa.me do WhatsApp do joiner com a cobrança pronta (enviado pelo WhatsApp do próprio GOM, sem bot)."""
    p = cob.participant
    linhas = '\n'.join(f'• {ln.descricao}: R$ {ln.valor:.2f}' for ln in cob.linhas.all())
    site = request.build_absolute_uri('/me/?tab=pagar')
    text = (f'Oi, {p.display_name}! Aqui é {cob.gom.name}. Você tem R$ {cob.valor_total:.2f} em aberto:\n{linhas}\n\n'
            f'Pix copia e cola (valor exato):\n{cob.copia_e_cola}\n\nReferência: {cob.referencia}. '
            f'Depois de pagar, me avisa por aqui ou toque em "Já paguei" no site: {site}')
    phone = ''.join(ch for ch in (p.whatsapp or '') if ch.isdigit())
    return f'https://wa.me/{phone}?text={quote(text)}' if phone else ''


@never_cache
@staff_required(PERM)
@require_http_methods(['GET', 'POST'])
def cobrar(request, participant_id):
    """Cobrar um joiner (no site ou não): escolher o que cobrar, gerar o Pix e mandar pelo WhatsApp do GOM."""
    gom = request.active_gom
    participant = get_object_or_404(Participant.objects.for_gom(gom), pk=participant_id)
    if request.method == 'POST':
        try:
            services.create_cobrancas(participant, gom, request.POST.getlist('groups'), created_by=request.user)
            messages.success(request, 'Pix gerado. Mande pelo WhatsApp e toque em Recebi quando cair.')
        except services.CobrancaError as exc:
            messages.error(request, str(exc))
        return redirect('pix_cobrar', participant_id=participant.id)
    abertas = list(Cobranca.objects.for_gom(gom).filter(participant=participant, status__in=Cobranca.OPEN)
                   .prefetch_related('linhas'))
    for cob in abertas:
        cob.whatsapp_url = whatsapp_link(cob, request)
        cob.qr = qr_svg(cob.copia_e_cola)
    ready = bool(gom.pix_nome_recebedor and gom.pix_cidade)
    return render(request, 'pagamentos/cobrar.html', {
        'joiner': participant, 'groups': services.open_groups(participant, gom) if ready else [],
        'abertas': abertas, 'pix_ready': ready,
    })
