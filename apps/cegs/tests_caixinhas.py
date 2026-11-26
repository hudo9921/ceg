"""Caixinhas abertas: /caixinhas/, trilho na página do GOM e campos do formulário da caixa (apps/cegs/caixinhas.py)."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.goms.models import Gom

from .models import Caixa


class CaixinhasAbertasTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Caixas A', slug='caixas-a')
        self.outro = Gom.objects.create(name='Caixas B', slug='caixas-b')
        agora = timezone.now()
        self.jp = Caixa.objects.create(gom=self.gom, nome='Mercari Novembro', origem=Caixa.Origem.JP,
                                       como_participar='Mande o link no direct.')
        self.kr = Caixa.objects.create(gom=self.outro, nome='KR Dezembro', origem=Caixa.Origem.KR,
                                       pedidos_ate=agora + timedelta(days=3))
        Caixa.objects.create(gom=self.gom, nome='Fechada pela GOM', origem=Caixa.Origem.JP, aceita_pedidos=False)
        Caixa.objects.create(gom=self.gom, nome='Prazo passou', origem=Caixa.Origem.CN, pedidos_ate=agora - timedelta(hours=1))
        Caixa.objects.create(gom=self.gom, nome='Já enviada', origem=Caixa.Origem.KR, status=Caixa.Status.ENVIADA)
        inativo = Gom.objects.create(name='Inativo', slug='inativo-c', is_active=False)
        Caixa.objects.create(gom=inativo, nome='De GOM inativo', origem=Caixa.Origem.KR)
        self.url = reverse('caixinhas_abertas')

    def nomes(self, res):
        return [c.nome for c in res.context['caixas']]

    def test_lista_so_as_abertas_com_prazo_mais_proximo_primeiro(self):
        res = self.client.get(self.url)
        self.assertEqual(self.nomes(res), ['KR Dezembro', 'Mercari Novembro'])
        self.assertContains(res, 'Mande o link no direct.')
        self.assertContains(res, 'por Caixas A')

    def test_filtro_por_origem_e_por_gom(self):
        self.assertEqual([o[0] for o in self.client.get(self.url).context['origens']], ['KR', 'JP'])
        self.assertEqual(self.nomes(self.client.get(self.url, {'origem': 'jp'})), ['Mercari Novembro'])
        self.assertEqual(self.nomes(self.client.get(self.url, {'gom': 'caixas-b'})), ['KR Dezembro'])
        self.assertEqual(self.nomes(self.client.get(self.url, {'origem': 'xx'})), ['KR Dezembro', 'Mercari Novembro'])

    def test_pagina_do_gom_mostra_so_as_caixinhas_dele(self):
        res = self.client.get(reverse('gom_public', args=['caixas-a']))
        self.assertEqual([c.nome for c in res.context['caixinhas_abertas']], ['Mercari Novembro'])
        self.assertContains(res, 'Caixinhas abertas')

    def test_detalhe_mostra_como_participar_so_enquanto_aberta(self):
        res = self.client.get(reverse('caixa_detail', args=[self.jp.slug]))
        self.assertContains(res, 'Caixinha aberta para pedidos')
        self.jp.atualizar_status(Caixa.Status.PRONTA_ENVIO, notify_participants=False)
        res = self.client.get(reverse('caixa_detail', args=[self.jp.slug]))
        self.assertNotContains(res, 'Caixinha aberta para pedidos')

    def test_formulario_salva_os_campos_da_caixinha(self):
        User.objects.create_superuser('adm-c', 'adm@example.com', 'senha-forte-123')
        self.client.login(username='adm-c', password='senha-forte-123')
        res = self.client.post(reverse('caixa_create'), {
            'nome': 'Nova JP', 'origem': 'JP', 'status': 'EM_CONSOLIDACAO', 'aceita_pedidos': '1',
            'pedidos_ate': '2030-01-10T18:00', 'como_participar': 'Só Mercari.',
        })
        self.assertEqual(res.status_code, 302)
        caixa = Caixa.objects.get(nome='Nova JP')
        self.assertTrue(caixa.aceita_pedidos)
        self.assertEqual(timezone.localtime(caixa.pedidos_ate).strftime('%d/%m %H:%M'), '10/01 18:00')
        self.assertEqual(caixa.como_participar, 'Só Mercari.')
        # Desmarcar (o checkbox não vem no POST) fecha a caixinha.
        self.client.post(reverse('caixa_update', args=[caixa.slug]), {'nome': 'Nova JP', 'origem': 'JP'})
        caixa.refresh_from_db()
        self.assertFalse(caixa.aceita_pedidos)
        self.assertIsNone(caixa.pedidos_ate)
