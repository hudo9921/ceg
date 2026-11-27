"""Procurar integrante: vagas livres em CEGs de todos os GOMs, Vitrine e repasses públicos; nada fechado ou de outro integrante."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot, ItemVitrine
from apps.goms.models import Gom
from apps.groups.models import Era, GroupMember, KpopGroup
from apps.participants.models import Participant


class ProcurarTests(TestCase):
    def setUp(self):
        self.ive = KpopGroup.objects.create(name='IVE', slug='ive')
        self.wony = GroupMember.objects.create(group=self.ive, name='Wonyoung', name_native='원영')
        GroupMember.objects.create(group=self.ive, name='Yujin')
        era = Era.objects.create(group=self.ive, name='IVE SECRET')
        self.gom_a = Gom.objects.create(name='Loja A', slug='loja-a')
        self.gom_b = Gom.objects.create(name='Loja B', slug='loja-b')
        self.aberta = self._ceg(self.gom_a, era, 'IVE SECRET POB A', CEG.Status.OPEN, 'Wonyoung', livres=2)
        self._ceg(self.gom_b, era, 'IVE SECRET POB B', CEG.Status.OPEN, 'Wonyoung', livres=1)
        self._ceg(self.gom_a, era, 'IVE fechada', CEG.Status.CLOSED, 'Wonyoung', livres=3)
        self._ceg(self.gom_a, era, 'IVE só Yujin', CEG.Status.OPEN, 'Yujin', livres=3)
        self._ceg(self.gom_b, era, 'IVE esgotada', CEG.Status.OPEN, 'Wonyoung', livres=0)
        ItemVitrine.objects.create(gom=self.gom_b, titulo='Wonyoung PC pronta', group=self.ive, integrante='wonyoung',
                                   preco=Decimal('25'))

    def _ceg(self, gom, era, titulo, status, membro, livres):
        ceg = CEG.objects.create(gom=gom, era=era, title=titulo, slug=titulo.lower().replace(' ', '-'), status=status)
        d = CEGItemDefinition.objects.create(ceg=ceg, name=f'{membro} POB', member_name=membro, default_price=Decimal('30'))
        s = CEGSet.objects.create(ceg=ceg, set_number=1)
        dono = Participant.objects.create(whatsapp=f'55119{ceg.id:08d}', name='Dono')
        ItemSlot.objects.create(set=s, item_definition=d, price=Decimal('30'), unit_number=0,
                                status=ItemSlot.Status.RESERVED, claimed_by=dono)
        for n in range(livres):
            ItemSlot.objects.create(set=s, item_definition=d, price=Decimal('30'), unit_number=n + 1)
        return ceg

    def test_um_nome_vai_direto_e_junta_todos_os_goms(self):
        res = self.client.get(reverse('procurar'), {'q': 'wonyo'})
        self.assertEqual(res.context['membro'], self.wony)
        titulos = [b['ceg'].title for b in res.context['cegs']]
        self.assertCountEqual(titulos, ['IVE SECRET POB A', 'IVE SECRET POB B'])
        self.assertEqual([v['titulo'] for v in res.context['vitrine']], ['Wonyoung PC pronta'])
        self.assertContains(res, 'Loja B')

    def test_nome_em_hangul(self):
        self.assertEqual(self.client.get(reverse('procurar'), {'q': '원영'}).context['membro'], self.wony)

    def test_varios_nomes_pede_para_escolher(self):
        GroupMember.objects.create(group=KpopGroup.objects.create(name='Outro', slug='outro'), name='Wonyoung B')
        res = self.client.get(reverse('procurar'), {'q': 'wonyoung'})
        self.assertIsNone(res.context['membro'])
        self.assertEqual(len(res.context['candidatos']), 2)

    def test_gom_inativo_some(self):
        Gom.objects.filter(pk=self.gom_b.pk).update(is_active=False)
        res = self.client.get(reverse('procurar'), {'m': self.wony.id})
        self.assertEqual([b['ceg'].title for b in res.context['cegs']], ['IVE SECRET POB A'])
        self.assertEqual(res.context['vitrine'], [])

    def test_mostra_vagas_livres(self):
        res = self.client.get(reverse('procurar'), {'m': self.wony.id})
        bloco = next(b for b in res.context['cegs'] if b['ceg'] == self.aberta)
        self.assertEqual(bloco['itens'][0].livres, 2)
