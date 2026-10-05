from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from apps.groups.models import KpopGroup, Era
from apps.participants.models import Participant
from apps.cegs.models import CEG, CEGSet, CEGItemDefinition, ItemSlot


class ItensAvulsosTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username='admin_ceg',
            email='admin@kpop.com',
            password='adminpassword123'
        )
        self.participant = Participant.objects.create(
            name='DIVE Fã',
            whatsapp='11999998888',
            social_handle='@dive_fan'
        )

        self.group = KpopGroup.objects.create(name='IVE')
        self.era = Era.objects.create(group=self.group, name='IVE SWITCH')

        self.ceg = CEG.objects.create(
            era=self.era,
            title='CEG IVE SWITCH - POBs & Álbuns',
            status=CEG.Status.OPEN
        )

        # Item regular (replicável)
        self.regular_def = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Photocard Wonyoung',
            member_name='Wonyoung',
            item_type=CEGItemDefinition.ItemType.PHOTOCARD,
            default_price=Decimal('45.00'),
            is_avulso=False
        )

        # Set 1 regular inicial
        self.set_1 = CEGSet.objects.create(
            ceg=self.ceg,
            set_number=1,
            is_active=True
        )
        self.set_1.generate_slots()

    def test_avulso_creation_and_generation(self):
        """Testa criação de item avulso e geração de slots com unit_number"""
        avulso_def = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Álbum Selado Ver. LOVER',
            item_type=CEGItemDefinition.ItemType.ALBUM,
            default_price=Decimal('120.00'),
            is_avulso=True,
            quantidade_avulsa=3
        )

        avulso_set = self.ceg.get_or_create_avulso_set()
        self.assertTrue(avulso_set.is_avulso)
        self.assertEqual(avulso_set.set_number, 0)

        slots = avulso_set.generate_slots()
        self.assertEqual(len(slots), 3)
        self.assertEqual([s.unit_number for s in slots], [1, 2, 3])
        for s in slots:
            self.assertTrue(s.is_avulso)
            self.assertEqual(s.price, Decimal('120.00'))

    def test_create_regular_set_does_not_replicate_avulso(self):
        """Verifica que adicionar um novo Set regular NÃO replica itens avulsos"""
        # Cria item avulso
        avulso_def = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Pôster Dobrado Oficial',
            item_type=CEGItemDefinition.ItemType.INCLUSION,
            default_price=Decimal('25.00'),
            is_avulso=True,
            quantidade_avulsa=2
        )
        avulso_set = self.ceg.get_or_create_avulso_set()
        avulso_set.generate_slots()

        self.assertEqual(ItemSlot.objects.filter(item_definition=avulso_def).count(), 2)

        # Admin adiciona Set 2 na CEG via /creations/set/create/
        self.client.force_login(self.admin)
        res = self.client.post('/creations/set/create/', {'ceg_id': self.ceg.id})
        self.assertEqual(res.status_code, 302)

        set_2 = CEGSet.objects.get(ceg=self.ceg, set_number=2)
        self.assertFalse(set_2.is_avulso)

        # Set 2 deve conter apenas o item regular, NÃO o pôster avulso
        set_2_slots = set_2.slots.all()
        self.assertEqual(set_2_slots.count(), 1)
        self.assertEqual(set_2_slots.first().item_definition, self.regular_def)

        # O item avulso continua rigorosamente com 2 unidades
        self.assertEqual(ItemSlot.objects.filter(item_definition=avulso_def).count(), 2)

    def test_create_avulso_item_view(self):
        """Testa o endpoint de adicionar item avulso via POST"""
        self.client.force_login(self.admin)

        payload = {
            'name': 'Mini Poster Fanclub',
            'member': 'Yujin',
            'item_type': 'INCLUSION',
            'price': '35.00',
            'quantity': 2,
        }
        res = self.client.post(
            f'/ceg/{self.ceg.slug}/avulsos/adicionar/',
            payload,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))

        item_def = CEGItemDefinition.objects.get(ceg=self.ceg, name='Mini Poster Fanclub')
        self.assertTrue(item_def.is_avulso)
        self.assertEqual(item_def.quantidade_avulsa, 2)
        self.assertEqual(item_def.default_price, Decimal('35.00'))

        slots = ItemSlot.objects.filter(item_definition=item_def).order_by('unit_number')
        self.assertEqual(slots.count(), 2)
        self.assertEqual(slots[0].unit_number, 1)
        self.assertEqual(slots[1].unit_number, 2)

    def test_update_avulso_item_view(self):
        """Testa edição de item avulso (nome, preço e alteração de quantidade)"""
        self.client.force_login(self.admin)

        item_def = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Special Card',
            item_type=CEGItemDefinition.ItemType.POB,
            default_price=Decimal('50.00'),
            is_avulso=True,
            quantidade_avulsa=2
        )
        av_set = self.ceg.get_or_create_avulso_set()
        av_set.generate_slots()

        # Aumenta quantidade para 4 unidades e altera preço para 55.00
        payload = {
            'name': 'Special Card Holográfico',
            'member': 'Rei',
            'item_type': 'POB',
            'price': '55.00',
            'quantity': 4,
        }
        res = self.client.post(
            f'/ceg/{self.ceg.slug}/avulsos/{item_def.id}/editar/',
            payload,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)

        item_def.refresh_from_db()
        self.assertEqual(item_def.name, 'Special Card Holográfico')
        self.assertEqual(item_def.default_price, Decimal('55.00'))
        self.assertEqual(item_def.quantidade_avulsa, 4)

        # Converte para lista em memória para reter as alterações
        slots = list(ItemSlot.objects.filter(item_definition=item_def).order_by('unit_number'))
        self.assertEqual(len(slots), 4)
        self.assertEqual([s.unit_number for s in slots], [1, 2, 3, 4])

        # Se reservar a unidade 4, tentar reduzir para 3 unidades deve ser bloqueado com erro 400
        unit_4 = slots[3]
        unit_4.status = ItemSlot.Status.RESERVED
        unit_4.claimed_by = self.participant
        unit_4.save()

        res_reduce = self.client.post(
            f'/ceg/{self.ceg.slug}/avulsos/{item_def.id}/editar/',
            {'name': 'Special Card Holográfico', 'price': '55.00', 'quantity': 3},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_reduce.status_code, 400)
        self.assertIn('reserva ativa', res_reduce.json().get('message', ''))

    def test_delete_avulso_item_view(self):
        """Testa exclusão com proteção contra exclusão de itens já pagos"""
        self.client.force_login(self.admin)

        item_def = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Item Teste Delete',
            item_type=CEGItemDefinition.ItemType.OTHER,
            default_price=Decimal('30.00'),
            is_avulso=True,
            quantidade_avulsa=2
        )
        av_set = self.ceg.get_or_create_avulso_set()
        av_set.generate_slots()

        # Marca uma unidade como PAGA
        paid_slot = ItemSlot.objects.filter(item_definition=item_def).first()
        paid_slot.is_item_paid = True
        paid_slot.status = ItemSlot.Status.PAID
        paid_slot.save()

        # Tentativa de exclusão deve falhar
        res_fail = self.client.post(
            f'/ceg/{self.ceg.slug}/avulsos/{item_def.id}/excluir/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_fail.status_code, 400)
        self.assertIn('pagamento já confirmado', res_fail.json().get('message', ''))

        # Se cancelar o pagamento, exclusão é permitida
        paid_slot.is_item_paid = False
        paid_slot.status = ItemSlot.Status.AVAILABLE
        paid_slot.save()

        res_ok = self.client.post(
            f'/ceg/{self.ceg.slug}/avulsos/{item_def.id}/excluir/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_ok.status_code, 200)
        self.assertFalse(CEGItemDefinition.objects.filter(id=item_def.id).exists())
        self.assertFalse(ItemSlot.objects.filter(item_definition_id=item_def.id).exists())

    def test_claim_avulso_slot(self):
        """Testa que um participante pode reservar com sucesso uma unidade de item avulso"""
        session = self.client.session
        session['participant_id'] = self.participant.id
        session.save()

        item_def = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Álbum Digipack Leeseo',
            item_type=CEGItemDefinition.ItemType.ALBUM,
            default_price=Decimal('80.00'),
            is_avulso=True,
            quantidade_avulsa=1
        )
        av_set = self.ceg.get_or_create_avulso_set()
        slots = av_set.generate_slots()
        slot = slots[0]

        res = self.client.post(
            f'/slots/{slot.id}/claim/',
            {
                'name': 'DIVE Fã',
                'whatsapp': '11999998888',
                'social_handle': '@dive_fan'
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))

        slot.refresh_from_db()
        self.assertEqual(slot.status, ItemSlot.Status.RESERVED)
        self.assertEqual(slot.claimed_by.name, 'DIVE Fã')

    def test_ceg_detail_view_renders_avulso_context(self):
        """Testa que a view de detalhes da CEG inclui os dados de avulsos no contexto"""
        CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Photocard Avulso',
            item_type=CEGItemDefinition.ItemType.PHOTOCARD,
            default_price=Decimal('40.00'),
            is_avulso=True,
            quantidade_avulsa=1
        )
        av_set = self.ceg.get_or_create_avulso_set()
        av_set.generate_slots()

        res = self.client.get(f'/ceg/{self.ceg.slug}/')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context['has_avulsos'])
        self.assertEqual(len(res.context['avulso_definitions']), 1)
        self.assertEqual(len(res.context['avulso_slots']), 1)
        content = res.content.decode('utf-8')
        self.assertIn('Apenas Itens Avulsos', content)
        self.assertIn('Itens Avulsos & Exclusivos', content)
