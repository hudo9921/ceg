"""Regras do GOM (C1): só o estreante aceita, antes do primeiro claim; veteranos nunca são barrados."""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cegs.models import CEG, AuditLog, CEGItemDefinition, CEGSet
from apps.cegs.services import ClaimService
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Claim, Participant

from .models import AceiteRegras, Gom, GomMembership
from .rules import needs_rules

User = get_user_model()
RULES = '1. Claim é compromisso.\n2. Pague em até 3 dias.'


class RulesTests(TestCase):
    def setUp(self):
        ClaimService.reset_in_memory_counters()
        self.gom = Gom.objects.create(name='Loja R', slug='loja-r', regras=RULES)
        era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa-r'), name='Rich', slug='rich-r')
        self.ceg = CEG.objects.create(era=era, gom=self.gom, title='CEG R', slug='ceg-r', status=CEG.Status.OPEN,
                                      opens_at=timezone.now() - timedelta(minutes=1), pix_key='pix@r')
        CEGItemDefinition.objects.create(ceg=self.ceg, name='PC Karina', member_name='Karina', default_price=40)
        CEGItemDefinition.objects.create(ceg=self.ceg, name='PC Winter', member_name='Winter', default_price=40)
        cset = CEGSet.objects.create(ceg=self.ceg, set_number=1)
        cset.generate_slots()
        self.slots = list(cset.slots.order_by('id'))
        self.joiner = Participant.objects.create(whatsapp='5511977770000', name='Nova', username='nova')

    def _login(self, participant=None):
        session = self.client.session
        session['participant_id'] = (participant or self.joiner).id
        session.save()

    def _claim(self, slot, **extra):
        return self.client.post(reverse('bulk_claim', args=[self.ceg.slug]),
                                data=json.dumps({'slot_ids': [slot.id], **extra}), content_type='application/json')

    def test_first_timer_is_asked_and_nothing_is_reserved(self):
        self._login()
        res = self._claim(self.slots[0])
        self.assertEqual(res.status_code, 409)
        self.assertTrue(res.json()['needs_rules'])
        self.assertFalse(Claim.objects.filter(participant=self.joiner).exists())

    def test_accepting_in_the_claim_records_and_reserves(self):
        self._login()
        res = self._claim(self.slots[0], accept_rules=True)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Claim.objects.filter(participant=self.joiner).exists())
        aceite = AceiteRegras.objects.get(participant=self.joiner, gom=self.gom)
        self.assertEqual(len(aceite.texto_hash), 64)
        self.assertTrue(AuditLog.objects.for_gom(self.gom).filter(metadata__acao='regras_aceitas').exists())

    def test_accept_before_opening_then_claim_goes_straight(self):
        self._login()
        res = self.client.post(reverse('gom_rules_accept', args=[self.gom.slug]))
        self.assertEqual(res.json(), {'success': True})
        self.assertEqual(self._claim(self.slots[0]).status_code, 200)

    def test_veteran_is_never_blocked_even_after_rules_change(self):
        self._login()
        self._claim(self.slots[0], accept_rules=True)
        AceiteRegras.objects.all().delete()  # joiner antigo: participou antes das regras existirem
        self.gom.regras = RULES + '\n3. Nova regra.'
        self.gom.save()
        self.assertFalse(needs_rules(self.joiner, self.gom))
        self.assertEqual(self._claim(self.slots[1]).status_code, 200)

    def test_gom_without_rules_asks_nothing(self):
        self.gom.regras = '  '
        self.gom.save()
        self._login()
        self.assertEqual(self._claim(self.slots[0]).status_code, 200)

    def test_participation_in_another_gom_does_not_count(self):
        other = Gom.objects.create(name='Outro', slug='outro-r')
        self.assertTrue(needs_rules(self.joiner, self.gom))
        AceiteRegras.objects.create(participant=self.joiner, gom=other)
        self.assertTrue(needs_rules(self.joiner, self.gom))

    def test_ceg_page_shows_banner_to_first_timer_only(self):
        self._login()
        self.assertContains(self.client.get(reverse('ceg_detail', args=[self.ceg.slug])), 'Primeira vez com o Loja R?')
        AceiteRegras.objects.create(participant=self.joiner, gom=self.gom)
        page = self.client.get(reverse('ceg_detail', args=[self.ceg.slug]))
        self.assertNotContains(page, 'mustAccept: true')
        self.assertContains(page, 'Regras do Loja R')

    def test_accept_endpoint_requires_login(self):
        self.assertEqual(self.client.post(reverse('gom_rules_accept', args=[self.gom.slug])).status_code, 401)

    def test_settings_tab_saves_rules_and_date(self):
        owner = User.objects.create_user('dono-r', password='x')
        GomMembership.objects.create(user=owner, gom=self.gom, role='OWNER')
        self.client.force_login(owner)
        url = reverse('gom_settings_tab', args=['regras'])
        self.client.post(url, {'regras': 'Regra nova'})
        self.gom.refresh_from_db()
        self.assertEqual(self.gom.regras, 'Regra nova')
        self.assertIsNotNone(self.gom.regras_atualizadas_em)
        self.assertContains(self.client.get(url), 'Quem precisa aceitar')
