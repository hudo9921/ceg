from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from apps.cegs.models import Caixa, CEG, CEGItemDefinition, CEGSet, ItemSlot, TipoItem, ItemVitrine
from apps.groups.models import KpopGroup, Era
from apps.participants.models import Participant


class VitrineTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Usuários
        self.admin_user = User.objects.create_superuser(
            username='admin_gom',
            password='password123',
            email='gom@valcegs.com'
        )
        self.normal_user = User.objects.create_user(
            username='joiner_normal',
            password='password123',
            email='joiner@valcegs.com'
        )

        # Categorias, Grupos e Eras
        self.tipo_pc, _ = TipoItem.objects.get_or_create(nome='Photocard')
        self.tipo_album, _ = TipoItem.objects.get_or_create(nome='Álbum')

        self.group, _ = KpopGroup.objects.get_or_create(name='aespa')
        self.era, _ = Era.objects.get_or_create(group=self.group, name='Armageddon')

        # Item Vitrine pré-existente
        self.item_vitrine = ItemVitrine.objects.create(
            titulo='Karina Armageddon POB',
            tipo_item=self.tipo_pc,
            group=self.group,
            era=self.era,
            integrante='Karina',
            preco=Decimal('55.00'),
            quantidade=1,
            status=ItemVitrine.Status.DISPONIVEL,
            destaque=True
        )

    def test_item_vitrine_creation_and_properties(self):
        self.assertTrue(self.item_vitrine.slug)
        self.assertTrue(self.item_vitrine.is_disponivel)
        self.assertEqual(str(self.item_vitrine), "Karina Armageddon POB - R$ 55.00 [Disponível à Pronta Entrega]")

    def test_vitrine_list_view_public_access(self):
        response = self.client.get(reverse('vitrine_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Karina Armageddon POB')
        self.assertContains(response, '55,00')

    def test_vitrine_list_filters(self):
        # Filtro de busca por nome
        resp = self.client.get(reverse('vitrine_list') + '?q=Karina')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Karina Armageddon POB')

        resp_none = self.client.get(reverse('vitrine_list') + '?q=GiselleInexistente')
        self.assertEqual(resp_none.status_code, 200)
        self.assertNotContains(resp_none, 'Karina Armageddon POB')

    def test_vitrine_create_requires_staff(self):
        # Acesso anônimo ou usuário comum deve redirecionar
        resp = self.client.get(reverse('vitrine_create'))
        self.assertEqual(resp.status_code, 302)

        self.client.login(username='joiner_normal', password='password123')
        resp = self.client.get(reverse('vitrine_create'))
        self.assertEqual(resp.status_code, 302)

    def test_vitrine_create_by_staff(self):
        self.client.login(username='admin_gom', password='password123')
        resp = self.client.get(reverse('vitrine_create'))
        self.assertEqual(resp.status_code, 200)

        post_data = {
            'titulo': 'Winter Supernova Card',
            'tipo_item': self.tipo_pc.id,
            'group': self.group.id,
            'era': self.era.id,
            'integrante': 'Winter',
            'preco': '49.90',
            'quantidade': '2',
            'condicao': ItemVitrine.Condicao.NOVO,
            'status': ItemVitrine.Status.DISPONIVEL,
            'descricao': 'Photocard original de primeira tiragem',
            'destaque': 'on',
        }
        resp_post = self.client.post(reverse('vitrine_create'), post_data)
        self.assertRedirects(resp_post, reverse('vitrine_list'))

        novo_item = ItemVitrine.objects.filter(titulo='Winter Supernova Card').first()
        self.assertIsNotNone(novo_item)
        self.assertEqual(novo_item.integrante, 'Winter')
        self.assertEqual(novo_item.preco, Decimal('49.90'))
        self.assertEqual(novo_item.quantidade, 2)
        self.assertTrue(novo_item.destaque)

    def test_vitrine_update_and_toggle_status(self):
        self.client.login(username='admin_gom', password='password123')

        # Update de dados
        resp = self.client.post(reverse('vitrine_edit', kwargs={'slug': self.item_vitrine.slug}), {
            'titulo': 'Karina Armageddon POB - Atualizado',
            'tipo_item': self.tipo_pc.id,
            'group': self.group.id,
            'era': self.era.id,
            'integrante': 'Karina',
            'preco': '60.00',
            'quantidade': '1',
            'condicao': ItemVitrine.Condicao.MINT,
            'status': ItemVitrine.Status.DISPONIVEL,
        })
        self.assertRedirects(resp, reverse('vitrine_list'))

        self.item_vitrine.refresh_from_db()
        self.assertEqual(self.item_vitrine.titulo, 'Karina Armageddon POB - Atualizado')
        self.assertEqual(self.item_vitrine.preco, Decimal('60.00'))

        # Toggle status para Vendido
        resp_toggle = self.client.post(reverse('vitrine_toggle_status', kwargs={'slug': self.item_vitrine.slug}), {
            'status': 'VENDIDO'
        })
        self.item_vitrine.refresh_from_db()
        self.assertEqual(self.item_vitrine.status, ItemVitrine.Status.VENDIDO)
        self.assertEqual(self.item_vitrine.quantidade, 0)

    def test_transfer_unclaimed_slots_from_caixa_to_vitrine(self):
        # 1. Cria Caixa com status ENTREGUE ("Chegou na casa da GOM")
        caixa = Caixa.objects.create(
            nome='Caixa KR 10 - Chegada',
            origem=Caixa.Origem.KR,
            status=Caixa.Status.ENTREGUE
        )

        # 2. Cria CEG atrelada à caixa
        ceg = CEG.objects.create(
            title='CEG Armageddon aespa',
            era=self.era,
            caixa=caixa,
            status=CEG.Status.OPEN
        )

        # 3. Cria Definições de Itens
        def_karina = CEGItemDefinition.objects.create(
            ceg=ceg,
            name='Photocard Karina',
            member_name='Karina',
            tipo_item=self.tipo_pc,
            default_price=Decimal('50.00')
        )
        def_giselle = CEGItemDefinition.objects.create(
            ceg=ceg,
            name='Photocard Giselle',
            member_name='Giselle',
            tipo_item=self.tipo_pc,
            default_price=Decimal('40.00')
        )

        # 4. Cria Set com 2 slots
        ceg_set = CEGSet.objects.create(ceg=ceg, set_number=1)
        slot_karina = ItemSlot.objects.create(
            set=ceg_set,
            item_definition=def_karina,
            price=Decimal('50.00'),
            status=ItemSlot.Status.RESERVED  # Reservado por joiner
        )
        participant = Participant.objects.create(name='Joiner Teste', whatsapp='5511999999999')
        slot_karina.claimed_by = participant
        slot_karina.save()

        slot_giselle = ItemSlot.objects.create(
            set=ceg_set,
            item_definition=def_giselle,
            price=Decimal('40.00'),
            status=ItemSlot.Status.AVAILABLE  # NÃO CLAIMADO!
        )

        # 5. Verifica visualização GET da transferência
        self.client.login(username='admin_gom', password='password123')
        url_transfer = reverse('caixa_transfer_unclaimed_vitrine', kwargs={'slug': caixa.slug})
        resp = self.client.get(url_transfer)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Photocard Giselle')
        self.assertNotContains(resp, 'Photocard Karina')  # Não deve conter o claimado da Karina!

        # 6. Executa POST de transferência
        post_data = {
            'selected_slots': [str(slot_giselle.id)],
            f'preco_{slot_giselle.id}': '42.50',
        }
        resp_post = self.client.post(url_transfer, post_data)
        self.assertRedirects(resp_post, reverse('vitrine_list'))

        # 7. Valida que o ItemVitrine foi gerado
        item_transferido = ItemVitrine.objects.filter(origem_slot=slot_giselle).first()
        self.assertIsNotNone(item_transferido)
        self.assertEqual(item_transferido.integrante, 'Giselle')
        self.assertEqual(item_transferido.preco, Decimal('42.50'))
        self.assertEqual(item_transferido.status, ItemVitrine.Status.DISPONIVEL)
        self.assertEqual(item_transferido.origem_caixa, caixa)

        # 8. Valida que o slot na CEG foi marcado como CANCELLED para evitar duplo claim
        slot_giselle.refresh_from_db()
        self.assertEqual(slot_giselle.status, ItemSlot.Status.CANCELLED)

        # 9. Teste de idempotência: se tentar listar novamente, slot_giselle não aparece mais
        resp_again = self.client.get(url_transfer)
        self.assertEqual(resp_again.context['unclaimed_count'], 0)
