"""Conversas (S5): abrir por assunto, enviar dos dois lados, não lidas, avisos e isolamento entre GOMs."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import PacoteNacional
from apps.goms.models import Gom, GomMembership
from apps.goms.services import set_permissions
from apps.participants.models import Participant

from .models import Conversa, Mensagem

User = get_user_model()


class ConversaTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja M', slug='loja-m')
        self.staff = User.objects.create_user('dono-m', password='x')
        GomMembership.objects.create(user=self.staff, gom=self.gom, role='OWNER')
        self.joiner = Participant.objects.create(whatsapp='5511955550000', name='Ana')
        self.joiner.known_by_goms.add(self.gom)
        self.pacote = PacoteNacional.objects.create(gom=self.gom, participant=self.joiner)

    def _as_joiner(self, p=None):
        session = self.client.session
        session['participant_id'] = (p or self.joiner).id
        session.save()

    def _start(self, texto='Meu pacote chegou?'):
        self._as_joiner()
        self.client.post(reverse('joiner_mensagem_nova'), {'gom_id': self.gom.id, 'tipo': 'pacote',
                                                           'alvo_id': self.pacote.id, 'texto': texto})
        return Conversa.objects.get()

    def test_joiner_starts_about_package_once(self):
        c = self._start()
        self._start('De novo')
        self.assertEqual(Conversa.objects.count(), 1)
        self.assertEqual((c.assunto, c.mensagens.count()), (f'Pacote {self.pacote.identificador}', 2))
        c.refresh_from_db()
        self.assertEqual(c.nao_lidas_gom, 2)
        self.assertEqual(self.gom.notificacoes.filter(title__startswith='Mensagem de').count(), 1)  # um aviso por rodada

    def test_gom_replies_and_joiner_is_notified_and_reads(self):
        c = self._start()
        self.client.force_login(self.staff)
        page = self.client.get(reverse('gom_mensagens') + f'?c={c.id}').content.decode()
        self.assertIn('Meu pacote chegou?', page)
        c.refresh_from_db()
        self.assertEqual(c.nao_lidas_gom, 0)
        res = self.client.post(reverse('gom_mensagem_enviar', args=[c.id]), {'texto': 'Chegou sim!'},
                               HTTP_ACCEPT='application/json')
        self.assertTrue(res.json()['success'])
        self.assertTrue(self.joiner.notifications.filter(title='Loja M respondeu').exists())
        self._as_joiner()
        data = self.client.get(reverse('joiner_mensagens_novas', args=[c.id]) + '?depois=0').json()
        self.assertEqual([m['texto'] for m in data['mensagens']], ['Meu pacote chegou?', 'Chegou sim!'])
        self.assertEqual([m['meu'] for m in data['mensagens']], [True, False])

    def test_joiner_cannot_open_someone_elses_package_or_conversation(self):
        c = self._start()
        other = Participant.objects.create(whatsapp='5511955559999', name='Bia')
        self._as_joiner(other)
        self.client.post(reverse('joiner_mensagem_nova'), {'gom_id': self.gom.id, 'tipo': 'pacote', 'alvo_id': self.pacote.id})
        self.assertEqual(Conversa.objects.count(), 1)
        self.assertEqual(self.client.get(reverse('joiner_mensagens_novas', args=[c.id])).status_code, 404)

    def test_other_gom_and_admin_without_permission_are_blocked(self):
        c = self._start()
        other = Gom.objects.create(name='Outra', slug='outra-m')
        user = User.objects.create_user('dono-outra-m', password='x')
        GomMembership.objects.create(user=user, gom=other, role='OWNER')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('gom_mensagens_novas', args=[c.id])).status_code, 404)
        admin = User.objects.create_user('adm-m', password='x')
        set_permissions(GomMembership.objects.create(user=admin, gom=self.gom, role='ADMIN'), ['ceg.editar'], self.staff)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('gom_mensagens')).status_code, 403)

    def test_empty_message_refused_and_export_includes_messages(self):
        c = self._start()
        res = self.client.post(reverse('joiner_mensagem_enviar', args=[c.id]), {'texto': '  '}, HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 400)
        from apps.core.privacy import export_participant_data
        self.assertEqual(export_participant_data(self.joiner)['mensagens'][0]['texto'], 'Meu pacote chegou?')

    def test_gom_starts_conversation_from_360(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('gom_mensagem_nova'), {'participant_id': self.joiner.id})
        c = Conversa.objects.get()
        self.assertEqual((c.tipo, c.participant), (Conversa.Tipo.GERAL, self.joiner))
        self.assertEqual(Mensagem.objects.count(), 0)
