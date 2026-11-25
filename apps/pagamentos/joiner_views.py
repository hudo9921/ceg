"""Joiner: gerar o Pix do que escolheu, rever o Pix, avisar "Já paguei" (comprovante opcional) e cancelar."""
import io
import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from apps.goms.models import Gom
from apps.participants.session_auth import get_session_participant

from . import services
from .models import Cobranca
from .pix import KEY_LABELS, normalize_key, qr_svg

MAX_PDF = 2 * 1024 * 1024
MAX_UPLOAD = 8 * 1024 * 1024


def _login_required(view):
    def _wrapped(request, *args, **kwargs):
        participant = get_session_participant(request)
        if participant is None:
            return JsonResponse({'success': False, 'requires_auth': True, 'redirect_url': '/me/login/?next=/me/%3Ftab%3Dpagar',
                                 'message': 'Entre na sua conta para pagar.'}, status=401)
        request.participant = participant
        return view(request, *args, **kwargs)
    _wrapped.__name__ = view.__name__
    return _wrapped


def cobranca_payload(cob):
    """O que a folha do Pix precisa: QR em SVG, copia e cola, valor, referência e as linhas."""
    _key, kind = normalize_key(cob.chave_pix)
    return {
        'ref': cob.referencia, 'total': f'{cob.valor_total:.2f}', 'status': cob.status,
        'status_label': cob.get_status_display(), 'gom': cob.gom.name,
        'key': cob.chave_pix, 'key_label': KEY_LABELS.get(kind, 'chave'), 'code': cob.copia_e_cola,
        'qr': qr_svg(cob.copia_e_cola), 'recado': cob.recado,
        'lines': [{'desc': ln.descricao, 'value': f'{ln.valor:.2f}'} for ln in cob.linhas.all()],
    }


@require_POST
@_login_required
def gerar(request):
    try:
        body = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({'success': False, 'message': 'Pedido inválido.'}, status=400)
    gom = get_object_or_404(Gom, pk=body.get('gom_id'), is_active=True)
    try:
        cobrancas = services.create_cobrancas(request.participant, gom, body.get('groups') or [])
    except services.CobrancaError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    return JsonResponse({'success': True, 'cobrancas': [cobranca_payload(c) for c in cobrancas]})


def _own(request, ref):
    return get_object_or_404(Cobranca.objects.select_related('gom'), referencia=ref, participant=request.participant)


@require_GET
@_login_required
def ver(request, ref):
    return JsonResponse({'success': True, 'cobrancas': [cobranca_payload(_own(request, ref))]})


def read_comprovante(upload):
    """(bytes, content_type) do comprovante: imagem vira JPEG até 1600 px; PDF até 2 MB. Levanta CobrancaError."""
    if upload is None:
        return None
    if upload.size > MAX_UPLOAD:
        raise services.CobrancaError('Comprovante grande demais (máx. 8 MB para imagem, 2 MB para PDF).')
    head = upload.read(5)
    upload.seek(0)
    if head.startswith(b'%PDF'):
        if upload.size > MAX_PDF:
            raise services.CobrancaError('PDF grande demais (máx. 2 MB). Mande um print da tela.')
        return upload.read(), 'application/pdf'
    from PIL import Image, UnidentifiedImageError
    try:
        img = Image.open(upload)
        img.thumbnail((1600, 1600))
        out = io.BytesIO()
        img.convert('RGB').save(out, format='JPEG', quality=72, optimize=True)
    except (UnidentifiedImageError, OSError):
        raise services.CobrancaError('O comprovante precisa ser uma imagem (print) ou um PDF.')
    return out.getvalue(), 'image/jpeg'


@require_POST
@_login_required
def paguei(request, ref):
    cob = _own(request, ref)
    try:
        services.informar(cob, read_comprovante(request.FILES.get('comprovante')))
    except services.CobrancaError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    return JsonResponse({'success': True, 'message': f'Avisamos {cob.gom.name}. Assim que conferirem, aparece como pago.'})


@require_POST
@_login_required
def cancelar(request, ref):
    try:
        services.cancelar(_own(request, ref))
    except services.CobrancaError as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=400)
    return JsonResponse({'success': True})
