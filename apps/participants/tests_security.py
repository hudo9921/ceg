"""
Regressões de segurança da Fase 1 (docs/SECURITY_PLAN.md):
vazamento de OTP, rate limit/lockout, open redirect, rotação de sessão
e troca de identidade via claims/votos.
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.auth_otp.models import WhatsAppOTP
from apps.auth_otp.services import OTPService, MAX_FAILED_VERIFICATIONS_PER_DAY
from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot, CEGInterestVote
from apps.cegs.services import ClaimService
from apps.groups.models import KpopGroup, Era
from apps.participants.models import Participant, Claim

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
PHONE = '5511912345678'


class OTPLeakTests(TestCase):
    def test_ajax_send_otp_never_returns_code_in_production(self):
        res = self.client.post('/me/login/', {'action': 'send_otp', 'phone': PHONE}, **AJAX)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertNotIn('dev_code', data)
        code = WhatsAppOTP.objects.get(phone=PHONE).code
        self.assertNotIn(code, res.content.decode())

    @override_settings(DEBUG=True, WHATSAPP_PROVIDER='evolution')
    def test_debug_with_real_provider_does_not_expose_code(self):
        from unittest import mock
        with mock.patch('apps.auth_otp.services.get_whatsapp_provider') as provider:
            provider.return_value.send_message.return_value = True
            res = self.client.post('/me/login/', {'action': 'send_otp', 'phone': PHONE}, **AJAX)
        self.assertNotIn('dev_code', res.json())
        res = self.client.get(f'/me/login/?step=verify&phone={PHONE}')
        self.assertIsNone(res.context['dev_code'])

    @override_settings(DEBUG=True, WHATSAPP_PROVIDER='console')
    def test_local_dev_console_still_shows_code(self):
        res = self.client.post('/me/login/', {'action': 'send_otp', 'phone': PHONE}, **AJAX)
        self.assertEqual(res.json()['dev_code'], WhatsAppOTP.objects.get(phone=PHONE).code)


class OTPRateLimitTests(TestCase):
    def test_fourth_send_in_15_minutes_is_refused(self):
        for _ in range(3):
            ok, _, _ = OTPService.send_otp(PHONE)
            self.assertTrue(ok)
        ok, msg, code = OTPService.send_otp(PHONE)
        self.assertFalse(ok)
        self.assertIsNone(code)
        self.assertEqual(WhatsAppOTP.objects.filter(phone=PHONE).count(), 3)

    def test_per_ip_limit_across_many_phones(self):
        for i in range(20):
            ok, _, _ = OTPService.send_otp(f'55119000000{i:02d}', ip_address='203.0.113.9')
            self.assertTrue(ok)
        ok, _, _ = OTPService.send_otp('5511988887777', ip_address='203.0.113.9')
        self.assertFalse(ok)
        ok, _, _ = OTPService.send_otp('5511988887777', ip_address='198.51.100.1')
        self.assertTrue(ok)

    def test_new_code_invalidates_previous_one(self):
        _, _, first = OTPService.send_otp(PHONE)
        _, _, second = OTPService.send_otp(PHONE)
        if first != second:
            ok, _, _ = OTPService.verify_otp(PHONE, first)
            self.assertFalse(ok)
        ok, _, _ = OTPService.verify_otp(PHONE, second)
        self.assertTrue(ok)

    def test_phone_locked_after_too_many_failures(self):
        WhatsAppOTP.objects.create(
            phone=PHONE, code='111111', expires_at=timezone.now() + timedelta(minutes=10),
            attempts=MAX_FAILED_VERIFICATIONS_PER_DAY, is_used=True,
        )
        ok, _, _ = OTPService.send_otp(PHONE)
        self.assertFalse(ok)
        live = WhatsAppOTP.objects.create(
            phone=PHONE, code='222222', expires_at=timezone.now() + timedelta(minutes=10),
        )
        ok, _, participant = OTPService.verify_otp(PHONE, live.code)
        self.assertFalse(ok)
        self.assertIsNone(participant)

    def test_failed_attempts_older_than_24h_do_not_lock(self):
        old = WhatsAppOTP.objects.create(
            phone=PHONE, code='111111', expires_at=timezone.now(),
            attempts=MAX_FAILED_VERIFICATIONS_PER_DAY, is_used=True,
        )
        WhatsAppOTP.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(hours=25))
        ok, _, _ = OTPService.send_otp(PHONE)
        self.assertTrue(ok)


class LoginRedirectAndSessionTests(TestCase):
    def _verify(self, next_url):
        _, _, code = OTPService.send_otp(PHONE)
        return self.client.post('/me/login/', {
            'action': 'verify_otp', 'phone': PHONE, 'code': code, 'next': next_url,
        })

    def test_protocol_relative_next_is_rejected(self):
        res = self._verify('//evil.example.com/phish')
        self.assertRedirects(res, '/me/', fetch_redirect_response=False)

    def test_absolute_external_next_is_rejected(self):
        res = self._verify('https://evil.example.com/')
        self.assertRedirects(res, '/me/', fetch_redirect_response=False)

    def test_internal_next_is_kept(self):
        res = self._verify('/ceg/alguma-ceg/')
        self.assertRedirects(res, '/ceg/alguma-ceg/', fetch_redirect_response=False)

    def test_session_key_rotates_on_login(self):
        self.client.get('/me/login/')
        session = self.client.session
        session['pre_login_marker'] = True
        session.save()
        before = session.session_key
        self._verify('')
        self.assertNotEqual(before, self.client.session.session_key)
        self.assertEqual(
            self.client.session['participant_id'],
            Participant.objects.get(whatsapp=PHONE).id,
        )

    def test_logout_clears_participant(self):
        self._verify('')
        self.client.get(reverse('logout_participant'))
        self.assertNotIn('participant_id', self.client.session)


class IdentitySpoofingTests(TestCase):
    """Um joiner autenticado não pode agir (nem logar) como outro número."""

    def setUp(self):
        ClaimService.reset_in_memory_counters()
        group = KpopGroup.objects.create(name="tripleS")
        era = Era.objects.create(group=group, name="Assemble24")
        self.ceg = CEG.objects.create(
            era=era, title="CEG Segurança", status=CEG.Status.OPEN,
            opens_at=timezone.now() - timedelta(minutes=1), pix_key="pix@test.com",
        )
        self.item = CEGItemDefinition.objects.create(
            ceg=self.ceg, name="PC Seoyeon", member_name="Seoyeon", default_price=Decimal("50.00"),
        )
        cset = CEGSet.objects.create(ceg=self.ceg, set_number=1, is_active=True)
        self.slot = ItemSlot.objects.create(
            set=cset, item_definition=self.item, price=Decimal("50.00"),
            status=ItemSlot.Status.AVAILABLE,
        )
        self.attacker = Participant.objects.create(name="Attacker", whatsapp="5511900000001")
        self.victim = Participant.objects.create(name="Victim", whatsapp="5511900000002")

    def _login_as(self, participant):
        session = self.client.session
        session['participant_id'] = participant.id
        session.save()

    def _assert_victim_untouched(self):
        self.victim.refresh_from_db()
        self.assertEqual(self.victim.name, "Victim")
        self.assertFalse(Claim.objects.filter(participant=self.victim).exists())
        self.assertEqual(self.client.session['participant_id'], self.attacker.id)

    def test_single_claim_with_foreign_whatsapp_stays_on_session_owner(self):
        self._login_as(self.attacker)
        self.client.post(
            reverse('claim_slot', args=[self.slot.id]),
            {'whatsapp': self.victim.whatsapp, 'name': 'Hacked'}, **AJAX,
        )
        self._assert_victim_untouched()
        self.assertEqual(Claim.objects.get(slot=self.slot).participant, self.attacker)

    def test_bulk_claim_with_foreign_whatsapp_stays_on_session_owner(self):
        self._login_as(self.attacker)
        self.client.post(
            reverse('bulk_claim', args=[self.ceg.slug]),
            data=json.dumps({'slot_ids': [self.slot.id], 'whatsapp': self.victim.whatsapp}),
            content_type='application/json',
        )
        self._assert_victim_untouched()
        self.assertEqual(Claim.objects.get(slot=self.slot).participant, self.attacker)

    def test_staff_can_still_claim_on_behalf_of_a_joiner(self):
        User.objects.create_superuser('gom', 'gom@test.com', 'pass123')
        self.client.login(username='gom', password='pass123')
        self.client.post(
            reverse('claim_slot', args=[self.slot.id]),
            {'whatsapp': self.victim.whatsapp, 'name': 'Victim'}, **AJAX,
        )
        self.assertEqual(Claim.objects.get(slot=self.slot).participant, self.victim)
        self.assertNotIn('participant_id', self.client.session)

    def _polling_vote(self, payload):
        self.ceg.status = CEG.Status.POLLING
        self.ceg.save()
        return self.client.post(
            reverse('ceg_vote', args=[self.ceg.slug]),
            data=json.dumps({'item_definition_ids': [self.item.id], **payload}),
            content_type='application/json',
        )

    def test_anonymous_vote_requires_login_and_never_creates_session(self):
        res = self._polling_vote({'whatsapp': self.victim.whatsapp, 'name': 'Hacked'})
        self.assertEqual(res.status_code, 401)
        self.assertTrue(res.json()['requires_auth'])
        self.assertNotIn('participant_id', self.client.session)
        self.assertFalse(CEGInterestVote.objects.exists())
        self.victim.refresh_from_db()
        self.assertEqual(self.victim.name, "Victim")

    def test_logged_vote_with_foreign_whatsapp_counts_for_session_owner(self):
        self._login_as(self.attacker)
        res = self._polling_vote({'whatsapp': self.victim.whatsapp})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(CEGInterestVote.objects.get().participant, self.attacker)
        self._assert_victim_untouched()
