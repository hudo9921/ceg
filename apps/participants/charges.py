"""
Seção "Pagar" do painel do joiner: todas as cobranças em aberto numa lista, agrupadas por GOM.

Só reorganiza o que o MyClaimsView já calcula (nenhuma regra de pagamento nova). Cada cobrança
leva a chave Pix certa pela hierarquia de docs/BUSINESS_RULES.md §1 (CEG/caixa/GOM).
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

KIND_LABELS = {
    'item': 'Item',
    'frete': 'Frete internacional',
    'taxa': 'Taxa aduaneira',
    'frete_nacional': 'Frete nacional',
}
# Ordem de exibição: mais urgente primeiro; sem prazo por último.
URGENCY_ORDER = {'VENCIDO': 0, 'HOJE': 1, 'EM_BREVE': 2, 'NORMAL': 3, 'SEM_PRAZO': 4}


def urgency(due, now):
    """(código, texto curto) do prazo. Mesmos limites do semáforo antigo: 24 h e 3 dias."""
    if not due:
        return 'SEM_PRAZO', 'Sem prazo'
    local = timezone.localtime(due)
    delta = due - now
    if delta.total_seconds() < 0:
        return 'VENCIDO', f'Venceu em {local:%d/%m}'
    if delta <= timedelta(hours=24):
        return 'HOJE', f'Vence hoje às {local:%H:%M}' if local.date() == timezone.localtime(now).date() \
            else f'Vence amanhã às {local:%H:%M}'
    if delta.days <= 3:
        return 'EM_BREVE', f'Vence em {delta.days} dias'
    return 'NORMAL', f'Vence em {local:%d/%m}'


def _line(*, kind, gom, title, amount, due, pix, now, count=1, url='', group=''):
    code, due_label = urgency(due, now)
    key, instructions = pix
    return {
        'kind': kind, 'kind_label': KIND_LABELS[kind], 'gom': gom, 'title': title, 'amount': amount,
        'count': count, 'due': due, 'urgency': code, 'due_label': due_label,
        'pix_key': key or '', 'pix_instructions': instructions or '', 'url': url,
        # Mesmo grupo de apps.pagamentos.services.open_groups (seleção para gerar o Pix).
        'group': group,
    }


def _ceg_lines(c, now):
    ceg, caixa = c['ceg'], c.get('caixa')
    url = f'/ceg/{ceg.slug}/'
    suffix = f' · {caixa.nome}' if caixa else ''
    lines = []
    if c['total_pending'] > 0:
        group = c['group'].name
        title = ceg.title if group.lower() in ceg.title.lower() else f'{group} · {ceg.title}'
        lines.append(_line(group=f'item:ceg:{getattr(ceg, "id", "")}', kind='item', gom=ceg.gom, title=title, count=c['count_pending'],
                           amount=c['total_pending'], due=ceg.prazo_pagamento_item, now=now, url=url,
                           pix=(ceg.get_pix_key_item(), ceg.get_pix_instructions_item())))
    if c['total_frete_inter_pendente'] > 0:
        due = (caixa.prazo_frete if caixa and caixa.prazo_frete else ceg.prazo_pagamento_frete_inter)
        lines.append(_line(group=f'frete:ceg:{getattr(ceg, "id", "")}', kind='frete', gom=ceg.gom, title=f'{ceg.title}{suffix}', count=c['count_inter_unpaid'],
                           amount=c['total_frete_inter_pendente'], due=due, now=now, url=url,
                           pix=(ceg.get_pix_key_frete(), ceg.get_pix_instructions_frete())))
    if c['total_taxa_aduaneira_pendente'] > 0:
        due = (caixa.prazo_taxa if caixa and caixa.prazo_taxa else ceg.prazo_pagamento_taxa_aduaneira)
        lines.append(_line(group=f'taxa:ceg:{getattr(ceg, "id", "")}', kind='taxa', gom=ceg.gom, title=f'{ceg.title}{suffix}', count=c['count_taxa_unpaid'],
                           amount=c['total_taxa_aduaneira_pendente'], due=due, now=now, url=url,
                           pix=(ceg.get_pix_key_taxa(), ceg.get_pix_instructions_taxa())))
    return lines


def _mercari_lines(m, now):
    item = m['item']
    caixa = item.caixa
    lines = []
    if m['prod_pending'] > 0:
        lines.append(_line(group=f'item:avulso:{getattr(item, "id", "")}', kind='item', gom=item.gom, title=f'{item.nome} (avulso)', amount=m['prod_pending'],
                           due=None, now=now, pix=item.gom.pix_for('item')))
    if m['frete_pending'] > 0:
        pix = (caixa.get_pix_key_frete(), caixa.get_pix_instructions_frete()) if caixa else item.gom.pix_for('frete')
        lines.append(_line(group=f'frete:avulso:{getattr(item, "id", "")}', kind='frete', gom=item.gom, title=item.nome, amount=m['frete_pending'], now=now, pix=pix,
                           due=item.prazo_frete_inter or (caixa.prazo_frete if caixa else None)))
    if m['taxa_pending'] > 0:
        pix = (caixa.get_pix_key_taxa(), caixa.get_pix_instructions_taxa()) if caixa else item.gom.pix_for('taxa')
        lines.append(_line(group=f'taxa:avulso:{getattr(item, "id", "")}', kind='taxa', gom=item.gom, title=item.nome, amount=m['taxa_pending'], now=now, pix=pix,
                           due=item.prazo_taxa_aduaneira or (caixa.prazo_taxa if caixa else None)))
    return lines


def _pacote_lines(pacote, now):
    value = pacote.valor_frete_nacional or Decimal('0.00')
    if value <= 0 or pacote.is_frete_pago:
        return []
    title = f'Pacote {pacote.identificador}' if getattr(pacote, 'identificador', '') else 'Seu pacote'
    return [_line(group=f'frete_nacional:pacote:{getattr(pacote, "id", "")}', kind='frete_nacional', gom=pacote.gom, title=title, amount=value, due=None, now=now,
                  pix=(pacote.pix_key_frete_nacional, pacote.pix_instructions_frete_nacional))]


def build_charges(cegs_data, mercari_pending, pacotes, now=None):
    """
    {'total', 'count', 'urgent_count', 'goms': [{'gom', 'total', 'count', 'lines': [...]}]}.
    `cegs_data`: valores do cegs_dict do MyClaimsView; `mercari_pending`: mercari_pendencias['items'].
    """
    now = now or timezone.now()
    lines = []
    for c in cegs_data:
        lines += _ceg_lines(c, now)
    for m in mercari_pending:
        lines += _mercari_lines(m, now)
    for p in pacotes:
        lines += _pacote_lines(p, now)

    groups = {}
    for line in lines:
        g = groups.setdefault(line['gom'].id, {'gom': line['gom'], 'total': Decimal('0.00'), 'lines': []})
        g['total'] += line['amount']
        g['lines'].append(line)
    for g in groups.values():
        g['lines'].sort(key=lambda x: (URGENCY_ORDER[x['urgency']], x['due'] or now, x['title']))
        g['count'] = len(g['lines'])
        g['first_urgency'] = URGENCY_ORDER[g['lines'][0]['urgency']]
    ordered = sorted(groups.values(), key=lambda g: (g['first_urgency'], g['gom'].name))
    return {
        'goms': ordered,
        'total': sum((line['amount'] for line in lines), Decimal('0.00')),
        'count': len(lines),
        'overdue_count': sum(1 for line in lines if line['urgency'] == 'VENCIDO'),
        'urgent_count': sum(1 for line in lines if line['urgency'] in ('VENCIDO', 'HOJE')),
    }


def attach_pix_state(charges, participant):
    """
    Liga a seção Pagar às cobranças Pix (S1): por GOM, se o QR está pronto, quais grupos estão livres para gerar
    o Pix e as cobranças em andamento. Linhas já numa cobrança aberta aparecem como "Pagamento em análise".
    """
    from apps.pagamentos.models import Cobranca
    from apps.pagamentos.pix import normalize_key
    from apps.pagamentos.services import open_groups

    for g in charges['goms']:
        gom = g['gom']
        ready = bool((gom.pix_nome_recebedor or '').strip() and (gom.pix_cidade or '').strip())
        free = {grp['key'] for grp in open_groups(participant, gom)} if ready else set()
        for line in g['lines']:
            valid_key = normalize_key(line['pix_key'])[0] is not None
            line['in_charge'] = ready and line['group'] not in free
            line['selectable'] = ready and valid_key and line['group'] in free
            # Chave que não é Pix (texto livre antigo): a linha continua com "Copiar Pix", sem QR.
            line['copy_mode'] = not (line['selectable'] or line['in_charge'])
        g['pix_ready'] = ready
        g['cobrancas'] = list(Cobranca.objects.filter(gom=gom, participant=participant, status__in=Cobranca.OPEN)
                              .order_by('-criada_em')) if ready else []
    return charges
