"""
Conferência de chegada da caixa: quando a caixa chega, a equipe marca quantas unidades de cada item da CEG chegaram
(e quais pedidos individuais chegaram). O que faltou mostra quem tem aquele item, para a GOM decidir o que fazer.
Nada é avisado nem mudado sozinho (docs/BUSINESS_RULES.md, "Conferência de chegada").
"""
from collections import defaultdict

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.core.permissions import staff_required

from .models import Caixa, CEGItemDefinition, ConferenciaChegada, ItemIndividual, ItemSlot

PERM = 'caixas.editar'


def _situacao(esperado, chegou, conferido):
    if not conferido:
        return 'pendente'
    return 'ok' if chegou >= esperado else 'faltou'


def montar(caixa):
    """{'cegs': [{ceg, linhas}], 'individuais': [linha], 'resumo': {...}} com o que se espera e o que foi marcado."""
    marcados = {(c.item_definition_id, c.item_individual_id): c.chegou
                for c in ConferenciaChegada.objects.filter(caixa=caixa)}
    slots = (ItemSlot.objects.filter(set__ceg__caixa=caixa, set__is_active=True)
             .exclude(status=ItemSlot.Status.CANCELLED)
             .select_related('item_definition', 'set__ceg', 'claimed_by'))
    por_def = defaultdict(list)
    for s in slots:
        por_def[s.item_definition_id].append(s)
    defs = {d.id: d for d in CEGItemDefinition.objects.filter(id__in=por_def).select_related('ceg')}

    cegs = {}
    for def_id, lista in sorted(por_def.items(), key=lambda kv: (defs[kv[0]].ceg.title, defs[kv[0]].name)):
        d = defs[def_id]
        esperado = len(lista)
        conferido = (def_id, None) in marcados
        chegou = marcados.get((def_id, None), 0)
        donos = sorted({s.claimed_by.display_name for s in lista if s.claimed_by_id})
        bloco = cegs.setdefault(d.ceg_id, {'ceg': d.ceg, 'linhas': []})
        bloco['linhas'].append({'tipo': 'item', 'id': def_id, 'nome': d.name, 'membro': d.member_name or '',
                                'img': d.image_url or d.ceg.display_image_url, 'esperado': esperado, 'chegou': chegou,
                                'conferido': conferido, 'situacao': _situacao(esperado, chegou, conferido),
                                'donos': donos})

    individuais = []
    for i in ItemIndividual.objects.filter(caixa=caixa).select_related('comprador').order_by('nome'):
        conferido = (None, i.id) in marcados
        chegou = marcados.get((None, i.id), 0)
        individuais.append({'tipo': 'individual', 'id': i.id, 'nome': i.nome, 'membro': '', 'img': i.image_display_url,
                            'esperado': 1, 'chegou': chegou, 'conferido': conferido,
                            'situacao': _situacao(1, chegou, conferido),
                            'donos': [i.comprador.display_name] if i.comprador_id else []})

    linhas = [l for b in cegs.values() for l in b['linhas']] + individuais
    faltando = [l for l in linhas if l['situacao'] == 'faltou']
    resumo = {
        'total': len(linhas),
        'conferidos': sum(l['conferido'] for l in linhas),
        'faltando_itens': len(faltando),
        'faltando_unidades': sum(l['esperado'] - l['chegou'] for l in faltando),
        'afetados': sorted({n for l in faltando for n in l['donos']}),
    }
    return {'cegs': list(cegs.values()), 'individuais': individuais, 'resumo': resumo}


def _caixa(request, slug):
    return get_object_or_404(Caixa.objects.for_gom(request.active_gom), slug=slug)


@staff_required(PERM)
def pagina(request, slug):
    caixa = _caixa(request, slug)
    return render(request, 'cegs/caixa_conferencia.html', {'caixa': caixa, **montar(caixa)})


def _gravar(request, caixa, tipo, alvo_id, chegou):
    if tipo == 'item':
        alvo = get_object_or_404(CEGItemDefinition.objects.filter(ceg__caixa=caixa), pk=alvo_id)
        maximo = ItemSlot.objects.filter(item_definition=alvo, set__is_active=True).exclude(
            status=ItemSlot.Status.CANCELLED).count()
        chave = {'item_definition': alvo}
    else:
        alvo = get_object_or_404(ItemIndividual.objects.filter(caixa=caixa), pk=alvo_id)
        maximo, chave = 1, {'item_individual': alvo}
    ConferenciaChegada.objects.update_or_create(
        caixa=caixa, **chave,
        defaults={'gom': caixa.gom, 'chegou': max(0, min(int(chegou), maximo)), 'atualizado_por': request.user})


@staff_required(PERM)
@require_POST
def marcar(request, slug):
    """{tipo: item|individual, id, chegou} — ou {ceg_id} para "chegou tudo" de uma CEG — ou {desfazer: tipo, id}."""
    import json
    caixa = _caixa(request, slug)
    try:
        body = json.loads(request.body or '{}')
        with transaction.atomic():
            if body.get('ceg_id'):
                for linha in next((b['linhas'] for b in montar(caixa)['cegs'] if b['ceg'].id == int(body['ceg_id'])), []):
                    _gravar(request, caixa, 'item', linha['id'], linha['esperado'])
            elif body.get('desfazer'):
                campo = 'item_definition_id' if body['desfazer'] == 'item' else 'item_individual_id'
                ConferenciaChegada.objects.filter(caixa=caixa, **{campo: int(body['id'])}).delete()
            else:
                _gravar(request, caixa, 'item' if body.get('tipo') == 'item' else 'individual', int(body['id']),
                        int(body.get('chegou', 0)))
    except (ValueError, TypeError, KeyError):
        return JsonResponse({'success': False, 'message': 'Pedido inválido.'}, status=400)
    dados = montar(caixa)
    linhas = {f"{l['tipo']}:{l['id']}": {k: l[k] for k in ('chegou', 'conferido', 'situacao')}
              for b in dados['cegs'] for l in b['linhas']}
    linhas.update({f"individual:{l['id']}": {k: l[k] for k in ('chegou', 'conferido', 'situacao')}
                   for l in dados['individuais']})
    return JsonResponse({'success': True, 'linhas': linhas, 'resumo': dados['resumo']})
