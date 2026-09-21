import json
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.cegs.models import CEG, CEGSet, CEGItemDefinition, ItemSlot
from apps.groups.models import KpopGroup, Era
from apps.participants.models import Participant, Claim
from apps.cegs.services_allocator import BulkJoinerAllocatorService

User = get_user_model()


class BulkJoinerAllocatorTestCase(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_superuser(
            username='admin_ceg',
            email='admin@kpopceg.com',
            password='testpassword123'
        )
        self.client = Client()
        self.client.force_login(self.staff_user)

        self.group = KpopGroup.objects.create(name='tripleS', slug='triples')
        self.era = Era.objects.create(group=self.group, name='Assemble24', slug='assemble24')

        # Cria CEG de teste com 2 Sets e 3 Itens
        self.ceg = CEG.objects.create(
            era=self.era,
            title='tripleS Assemble24 — Fansign Allocator Test',
            slug='triples-assemble24-allocator-test',
            status=CEG.Status.OPEN
        )

        self.item_seoyeon = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Photocard Seoyeon',
            member_name='Seoyeon',
            default_price=Decimal('50.00'),
            item_type=CEGItemDefinition.ItemType.PHOTOCARD
        )
        self.item_chaeyeon = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Photocard Chaeyeon',
            member_name='Chaeyeon',
            default_price=Decimal('45.00'),
            item_type=CEGItemDefinition.ItemType.PHOTOCARD
        )
        self.item_jiwoo = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Photocard Jiwoo',
            member_name='Jiwoo',
            default_price=Decimal('45.00'),
            item_type=CEGItemDefinition.ItemType.PHOTOCARD
        )

        self.set1 = CEGSet.objects.create(ceg=self.ceg, set_number=1, is_active=True)
        self.set2 = CEGSet.objects.create(ceg=self.ceg, set_number=2, is_active=True)

        # Slots Set 1
        self.slot_s1_seoyeon = ItemSlot.objects.create(set=self.set1, item_definition=self.item_seoyeon, price=Decimal('50.00'))
        self.slot_s1_chaeyeon = ItemSlot.objects.create(set=self.set1, item_definition=self.item_chaeyeon, price=Decimal('45.00'))
        self.slot_s1_jiwoo = ItemSlot.objects.create(set=self.set1, item_definition=self.item_jiwoo, price=Decimal('45.00'))

        # Slots Set 2
        self.slot_s2_seoyeon = ItemSlot.objects.create(set=self.set2, item_definition=self.item_seoyeon, price=Decimal('50.00'))
        self.slot_s2_chaeyeon = ItemSlot.objects.create(set=self.set2, item_definition=self.item_chaeyeon, price=Decimal('45.00'))
        self.slot_s2_jiwoo = ItemSlot.objects.create(set=self.set2, item_definition=self.item_jiwoo, price=Decimal('45.00'))

        # Participante pré-cadastrado
        self.participant1 = Participant.objects.create(
            name='Bia Silva',
            whatsapp='5511988887777',
            social_handle='@biasilva'
        )

    def test_ceg_matrix_generation(self):
        """Valida que a matriz Sets x Itens é gerada com contagens e slots corretos."""
        # Aloca 1 slot previamente
        self.slot_s1_seoyeon.claimed_by = self.participant1
        self.slot_s1_seoyeon.status = ItemSlot.Status.PAID
        self.slot_s1_seoyeon.is_item_paid = True
        self.slot_s1_seoyeon.save()

        matrix = BulkJoinerAllocatorService.get_ceg_matrix(self.ceg)
        self.assertEqual(matrix['ceg']['slug'], self.ceg.slug)
        self.assertEqual(len(matrix['sets']), 2)
        self.assertEqual(len(matrix['items']), 3)
        self.assertEqual(matrix['total_slots'], 6)
        self.assertEqual(matrix['occupied_slots'], 1)
        self.assertEqual(matrix['paid_slots'], 1)

        # Checa slot alocado
        row_seoyeon = next(it for it in matrix['items'] if it['id'] == self.item_seoyeon.id)
        slot_s1_data = row_seoyeon['slots'][self.set1.id]
        self.assertEqual(slot_s1_data['claimed_by']['name'], 'Bia Silva')
        self.assertTrue(slot_s1_data['is_item_paid'])

    def test_allocator_filters_cegs_by_search_group_and_era(self):
        other_group = KpopGroup.objects.create(name='NewJeans', slug='newjeans')
        other_era = Era.objects.create(group=other_group, name='Get Up', slug='get-up')
        other_ceg = CEG.objects.create(
            era=other_era,
            title='NewJeans Get Up Allocator Test',
            slug='newjeans-get-up-allocator-test',
            status=CEG.Status.OPEN
        )
        url = reverse('bulk_joiner_allocator_global')

        response = self.client.get(url, {'q': 'NewJeans Get Up'})
        self.assertContains(response, other_ceg.title)
        self.assertNotContains(response, self.ceg.title)

        response = self.client.get(url, {'group_id': other_group.id})
        self.assertContains(response, other_ceg.title)
        self.assertNotContains(response, self.ceg.title)

        response = self.client.get(url, {'era_id': other_era.id})
        self.assertContains(response, other_ceg.title)
        self.assertNotContains(response, self.ceg.title)

    def test_parse_allocation_text_explicit_set(self):
        """Valida parser com set explícito, telefone e status pago."""
        raw = "Set 2 | Seoyeon | 11 98888-7777 | Pago"
        result = BulkJoinerAllocatorService.parse_allocation_text(self.ceg, raw)
        self.assertTrue(result['success'])
        self.assertEqual(result['summary']['ready'], 1)
        self.assertEqual(result['summary']['errors'], 0)

        row = result['rows'][0]
        self.assertEqual(row['status'], 'READY')
        self.assertEqual(row['target_set_number'], 2)
        self.assertEqual(row['target_item_id'], self.item_seoyeon.id)
        self.assertEqual(row['participant_id'], self.participant1.id)
        self.assertTrue(row['is_paid'])

    def test_parse_allocation_text_auto_next_set(self):
        """Valida que duas linhas para o mesmo item sem set especificado ocupam Set 1 e Set 2."""
        raw = """
        Seoyeon | 11988887777 | Pendente
        Seoyeon | 11999990000 | Pago
        """
        result = BulkJoinerAllocatorService.parse_allocation_text(self.ceg, raw, options={'auto_next_set': True})
        self.assertTrue(result['success'])
        self.assertEqual(result['summary']['ready'], 2)

        row1 = result['rows'][0]
        row2 = result['rows'][1]

        self.assertEqual(row1['target_set_number'], 1)
        self.assertEqual(row2['target_set_number'], 2)
        self.assertFalse(row1['is_paid'])
        self.assertTrue(row2['is_paid'])
        self.assertTrue(row2['participant_is_new'])

    def test_execute_bulk_allocations_and_auto_create_participant(self):
        """Executa gravação com participante novo e garante padronização canônica e criação do Claim."""
        raw = "Set 1 | Chaeyeon | Camila Mendes | (11) 97777-6666 | @camilam | Pago"
        parsed = BulkJoinerAllocatorService.parse_allocation_text(self.ceg, raw)
        self.assertEqual(parsed['summary']['ready'], 1)

        res = BulkJoinerAllocatorService.execute_bulk_allocations(
            self.ceg,
            parsed['rows'],
            options={'auto_create_participants': True}
        )
        self.assertTrue(res['success'])
        self.assertEqual(res['allocated_count'], 1)
        self.assertEqual(res['new_participants_count'], 1)

        # Checa novo participante no banco
        p = Participant.objects.filter(whatsapp='5511977776666').first()
        self.assertIsNotNone(p)
        self.assertEqual(p.name, 'Camila Mendes')
        self.assertEqual(p.social_handle, '@camilam')

        # Checa slot
        self.slot_s1_chaeyeon.refresh_from_db()
        self.assertEqual(self.slot_s1_chaeyeon.claimed_by, p)
        self.assertEqual(self.slot_s1_chaeyeon.status, ItemSlot.Status.PAID)
        self.assertTrue(self.slot_s1_chaeyeon.is_item_paid)

        # Checa claim
        claim = Claim.objects.filter(slot=self.slot_s1_chaeyeon).first()
        self.assertIsNotNone(claim)
        self.assertEqual(claim.participant, p)
        self.assertEqual(claim.status, Claim.Status.PAID)

    def test_conflict_handling_overwrite_toggle(self):
        """Testa se conflitos em slots ocupados são detectados ou sobrescritos com overwrite."""
        # Pré-ocupa o slot Set 1 Jiwoo
        self.slot_s1_jiwoo.claimed_by = self.participant1
        self.slot_s1_jiwoo.status = ItemSlot.Status.RESERVED
        self.slot_s1_jiwoo.save()

        raw = "Set 1 | Jiwoo | 11955554444"

        # Sem overwrite -> conflito
        res_conflict = BulkJoinerAllocatorService.parse_allocation_text(self.ceg, raw, options={'overwrite': False})
        self.assertEqual(res_conflict['summary']['conflicts'], 1)
        self.assertEqual(res_conflict['summary']['ready'], 0)

        # Com overwrite -> pronto
        res_overwrite = BulkJoinerAllocatorService.parse_allocation_text(self.ceg, raw, options={'overwrite': True})
        self.assertEqual(res_overwrite['summary']['conflicts'], 0)
        self.assertEqual(res_overwrite['summary']['ready'], 1)

    def test_save_matrix_allocations(self):
        """Testa operações em lote da matriz interativa (assign, toggle_payment, release)."""
        updates = [
            # 1. Atribui Bia Silva ao Set 1 Chaeyeon (Pago)
            {
                'slot_id': self.slot_s1_chaeyeon.id,
                'action': 'assign',
                'participant_id': self.participant1.id,
                'is_paid': True
            },
            # 2. Atribui e depois libera
            {
                'slot_id': self.slot_s2_jiwoo.id,
                'action': 'assign',
                'participant_id': self.participant1.id,
                'is_paid': False
            }
        ]
        res = BulkJoinerAllocatorService.save_matrix_allocations(self.ceg, updates)
        self.assertTrue(res['success'])
        self.assertEqual(res['updated_count'], 2)

        self.slot_s1_chaeyeon.refresh_from_db()
        self.assertEqual(self.slot_s1_chaeyeon.claimed_by, self.participant1)
        self.assertTrue(self.slot_s1_chaeyeon.is_item_paid)

        # Agora libera o slot 2 de Jiwoo
        res_rel = BulkJoinerAllocatorService.save_matrix_allocations(self.ceg, [{'slot_id': self.slot_s2_jiwoo.id, 'action': 'release'}])
        self.assertTrue(res_rel['success'])
        self.assertEqual(res_rel['released_count'], 1)

        self.slot_s2_jiwoo.refresh_from_db()
        self.assertIsNone(self.slot_s2_jiwoo.claimed_by)
        self.assertEqual(self.slot_s2_jiwoo.status, ItemSlot.Status.AVAILABLE)

    def test_views_and_api_endpoints(self):
        """Valida carregamento de tela e requisições HTTP aos endpoints AJAX."""
        # 1. GET tela do alocador
        url = f'/ceg/{self.ceg.slug}/alocar-massa/'
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Alocador de Joiners em Massa')

        # 2. POST API parse_text
        api_url = f'/ceg/{self.ceg.slug}/alocar-massa/api/'
        payload_parse = {
            'action': 'parse_text',
            'raw_text': 'Set 1 | Seoyeon | 11988887777 | Pago'
        }
        res_parse = self.client.post(api_url, json.dumps(payload_parse), content_type='application/json')
        self.assertEqual(res_parse.status_code, 200)
        data_parse = res_parse.json()
        self.assertTrue(data_parse['success'])
        self.assertEqual(data_parse['summary']['ready'], 1)

        # 3. POST API execute_bulk
        payload_exec = {
            'action': 'execute_bulk',
            'rows': data_parse['rows']
        }
        res_exec = self.client.post(api_url, json.dumps(payload_exec), content_type='application/json')
        self.assertEqual(res_exec.status_code, 200)
        data_exec = res_exec.json()
        self.assertTrue(data_exec['success'])
        self.assertEqual(data_exec['allocated_count'], 1)

        # 4. POST API get_matrix
        res_mat = self.client.post(api_url, json.dumps({'action': 'get_matrix'}), content_type='application/json')
        self.assertEqual(res_mat.status_code, 200)
        self.assertTrue(res_mat.json()['success'])

    def test_save_matrix_assign_marked_as_paid(self):
        """
        Valida o cenário onde slots são atribuídos na matriz e marcados como pagos antes de salvar.
        Garante que tanto a atribuição (claimed_by) quanto o Claim e o status de pagamento são gravados.
        """
        updates = [
            {
                'slot_id': self.slot_s1_seoyeon.id,
                'action': 'assign',
                'participant_id': self.participant1.id,
                'is_paid': True
            }
        ]
        res = BulkJoinerAllocatorService.save_matrix_allocations(self.ceg, updates)
        self.assertTrue(res['success'])
        self.assertEqual(res['updated_count'], 1)

        self.slot_s1_seoyeon.refresh_from_db()
        self.assertEqual(self.slot_s1_seoyeon.claimed_by, self.participant1)
        self.assertTrue(self.slot_s1_seoyeon.is_item_paid)
        self.assertEqual(self.slot_s1_seoyeon.status, ItemSlot.Status.PAID)

        # Claim deve ter sido criado com status PAID
        claim = Claim.objects.get(slot=self.slot_s1_seoyeon)
        self.assertEqual(claim.participant, self.participant1)
        self.assertEqual(claim.status, Claim.Status.PAID)
        self.assertIsNotNone(claim.paid_at)

    def test_save_matrix_toggle_payment_with_participant_id_heals_unassigned_slot(self):
        """
        Valida que se toggle_payment for enviado com participant_id para um slot que ainda não
        estava salvo no banco, a atribuição é realizada e o Claim é criado como PAID.
        """
        updates = [
            {
                'slot_id': self.slot_s2_seoyeon.id,
                'action': 'toggle_payment',
                'participant_id': self.participant1.id,
                'is_paid': True
            }
        ]
        res = BulkJoinerAllocatorService.save_matrix_allocations(self.ceg, updates)
        self.assertTrue(res['success'])
        self.assertEqual(res['updated_count'], 1)

        self.slot_s2_seoyeon.refresh_from_db()
        self.assertEqual(self.slot_s2_seoyeon.claimed_by, self.participant1)
        self.assertTrue(self.slot_s2_seoyeon.is_item_paid)
        self.assertEqual(self.slot_s2_seoyeon.status, ItemSlot.Status.PAID)

        claim = Claim.objects.get(slot=self.slot_s2_seoyeon)
        self.assertEqual(claim.participant, self.participant1)
        self.assertEqual(claim.status, Claim.Status.PAID)

