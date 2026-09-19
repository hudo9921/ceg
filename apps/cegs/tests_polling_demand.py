import json
import time
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from apps.groups.models import KpopGroup, Era
from apps.cegs.models import (
    CEG, CEGItemDefinition, TipoItem, CEGInterestVote, AuditLog, ItemSlot
)
from apps.cegs.polling_service import PollingDemandService, PollingError
from apps.participants.models import Participant, Claim, ParticipantNotification


class CEGPollingDemandTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username="admin", email="admin@test.com", password="password123"
        )
        self.group = KpopGroup.objects.create(name="IVE", slug="ive")
        self.era = Era.objects.create(group=self.group, name="I'VE MINE", slug="ive-mine")
        self.tipo_pc, _ = TipoItem.objects.get_or_create(nome="Photocard")

        # Create CEG in POLLING status with payment deadline configured
        self.payment_deadline = timezone.now() + timedelta(days=2)
        self.ceg = CEG.objects.create(
            era=self.era,
            title="IVE MINE Enquete CEG",
            slug="ive-mine-enquete-ceg",
            status=CEG.Status.POLLING,
            pix_key="pix@test.com",
            prazo_pagamento_item=self.payment_deadline,
        )

        # 3 Item Definitions (members)
        self.item_wonyoung = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name="Wonyoung POB",
            member_name="Wonyoung",
            tipo_item=self.tipo_pc,
            default_price=Decimal("60.00"),
            order_index=1
        )
        self.item_yujin = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name="Yujin POB",
            member_name="Yujin",
            tipo_item=self.tipo_pc,
            default_price=Decimal("55.00"),
            order_index=2
        )
        self.item_rei = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name="Rei POB",
            member_name="Rei",
            tipo_item=self.tipo_pc,
            default_price=Decimal("50.00"),
            order_index=3
        )

        # Participants
        self.p1 = Participant.objects.create(name="DIVE 1", whatsapp="5511999990001", username="dive1")
        self.p2 = Participant.objects.create(name="DIVE 2", whatsapp="5511999990002", username="dive2")
        self.p3 = Participant.objects.create(name="DIVE 3", whatsapp="5511999990003", username="dive3")

    def test_multi_member_voting(self):
        """Participant can vote on multiple members in a single request."""
        url = reverse('ceg_vote', kwargs={'slug': self.ceg.slug})
        payload = {
            'item_definition_ids': [self.item_wonyoung.id, self.item_yujin.id],
            'whatsapp': self.p1.whatsapp,
            'name': self.p1.name,
            'username': self.p1.username,
        }
        res = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['recorded_count'], 2)

        # Verify votes in DB
        votes = CEGInterestVote.objects.filter(ceg=self.ceg, participant=self.p1)
        self.assertEqual(votes.count(), 2)
        voted_item_ids = set(votes.values_list('item_definition_id', flat=True))
        self.assertEqual(voted_item_ids, {self.item_wonyoung.id, self.item_yujin.id})

        # Verify audit logs
        audit_logs = AuditLog.objects.filter(ceg=self.ceg, event_type=AuditLog.EventType.POLLING_VOTE)
        self.assertEqual(audit_logs.count(), 2)
        self.assertTrue(all(log.created_at is not None for log in audit_logs))

    def test_duplicate_vote_prevention(self):
        """Voting again for the same member is ignored or noted in result."""
        # First vote
        PollingDemandService.record_votes(
            ceg=self.ceg,
            item_definition_ids=[self.item_wonyoung.id],
            participant=self.p1
        )
        # Second vote
        res = PollingDemandService.record_votes(
            ceg=self.ceg,
            item_definition_ids=[self.item_wonyoung.id, self.item_rei.id],
            participant=self.p1
        )
        self.assertEqual(len(res['created_votes']), 1)
        self.assertEqual(len(res['existing_votes']), 1)
        self.assertEqual(res['created_votes'][0].item_definition_id, self.item_rei.id)

    def test_polling_summary_and_viability(self):
        """Summary correctly ranks voters by timestamp and calculates viable sets."""
        # DIVE 1 votes for Wonyoung & Yujin & Rei
        PollingDemandService.record_votes(self.ceg, [self.item_wonyoung.id, self.item_yujin.id, self.item_rei.id], self.p1)
        # Small delay to ensure strictly distinct timestamps
        time.sleep(0.01)
        # DIVE 2 votes for Wonyoung & Yujin
        PollingDemandService.record_votes(self.ceg, [self.item_wonyoung.id, self.item_yujin.id], self.p2)
        # DIVE 3 votes for Wonyoung
        PollingDemandService.record_votes(self.ceg, [self.item_wonyoung.id], self.p3)

        summary = PollingDemandService.get_polling_summary(self.ceg)
        self.assertEqual(summary['total_votes'], 6)
        # Only 1 set is 100% closed/viable because Rei has only 1 vote
        self.assertEqual(summary['viable_sets'], 1)
        self.assertEqual(summary['max_demand'], 3)

        # Wonyoung summary should have 3 voters in order [DIVE 1, DIVE 2, DIVE 3]
        wy_summary = next(s for s in summary['item_summaries'] if s['item_definition_id'] == self.item_wonyoung.id)
        self.assertEqual(wy_summary['votes_count'], 3)
        self.assertEqual(wy_summary['voters'][0]['participant_id'], self.p1.id)
        self.assertEqual(wy_summary['voters'][1]['participant_id'], self.p2.id)
        self.assertEqual(wy_summary['voters'][2]['participant_id'], self.p3.id)

    def test_consolidation_to_sets_allocates_slots_and_notifies_ONLY_winners(self):
        """
        Consolidation test verifying:
        1. Winning voters get slots in timestamp order.
        2. Official Claim objects are created.
        3. Winning voters get notifications with deadlines.
        4. Excedentes (unallocated voters) receive NO notifications.
        5. Full audit logging with microseconds.
        """
        # Scenario:
        # Wonyoung: 3 votes (p1, p2, p3)
        # Yujin: 2 votes (p1, p2)
        # Rei: 1 vote (p1)
        PollingDemandService.record_votes(self.ceg, [self.item_wonyoung.id, self.item_yujin.id, self.item_rei.id], self.p1)
        time.sleep(0.01)
        PollingDemandService.record_votes(self.ceg, [self.item_wonyoung.id, self.item_yujin.id], self.p2)
        time.sleep(0.01)
        PollingDemandService.record_votes(self.ceg, [self.item_wonyoung.id], self.p3)

        # Organizer decides to open 2 Sets (N = 2)
        self.client.login(username="admin", password="password123")
        url = reverse('consolidate_polling', kwargs={'slug': self.ceg.slug})
        res = self.client.post(url, data=json.dumps({'num_sets': 2}), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['sets_created'], 2)
        self.assertEqual(data['slots_allocated'], 5)
        self.assertEqual(data['unallocated_votes'], 1)

        # Refresh CEG from DB
        self.ceg.refresh_from_db()
        self.assertEqual(self.ceg.status, CEG.Status.OPEN)
        self.assertEqual(self.ceg.sets.count(), 2)

        # Check Sets & Slots allocation:
        # Set 1:
        # - Wonyoung -> claimed by p1
        # - Yujin -> claimed by p1
        # - Rei -> claimed by p1
        # Set 2:
        # - Wonyoung -> claimed by p2
        # - Yujin -> claimed by p2
        # - Rei -> empty (no 2nd vote)
        set1 = self.ceg.sets.get(set_number=1)
        set2 = self.ceg.sets.get(set_number=2)

        s1_wy = set1.slots.get(item_definition=self.item_wonyoung)
        self.assertEqual(s1_wy.claimed_by, self.p1)
        s2_wy = set2.slots.get(item_definition=self.item_wonyoung)
        self.assertEqual(s2_wy.claimed_by, self.p2)

        # Unallocated vote:
        # p3 voted for Wonyoung but only 2 sets opened -> p3 did NOT get a slot!
        p3_vote = CEGInterestVote.objects.get(ceg=self.ceg, item_definition=self.item_wonyoung, participant=self.p3)
        self.assertFalse(p3_vote.is_converted)
        self.assertIsNone(p3_vote.converted_slot)

        # CRITICAL CONSTRAINT VERIFICATION:
        # Notifications must be created ONLY for p1 and p2 (the winners).
        # p3 MUST NOT receive ANY notification!
        p1_notifs = ParticipantNotification.objects.filter(participant=self.p1)
        p2_notifs = ParticipantNotification.objects.filter(participant=self.p2)
        p3_notifs = ParticipantNotification.objects.filter(participant=self.p3)

        self.assertGreaterEqual(p1_notifs.count(), 1)
        self.assertGreaterEqual(p2_notifs.count(), 1)
        self.assertEqual(p3_notifs.count(), 0, "CRITICAL: Unallocated participant (p3) MUST NOT receive any notification!")

        # Verify notification content includes deadline & details
        p1_msg = p1_notifs.first().message
        self.assertIn(self.ceg.title, p1_msg)
        self.assertIn("Prazo de Pagamento:", p1_msg)

        # Verify Claims created in DB for p1 and p2
        p1_claims = Claim.objects.filter(participant=self.p1, slot__set__ceg=self.ceg)
        self.assertEqual(p1_claims.count(), 3)
        p2_claims = Claim.objects.filter(participant=self.p2, slot__set__ceg=self.ceg)
        self.assertEqual(p2_claims.count(), 2)
        p3_claims = Claim.objects.filter(participant=self.p3, slot__set__ceg=self.ceg)
        self.assertEqual(p3_claims.count(), 0)

        # Audit Logs check:
        # Must have POLLING_CONVERTED logs for both allocated and unallocated votes
        conv_logs = AuditLog.objects.filter(ceg=self.ceg, event_type=AuditLog.EventType.POLLING_CONVERTED)
        self.assertEqual(conv_logs.count(), 6)
        # Winner log
        self.assertTrue(conv_logs.filter(participant_id=self.p1.id, action_label__icontains="Voto Contemplado").exists())
        # Non-winner log
        self.assertTrue(conv_logs.filter(participant_id=self.p3.id, action_label__icontains="Voto Excedente").exists())

    def test_voting_on_non_polling_ceg_fails(self):
        """Attempting to vote on an OPEN or CLOSED CEG is rejected."""
        self.ceg.status = CEG.Status.OPEN
        self.ceg.save()

        url = reverse('ceg_vote', kwargs={'slug': self.ceg.slug})
        payload = {
            'item_definition_ids': [self.item_wonyoung.id],
            'whatsapp': self.p1.whatsapp,
            'name': self.p1.name,
        }
        res = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data['success'])

    def test_polling_standby_countdown_blocks_and_unlocks_voting(self):
        """A Polling CEG with opens_at in the future is in standby, rejecting votes until opens_at passes."""
        # 1. Configure future opens_at (1 hour in future)
        self.ceg.opens_at = timezone.now() + timezone.timedelta(hours=1)
        self.ceg.save()

        self.assertTrue(self.ceg.is_standby)
        self.assertGreater(self.ceg.countdown_seconds, 0)

        # 2. Service-level attempt raises PollingError
        with self.assertRaises(PollingError) as ctx:
            PollingDemandService.record_votes(
                self.ceg,
                [self.item_wonyoung.id],
                self.p1
            )
        self.assertIn("ainda não abriu", str(ctx.exception))

        # 3. HTTP View attempt returns 400 with error message
        url = reverse('ceg_vote', kwargs={'slug': self.ceg.slug})
        payload = {
            'item_definition_ids': [self.item_wonyoung.id],
            'whatsapp': self.p1.whatsapp,
            'name': self.p1.name,
        }
        res = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data['success'])
        self.assertIn("ainda não abriu", data['message'])

        # 4. Immediate opening (opens_at in the past or cleared) unlocks voting
        self.ceg.opens_at = timezone.now() - timezone.timedelta(minutes=5)
        self.ceg.save()

        self.assertFalse(self.ceg.is_standby)
        self.assertEqual(self.ceg.countdown_seconds, 0)

        res2 = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertTrue(data2['success'])
        self.assertEqual(self.ceg.interest_votes.count(), 1)

    def test_vote_audit_accordion_and_dark_mode_rendering(self):
        """Test model audit properties (timestamp, masked phone) and template accordion rendering."""
        # 1. Record a vote
        PollingDemandService.record_votes(
            ceg=self.ceg,
            item_definition_ids=[self.item_wonyoung.id],
            participant=self.p1
        )
        vote = CEGInterestVote.objects.get(ceg=self.ceg, item_definition=self.item_wonyoung, participant=self.p1)

        # 2. Check model properties
        self.assertTrue(len(vote.formatted_created_at) > 0)
        self.assertIn(":", vote.formatted_created_at)
        self.assertIn(".", vote.formatted_created_at)  # microsecond/millisecond precision
        self.assertTrue(vote.masked_whatsapp.startswith("****-") or "*" in vote.masked_whatsapp)

        # 3. Request CEG Detail Page
        url = reverse('ceg_detail', kwargs={'slug': self.ceg.slug})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        # 4. Assert context contains polling_item_definitions
        self.assertIn('polling_item_definitions', res.context)

        # 5. Assert HTML includes accordion controls and dark mode classes
        content = res.content.decode('utf-8')
        self.assertIn('toggleVotesAccordion', content)
        self.assertIn('isVotesAccordionOpen', content)
        self.assertIn('Ver Votos', content)
        self.assertIn('dark:bg-[#131B2E]', content)
        self.assertIn(self.p1.name, content)
        self.assertIn(vote.formatted_created_at, content)

