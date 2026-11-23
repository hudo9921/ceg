"""Painel do joiner com vários GOMs (M3): visão por GOM, Pix do GOM certo e envio por GOM."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ConfiguracaoEnvio, ItemIndividual, ItemSlot, PacoteNacional, TipoItem
from apps.goms.models import Gom
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Claim, Participant


class JoinerWithTwoGomsTests(TestCase):
    def setUp(self):
        self.gom_a = Gom.objects.create(name='Loja Alfa', slug='loja-alfa', default_pix_key='pix-alfa@x.com')
        self.gom_b = Gom.objects.create(name='Loja Beta', slug='loja-beta', default_pix_key='pix-beta@x.com')
        era = Era.objects.create(group=KpopGroup.objects.create(name='ILLIT'), name='Super Real Me')
        self.tipo = TipoItem.objects.create(nome='PC Multi')
        self.joiner = Participant.objects.create(name='Bia', whatsapp='5511912345678')
        self.ceg_a = self._ceg(self.gom_a, era, 'CEG da Alfa', 'ceg-pix-alfa@x.com')
        self.ceg_b = self._ceg(self.gom_b, era, 'CEG da Beta', 'ceg-pix-beta@x.com')
        self.item_a = self._mercari(self.gom_a, 'Mercari Alfa')
        self.item_b = self._mercari(self.gom_b, 'Mercari Beta')
        session = self.client.session
        session['participant_id'] = self.joiner.id
        session.save()

    def _ceg(self, gom, era, title, pix):
        ceg = CEG.objects.create(gom=gom, era=era, title=title, status=CEG.Status.OPEN, pix_key=pix,
                                 opens_at=timezone.now() - timedelta(minutes=5))
        idef = CEGItemDefinition.objects.create(ceg=ceg, name=f'PC {title}', default_price=Decimal('30.00'))
        cset = CEGSet.objects.create(ceg=ceg, set_number=1, is_active=True)
        slot = ItemSlot.objects.create(set=cset, item_definition=idef, price=Decimal('30.00'),
                                       status=ItemSlot.Status.RESERVED, claimed_by=self.joiner)
        Claim.objects.create(slot=slot, participant=self.joiner, total_price=Decimal('30.00'))
        return ceg

    def _mercari(self, gom, nome):
        return ItemIndividual.objects.create(gom=gom, nome=nome, comprador=self.joiner, tipo_item=self.tipo,
                                             preco_produto=Decimal('40.00'), produto_pago=False)

    def test_panel_lists_each_gom_with_its_items(self):
        ctx = self.client.get(reverse('my_claims')).context
        names = [g['name'] for g in ctx['goms_list']]
        self.assertEqual(names, ['Loja Alfa', 'Loja Beta'])
        self.assertTrue(all(g['items_count'] == 2 for g in ctx['goms_list']))
        gom_ids = {c['gom_id'] for c in ctx['cegs_filter_list']}
        self.assertEqual(gom_ids, {str(self.gom_a.id), str(self.gom_b.id)})

    def test_mercari_pix_never_uses_another_goms_key(self):
        pend = self.client.get(reverse('my_claims')).context['mercari_pendencias']
        self.assertEqual(pend['pix_key'], '')  # dois GOMs: nenhuma chave única
        by_gom = {g['gom'].slug: g['pix_key'] for g in pend['por_gom']}
        self.assertEqual(by_gom, {'loja-alfa': 'pix-alfa@x.com', 'loja-beta': 'pix-beta@x.com'})

    def test_items_without_caixa_from_two_goms_have_no_single_pix(self):
        caixas = self.client.get(reverse('my_claims')).context['caixas_com_pendencias']
        sem_caixa = next(c for c in caixas if c['id'] == 'NONE')
        self.assertTrue(sem_caixa['mixed_goms'])
        self.assertEqual(sem_caixa['pix_key'], '')

    def test_single_gom_keeps_one_key(self):
        self.item_b.delete()
        pend = self.client.get(reverse('my_claims')).context['mercari_pendencias']
        self.assertEqual(pend['pix_key'], 'pix-alfa@x.com')

    def test_caixinha_shows_each_goms_shipping_form_and_request_splits_packages(self):
        ConfiguracaoEnvio.objects.create(gom=self.gom_b, link_formulario_google='https://forms.example/beta')
        ItemIndividual.objects.filter(pk__in=[self.item_a.pk, self.item_b.pk]).update(produto_pago=True)
        ctx = self.client.get(reverse('my_claims')).context
        forms = {e['gom'].slug: e['config'].link_formulario_google for e in ctx['envio_por_gom']}
        self.assertEqual(forms, {'loja-alfa': '', 'loja-beta': 'https://forms.example/beta'})

        self.client.post(reverse('solicitar_envio_nacional'),
                         {'selected_uids': f'mercari_{self.item_a.id},mercari_{self.item_b.id}'})
        pacotes = PacoteNacional.objects.filter(participant=self.joiner)
        self.assertEqual(sorted(p.gom.slug for p in pacotes), ['loja-alfa', 'loja-beta'])

    def test_public_gom_page_shows_only_its_cegs(self):
        res = self.client.get(reverse('gom_public', args=['loja-beta']))
        self.assertContains(res, 'CEG da Beta')
        self.assertNotContains(res, 'CEG da Alfa')
        self.gom_b.is_active = False
        self.gom_b.save()
        self.assertEqual(self.client.get(reverse('gom_public', args=['loja-beta'])).status_code, 404)

    def test_home_shows_gom_filter_when_several_goms_are_open(self):
        res = self.client.get(reverse('home'))
        self.assertTrue(res.context['multi_gom'])
        self.assertContains(res, 'Todos os GOMs')
