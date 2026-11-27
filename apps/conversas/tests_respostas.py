"""Respostas prontas: padrão no primeiro uso, {nome}/{valor}/{gom} preenchidos, edição e isolamento entre GOMs."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import PacoteNacional
from apps.goms.models import Gom, GomMembership
from apps.participants.models import Participant

from .models import Conversa, RespostaPronta
from .respostas import PADRAO, preenchidas

User = get_user_model()


class RespostasProntasTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja M', slug='loja-m')
        self.staff = User.objects.create_user('dono-m', password='x')
        GomMembership.objects.create(user=self.staff, gom=self.gom, role='OWNER')
        self.joiner = Participant.objects.create(whatsapp='5511955550000', name='Ana Souza')
        self.joiner.known_by_goms.add(self.gom)
        PacoteNacional.objects.create(gom=self.gom, participant=self.joiner, valor_frete_nacional=Decimal('1234.5'))
        self.conversa = Conversa.objects.create(gom=self.gom, participant=self.joiner, assunto='Geral')

    def test_padrao_preenchido_com_nome_valor_e_gom(self):
        respostas = preenchidas(self.conversa)
        self.assertEqual(len(respostas), len(PADRAO))
        lembrete = next(r['texto'] for r in respostas if r['titulo'] == 'Lembrete de pagamento')
        self.assertIn('Oi, Ana!', lembrete)
        self.assertIn('R$ 1.234,50', lembrete)
        self.assertIn('Loja M', lembrete)

    def test_apagar_todas_nao_volta_o_padrao(self):
        preenchidas(self.conversa)
        RespostaPronta.objects.all().delete()
        self.assertEqual(preenchidas(self.conversa), [])

    def test_conversa_da_equipe_mostra_respostas(self):
        self.client.force_login(self.staff)
        html = self.client.get(reverse('gom_mensagens') + f'?c={self.conversa.id}').content.decode()
        self.assertIn('id="chat-respostas"', html)
        self.assertIn('Oi, Ana!', html)

    def test_criar_editar_apagar(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('gom_respostas'), {'acao': 'salvar', 'titulo': 'Frete', 'texto': 'Oi {nome}, frete lançado.'})
        nova = RespostaPronta.objects.get(titulo='Frete')
        self.assertEqual(RespostaPronta.objects.count(), len(PADRAO) + 1)
        self.client.post(reverse('gom_respostas'), {'acao': 'salvar', 'id': nova.id, 'titulo': 'Frete!', 'texto': 'Novo'})
        nova.refresh_from_db()
        self.assertEqual((nova.titulo, nova.texto), ('Frete!', 'Novo'))
        self.client.post(reverse('gom_respostas'), {'acao': 'apagar', 'id': nova.id})
        self.assertFalse(RespostaPronta.objects.filter(pk=nova.pk).exists())

    def test_outro_gom_nao_edita(self):
        outro = Gom.objects.create(name='Outra', slug='outra')
        alheia = RespostaPronta.objects.create(gom=outro, titulo='X', texto='Y')
        self.client.force_login(self.staff)
        res = self.client.post(reverse('gom_respostas'), {'acao': 'apagar', 'id': alheia.id})
        self.assertEqual(res.status_code, 404)
        self.assertTrue(RespostaPronta.objects.filter(pk=alheia.pk).exists())
