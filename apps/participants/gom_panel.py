"""
Painel do joiner com vários GOMs (docs/MULTI_GOM_DESIGN.md §4, entrega M3).

Regra de ouro do Pix: o joiner só vê, para cada dívida, uma chave do MESMO GOM a quem deve.
Nunca usar a chave de um GOM como "padrão" para itens de outro.
"""
from decimal import Decimal

from apps.cegs.models import ConfiguracaoEnvio


def gom_pix_defaults(cegs_data, itens):
    """
    Chave Pix "padrão" de cada GOM para itens sem chave própria (Mercari, caixas sem chave):
    `Gom.default_pix_key` ou, na falta, a chave da primeira CEG daquele GOM.
    Retorna {gom_id: (chave, instruções)}.
    """
    defaults = {}
    goms = {c['ceg'].gom_id: c['ceg'].gom for c in cegs_data}
    goms.update({it.gom_id: it.gom for it in itens})
    for gom_id, gom in goms.items():
        defaults[gom_id] = (gom.default_pix_key or '', gom.default_pix_instructions or '')
    for c in cegs_data:
        ceg = c['ceg']
        if not defaults[ceg.gom_id][0] and ceg.pix_key:
            defaults[ceg.gom_id] = (ceg.pix_key, ceg.pix_instructions or '')
    return defaults


def mercari_pix_by_gom(pending_items, gom_pix):
    """Agrupa as pendências Mercari por GOM, cada grupo com a chave Pix do próprio GOM."""
    groups = {}
    for m in pending_items:
        item = m['item']
        g = groups.setdefault(item.gom_id, {
            'gom': item.gom, 'total': Decimal('0.00'), 'count': 0,
            'pix_key': gom_pix.get(item.gom_id, ('', ''))[0],
            'pix_instructions': gom_pix.get(item.gom_id, ('', ''))[1],
        })
        g['total'] += m['total_pending']
        g['count'] += 1
    return sorted(groups.values(), key=lambda g: g['gom'].name)


def goms_summary(cegs_data, itens, pacotes, mercari_pending):
    """GOMs com que o joiner tem algo: itens, pendências e pacotes (filtro e visão por GOM)."""
    summary = {}

    def entry(gom):
        return summary.setdefault(gom.id, {
            'id': gom.id, 'name': gom.name, 'slug': gom.slug, 'logo_url': gom.logo_url,
            'whatsapp_contato': gom.whatsapp_contato, 'instagram': gom.instagram,
            'items_count': 0, 'cegs_count': 0, 'mercari_count': 0, 'pacotes_count': 0,
            'total_pendente': Decimal('0.00'),
        })

    for c in cegs_data:
        e = entry(c['ceg'].gom)
        e['cegs_count'] += 1
        e['items_count'] += len(c['claims'])
        e['total_pendente'] += c.get('total_geral_pendente') or Decimal('0.00')
    for it in itens:
        e = entry(it.gom)
        e['mercari_count'] += 1
        e['items_count'] += 1
    for m in mercari_pending:
        summary[m['item'].gom_id]['total_pendente'] += m['total_pending']
    for p in pacotes:
        entry(p.gom)['pacotes_count'] += 1
    return sorted(summary.values(), key=lambda g: g['name'])


def shipping_configs_by_gom(prontos, goms_by_id):
    """Instruções/formulário de envio de cada GOM que tem itens prontos na Caixinha."""
    counts = {}
    for item in prontos:
        counts[item['gom_id']] = counts.get(item['gom_id'], 0) + 1
    configs = []
    for gom_id, count in counts.items():
        gom = goms_by_id.get(gom_id)
        if gom is None:
            continue
        configs.append({'gom': gom, 'config': ConfiguracaoEnvio.get_for_gom(gom), 'items_count': count})
    return sorted(configs, key=lambda c: c['gom'].name)
