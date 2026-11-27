"""
Minha coleção (/me/colecao/): o que já chegou na casa do joiner — itens de CEG e pedidos individuais de pacotes
entregues —, como um fichário: um por grupo ou um só com todos (Participant.colecao_modo, escolha do dono), páginas de 9 bolsos (sem texto; integrante, grupo, era e
origem aparecem ao parar o mouse ou tocar na carta). O joiner pode ligar um link público (/colecao/<token>/) para mostrar;
a página pública não mostra preço, telefone nem GOM. Desligar apaga o link (o antigo para de funcionar).
"""
import re
import secrets
from collections import OrderedDict

from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import Claim, Participant
from .session_auth import get_session_participant

ENTREGUE = 'ENTREGUE'
BOLSOS = 9  # página de fichário 3x3


def origem(ceg):
    """De onde veio a carta, pelo título da CEG sem o nome do grupo e sem o código no fim.
    'LE SSERAFIM — WEVERSE GLOBAL 2.0 (PF-33)' -> 'WEVERSE GLOBAL 2.0'."""
    titulo = re.sub(r'^\s*' + re.escape(ceg.era.group.name) + r'\s*[—–:|·-]\s*', '', ceg.title, flags=re.I)
    titulo = re.sub(r'\s*\([A-Za-z]{1,5}-?\d+\)\s*$', '', titulo).strip()
    return titulo or ceg.title


def paginas(cartas):
    """Divide as cartas em páginas de 9 bolsos; a última é completada com bolsos vazios (None)."""
    return [cartas[i:i + BOLSOS] + [None] * (BOLSOS - len(cartas[i:i + BOLSOS])) for i in range(0, len(cartas), BOLSOS)]


def itens(participant):
    """[{grupo, id, total, paginas: [[carta|None x9]]}] e o total. Carta: {nome, membro, grupo, era, origem, img};
    dentro do grupo, ordem por era e integrante."""
    from apps.cegs.models import ItemIndividual

    cartas = []
    claims = (Claim.objects.filter(participant=participant, slot__pacote_nacional__status=ENTREGUE)
              .exclude(status=Claim.Status.CANCELLED)
              .select_related('slot__item_definition', 'slot__set__ceg__era__group'))
    for c in claims:
        d, ceg = c.slot.item_definition, c.slot.set.ceg
        cartas.append({'grupo': ceg.era.group.name, 'grupo_id': ceg.era.group_id, 'era': ceg.era.name,
                       'nome': d.name, 'membro': d.member_name or '', 'origem': origem(ceg),
                       'img': d.image_url or ceg.display_image_url})
    for i in ItemIndividual.objects.filter(comprador=participant, pacote_nacional__status=ENTREGUE):
        cartas.append({'grupo': 'Pedidos individuais', 'grupo_id': 0, 'era': 'Mercari e lojas', 'nome': i.nome,
                       'membro': '', 'origem': 'Pedido individual', 'img': i.image_display_url})
    grupos = OrderedDict()
    for c in sorted(cartas, key=lambda c: (c['grupo'].lower(), c['era'].lower(), c['membro'].lower(), c['nome'].lower())):
        grupos.setdefault(c['grupo_id'], {'grupo': c['grupo'], 'id': c['grupo_id'], 'cartas': []})['cartas'].append(c)
    lista = [{'grupo': g['grupo'], 'id': g['id'], 'total': len(g['cartas']),
              'paginas': [{'cartas': cs, 'rotulo': ''} for cs in paginas(g['cartas'])]} for g in grupos.values()]
    return lista, len(cartas)


def fichario_unico(grupos):
    """Um fichário só: cada grupo começa numa página nova, com o nome do grupo na aba da primeira página.
    Devolve as páginas e, por grupo, o índice da primeira página (para os chips pularem até ele)."""
    todas, inicio = [], {}
    for g in grupos:
        inicio[g['id']] = len(todas)
        todas += [{'cartas': p['cartas'], 'rotulo': g['grupo'] if i == 0 else ''} for i, p in enumerate(g['paginas'])]
    return todas, inicio


def contexto(participant, publica):
    grupos, total = itens(participant)
    ctx = {'grupos': grupos, 'total': total, 'dono': participant, 'publica': publica,
           'modo': participant.colecao_modo or 'grupos'}
    if ctx['modo'] == 'unico':
        ctx['paginas_unico'], inicio = fichario_unico(grupos)
        for g in grupos:
            g['inicio'] = inicio[g['id']]
            g['fim'] = g['inicio'] + len(g['paginas']) - 1
    return ctx


@never_cache
def pagina(request):
    participant = get_session_participant(request)
    if participant is None:
        return redirect('/me/login/?next=/me/colecao/')
    ctx = contexto(participant, publica=False)
    ctx['link'] = request.build_absolute_uri(f'/colecao/{participant.colecao_token}/') if participant.colecao_token else ''
    ctx['modos'] = Participant.COLECAO_MODOS
    return render(request, 'participants/colecao.html', ctx)


@require_POST
def compartilhar(request):
    participant = get_session_participant(request)
    if participant is None:
        return redirect('/me/login/?next=/me/colecao/')
    participant.colecao_token = secrets.token_urlsafe(12) if request.POST.get('ligar') == '1' else ''
    participant.save(update_fields=['colecao_token'])
    return redirect('minha_colecao')


@require_POST
def escolher_modo(request):
    """Um fichário por grupo ou um fichário só; vale para o dono e para o link compartilhado."""
    participant = get_session_participant(request)
    if participant is None:
        return redirect('/me/login/?next=/me/colecao/')
    modo = request.POST.get('modo')
    if modo in dict(Participant.COLECAO_MODOS):
        participant.colecao_modo = modo
        participant.save(update_fields=['colecao_modo'])
    return redirect('minha_colecao')


def publica(request, token):
    if not token or len(token) < 10:
        raise Http404
    participant = Participant.objects.filter(colecao_token=token).first()
    if participant is None:
        raise Http404('Esta coleção não está mais compartilhada.')
    return render(request, 'participants/colecao.html', contexto(participant, publica=True))
