"""
Regras das cobranças Pix (S1). O que está em aberto vem dos mesmos campos de pagamento que a equipe marca à mão
(ItemSlot.is_*_paid, ItemIndividual.*_pago, PacoteNacional.is_frete_pago); confirmar usa os mesmos métodos.
"""
from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Cobranca, CobrancaLinha
from .pix import brcode, normalize_key

ZERO = Decimal('0.00')


class CobrancaError(ValueError):
    """Algo que o joiner ou o GOM precisa resolver (mensagem pronta para a tela)."""


def _unit(tipo, desc, valor, key, group, group_title, **target):
    return {'tipo': tipo, 'descricao': desc[:200], 'valor': Decimal(valor), 'chave': key or '', 'group': group,
            'group_title': group_title, **target}


def _unit_key(u):
    target = (f"slot:{u['slot'].id}" if u.get('slot') else
              f"avulso:{u['item_individual'].id}" if u.get('item_individual') else
              f"vitrine:{u['reserva_vitrine'].id}" if u.get('reserva_vitrine') else f"pacote:{u['pacote'].id}")
    return f"{u['tipo']}:{target}"


STALE_DAYS = 7


def expire_stale(participant, gom):
    """Pix gerado e esquecido (sem "Já paguei") por mais de 7 dias é cancelado: as cobranças voltam a ficar livres."""
    now = timezone.now()
    Cobranca.objects.filter(gom=gom, participant=participant, status=Cobranca.Status.AGUARDANDO,
                            criada_em__lt=now - timedelta(days=STALE_DAYS)).update(
        status=Cobranca.Status.CANCELADA, resolvida_em=now)


def open_units(participant, gom):
    """Tudo o que o joiner deve a este GOM, unidade por unidade, menos o que já está numa cobrança aberta."""
    from apps.cegs.models import ItemIndividual, PacoteNacional
    from apps.participants.models import Claim

    expire_stale(participant, gom)
    units = []
    claims = (Claim.objects.for_gom(gom).filter(participant=participant)
              .exclude(status=Claim.Status.CANCELLED).select_related('slot__item_definition', 'slot__set__ceg'))
    for claim in claims:
        slot, ceg = claim.slot, claim.slot.set.ceg
        name = slot.item_definition.name
        if claim.status == Claim.Status.PENDING and claim.total_price > 0:
            units.append(_unit('item', f'{name} · {ceg.title}', claim.total_price, ceg.get_pix_key_item(),
                               f'item:ceg:{ceg.id}', ceg.title, slot=slot))
        frete, taxa = slot.frete_inter or ZERO, slot.taxa_aduaneira or ZERO
        if frete > 0 and not slot.is_frete_inter_paid:
            units.append(_unit('frete', f'Frete · {name} · {ceg.title}', frete, ceg.get_pix_key_frete(),
                               f'frete:ceg:{ceg.id}', ceg.title, slot=slot))
        if taxa > 0 and not slot.is_taxa_aduaneira_paid:
            units.append(_unit('taxa', f'Taxa · {name} · {ceg.title}', taxa, ceg.get_pix_key_taxa(),
                               f'taxa:ceg:{ceg.id}', ceg.title, slot=slot))

    for item in ItemIndividual.objects.for_gom(gom).filter(comprador=participant).select_related('caixa'):
        caixa = item.caixa
        if not item.produto_pago and (item.preco_produto or ZERO) > 0:
            units.append(_unit('item', f'{item.nome} (avulso)', item.preco_produto, gom.pix_for('item')[0],
                               f'item:avulso:{item.id}', f'{item.nome} (avulso)', item_individual=item))
        if (item.frete_inter or ZERO) > 0 and not item.frete_inter_pago:
            key = caixa.get_pix_key_frete() if caixa else gom.pix_for('frete')[0]
            units.append(_unit('frete', f'Frete · {item.nome}', item.frete_inter, key,
                               f'frete:avulso:{item.id}', item.nome, item_individual=item))
        if (item.taxa_aduaneira or ZERO) > 0 and not item.taxa_aduaneira_paga:
            key = caixa.get_pix_key_taxa() if caixa else gom.pix_for('taxa')[0]
            units.append(_unit('taxa', f'Taxa · {item.nome}', item.taxa_aduaneira, key,
                               f'taxa:avulso:{item.id}', item.nome, item_individual=item))

    for pacote in PacoteNacional.objects.for_gom(gom).filter(participant=participant, is_frete_pago=False,
                                                             valor_frete_nacional__gt=0):
        units.append(_unit('frete_nacional', f'Frete nacional · {pacote.identificador}', pacote.valor_frete_nacional,
                           pacote.pix_key_frete_nacional, f'frete_nacional:pacote:{pacote.id}',
                           f'Pacote {pacote.identificador}', pacote=pacote))

    from apps.conversas.models import ReservaVitrine
    for r in ReservaVitrine.objects.filter(participant=participant, item__gom=gom,
                                           status=ReservaVitrine.Status.RESERVADA).select_related('item'):
        units.append(_unit('item', f'{r.item.titulo} (Vitrine)', r.preco, gom.pix_for('item')[0],
                           f'item:vitrine:{r.id}', f'{r.item.titulo} (Vitrine)', reserva_vitrine=r))

    busy = {line.unit_key for line in CobrancaLinha.objects.filter(
        cobranca__gom=gom, cobranca__participant=participant, cobranca__status__in=Cobranca.OPEN)}
    return [u for u in units if _unit_key(u) not in busy]


def open_groups(participant, gom):
    """As unidades agrupadas como na tela Pagar (por CEG/item/pacote e tipo), na ordem em que aparecem."""
    groups = OrderedDict()
    for u in open_units(participant, gom):
        g = groups.setdefault(u['group'], {'key': u['group'], 'tipo': u['tipo'], 'title': u['group_title'],
                                           'tipo_label': CobrancaLinha.Tipo(u['tipo']).label,
                                           'total': ZERO, 'count': 0, 'units': []})
        g['total'] += u['valor']
        g['count'] += 1
        g['units'].append(u)
    return list(groups.values())


def _check_receiver(gom):
    if not (gom.pix_nome_recebedor or '').strip() or not (gom.pix_cidade or '').strip():
        raise CobrancaError(f'{gom.name} ainda não configurou o Pix com QR code (nome de quem recebe e cidade).')


@transaction.atomic
def create_cobrancas(participant, gom, group_keys, created_by=None):
    """Cria uma cobrança por chave Pix com os grupos escolhidos. Devolve a lista de cobranças."""
    _check_receiver(gom)
    wanted = set(group_keys or [])
    units = [u for u in open_units(participant, gom) if u['group'] in wanted]
    if not units:
        raise CobrancaError('Escolha pelo menos uma cobrança em aberto.')
    by_key = OrderedDict()
    for u in units:
        key, _kind = normalize_key(u['chave'])
        if key is None:
            raise CobrancaError(f'A chave Pix de "{u["group_title"]}" não é válida. Fale com {gom.name}.')
        by_key.setdefault(key, []).append(u)
    created = []
    for key, items in by_key.items():
        total = sum((u['valor'] for u in items), ZERO)
        cob = Cobranca(gom=gom, participant=participant, chave_pix=key, valor_total=total, criada_por=created_by)
        while Cobranca.objects.filter(referencia=cob.referencia).exists():
            cob.referencia = Cobranca._meta.get_field('referencia').default()
        cob.copia_e_cola = brcode(key=key, name=gom.pix_nome_recebedor, city=gom.pix_cidade, amount=total,
                                  reference=cob.referencia)
        cob.save()
        CobrancaLinha.objects.bulk_create([
            CobrancaLinha(cobranca=cob, tipo=u['tipo'], descricao=u['descricao'], valor=u['valor'],
                          slot=u.get('slot'), item_individual=u.get('item_individual'), pacote=u.get('pacote'),
                          reserva_vitrine=u.get('reserva_vitrine'))
            for u in items])
        created.append(cob)
    return created


def informar(cobranca, comprovante=None):
    """Joiner tocou "Já paguei" (com ou sem comprovante)."""
    if cobranca.status not in (Cobranca.Status.AGUARDANDO, Cobranca.Status.RECUSADA):
        raise CobrancaError('Esta cobrança já foi avisada ou resolvida.')
    cobranca.status = Cobranca.Status.INFORMADA
    cobranca.informada_em = timezone.now()
    cobranca.save(update_fields=['status', 'informada_em'])
    if comprovante is not None:
        from .models import Comprovante
        data, content_type = comprovante
        Comprovante.objects.update_or_create(cobranca=cobranca, defaults={'conteudo': data, 'content_type': content_type})
    _notify_gom(cobranca)


def _mark_paid(line, actor):
    if line.slot_id:
        line.slot.toggle_payment({'item': 'item', 'frete': 'frete_inter', 'taxa': 'taxa'}[line.tipo], value=True, actor=actor)
    elif line.item_individual_id:
        item = line.item_individual
        field = {'item': 'produto_pago', 'frete': 'frete_inter_pago', 'taxa': 'taxa_aduaneira_paga'}[line.tipo]
        setattr(item, field, True)
        item.save(update_fields=[field])
    elif line.pacote_id:
        line.pacote.is_frete_pago = True
        line.pacote.save(update_fields=['is_frete_pago'])
    elif line.reserva_vitrine_id and line.reserva_vitrine.status == 'RESERVADA':
        from apps.conversas.reservas import marcar_paga
        marcar_paga(line.reserva_vitrine)


@transaction.atomic
def confirmar(cobranca, actor):
    """GOM tocou "Recebi": tudo o que a cobrança cobre fica pago, com auditoria, e o joiner é avisado."""
    cobranca = Cobranca.objects.select_for_update().get(pk=cobranca.pk)
    if not cobranca.is_open:
        raise CobrancaError('Esta cobrança já foi resolvida.')
    for line in cobranca.linhas.select_related('slot__set__ceg', 'item_individual', 'pacote', 'reserva_vitrine__item__gom'):
        _mark_paid(line, actor)
    cobranca.status = Cobranca.Status.CONFIRMADA
    cobranca.resolvida_em, cobranca.resolvida_por = timezone.now(), actor
    cobranca.save(update_fields=['status', 'resolvida_em', 'resolvida_por'])
    _audit(cobranca, actor, f'Pix {cobranca.referencia} recebido (R$ {cobranca.valor_total})')
    _notify_joiner(cobranca, 'Pagamento confirmado',
                   f'{cobranca.gom.name} confirmou seu Pix {cobranca.referencia} de R$ {cobranca.valor_total}.',
                   categoria='pagamentos')


def recusar(cobranca, actor, recado=''):
    """GOM tocou "Não recebi": a cobrança volta a esperar o pagamento, com o recado para o joiner."""
    if not cobranca.is_open:
        raise CobrancaError('Esta cobrança já foi resolvida.')
    cobranca.status = Cobranca.Status.RECUSADA
    cobranca.recado = (recado or '')[:255]
    cobranca.resolvida_em, cobranca.resolvida_por = timezone.now(), actor
    cobranca.save(update_fields=['status', 'recado', 'resolvida_em', 'resolvida_por'])
    _audit(cobranca, actor, f'Pix {cobranca.referencia} não encontrado pelo GOM')
    _notify_joiner(cobranca, 'Pagamento não encontrado',
                   f'{cobranca.gom.name} não encontrou seu Pix {cobranca.referencia}.' + (f' Recado: {recado}' if recado else ''))


def cancelar(cobranca):
    """Joiner (ou o prazo) desiste da cobrança: as linhas voltam a ficar livres."""
    if cobranca.status not in (Cobranca.Status.AGUARDANDO, Cobranca.Status.RECUSADA):
        raise CobrancaError('Esta cobrança não pode mais ser cancelada.')
    cobranca.status = Cobranca.Status.CANCELADA
    cobranca.resolvida_em = timezone.now()
    cobranca.save(update_fields=['status', 'resolvida_em'])


def _audit(cobranca, actor, label):
    from apps.cegs.models import AuditLog
    p = cobranca.participant
    AuditLog.objects.create(gom=cobranca.gom, event_type=AuditLog.EventType.PAYMENT_ITEM, actor=actor,
                            actor_name=getattr(actor, 'username', '') or '', participant=p,
                            participant_name=p.display_name, participant_phone=p.whatsapp or '', action_label=label,
                            metadata={'cobranca': cobranca.referencia, 'valor': str(cobranca.valor_total)})


def _notify_joiner(cobranca, title, message, categoria='importante'):
    from apps.participants.models import ParticipantNotification
    ParticipantNotification.objects.create(participant=cobranca.participant, title=title, message=message, categoria=categoria,
                                           notification_type=ParticipantNotification.NotificationType.GENERAL)


def _notify_gom(cobranca):
    from apps.cegs.models import GOMNotification
    GOMNotification.objects.create(
        gom=cobranca.gom, notification_type=GOMNotification.NotificationType.PAYMENT,
        participant=cobranca.participant, title=f'Pix avisado: R$ {cobranca.valor_total}',
        message=f'{cobranca.participant.display_name} avisou que pagou o Pix {cobranca.referencia}. Confira e toque em Recebi.')
