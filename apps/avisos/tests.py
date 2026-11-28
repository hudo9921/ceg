"""Push (S4): inscrever/cancelar, quem recebe o quê, limpeza de inscrição morta, service worker e manifesto."""
import base64
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.cegs.models import GOMNotification
from apps.goms.models import Gom, GomMembership
from apps.participants.models import Participant, ParticipantNotification

from .models import Inscricao
from .vapid import chave_publica

User = get_user_model()


def sub(n):
    return {'endpoint': f'https://push.example.com/{n}', 'keys': {'p256dh': f'chave{n}', 'auth': f'auth{n}'}}


@override_settings(PUSH_SINCRONO=True)
class PushTests(TestCase):
    def setUp(self):
        self.ana = Participant.objects.create(whatsapp='5511900001111', name='Ana')
        self.gom = Gom.objects.create(name='Loja Push', slug='loja-push')
        self.dono = User.objects.create_user('dono-push', password='x')
        GomMembership.objects.create(user=self.dono, gom=self.gom, role='OWNER')

    def entrar(self):
        session = self.client.session
        session['participant_id'] = self.ana.id
        session.save()

    def inscrever(self, n):
        return self.client.post(reverse('push_inscrever'), json.dumps({'subscription': sub(n), 'aparelho': 'Android'}),
                                content_type='application/json')

    def test_inscrever_exige_login_e_cancelar(self):
        self.assertEqual(self.inscrever(1).status_code, 401)
        self.entrar()
        self.assertEqual(self.inscrever(1).status_code, 200)
        self.assertEqual(Inscricao.objects.get().participant, self.ana)
        self.client.post(reverse('push_cancelar'), json.dumps({'endpoint': sub(1)['endpoint']}), content_type='application/json')
        self.assertFalse(Inscricao.objects.exists())

    def test_aviso_do_joiner_vai_por_push(self):
        Inscricao.objects.create(participant=self.ana, **{k: v for k, v in [('endpoint', sub(1)['endpoint']),
                                                                             ('p256dh', 'k'), ('auth', 'a')]})
        with mock.patch('pywebpush.webpush') as webpush, self.captureOnCommitCallbacks(execute=True):
            ParticipantNotification.objects.create(participant=self.ana, title='Pix confirmado', message='R$ 40',
                                                   notification_type='GENERAL')
        payload = json.loads(webpush.call_args.args[1])
        self.assertEqual((payload['title'], payload['body'], payload['url']), ('Pix confirmado', 'R$ 40', '/me/'))

    def test_equipe_recebe_so_os_tipos_importantes(self):
        Inscricao.objects.create(user=self.dono, endpoint=sub(2)['endpoint'], p256dh='k', auth='a')
        with mock.patch('pywebpush.webpush') as webpush, self.captureOnCommitCallbacks(execute=True):
            GOMNotification.objects.create(gom=self.gom, notification_type='CLAIM', title='Reserva', message='x')
            GOMNotification.objects.create(gom=self.gom, notification_type='PAYMENT', title='Pix avisado', message='y')
        self.assertEqual([json.loads(c.args[1])['title'] for c in webpush.call_args_list], ['Pix avisado'])

    def test_inscricao_morta_e_apagada(self):
        from pywebpush import WebPushException
        Inscricao.objects.create(participant=self.ana, endpoint=sub(3)['endpoint'], p256dh='k', auth='a')
        erro = WebPushException('gone', response=mock.Mock(status_code=410))
        with mock.patch('pywebpush.webpush', side_effect=erro), self.captureOnCommitCallbacks(execute=True):
            ParticipantNotification.objects.create(participant=self.ana, title='t', message='m')
        self.assertFalse(Inscricao.objects.exists())

    def test_service_worker_manifesto_e_chave(self):
        sw = self.client.get('/sw.js')
        self.assertEqual((sw['Content-Type'], sw['Service-Worker-Allowed']), ('application/javascript', '/'))
        self.assertContains(sw, "addEventListener('push'")
        man = json.loads(self.client.get('/manifest.webmanifest').content)
        self.assertEqual((man['name'], man['display']), ('CegManager', 'standalone'))
        chave = self.client.get(reverse('push_chave')).json()['chave']
        bruto = base64.urlsafe_b64decode(chave + '=' * (-len(chave) % 4))
        self.assertEqual((len(bruto), bruto[0], chave), (65, 4, chave_publica()))  # ponto P-256 não comprimido, estável

    def test_ajuda_android_iphone(self):
        res = self.client.get(reverse('ajuda_notificacoes'))
        self.assertContains(res, 'Adicionar à Tela de Início')
        self.assertContains(res, 'Entrar para ativar')
        self.entrar()
        self.assertContains(self.client.get(reverse('my_claims')), reverse('ajuda_notificacoes'))



@override_settings(PUSH_SINCRONO=True)
class PreferenciasTests(TestCase):
    def setUp(self):
        self.ana = Participant.objects.create(whatsapp='5511900004444', name='Ana')
        Inscricao.objects.create(participant=self.ana, endpoint='https://push.example.com/ana', p256dh='k', auth='a')
        self.gom = Gom.objects.create(name='Loja Pref', slug='loja-pref')
        self.dono = User.objects.create_user('dono-pref', password='x')
        GomMembership.objects.create(user=self.dono, gom=self.gom, role='OWNER')
        self.ajudante = User.objects.create_user('ajudante-pref', password='x')
        from apps.goms.services import set_permissions
        set_permissions(GomMembership.objects.create(user=self.ajudante, gom=self.gom, role='ADMIN'),
                        ['pedidos.ver', 'envios.pacotes', 'mensagens.responder'], self.dono)
        for u in (self.dono, self.ajudante):
            Inscricao.objects.create(user=u, endpoint=f'https://push.example.com/{u.username}', p256dh='k', auth='a')

    def enviados(self, criar):
        with mock.patch('pywebpush.webpush') as webpush, self.captureOnCommitCallbacks(execute=True):
            criar()
        return [(c.args[0]['endpoint'].rsplit('/', 1)[1], json.loads(c.args[1])['title']) for c in webpush.call_args_list]

    def test_joiner_desliga_pagamentos_mas_importante_chega(self):
        session = self.client.session
        session['participant_id'] = self.ana.id
        session.save()
        opcoes = self.client.get(reverse('push_preferencias')).json()['opcoes']
        self.assertEqual([o['chave'] for o in opcoes], ['pagamentos', 'envios', 'mensagens', 'repasses'])
        self.client.post(reverse('push_preferencias'), json.dumps({'publico': 'joiner', 'ligados': ['envios', 'mensagens', 'repasses']}),
                         content_type='application/json')
        criar = ParticipantNotification.objects.create
        self.assertEqual(self.enviados(lambda: criar(participant=self.ana, title='Pagamento confirmado', message='',
                                                     categoria='pagamentos')), [])
        self.assertEqual(self.enviados(lambda: criar(participant=self.ana, title='Set cancelado', message='',
                                                     notification_type='SET_CANCELLED')), [('ana', 'Set cancelado')])

    def test_equipe_recebe_pela_permissao_e_pode_desligar(self):
        criar = GOMNotification.objects.create
        self.assertEqual(self.enviados(lambda: criar(gom=self.gom, notification_type='PAYMENT', title='Pix avisado', message='')),
                         [('dono-pref', 'Pix avisado')])  # ajudante de logística não confirma Pix
        self.client.force_login(self.dono)
        self.client.post(reverse('push_preferencias'), json.dumps({'publico': 'gom', 'ligados': ['pix', 'envios', 'repasses']}),
                         content_type='application/json')
        msg = lambda: criar(gom=self.gom, notification_type='SYSTEM', title='Mensagem de Ana', message='',
                            metadata={'categoria': 'mensagens'})
        self.assertEqual(self.enviados(msg), [('ajudante-pref', 'Mensagem de Ana')])
