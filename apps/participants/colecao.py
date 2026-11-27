"""
Minha coleção (/me/colecao/): o que já chegou na casa do joiner — itens de CEG e pedidos individuais de pacotes
entregues —, como um fichário por grupo e era. O joiner pode ligar um link público (/colecao/<token>/) para mostrar;
a página pública não mostra preço, telefone nem GOM. Desligar apaga o link (o antigo para de funcionar).
"""
import secrets
from collections import OrderedDict

from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import Claim, Participant
from .session_auth import get_session_participant

ENTREGUE = 'ENTREGUE'


def itens(participant):
    """[{grupo, eras: [{era, cartas: [{nome, membro, img}]}]}] e o total, mais recentes primeiro dentro de cada era."""
    from apps.cegs.models import ItemIndividual

    cartas = []
    claims = (Claim.objects.filter(participant=participant, slot__pacote_nacional__status=ENTREGUE)
              .exclude(status=Claim.Status.CANCELLED)
              .select_related('slot__item_definition', 'slot__set__ceg__era__group'))
    for c in claims:
        d, ceg = c.slot.item_definition, c.slot.set.ceg
        cartas.append({'grupo': ceg.era.group.name, 'grupo_id': ceg.era.group_id, 'era': ceg.era.name,
                       'nome': d.name, 'membro': d.member_name or '', 'img': d.image_url or ceg.display_image_url})
    for i in ItemIndividual.objects.filter(comprador=participant, pacote_nacional__status=ENTREGUE):
        cartas.append({'grupo': 'Pedidos individuais', 'grupo_id': 0, 'era': 'Mercari e lojas', 'nome': i.nome,
                       'membro': '', 'img': i.image_display_url})
    grupos = OrderedDict()
    for c in sorted(cartas, key=lambda c: (c['grupo'].lower(), c['era'].lower(), c['membro'].lower(), c['nome'].lower())):
        g = grupos.setdefault(c['grupo_id'], {'grupo': c['grupo'], 'id': c['grupo_id'], 'eras': OrderedDict(), 'total': 0})
        g['eras'].setdefault(c['era'], []).append(c)
        g['total'] += 1
    lista = [{**g, 'eras': [{'era': e, 'cartas': cs} for e, cs in g['eras'].items()]} for g in grupos.values()]
    return lista, len(cartas)


@never_cache
def pagina(request):
    participant = get_session_participant(request)
    if participant is None:
        return redirect('/me/login/?next=/me/colecao/')
    grupos, total = itens(participant)
    link = request.build_absolute_uri(f'/colecao/{participant.colecao_token}/') if participant.colecao_token else ''
    return render(request, 'participants/colecao.html', {
        'grupos': grupos, 'total': total, 'dono': participant, 'link': link, 'publica': False})


@require_POST
def compartilhar(request):
    participant = get_session_participant(request)
    if participant is None:
        return redirect('/me/login/?next=/me/colecao/')
    participant.colecao_token = secrets.token_urlsafe(12) if request.POST.get('ligar') == '1' else ''
    participant.save(update_fields=['colecao_token'])
    return redirect('minha_colecao')


def publica(request, token):
    if not token or len(token) < 10:
        raise Http404
    participant = Participant.objects.filter(colecao_token=token).first()
    if participant is None:
        raise Http404('Esta coleção não está mais compartilhada.')
    grupos, total = itens(participant)
    return render(request, 'participants/colecao.html', {
        'grupos': grupos, 'total': total, 'dono': participant, 'publica': True})
