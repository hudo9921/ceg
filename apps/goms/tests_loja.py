"""Loja da página pública do GOM: filtros, vistas, paginação e isolamento (apps/goms/loja.py)."""
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot, ItemVitrine
from apps.groups.models import Era, KpopGroup

from .loja import POR_PAGINA
from .models import Gom


def criar_ceg(gom, era, titulo, itens, sets=1):
    ceg = CEG.objects.create(era=era, gom=gom, title=titulo, status=CEG.Status.OPEN)
    for nome, membro, preco in itens:
        CEGItemDefinition.objects.create(ceg=ceg, name=nome, member_name=membro, default_price=preco)
    for n in range(1, sets + 1):
        CEGSet.objects.create(ceg=ceg, set_number=n).generate_slots()
    return ceg


class LojaGomTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja L', slug='loja-l')
        aespa = KpopGroup.objects.create(name='aespa', slug='aespa-l')
        ive = KpopGroup.objects.create(name='IVE', slug='ive-l')
        KpopGroup.objects.create(name='Grupo Só no Catálogo', slug='so-catalogo-l')
        self.aespa, self.ive = aespa, ive
        self.rich = Era.objects.create(group=aespa, name='Rich Man', slug='rich-l')
        self.empathy = Era.objects.create(group=ive, name='Empathy', slug='empathy-l')
        self.c1 = criar_ceg(self.gom, self.rich, 'Rich Man POB', [('PC A', 'Karina', 30), ('PC B', 'Winter', 25)], sets=2)
        self.c2 = criar_ceg(self.gom, self.empathy, 'Empathy Lucky Draw', [('LD', 'Wonyoung', 40)])
        outro = Gom.objects.create(name='Outra', slug='outra-l')
        criar_ceg(outro, self.rich, 'CEG de Outro GOM', [('PC', 'Karina', 10)])
        self.url = reverse('gom_public', args=['loja-l'])

    def test_sem_filtro_mostra_as_cegs_do_gom(self):
        res = self.client.get(self.url)
        self.assertContains(res, 'Rich Man POB')
        self.assertContains(res, 'Empathy Lucky Draw')
        self.assertNotContains(res, 'CEG de Outro GOM')

    def test_filtros_so_oferecem_grupos_a_venda(self):
        res = self.client.get(self.url)
        nomes = [g['name'] for g in res.context['grupos_topo']]
        self.assertEqual(sorted(nomes), ['IVE', 'aespa'])
        self.assertNotContains(res, 'Grupo Só no Catálogo')

    def test_grupo_e_integrante(self):
        res = self.client.get(self.url, {'grupo': self.aespa.id})
        self.assertEqual([c.title for c in res.context['resultados']], ['Rich Man POB'])
        self.assertEqual([i['nome'] for i in res.context['integrantes']], ['Karina', 'Winter'])
        ItemSlot.objects.filter(item_definition__member_name='Karina').update(status=ItemSlot.Status.RESERVED)
        res = self.client.get(self.url, {'grupo': self.aespa.id, 'integrante': 'karina'})
        self.assertEqual(res.context['resultados'], [])

    def test_vista_itens_vira_produto_com_link_para_o_item(self):
        res = self.client.get(self.url, {'vista': 'itens', 'grupo': self.aespa.id, 'ordem': 'preco'})
        itens = res.context['resultados']
        self.assertEqual([(i['titulo'], i['vagas'], int(i['preco'])) for i in itens], [('Winter', 2, 25), ('Karina', 2, 30)])
        karina = CEGItemDefinition.objects.get(member_name='Karina', ceg=self.c1)
        self.assertContains(res, f'{reverse("ceg_detail", args=[self.c1.slug])}?item={karina.id}')

    def test_busca_e_preco(self):
        res = self.client.get(self.url, {'q': 'wonyoung'})
        self.assertEqual([c.title for c in res.context['resultados']], ['Empathy Lucky Draw'])
        res = self.client.get(self.url, {'preco_max': '28'})
        self.assertEqual([c.title for c in res.context['resultados']], ['Rich Man POB'])

    def test_parciais(self):
        corpo = self.client.get(self.url, {'parcial': '1', 'grupo': self.ive.id})
        self.assertTemplateUsed(corpo, 'goms/partials/_loja_corpo.html')
        self.assertNotContains(corpo, '<html')
        self.assertContains(corpo, 'Empathy Lucky Draw')

    def test_paginacao(self):
        for n in range(POR_PAGINA + 3):
            criar_ceg(self.gom, self.rich, f'Extra {n}', [('PC', 'Giselle', 20)])
        res = self.client.get(self.url)
        self.assertEqual(len(res.context['resultados']), POR_PAGINA)
        self.assertTrue(res.context['tem_mais'])
        mais = self.client.get(self.url + res.context['proxima_url'] + '&parcial=mais')
        self.assertTemplateUsed(mais, 'goms/partials/_loja_cards.html')
        self.assertEqual(len(mais.context['resultados']), 5)
        self.assertFalse(mais.context['tem_mais'])

    def test_consultas_nao_crescem_com_o_catalogo_nem_com_cegs(self):
        self.client.get(self.url)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as antes:
            self.client.get(self.url)
        for n in range(10):
            g = KpopGroup.objects.create(name=f'Cat {n}', slug=f'cat-l-{n}')
            criar_ceg(self.gom, Era.objects.create(group=g, name='E', slug=f'e-l-{n}'), f'Mais {n}', [('PC', f'M{n}', 15)])
        with CaptureQueriesContext(connection) as depois:
            self.client.get(self.url)
        self.assertEqual(len(antes.captured_queries), len(depois.captured_queries))

    def test_pronta_entrega(self):
        ItemVitrine.objects.create(gom=self.gom, titulo='Karina POB pronta', group=self.aespa, integrante='Karina',
                                   preco=50, quantidade=1, status=ItemVitrine.Status.DISPONIVEL)
        res = self.client.get(self.url, {'aba': 'pronta'})
        self.assertContains(res, 'Karina POB pronta')
        self.assertContains(res, '?item=')
        self.gom.pagina_mostrar_vitrine = False
        self.gom.save()
        res = self.client.get(self.url, {'aba': 'pronta'})
        self.assertNotContains(res, 'Karina POB pronta')
        self.assertContains(res, 'Rich Man POB')
