"""Telas das cobranças Pix: joiner (gerar, Já paguei, cancelar) e GOM (fila, Recebi, comprovante, Cobrar no WhatsApp)."""
import io
import json
from datetime import timedelta
from urllib.parse import unquote

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.goms.models import Gom, GomMembership
from apps.goms.services import set_permissions
from apps.participants.models import Participant

from . import services
from .models import Cobranca
from .tests import CobrancaFixture


def _png():
    buf = io.BytesIO()
    Image.new('RGB', (40, 40), 'white').save(buf, format='PNG')
    return SimpleUploadedFile('print.png', buf.getvalue(), content_type='image/png')


class JoinerViewsTests(CobrancaFixture):
    def setUp(self):
        super().setUp()
        session = self.client.session
        session['participant_id'] = self.joiner.id
        session.save()
        self.item = 'item:ceg:%d' % self.ceg.id

    def _gerar(self, *groups):
        return self.client.post(reverse('pix_gerar'), data=json.dumps({'gom_id': self.gom.id, 'groups': list(groups)}),
                                content_type='application/json')

    def test_gerar_returns_qr_code_and_reference(self):
        data = self._gerar(self.item).json()
        self.assertTrue(data['success'])
        pix = data['cobrancas'][0]
        self.assertEqual(pix['total'], '40.00')
        self.assertTrue(pix['qr'].startswith('data:image/svg+xml;base64,'))
        self.assertIn('br.gov.bcb.pix', pix['code'])

    def test_paguei_with_receipt_then_page_shows_in_analysis(self):
        ref = self._gerar(self.item).json()['cobrancas'][0]['ref']
        res = self.client.post(reverse('pix_paguei', args=[ref]), {'comprovante': _png()})
        self.assertTrue(res.json()['success'])
        cob = Cobranca.objects.get(referencia=ref)
        self.assertEqual((cob.status, cob.comprovante.content_type), ('INFORMADA', 'image/jpeg'))
        page = self.client.get(reverse('my_claims') + '?tab=pagar').content.decode()
        self.assertIn('Pagamento em análise', page)
        self.assertIn(ref, page)

    def test_bad_receipt_is_refused(self):
        ref = self._gerar(self.item).json()['cobrancas'][0]['ref']
        res = self.client.post(reverse('pix_paguei', args=[ref]),
                               {'comprovante': SimpleUploadedFile('x.txt', b'nada', content_type='text/plain')})
        self.assertEqual(res.status_code, 400)

    def test_other_joiner_cannot_see_or_cancel(self):
        ref = self._gerar(self.item).json()['cobrancas'][0]['ref']
        other = Participant.objects.create(whatsapp='5511900009999', name='Outra')
        session = self.client.session
        session['participant_id'] = other.id
        session.save()
        self.assertEqual(self.client.get(reverse('pix_ver', args=[ref])).status_code, 404)
        self.assertEqual(self.client.post(reverse('pix_cancelar', args=[ref])).status_code, 404)

    def test_needs_login(self):
        self.client.session.flush()
        self.client.cookies.clear()
        self.assertEqual(self._gerar(self.item).status_code, 401)

    def test_stale_pix_expires_and_frees_items(self):
        ref = self._gerar(self.item).json()['cobrancas'][0]['ref']
        Cobranca.objects.filter(referencia=ref).update(criada_em=timezone.now() - timedelta(days=8))
        self.assertIn(self.item, [g['key'] for g in services.open_groups(self.joiner, self.gom)])
        self.assertEqual(Cobranca.objects.get(referencia=ref).status, 'CANCELADA')

    def test_gom_without_receiver_keeps_copy_key(self):
        self.gom.pix_nome_recebedor = ''
        self.gom.save()
        page = self.client.get(reverse('my_claims') + '?tab=pagar').content.decode()
        self.assertIn('Copiar Pix', page)
        self.assertNotIn('x-data="pixPay(', page)


class GomViewsTests(CobrancaFixture):
    def setUp(self):
        super().setUp()
        GomMembership.objects.create(user=self.staff, gom=self.gom, role='OWNER')
        self.client.force_login(self.staff)
        self.cob = services.create_cobrancas(self.joiner, self.gom, ['item:ceg:%d' % self.ceg.id])[0]

    def test_queue_lists_and_recebi_confirms(self):
        services.informar(self.cob, (b'%PDF-1.4 teste', 'application/pdf'))
        page = self.client.get(reverse('pix_fila')).content.decode()
        self.assertIn(self.cob.referencia, page)
        self.assertIn('Já pagou', page)
        proof = self.client.get(reverse('pix_comprovante', args=[self.cob.referencia]))
        self.assertEqual((proof.status_code, proof['Content-Type']), (200, 'application/pdf'))
        self.client.post(reverse('pix_fila'), {'ref': self.cob.referencia, 'action': 'recebi'})
        self.slot.refresh_from_db()
        self.assertTrue(self.slot.is_item_paid)

    def test_nao_recebi_with_note(self):
        self.client.post(reverse('pix_fila'), {'ref': self.cob.referencia, 'action': 'nao_recebi', 'recado': 'Não caiu'})
        self.cob.refresh_from_db()
        self.assertEqual((self.cob.status, self.cob.recado), ('RECUSADA', 'Não caiu'))

    def test_cobrar_no_whatsapp_builds_link_with_pix_code(self):
        page = self.client.get(reverse('pix_cobrar', args=[self.joiner.id])).content.decode()
        self.assertIn('https://wa.me/5511933332222?text=', page)
        link = page.split('https://wa.me/5511933332222?text=')[1].split('"')[0]
        self.assertIn(self.cob.copia_e_cola, unquote(link.replace('&amp;', '&')))

    def test_cobrar_creates_pix_for_offline_joiner(self):
        self.client.post(reverse('pix_cobrar', args=[self.joiner.id]), {'groups': ['frete:ceg:%d' % self.ceg.id]})
        nova = Cobranca.objects.exclude(pk=self.cob.pk).get()
        self.assertEqual((nova.valor_total, nova.criada_por), (self.slot.frete_inter, self.staff))

    def test_admin_without_payment_permission_is_denied(self):
        from django.contrib.auth import get_user_model
        admin = get_user_model().objects.create_user('adm-sem-pag', password='x')
        set_permissions(GomMembership.objects.create(user=admin, gom=self.gom, role='ADMIN'), ['ceg.editar'], self.staff)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('pix_fila')).status_code, 403)

    def test_other_gom_cannot_touch_this_charge(self):
        from django.contrib.auth import get_user_model
        other = Gom.objects.create(name='Outra', slug='outra-pg')
        user = get_user_model().objects.create_user('dono-outra', password='x')
        GomMembership.objects.create(user=user, gom=other, role='OWNER')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('pix_comprovante', args=[self.cob.referencia])).status_code, 404)
        self.client.post(reverse('pix_fila'), {'ref': self.cob.referencia, 'action': 'recebi'})
        self.cob.refresh_from_db()
        self.assertEqual(self.cob.status, 'AGUARDANDO')


class InvalidKeyLineTests(JoinerViewsTests):
    def test_line_with_free_text_key_keeps_copy_mode_others_get_pix(self):
        self.ceg.pix_key = 'Nubank, me chama no direct'
        self.ceg.pix_key_frete = 'frete@pix.com'
        self.ceg.save()
        page = self.client.get(reverse('my_claims') + '?tab=pagar').content.decode()
        self.assertIn('Copiar Pix', page)                       # item da CEG: chave em texto livre
        self.assertIn('value="frete:ceg:%d"' % self.ceg.id, page)  # frete com chave válida: QR ok
        self.assertNotIn('value="item:ceg:%d"' % self.ceg.id, page)
