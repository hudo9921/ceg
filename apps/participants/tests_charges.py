"""Seção Pagar (apps/participants/charges.py): cobranças por GOM, prazos e chaves Pix."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace as NS

from django.test import SimpleTestCase
from django.utils import timezone

from .charges import build_charges, urgency

NOW = timezone.now()


def gom(gid, name, pix=None):
    pix = pix or {}
    return NS(id=gid, name=name, pix_for=lambda kind: (pix.get(kind, f'{name.lower()}-{kind}'), ''))


def ceg_data(g, *, item=0, frete=0, taxa=0, due=None):
    ceg = NS(title=f'CEG {g.name}', slug=f'ceg-{g.id}', gom=g, prazo_pagamento_item=due,
             prazo_pagamento_frete_inter=None, prazo_pagamento_taxa_aduaneira=None,
             get_pix_key_item=lambda: f'{g.name}-item', get_pix_instructions_item=lambda: '',
             get_pix_key_frete=lambda: f'{g.name}-frete', get_pix_instructions_frete=lambda: '',
             get_pix_key_taxa=lambda: f'{g.name}-taxa', get_pix_instructions_taxa=lambda: '')
    return {'ceg': ceg, 'caixa': None, 'group': NS(name='aespa'), 'total_pending': Decimal(item), 'count_pending': 2,
            'total_frete_inter_pendente': Decimal(frete), 'count_inter_unpaid': 2,
            'total_taxa_aduaneira_pendente': Decimal(taxa), 'count_taxa_unpaid': 2}


class UrgencyTests(SimpleTestCase):
    def test_labels(self):
        self.assertEqual(urgency(None, NOW)[0], 'SEM_PRAZO')
        self.assertEqual(urgency(NOW - timedelta(hours=1), NOW)[0], 'VENCIDO')
        self.assertEqual(urgency(NOW + timedelta(hours=3), NOW)[0], 'HOJE')
        self.assertEqual(urgency(NOW + timedelta(days=2, hours=1), NOW), ('EM_BREVE', 'Vence em 2 dias'))
        self.assertEqual(urgency(NOW + timedelta(days=9), NOW)[0], 'NORMAL')


class BuildChargesTests(SimpleTestCase):
    def test_groups_by_gom_most_urgent_first_with_right_pix(self):
        a, b = gom(1, 'Alfa'), gom(2, 'Beta')
        result = build_charges(
            [ceg_data(a, item=80, frete=20), ceg_data(b, item=50, due=NOW + timedelta(hours=2))], [], [], now=NOW)
        self.assertEqual(result['total'], Decimal('150'))
        self.assertEqual(result['count'], 3)
        self.assertEqual(result['urgent_count'], 1)
        self.assertEqual([g['gom'].name for g in result['goms']], ['Beta', 'Alfa'])  # Beta vence hoje
        alfa = {l['kind']: l for l in result['goms'][1]['lines']}
        self.assertEqual((alfa['item']['pix_key'], alfa['frete']['pix_key']), ('Alfa-item', 'Alfa-frete'))
        self.assertEqual(result['goms'][1]['total'], Decimal('100'))

    def test_national_freight_and_paid_package_left_out(self):
        g = gom(1, 'Alfa', pix={'frete_nacional': 'alfa-correios'})
        open_pkg = NS(gom=g, identificador='PAC-1', valor_frete_nacional=Decimal('22'), is_frete_pago=False,
                      pix_key_frete_nacional='alfa-correios', pix_instructions_frete_nacional='')
        paid_pkg = NS(gom=g, identificador='PAC-2', valor_frete_nacional=Decimal('30'), is_frete_pago=True)
        result = build_charges([], [], [open_pkg, paid_pkg], now=NOW)
        self.assertEqual(result['count'], 1)
        line = result['goms'][0]['lines'][0]
        self.assertEqual((line['kind'], line['title'], line['pix_key']), ('frete_nacional', 'Pacote PAC-1', 'alfa-correios'))

    def test_nothing_owed(self):
        result = build_charges([ceg_data(gom(1, 'Alfa'))], [], [], now=NOW)
        self.assertEqual((result['count'], result['total'], result['goms']), (0, Decimal('0.00'), []))
