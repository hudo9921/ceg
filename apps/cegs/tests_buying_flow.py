"""Compra competitiva do joiner na página da CEG (DESIGN_SYSTEM §7.6).

A lista pode ser montada durante a contagem, mas a reserva só sai quando o joiner toca em
"Pegar meus X" depois da abertura. Nada é comprado automaticamente.
"""
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet
from apps.cegs.services import ClaimService
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Claim, Participant


class CompetitiveBuyingFlowTests(TestCase):
    def setUp(self):
        ClaimService.reset_in_memory_counters()
        self.client = Client()
        group = KpopGroup.objects.create(name='aespa', slug='aespa')
        self.era = Era.objects.create(group=group, name='Whiplash', slug='whiplash')
        self.joiner = Participant.objects.create(whatsapp='5511988887777', name='Joiner Rápida', username='rapida')

    def _ceg(self, opens_in):
        ceg = CEG.objects.create(
            era=self.era, title='CEG Buy Flow', slug='ceg-buy-flow',
            status=CEG.Status.SCHEDULED if opens_in > timedelta(0) else CEG.Status.OPEN,
            opens_at=timezone.now() + opens_in, pix_key='pix@gom.com',
        )
        CEGItemDefinition.objects.create(ceg=ceg, name='PC Karina', member_name='Karina', default_price=40)
        cset = CEGSet.objects.create(ceg=ceg, set_number=1)
        cset.generate_slots()
        return ceg, cset.slots.first()

    def _login_joiner(self):
        session = self.client.session
        session['participant_id'] = self.joiner.id
        session.save()

    def _get(self, ceg):
        return self.client.get(reverse('ceg_detail', kwargs={'slug': ceg.slug}))

    def test_anonymous_sees_login_cta_in_buybar(self):
        ceg, _ = self._ceg(timedelta(hours=1))
        resp = self._get(ceg)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Entrar para reservar')
        self.assertNotContains(resp, '@click="quickClaim()"')

    def test_joiner_can_build_list_during_standby(self):
        ceg, _ = self._ceg(timedelta(hours=1))
        self._login_joiner()
        resp = self._get(ceg)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Adicionar à lista')
        self.assertNotContains(resp, 'Aguarde abertura')
        self.assertContains(resp, "'Abre em ' + countdownShort()")
        self.assertContains(resp, '@click="quickClaim()"')
        self.assertContains(resp, 'Resultado da reserva')

    def test_joiner_open_page_has_buybar(self):
        ceg, _ = self._ceg(-timedelta(minutes=5))
        self._login_joiner()
        resp = self._get(ceg)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "'Pegar meus ' + listCount()")

    def test_staff_keeps_assisted_claim_bar(self):
        ceg, _ = self._ceg(-timedelta(minutes=5))
        User.objects.create_superuser(username='gom', password='pw-123456', email='g@x.com')
        self.client.login(username='gom', password='pw-123456')
        resp = self._get(ceg)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, '@click="quickClaim()"')

    def test_quick_claim_body_without_identity_uses_session(self):
        """O toque único manda só as vagas; nome e WhatsApp vêm da sessão do joiner."""
        ceg, slot = self._ceg(-timedelta(minutes=5))
        self._login_joiner()
        resp = self.client.post(
            f'/ceg/{ceg.slug}/bulk-claim/',
            data=json.dumps({'slot_ids': [slot.id], 'avulso_claims': [], 'entrega_tipo': 'CAIXINHA'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['summary']['succeeded'], 1)
        self.assertTrue(Claim.objects.filter(slot=slot, participant=self.joiner).exists())

    def test_quick_claim_before_opening_does_not_buy(self):
        ceg, slot = self._ceg(timedelta(hours=1))
        self._login_joiner()
        resp = self.client.post(
            f'/ceg/{ceg.slug}/bulk-claim/',
            data=json.dumps({'slot_ids': [slot.id], 'avulso_claims': []}),
            content_type='application/json',
        )
        self.assertFalse(Claim.objects.filter(slot=slot).exists())
        self.assertIn(resp.status_code, (200, 400, 403))
