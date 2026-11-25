"""
Seção "Meus itens" do painel do joiner (P3b): todos os itens (claims de CEG e itens avulsos)
numa lista única, com a etapa do ciclo de vida (`lifecycle`, 1 a 5), para agrupar por GOM,
CEG ou caixa e filtrar por etapa no navegador.
"""
from apps.core.thumbnails import thumbnail_url

# Etapas do filtro e da barra de progresso. Vêm do `code` do lifecycle (não do número `stage`: um item
# já pago mas ainda sem caixa também é stage 1 no lifecycle, e não deve aparecer em "A pagar").
STAGES = [
    (1, 'A pagar'),
    (2, 'A caminho'),
    (3, 'No Brasil'),
    (4, 'Na caixinha'),
    (5, 'Enviado'),
]
CODE_STAGE = {
    'PENDING_PAYMENT': 1,
    'ITEM_PAID': 2, 'COMPRADO': 2, 'WAREHOUSE': 2, 'CONSOLIDATION': 2, 'IN_TRANSIT': 2,
    'CUSTOMS_PENDING': 3, 'CUSTOMS_CLEARING': 3,
    'READY_CAIXINHA': 4,
    'PACKAGING': 5, 'SHIPPED': 5, 'DELIVERED': 5,
}


def _stage(life):
    return CODE_STAGE.get(life.get('code'), life.get('stage', 1))


def _avulso_photo(item):
    if item.foto_arquivo:
        try:
            return item.foto_arquivo.url
        except ValueError:
            return ''
    return item.foto_url or ''


def _claim_entry(claim):
    slot = claim.slot
    ceg, definition = slot.set.ceg, slot.item_definition
    life = claim.lifecycle
    caixa = ceg.caixa
    image = definition.image_url or ''
    member = definition.member_name or ''
    name = definition.name if not member or member.lower() in definition.name.lower() else f'{member} · {definition.name}'
    return {
        'key': f'c{claim.id}', 'preview': str(claim.id), 'name': name, 'set': slot.set.set_number,
        'image': image, 'thumb': thumbnail_url(image) if image else '',
        'ceg': ceg.title, 'ceg_url': f'/ceg/{ceg.slug}/', 'group': ceg.era.group.name if ceg.era_id else '',
        'gom_id': ceg.gom_id, 'gom': ceg.gom.name, 'gom_url': f'/gom/{ceg.gom.slug}/',
        'caixa_id': caixa.id if caixa else None, 'caixa': caixa.nome if caixa else 'Sem caixa ainda',
        'price': f'{claim.total_price:.2f}', 'stage': _stage(life), 'label': life.get('label', ''),
        'detail': life.get('detail', ''),
    }


def _avulso_entry(item):
    life = item.lifecycle
    image = _avulso_photo(item)
    caixa = item.caixa
    return {
        'key': f'a{item.id}', 'preview': '', 'name': item.nome, 'set': None,
        'image': image, 'thumb': thumbnail_url(image) if image else '',
        'ceg': 'Item avulso', 'ceg_url': '', 'group': '',
        'gom_id': item.gom_id, 'gom': item.gom.name, 'gom_url': f'/gom/{item.gom.slug}/',
        'caixa_id': caixa.id if caixa else None, 'caixa': caixa.nome if caixa else 'Sem caixa ainda',
        'price': f'{(item.preco_produto or 0):.2f}', 'stage': _stage(life), 'label': life.get('label', ''),
        'detail': life.get('detail', ''),
    }


def build_items(claims, itens_individuais):
    """Lista de itens para o painel (ordem: mais recentes primeiro, como chegam do view)."""
    return [_claim_entry(c) for c in claims] + [_avulso_entry(i) for i in itens_individuais]


def stage_options():
    return [{'stage': n, 'label': label} for n, label in STAGES]
