import threading
import time
from datetime import timedelta
from decimal import Decimal
from django.test import TransactionTestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import connection

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot, ClaimAttemptLog, ItemWaitingList
from apps.cegs.services import (
    ClaimService,
    SlotUnavailableError,
    CEGNotOpenYetError,
    AddedToWaitingListError,
)
from apps.groups.models import KpopGroup, Era
from apps.participants.models import Participant, Claim


class SimultaneousClaimSimulationTests(TransactionTestCase):
    """
    Simulacoes de alta concorrencia com 10 a 50 participantes simultaneos
    testando Auto-Fallback entre sets, Lista de Espera por Item e Alocacao Automatica.
    """

    def setUp(self):
        ClaimService.reset_in_memory_counters()
        self.group = KpopGroup.objects.create(name="tripleS")
        self.era = Era.objects.create(group=self.group, name="Assemble24")
        self.admin_user = User.objects.create_superuser('admin_test', 'admin@test.com', 'pass123')

    def _create_ceg(self, num_sets=1, is_scheduled_opened=True, is_standby=False):
        """Cria uma CEG com N sets e 1 item definition (Photocard Seoyeon)."""
        now = timezone.now()
        if is_standby:
            opens_at = now + timedelta(minutes=10)
            status = CEG.Status.SCHEDULED
        elif is_scheduled_opened:
            opens_at = now - timedelta(seconds=5)
            status = CEG.Status.OPEN
        else:
            opens_at = None
            status = CEG.Status.OPEN

        ceg = CEG.objects.create(
            era=self.era,
            title=f"CEG Concurrency Test ({num_sets} Sets)",
            status=status,
            opens_at=opens_at,
            pix_key="test@pix.com"
        )

        item_def = CEGItemDefinition.objects.create(
            ceg=ceg,
            name="Photocard Seoyeon",
            member_name="Seoyeon",
            default_price=Decimal("50.00")
        )

        sets = []
        slots = []
        for i in range(1, num_sets + 1):
            cset = CEGSet.objects.create(
                ceg=ceg,
                set_number=i,
                is_active=True
            )
            slot = ItemSlot.objects.create(
                set=cset,
                item_definition=item_def,
                price=Decimal("50.00"),
                status=ItemSlot.Status.AVAILABLE
            )
            sets.append(cset)
            slots.append(slot)

        return ceg, item_def, sets, slots

    def test_simultaneous_claim_1_set_10_people(self):
        """
        Teste 1: CEG com 1 SET e 10 PESSOAS dando claim no mesmo milissegundo.
        1 pessoa garante o slot (1º lugar).
        As outras 9 pessoas entram na Lista de Espera por Item (posições 1 a 9).
        """
        ceg, item_def, sets, slots = self._create_ceg(num_sets=1)
        target_slot = slots[0]
        num_users = 10

        results = []
        waiting_list_errors = []
        barrier = threading.Barrier(num_users)

        def claim_worker(user_id):
            connection.close()
            try:
                barrier.wait()
                claim = ClaimService.claim_slot(
                    slot_id=target_slot.id,
                    name=f"Participante {user_id}",
                    phone=f"551198888{user_id:04d}",
                    social_handle=f"@user_{user_id}"
                )
                results.append((user_id, claim))
            except AddedToWaitingListError as e:
                waiting_list_errors.append((user_id, e.position, str(e)))
            except Exception as e:
                waiting_list_errors.append((user_id, None, f"{type(e).__name__}: {e}"))
            finally:
                connection.close()

        threads = [threading.Thread(target=claim_worker, args=(i,)) for i in range(num_users)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        print("\n" + "="*70)
        print(f"[RESULTADO TESTE 1]: 1 SET - {num_users} PESSOAS CONCORRENTES")
        print("="*70)
        print(f"[Vencedores] Claim garantido: {len(results)}")
        if results:
            for w_id, w_claim in results:
                print(f"   Vencedor: Participante {w_id} (Claim #{w_claim.id}, Slot #{w_claim.slot.id})")
        print(f"[Fila de Espera] Adicionados a Fila: {len(waiting_list_errors)}")
        for err in waiting_list_errors[:5]:
            print(f"   Posicao na Fila: #{err[1]} -> User {err[0]}")

        self.assertEqual(len(results), 1, "Apenas 1 pessoa DEVE conseguir a vaga fisica do unico set!")
        self.assertEqual(len(waiting_list_errors), 9, "As outras 9 pessoas DEVEM ser colocadas na Lista de Espera!")
        target_slot.refresh_from_db()
        self.assertEqual(target_slot.status, ItemSlot.Status.RESERVED)
        self.assertEqual(ItemWaitingList.objects.filter(item_definition=item_def, status=ItemWaitingList.Status.WAITING).count(), 9)

    def test_simultaneous_claim_1_set_50_people(self):
        """
        Teste 2: CEG com 1 SET e 50 PESSOAS dando claim no mesmo milissegundo.
        1 pessoa garante o slot; 49 entram ordenadamente na Lista de Espera.
        """
        ceg, item_def, sets, slots = self._create_ceg(num_sets=1)
        target_slot = slots[0]
        num_users = 50

        results = []
        waiting_list_errors = []
        barrier = threading.Barrier(num_users)

        def claim_worker(user_id):
            connection.close()
            try:
                barrier.wait()
                claim = ClaimService.claim_slot(
                    slot_id=target_slot.id,
                    name=f"Participante {user_id}",
                    phone=f"551197777{user_id:04d}",
                    social_handle=f"@user_{user_id}"
                )
                results.append((user_id, claim))
            except AddedToWaitingListError as e:
                waiting_list_errors.append((user_id, e.position, str(e)))
            except Exception as e:
                waiting_list_errors.append((user_id, None, f"{type(e).__name__}: {e}"))
            finally:
                connection.close()

        threads = [threading.Thread(target=claim_worker, args=(i,)) for i in range(num_users)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        print("\n" + "="*70)
        print(f"[RESULTADO TESTE 2]: 1 SET - {num_users} PESSOAS CONCORRENTES")
        print("="*70)
        print(f"[Vencedores]: {len(results)}")
        print(f"[Fila de Espera]: {len(waiting_list_errors)}")

        self.assertEqual(len(results), 1, "Apenas 1 pessoa ganha o unico slot!")
        self.assertEqual(len(waiting_list_errors), 49, "49 pessoas entram na Lista de Espera!")
        self.assertEqual(ItemWaitingList.objects.filter(item_definition=item_def, status=ItemWaitingList.Status.WAITING).count(), 49)

    def test_simultaneous_claim_3_sets_with_autofallback_and_waiting_list(self):
        """
        Teste 3: CEG com 3 SETS — 50 PESSOAS clicando no slot do SET 1.
        Com o AUTO-FALLBACK implementado:
        - 1º a chegar garante o Set 1.
        - 2º a chegar ganha o Set 2 via Auto-Fallback.
        - 3º a chegar ganha o Set 3 via Auto-Fallback.
        - As outras 47 pessoas entram na Lista de Espera por Item como #1 a #47.
        """
        ceg, item_def, sets, slots = self._create_ceg(num_sets=3)
        slot_set1, slot_set2, slot_set3 = slots[0], slots[1], slots[2]
        num_users = 50

        results = []
        waiting_list_errors = []
        barrier = threading.Barrier(num_users)

        def claim_worker(user_id):
            connection.close()
            try:
                barrier.wait()
                # Todos os 50 clicam na opcao do Set 1
                claim = ClaimService.claim_slot(
                    slot_id=slot_set1.id,
                    name=f"Participante {user_id}",
                    phone=f"551196666{user_id:04d}",
                    social_handle=f"@user_{user_id}"
                )
                results.append((user_id, claim))
            except AddedToWaitingListError as e:
                waiting_list_errors.append((user_id, e.position, str(e)))
            except Exception as e:
                waiting_list_errors.append((user_id, None, f"{type(e).__name__}: {e}"))
            finally:
                connection.close()

        threads = [threading.Thread(target=claim_worker, args=(i,)) for i in range(num_users)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        slot_set1.refresh_from_db()
        slot_set2.refresh_from_db()
        slot_set3.refresh_from_db()

        print("\n" + "="*70)
        print(f"[RESULTADO TESTE 3]: 3 SETS DISPONIVEIS - 50 PESSOAS CLICANDO NO SET 1")
        print("="*70)
        print(f"Set 1 (Slot #{slot_set1.id}): Status = {slot_set1.status}, Claimed By = {slot_set1.claimed_by}")
        print(f"Set 2 (Slot #{slot_set2.id}): Status = {slot_set2.status}, Claimed By = {slot_set2.claimed_by}")
        print(f"Set 3 (Slot #{slot_set3.id}): Status = {slot_set3.status}, Claimed By = {slot_set3.claimed_by}")
        print(f"Total de Claims Garantidos (Set 1 + Fallback Set 2 e 3): {len(results)}")
        print(f"Total Adicionados a Fila de Espera: {len(waiting_list_errors)}")
        print("="*70)

        # Validações estritas do Auto-Fallback
        self.assertEqual(len(results), 3, "Exatamente 3 pessoas devem garantir vagas (1 em cada set)!")
        self.assertEqual(slot_set1.status, ItemSlot.Status.RESERVED)
        self.assertEqual(slot_set2.status, ItemSlot.Status.RESERVED)
        self.assertEqual(slot_set3.status, ItemSlot.Status.RESERVED)
        self.assertIsNotNone(slot_set1.claimed_by)
        self.assertIsNotNone(slot_set2.claimed_by)
        self.assertIsNotNone(slot_set3.claimed_by)

        # Verifica se os 3 vencedores sao pessoas diferentes
        claimed_participant_ids = {c[1].participant.id for c in results}
        self.assertEqual(len(claimed_participant_ids), 3)

        # Validação da Fila de Espera
        self.assertEqual(len(waiting_list_errors), 47, "Os outros 47 devem estar na fila de espera!")
        waiting_count = ItemWaitingList.objects.filter(item_definition=item_def, status=ItemWaitingList.Status.WAITING).count()
        self.assertEqual(waiting_count, 47)

    def test_standby_scheduled_ceg_blocks_all_before_opens_at(self):
        """
        Teste 4: CEG Programada AINDA EM STANDBY — 20 pessoas tentando dar claim antes do horário.
        """
        ceg, item_def, sets, slots = self._create_ceg(num_sets=1, is_standby=True)
        target_slot = slots[0]
        num_users = 20

        results = []
        errors = []
        barrier = threading.Barrier(num_users)

        def claim_worker(user_id):
            connection.close()
            try:
                barrier.wait()
                claim = ClaimService.claim_slot(
                    slot_id=target_slot.id,
                    name=f"Participante {user_id}",
                    phone=f"551195555{user_id:04d}",
                    social_handle=f"@user_{user_id}"
                )
                results.append((user_id, claim))
            except Exception as e:
                errors.append((user_id, type(e).__name__, str(e)))
            finally:
                connection.close()

        threads = [threading.Thread(target=claim_worker, args=(i,)) for i in range(num_users)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 0, "Nenhum claim pode ser feito durante o Standby!")
        self.assertEqual(len(errors), num_users, "Todos os 20 participantes devem ser bloqueados!")
        self.assertTrue(all(err[1] == "CEGNotOpenYetError" for err in errors))

    def test_allocate_waiting_list_when_extra_set_created(self):
        """
        Teste 5: Criar um Set Extra aloca automaticamente pessoas da Lista de Espera.
        """
        ceg, item_def, sets, slots = self._create_ceg(num_sets=1)
        slot1 = slots[0]

        # 1. Participante 1 garante o Set 1
        claim1 = ClaimService.claim_slot(
            slot_id=slot1.id,
            name="Participante Titular",
            phone="5511999990001",
            social_handle="@titular"
        )
        self.assertIsNotNone(claim1)

        # 2. Participante 2 tenta e entra na fila de espera (#1 da fila)
        with self.assertRaises(AddedToWaitingListError) as ctx:
            ClaimService.claim_slot(
                slot_id=slot1.id,
                name="Participante da Fila",
                phone="5511999990002",
                social_handle="@fila"
            )
        self.assertEqual(ctx.exception.position, 1)

        waiting_entry = ItemWaitingList.objects.get(item_definition=item_def, status=ItemWaitingList.Status.WAITING)
        self.assertEqual(waiting_entry.name, "Participante da Fila")

        # 3. Organizador cria o Set 2
        set2 = CEGSet.objects.create(ceg=ceg, set_number=2, is_active=True)
        created_slots = set2.generate_slots()
        self.assertEqual(len(created_slots), 1)

        # 4. Aloca vagas da fila de espera para o novo set
        promoted = ClaimService.allocate_waiting_list_for_slots(created_slots)
        self.assertEqual(promoted, 1)

        # 5. Verifica se o novo slot do Set 2 foi automaticamente reservado para o Participante da Fila
        slot_set2 = created_slots[0]
        slot_set2.refresh_from_db()
        self.assertEqual(slot_set2.status, ItemSlot.Status.RESERVED)
        self.assertEqual(slot_set2.claimed_by.name, "Participante da Fila")

        waiting_entry.refresh_from_db()
        self.assertEqual(waiting_entry.status, ItemWaitingList.Status.PROMOTED)
        self.assertEqual(waiting_entry.allocated_slot, slot_set2)

    def test_promote_waiting_list_when_claim_cancelled(self):
        """
        Teste 6: Quando quem deu o 1º claim desiste/é cancelado, a vaga é repassada
        para o 1º colocado da lista de espera.
        """
        ceg, item_def, sets, slots = self._create_ceg(num_sets=1)
        slot1 = slots[0]

        # 1. Participante 1 garante a vaga
        ClaimService.claim_slot(
            slot_id=slot1.id,
            name="Participante 1",
            phone="5511999990001",
            social_handle="@user1"
        )

        # 2. Participante 2 entra na fila de espera
        try:
            ClaimService.claim_slot(
                slot_id=slot1.id,
                name="Participante 2 (Fila)",
                phone="5511999990002",
                social_handle="@user2"
            )
        except AddedToWaitingListError:
            pass

        # 3. Participante 1 desiste: remove reserva do slot1
        slot1.refresh_from_db()
        if hasattr(slot1, 'claim'):
            slot1.claim.delete()

        promoted = ClaimService.promote_from_waiting_list_on_slot_released(slot1)
        self.assertIsNotNone(promoted)
        self.assertEqual(promoted.name, "Participante 2 (Fila)")

        slot1.refresh_from_db()
        self.assertEqual(slot1.status, ItemSlot.Status.RESERVED)
        self.assertEqual(slot1.claimed_by.name, "Participante 2 (Fila)")
        self.assertEqual(slot1.claim.participant.name, "Participante 2 (Fila)")

    def test_ceg_logs_and_waiting_list_api_view(self):
        """
        Teste 7: Endpoint JSON /ceg/<slug>/logs-espera/ retorna logs e fila de espera para o admin.
        """
        ceg, item_def, sets, slots = self._create_ceg(num_sets=1)
        client = Client()
        client.force_login(self.admin_user)

        # Faz um claim e gera uma entrada de fila de espera
        ClaimService.claim_slot(
            slot_id=slots[0].id,
            name="Alice",
            phone="5511999990010",
            social_handle="@alice"
        )
        try:
            ClaimService.claim_slot(
                slot_id=slots[0].id,
                name="Bob",
                phone="5511999990020",
                social_handle="@bob"
            )
        except AddedToWaitingListError:
            pass

        response = client.get(f'/ceg/{ceg.slug}/logs-espera/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertGreaterEqual(len(data['logs']), 2)
        self.assertGreaterEqual(len(data['waiting_list']), 1)
        self.assertEqual(data['waiting_list'][0]['participant_name'], 'Bob')
