"""Fase 4 (LGPD): criptografia em repouso, direitos do titular, auditoria e retenção."""
import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.auth_otp.models import WhatsAppOTP
from apps.cegs.models import (
    AuditLog, CEG, CEGItemDefinition, CEGSet, GOMNotification, ItemSlot, PacoteNacional,
)
from apps.core.crypto import PREFIX, DecryptionError
from apps.core.privacy import AnonymizationBlocked, ANONYMIZED_NAME, anonymize_participant
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Claim, Participant

ADDRESS = 'Rua das Flores, 123 — Ap 45, São Paulo/SP'


def raw_column(pacote, column):
    with connection.cursor() as cur:
        cur.execute(f"SELECT {column} FROM cegs_pacotenacional WHERE id = %s", [pacote.id])
        return cur.fetchone()[0]


class EncryptionAtRestTests(TestCase):
    def setUp(self):
        self.p = Participant.objects.create(name='Ana', whatsapp='5511911110000')

    def test_address_is_encrypted_in_database_and_plain_in_python(self):
        pacote = PacoteNacional.objects.create(
            participant=self.p, endereco_destinatario=ADDRESS, cep_destinatario='01310-100')
        self.assertTrue(raw_column(pacote, 'endereco_destinatario').startswith(PREFIX))
        self.assertNotIn('Flores', raw_column(pacote, 'endereco_destinatario'))
        self.assertNotIn('01310', raw_column(pacote, 'cep_destinatario'))
        pacote.refresh_from_db()
        self.assertEqual(pacote.endereco_destinatario, ADDRESS)
        self.assertEqual(pacote.cep_destinatario, '01310-100')

    def test_legacy_plaintext_is_readable_and_encrypted_on_save(self):
        pacote = PacoteNacional.objects.create(participant=self.p)
        PacoteNacional.objects.filter(id=pacote.id).update(cep_destinatario='')
        with connection.cursor() as cur:
            cur.execute("UPDATE cegs_pacotenacional SET endereco_destinatario=%s WHERE id=%s", [ADDRESS, pacote.id])
        pacote.refresh_from_db()
        self.assertEqual(pacote.endereco_destinatario, ADDRESS)
        pacote.save()
        self.assertTrue(raw_column(pacote, 'endereco_destinatario').startswith(PREFIX))

    def test_key_rotation_and_wrong_key(self):
        old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with override_settings(FIELD_ENCRYPTION_KEYS=[old]):
            pacote = PacoteNacional.objects.create(participant=self.p, endereco_destinatario=ADDRESS)
        with override_settings(FIELD_ENCRYPTION_KEYS=[new, old]):
            call_command('rotate_encryption_keys', stdout=StringIO())
        with override_settings(FIELD_ENCRYPTION_KEYS=[new]):
            pacote.refresh_from_db()
            self.assertEqual(pacote.endereco_destinatario, ADDRESS)
        with override_settings(FIELD_ENCRYPTION_KEYS=[Fernet.generate_key().decode()]):
            with self.assertRaises(DecryptionError):
                pacote.refresh_from_db()


class DataSubjectRightsTests(TestCase):
    def setUp(self):
        self.p = Participant.objects.create(name='Ana Lima', whatsapp='5511922220000', social_handle='@ana')
        self.pacote = PacoteNacional.objects.create(
            participant=self.p, endereco_destinatario=ADDRESS, status=PacoteNacional.Status.ENTREGUE)

    def _login(self):
        s = self.client.session
        s['participant_id'] = self.p.id
        s.save()

    def test_export_requires_login(self):
        res = self.client.get(reverse('export_my_data'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('/me/login/', res['Location'])

    def test_export_returns_own_data_including_decrypted_address(self):
        self._login()
        res = self.client.get(reverse('export_my_data'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('attachment', res['Content-Disposition'])
        data = json.loads(res.content)
        self.assertEqual(data['perfil']['whatsapp'], self.p.whatsapp)
        self.assertEqual(data['pacotes_nacionais'][0]['endereco'], ADDRESS)
        self.assertTrue(AuditLog.objects.filter(event_type=AuditLog.EventType.DATA_EXPORT, participant=self.p).exists())

    def test_deletion_request_needs_confirmation_and_notifies_gom_once(self):
        self._login()
        self.client.post(reverse('request_data_deletion'), {'confirmacao': 'nao'})
        self.assertFalse(GOMNotification.objects.filter(participant=self.p, title__icontains='exclusão').exists())
        for _ in range(2):
            self.client.post(reverse('request_data_deletion'), {'confirmacao': 'excluir'})
        self.assertEqual(GOMNotification.objects.filter(
            participant=self.p, title__icontains='exclusão').count(), 1)

    def test_privacy_page_is_public(self):
        self.assertEqual(self.client.get(reverse('privacy_policy')).status_code, 200)


class AnonymizationTests(TestCase):
    def setUp(self):
        self.p = Participant.objects.create(name='Bia Souza', whatsapp='5511933330000', social_handle='@bia')
        group = KpopGroup.objects.create(name='TWICE')
        era = Era.objects.create(group=group, name='With YOU-th')
        ceg = CEG.objects.create(era=era, title='CEG Anon', status=CEG.Status.OPEN, pix_key='pix@x.com')
        item = CEGItemDefinition.objects.create(ceg=ceg, name='PC Nayeon', default_price=Decimal('40'))
        cset = CEGSet.objects.create(ceg=ceg, set_number=1, is_active=True)
        self.slot = ItemSlot.objects.create(set=cset, item_definition=item, price=Decimal('40'))

    def test_blocked_while_there_are_open_obligations(self):
        Claim.objects.create(slot=self.slot, participant=self.p, total_price=Decimal('40'))
        with self.assertRaises(AnonymizationBlocked):
            anonymize_participant(self.p)
        self.p.refresh_from_db()
        self.assertEqual(self.p.name, 'Bia Souza')

    def test_anonymize_removes_identity_and_old_phone_cannot_log_in_as_it(self):
        pacote = PacoteNacional.objects.create(
            participant=self.p, endereco_destinatario=ADDRESS, status=PacoteNacional.Status.ENTREGUE)
        WhatsAppOTP.objects.create(phone=self.p.whatsapp, code='123456',
                                   expires_at=timezone.now() + timedelta(minutes=5))
        anonymize_participant(self.p)
        self.p.refresh_from_db()
        pacote.refresh_from_db()
        self.assertEqual(self.p.name, ANONYMIZED_NAME)
        self.assertEqual(self.p.social_handle, '')
        self.assertEqual(self.p.whatsapp, f'removido-{self.p.id}')
        self.assertEqual(pacote.endereco_destinatario, '')
        self.assertFalse(WhatsAppOTP.objects.filter(phone='5511933330000').exists())
        self.assertFalse(AuditLog.objects.filter(participant_phone='5511933330000').exists())
        from apps.auth_otp.services import OTPService
        _, _, code = OTPService.send_otp('5511933330000')
        ok, _, logged = OTPService.verify_otp('5511933330000', code)
        self.assertTrue(ok)
        self.assertNotEqual(logged.id, self.p.id)  # o número antigo vira uma conta nova e vazia

    def test_admin_action_reports_blocked_participants(self):
        Claim.objects.create(slot=self.slot, participant=self.p, total_price=Decimal('40'))
        admin = User.objects.create_superuser('gom_lgpd', 'g@l.com', 'x')
        self.client.force_login(admin)
        res = self.client.post('/admin/participants/participant/', {
            'action': 'anonymize_lgpd', '_selected_action': [self.p.id]}, follow=True)
        self.assertContains(res, 'Não anonimizado')


class PIIAccessAndRetentionTests(TestCase):
    def setUp(self):
        self.p = Participant.objects.create(name='Caio', whatsapp='5511944440000')

    def test_admin_viewing_address_is_audited(self):
        pacote = PacoteNacional.objects.create(participant=self.p, endereco_destinatario=ADDRESS)
        self.client.force_login(User.objects.create_superuser('gom_pii', 'g@p.com', 'x'))
        res = self.client.get(f'/admin/cegs/pacotenacional/{pacote.id}/change/')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(
            event_type=AuditLog.EventType.PII_ACCESS, participant=self.p).exists())

    @override_settings(PII_RETENTION_DAYS=180, OTP_RETENTION_DAYS=30)
    def test_purge_clears_old_delivered_addresses_and_old_otps(self):
        old = PacoteNacional.objects.create(
            participant=self.p, endereco_destinatario=ADDRESS, status=PacoteNacional.Status.ENTREGUE,
            data_entrega=timezone.now() - timedelta(days=200))
        recent = PacoteNacional.objects.create(
            participant=self.p, endereco_destinatario=ADDRESS, status=PacoteNacional.Status.ENTREGUE,
            data_entrega=timezone.now() - timedelta(days=10))
        in_transit = PacoteNacional.objects.create(
            participant=self.p, endereco_destinatario=ADDRESS, status=PacoteNacional.Status.ENVIADO)
        otp = WhatsAppOTP.objects.create(phone='5511944440000', code='111111', expires_at=timezone.now())
        WhatsAppOTP.objects.filter(id=otp.id).update(created_at=timezone.now() - timedelta(days=40))

        call_command('purge_personal_data', '--dry-run', stdout=StringIO())
        old.refresh_from_db()
        self.assertEqual(old.endereco_destinatario, ADDRESS)

        call_command('purge_personal_data', stdout=StringIO())
        for obj in (old, recent, in_transit):
            obj.refresh_from_db()
        self.assertEqual(old.endereco_destinatario, '')
        self.assertEqual(recent.endereco_destinatario, ADDRESS)
        self.assertEqual(in_transit.endereco_destinatario, ADDRESS)
        self.assertFalse(WhatsAppOTP.objects.filter(id=otp.id).exists())
