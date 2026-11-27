"""Minha coleção: só o que chegou (pacote entregue), link público liga/desliga e sem dados sensíveis na pública."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot, PacoteNacional
from apps.goms.models import Gom
from apps.groups.models import Era, KpopGroup
from apps.participants.colecao import origem, paginas
from apps.participants.models import Claim, Participant


class ColecaoTests(TestCase):
    def setUp(self):
        gom = Gom.objects.create(name='Loja C', slug='loja-c')
        self.joiner = Participant.objects.create(whatsapp='5511955556666', name='Lia', username='lia')
        era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa'), name='Armageddon')
        ceg = CEG.objects.create(gom=gom, era=era, title='Armageddon POB', slug='arma-pob')
        s = CEGSet.objects.create(ceg=ceg, set_number=1)
        entregue = PacoteNacional.objects.create(gom=gom, participant=self.joiner, status=PacoteNacional.Status.ENTREGUE)
        caminho = PacoteNacional.objects.create(gom=gom, participant=self.joiner, status=PacoteNacional.Status.ENVIADO)
        for nome, pac in (('Karina', entregue), ('Winter', caminho), ('Ningning', None)):
            d = CEGItemDefinition.objects.create(ceg=ceg, name=f'{nome} POB', member_name=nome, default_price=Decimal('30'))
            slot = ItemSlot.objects.create(set=s, item_definition=d, price=Decimal('30'), unit_number=1,
                                           status=ItemSlot.Status.PAID, claimed_by=self.joiner, pacote_nacional=pac)
            Claim.objects.create(slot=slot, participant=self.joiner, total_price=Decimal('30'), status=Claim.Status.PAID)

    def _entrar(self):
        session = self.client.session
        session['participant_id'] = self.joiner.id
        session.save()

    def test_so_o_que_chegou(self):
        self._entrar()
        res = self.client.get(reverse('minha_colecao'))
        self.assertEqual(res.context['total'], 1)
        self.assertContains(res, 'Karina')
        self.assertNotContains(res, 'Winter POB')

    def test_link_publico_liga_e_desliga(self):
        self._entrar()
        self.client.post(reverse('colecao_compartilhar'), {'ligar': '1'})
        self.joiner.refresh_from_db()
        token = self.joiner.colecao_token
        self.assertTrue(token)
        self.client.logout()
        publica = self.client.get(reverse('colecao_publica', args=[token]))
        self.assertContains(publica, 'Coleção de lia')
        self.assertContains(publica, 'Karina')
        self.assertNotContains(publica, '5511955556666')
        self.assertNotContains(publica, 'R$')
        self._entrar()
        self.client.post(reverse('colecao_compartilhar'), {'ligar': '0'})
        self.assertEqual(self.client.get(reverse('colecao_publica', args=[token])).status_code, 404)

    def test_precisa_entrar(self):
        self.assertEqual(self.client.get(reverse('minha_colecao')).status_code, 302)


class FicharioTests(TestCase):
    def test_origem_tira_grupo_e_codigo(self):
        g = KpopGroup.objects.create(name='LE SSERAFIM', slug='lsf')
        era = Era.objects.create(group=g, name='Crazy')
        gom = Gom.objects.create(name='Loja F', slug='loja-f')
        c = CEG.objects.create(gom=gom, era=era, title='LE SSERAFIM — WEVERSE GLOBAL 2.0 (PF-33)', slug='lsf-wv')
        self.assertEqual(origem(c), 'WEVERSE GLOBAL 2.0')
        c.title = 'Makestar'
        self.assertEqual(origem(c), 'Makestar')

    def test_paginas_de_nove_com_bolsos_vazios(self):
        ps = paginas(list(range(10)))
        self.assertEqual([len(p) for p in ps], [9, 9])
        self.assertEqual(ps[1][1:], [None] * 8)
