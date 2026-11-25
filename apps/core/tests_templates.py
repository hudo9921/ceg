"""XSS: valores controlados por joiners (nome, metadados) não podem quebrar tags/atributos."""
import json

from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import TestCase

from apps.cegs.models import AuditLog
from apps.participants.models import Participant

EVIL = '</script><script>alert(1)</script>"><img src=x onerror=alert(2)>'


class JsonEmbedFilterTests(TestCase):
    def render(self, tpl, **ctx):
        return Template(tpl).render(Context(ctx))

    def test_json_embed_escapes_tag_breakers_and_stays_valid_json(self):
        out = self.render('{{ v|json_embed }}', v={'name': EVIL})
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)
        self.assertEqual(json.loads(out)['name'], EVIL)

    def test_json_embed_accepts_prebuilt_json_string_and_default(self):
        out = self.render('{{ v|json_embed:"[]" }}', v=json.dumps([{'n': EVIL}]))
        self.assertNotIn('</script>', out)
        self.assertEqual(json.loads(out)[0]['n'], EVIL)
        self.assertEqual(self.render('{{ v|json_embed:"[]" }}', v=''), '[]')

    def test_json_attr_cannot_close_the_attribute(self):
        out = self.render('<b x="{{ v|json_attr }}">', v={'name': EVIL})
        self.assertEqual(out.count('"'), 2)
        self.assertNotIn('<img', out)


class StaffPagesXSSTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser('gom_xss', 'g@x.com', 'pass123')
        self.client.force_login(self.staff)
        self.evil = Participant.objects.create(name=EVIL, whatsapp='5511911112222')

    def test_creations_hub_does_not_render_raw_participant_markup(self):
        res = self.client.get('/creations/')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('<script>alert(1)</script>', res.content.decode())

    def test_audit_page_metadata_cannot_inject_html(self):
        AuditLog.objects.create(
            event_type=AuditLog.EventType.CLAIM_CREATED if hasattr(AuditLog.EventType, 'CLAIM_CREATED')
            else AuditLog.EventType.choices[0][0],
            action_label='teste', participant=self.evil, participant_name=EVIL,
            metadata={'nome': EVIL},
        )
        res = self.client.get('/auditoria/')
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertNotIn('<img src=x', html)
        self.assertNotIn('<script>alert(1)</script>', html)
