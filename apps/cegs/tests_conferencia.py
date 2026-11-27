"""Conferência de chegada: esperado por item, marcar/desfazer, "chegou tudo", quem foi afetado e isolamento entre GOMs."""
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import (CEG, Caixa, CEGItemDefinition, CEGSet, ConferenciaChegada, ItemIndividual, ItemSlot)
from apps.goms.models import Gom
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Participant

User = get_user_model()


class ConferenciaChegadaTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser('gom-c', 'c@x.com', 'x'))
        era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa'), name='Dirty Work')
        self.caixa = Caixa.objects.create(nome='Caixa KR 9', status=Caixa.Status.ENTREGUE)
        self.ceg = CEG.objects.create(era=era, title='Dirty Work POB', slug='dw-pob', caixa=self.caixa)
        self.karina = CEGItemDefinition.objects.create(ceg=self.ceg, name='Karina POB', member_name='Karina',
                                                       default_price=Decimal('30'))
        self.ana = Participant.objects.create(whatsapp='5511911110000', name='Ana', username='ana')
        self.bia = Participant.objects.create(whatsapp='5511922220000', name='Bia', username='bia')
        for n in (1, 2):
            s = CEGSet.objects.create(ceg=self.ceg, set_number=n)
            ItemSlot.objects.create(set=s, item_definition=self.karina, price=Decimal('30'), unit_number=1,
                                    status=ItemSlot.Status.RESERVED, claimed_by=self.ana if n == 1 else self.bia)
        self.mercari = ItemIndividual.objects.create(caixa=self.caixa, nome='Lucky draw Winter', comprador=self.ana)
        self.url = reverse('caixa_conferencia', kwargs={'slug': self.caixa.slug})
        self.marcar = reverse('caixa_conferencia_marcar', kwargs={'slug': self.caixa.slug})

    def _post(self, corpo):
        return self.client.post(self.marcar, json.dumps(corpo), content_type='application/json').json()

    def test_pagina_lista_o_esperado(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        linha = res.context['cegs'][0]['linhas'][0]
        self.assertEqual((linha['nome'], linha['esperado'], linha['situacao']), ('Karina POB', 2, 'pendente'))
        self.assertEqual(res.context['resumo']['total'], 2)

    def test_faltou_mostra_afetados(self):
        data = self._post({'tipo': 'item', 'id': self.karina.id, 'chegou': 1})
        self.assertEqual(data['linhas'][f'item:{self.karina.id}']['situacao'], 'faltou')
        self.assertEqual(data['resumo']['faltando_unidades'], 1)
        self.assertEqual(data['resumo']['afetados'], ['ana', 'bia'])

    def test_chegou_tudo_da_ceg_e_desfazer(self):
        data = self._post({'ceg_id': self.ceg.id})
        self.assertEqual(data['linhas'][f'item:{self.karina.id}'], {'chegou': 2, 'conferido': True, 'situacao': 'ok'})
        self._post({'desfazer': 'item', 'id': self.karina.id})
        self.assertFalse(ConferenciaChegada.objects.filter(item_definition=self.karina).exists())

    def test_nao_passa_do_esperado_e_individual(self):
        self._post({'tipo': 'item', 'id': self.karina.id, 'chegou': 99})
        self.assertEqual(ConferenciaChegada.objects.get(item_definition=self.karina).chegou, 2)
        data = self._post({'tipo': 'individual', 'id': self.mercari.id, 'chegou': 0})
        self.assertEqual(data['linhas'][f'individual:{self.mercari.id}']['situacao'], 'faltou')
        self.assertEqual(data['resumo']['afetados'], ['ana'])

    def test_nao_muda_nada_alem_da_conferencia(self):
        self._post({'tipo': 'item', 'id': self.karina.id, 'chegou': 0})
        self.assertEqual(ItemSlot.objects.filter(status=ItemSlot.Status.RESERVED).count(), 2)
        self.assertFalse(self.ana.notifications.exists())

    def test_caixa_de_outro_gom(self):
        outro = Gom.objects.create(name='Outro', slug='outro')
        alheia = Caixa.objects.create(gom=outro, nome='Alheia')
        self.assertEqual(self.client.get(reverse('caixa_conferencia', kwargs={'slug': alheia.slug})).status_code, 404)
