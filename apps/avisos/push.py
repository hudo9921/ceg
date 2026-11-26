"""
Envio de push (Web Push + VAPID, sem serviço pago). Roda numa thread depois do commit para não atrasar quem clicou
(ex.: o GOM confirmando um Pix). Inscrição que o navegador diz que não existe mais (404/410) é apagada; depois de 5
falhas seguidas também.

O que vai por push:
- joiner: toda ParticipantNotification (pagamento confirmado, set cancelado, pacote enviado, repasse, resposta do GOM…);
- equipe do GOM: GOMNotification dos tipos em TIPOS_GOM (Pix avisado, pedido de envio, repasse, mensagem/sistema).
  Reserva de vaga e voto em enquete ficam só na central do site (seriam centenas no segundo zero).
Nunca há push de "CEG nova" para quem segue (decisão: seria spam).
"""
import json
import logging
import queue
import threading

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Inscricao

logger = logging.getLogger(__name__)

TIPOS_GOM = {'PAYMENT', 'PACKAGE_REQUEST', 'REPASSE', 'SYSTEM'}
MAX_FALHAS = 5


def _vapid():
    from py_vapid import Vapid

    from .vapid import chave_privada_pem
    return Vapid.from_pem(chave_privada_pem().encode())


def _assunto():
    return getattr(settings, 'VAPID_SUBJECT', '') or 'https://valcegs.duckdns.org'


def _enviar_agora(ids, payload):
    from pywebpush import WebPushException, webpush

    vapid = _vapid()
    for insc in Inscricao.objects.filter(id__in=ids):
        try:
            webpush(insc.como_webpush(), json.dumps(payload), vapid_private_key=vapid,
                    vapid_claims={'sub': _assunto()}, timeout=8, ttl=60 * 60 * 24)
            Inscricao.objects.filter(pk=insc.pk).update(ultimo_envio=timezone.now(), falhas=0)
        except WebPushException as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status in (404, 410) or insc.falhas + 1 >= MAX_FALHAS:
                insc.delete()  # o navegador cancelou ou trocou a inscrição
            else:
                Inscricao.objects.filter(pk=insc.pk).update(falhas=insc.falhas + 1)
            logger.info('Push não entregue (%s): %s', status, exc)
        except Exception:
            logger.exception('Falha inesperada no push')


def enviar(inscricoes, titulo, corpo='', url='/', tag=''):
    """Agenda o envio para as inscrições (queryset ou lista) depois do commit. Devolve quantas."""
    ids = [i.pk for i in inscricoes]
    if not ids:
        return 0
    payload = {'title': titulo[:120], 'body': (corpo or '')[:240], 'url': url or '/', 'tag': tag}
    if getattr(settings, 'PUSH_SINCRONO', False):  # testes
        transaction.on_commit(lambda: _enviar_agora(ids, payload))
    else:
        transaction.on_commit(lambda: _fila().put((ids, payload)))
    return len(ids)


_FILA = None
_TRAVA = threading.Lock()


def _fila():
    """Uma fila e uma thread por processo: uma caixa com 200 joiners não abre 200 threads."""
    global _FILA
    with _TRAVA:
        if _FILA is None:
            _FILA = queue.Queue()
            threading.Thread(target=_trabalhar, args=(_FILA,), daemon=True, name='push').start()
    return _FILA


def _trabalhar(fila):
    from django.db import close_old_connections
    while True:
        ids, payload = fila.get()
        try:
            _enviar_agora(ids, payload)
        except Exception:
            logger.exception('Falha no envio de push')
        finally:
            close_old_connections()


def para_joiner(participant, titulo, corpo='', url='/me/', tag='', categoria=''):
    """Push para os aparelhos do joiner, se ele não desligou esta categoria ('importante' sempre vai)."""
    from .preferencias import IMPORTANTE, desligados
    if categoria and categoria != IMPORTANTE and categoria in desligados(participant=participant):
        return 0
    return enviar(Inscricao.objects.filter(participant=participant), titulo, corpo, url, tag)


def para_gom(gom, titulo, corpo='', url='', tag='', categoria=''):
    """Para quem é da equipe deste GOM, tem a permissão da área do aviso e não desligou a categoria."""
    from apps.goms.models import GomMembership
    from apps.goms.permissions import membership_permissions

    from .models import Preferencia
    from .preferencias import PERMISSAO_GOM

    perm = PERMISSAO_GOM.get(categoria)
    users = [m.user_id for m in GomMembership.objects.filter(gom=gom, is_active=True)
             if not perm or perm in membership_permissions(m)]
    if categoria:  # equipe é pequena: confere em Python (JSON __contains não existe no SQLite)
        sem = {p.user_id for p in Preferencia.objects.filter(user_id__in=users) if categoria in p.desligados}
        users = [u for u in users if u not in sem]
    return enviar(Inscricao.objects.filter(user_id__in=users), titulo, corpo, url or '/notificacoes/', tag)
