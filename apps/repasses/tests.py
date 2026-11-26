"""Repasse de item: A pede → B aceita (ou pede a vaga pública) → o GOM aprova; regras de bloqueio e isolamento."""
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, GOMNotification, ItemSlot
from apps.goms.models import Gom, GomMembership
from apps.groups.models import Era, KpopGroup
from apps.pagamentos import services as pix
from apps.participants.models import Claim, Participant, ParticipantNotification

from . import services
from .models import Repasse

User = get_user_model()


class RepasseFixture(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja Rep', slug='loja-rep', default_pix_key='loja@pix.com',
                                      pix_nome_recebedor='Loja', pix_cidade='Sao Paulo')
        era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa-rp'), name='Rich', slug='rich-rp')
        self.ceg = CEG.objects.create(era=era, gom=self.gom, title='CEG Rep', slug='ceg-rep', status=CEG.Status.OPEN)
        idef = CEGItemDefinition.objects.create(ceg=self.ceg, name='PC Karina', default_price=40)
        self.ana = Participant.objects.create(whatsapp='5511933332222', name='Ana')
        self.bia = Participant.objects.create(whatsapp='5511944443333', name='Bia')
        self.slot = ItemSlot.objects.create(set=CEGSet.objects.create(ceg=self.ceg, set_number=1), item_definition=idef,
                                            price=Decimal('40'), claimed_by=self.ana, status=ItemSlot.Status.RESERVED,
                                            frete_inter_valor=Decimal('12.50'))
        self.claim = Claim.objects.create(slot=self.slot, participant=self.ana, total_price=Decimal('40'))
        self.staff = User.objects.create_user('equipe-rep', password='x')
        GomMembership.objects.create(user=self.staff, gom=self.gom, role='OWNER')

    def entrar(self, p):
        session = self.client.session
        session['participant_id'] = p.id
        session.save()

    def post(self, nome, body=None, *args):
        res = self.client.post(reverse(nome, args=args), json.dumps(body or {}), content_type='application/json')
        return res.status_code, res.json()


class FluxoTests(RepasseFixture):
    def test_para_uma_pessoa_aceita_e_gom_aprova(self):
        self.entrar(self.ana)
        code, data = self.post('repasse_criar', {'slot_id': self.slot.id, 'whatsapp': '(11) 94444-3333', 'recado': 'oi'})
        self.assertEqual(code, 200, data)
        rep = Repasse.objects.get()
        self.assertEqual((rep.status, rep.para), (Repasse.Status.AGUARDANDO_ACEITE, self.bia))
        self.entrar(self.bia)
        self.assertEqual(self.post('repasse_responder', {'aceitar': True}, rep.pk)[0], 200)
        self.assertTrue(GOMNotification.objects.filter(gom=self.gom, notification_type='REPASSE').exists())

        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse('gom_repasses')), 'Frete internacional R$ 12,50')
        self.client.post(reverse('gom_repasses'), {'repasse': rep.pk, 'acao': 'aprovar'})
        self.claim.refresh_from_db()
        self.slot.refresh_from_db()
        self.assertEqual((self.claim.participant, self.slot.claimed_by), (self.bia, self.bia))
        self.assertTrue(self.bia.known_by_goms.filter(pk=self.gom.pk).exists())
        self.assertTrue(ParticipantNotification.objects.filter(participant=self.ana, title='Repasse aprovado').exists())

    def test_numero_sem_conta_ve_o_pedido_quando_entrar(self):
        rep = services.criar(self.ana, self.slot, '11 95555-0000')
        self.assertIsNone(rep.para)
        nova = Participant.objects.create(whatsapp='5511955550000', name='Cris')
        self.assertEqual(list(services.recebidos(nova)), [rep])
        services.responder(rep, nova, True)
        rep.refresh_from_db()
        self.assertEqual((rep.para, rep.status), (nova, Repasse.Status.AGUARDANDO_GOM))

    def test_publico_recusado_volta_a_ficar_disponivel(self):
        rep = services.criar(self.ana, self.slot, publico=True)
        self.assertContains(self.client.get(reverse('repasses_disponiveis')), 'PC Karina')
        self.assertContains(self.client.get(reverse('ceg_detail', args=[self.ceg.slug])), 'Vagas para repasse')
        self.entrar(self.bia)
        self.assertEqual(self.post('repasse_pedir', {}, rep.pk)[0], 200)
        services.recusar(Repasse.objects.get(pk=rep.pk), self.staff, 'já prometida')
        rep.refresh_from_db()
        self.assertEqual((rep.status, rep.para), (Repasse.Status.DISPONIVEL, None))

    def test_recusa_e_cancelamento(self):
        rep = services.criar(self.ana, self.slot, '11944443333')
        services.responder(rep, self.bia, False)
        self.assertEqual(Repasse.objects.get(pk=rep.pk).status, Repasse.Status.RECUSADO_PESSOA)
        rep2 = services.criar(self.ana, self.slot, publico=True)
        services.cancelar(rep2, self.ana)
        self.assertEqual(Repasse.objects.get(pk=rep2.pk).status, Repasse.Status.CANCELADO)


class BloqueiosTests(RepasseFixture):
    def test_so_o_dono_e_sem_pix_aberto_nem_repasse_duplicado(self):
        with self.assertRaisesMessage(services.RepasseError, 'não é sua'):
            services.criar(self.bia, self.slot, publico=True)
        cob = pix.create_cobrancas(self.ana, self.gom, ['item:ceg:%d' % self.ceg.id])[0]
        with self.assertRaisesMessage(services.RepasseError, 'Pix em aberto'):
            services.criar(self.ana, self.slot, publico=True)
        pix.cancelar(cob)
        services.criar(self.ana, self.slot, publico=True)
        with self.assertRaisesMessage(services.RepasseError, 'já tem um repasse'):
            services.criar(self.ana, self.slot, '11944443333')

    def test_proprio_numero_e_pedir_a_propria_vaga(self):
        with self.assertRaisesMessage(services.RepasseError, 'é o seu'):
            services.criar(self.ana, self.slot, '11933332222')
        rep = services.criar(self.ana, self.slot, publico=True)
        with self.assertRaisesMessage(services.RepasseError, 'já é sua'):
            services.pedir_publico(rep, self.ana)

    def test_outro_gom_nao_aprova(self):
        rep = services.criar(self.ana, self.slot, publico=True)
        services.pedir_publico(rep, self.bia)
        outro = User.objects.create_user('outro-rep', password='x')
        GomMembership.objects.create(user=outro, gom=Gom.objects.create(name='Outra', slug='outra-rep'), role='OWNER')
        self.client.force_login(outro)
        self.assertEqual(self.client.post(reverse('gom_repasses'), {'repasse': rep.pk, 'acao': 'aprovar'}).status_code, 404)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.participant, self.ana)

    def test_pedir_sem_login(self):
        rep = services.criar(self.ana, self.slot, publico=True)
        code, data = self.post('repasse_pedir', {}, rep.pk)
        self.assertEqual((code, data.get('requires_auth')), (401, True))
