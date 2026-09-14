import logging
import threading
import time
from collections import defaultdict
from decimal import Decimal
from django.db import transaction, OperationalError
from django.utils import timezone
from apps.cegs.models import ItemSlot, CEG, ClaimAttemptLog, ItemWaitingList
from apps.participants.models import Participant, Claim, clean_phone_number

logger = logging.getLogger('cegs.concurrency')

_slot_counter_lock = threading.Lock()
_slot_attempts_count = defaultdict(int)
_claim_mutex = threading.RLock()
LAST_CLAIM_DISPUTES = []


def _get_next_attempt_number(slot_id: int) -> int:
    """Retorna e incrementa de forma thread-safe a ordem de tentativa/chegada para o slot."""
    with _slot_counter_lock:
        try:
            db_count = ClaimAttemptLog.objects.filter(slot_id=slot_id).count()
        except Exception:
            db_count = 0
        current = max(_slot_attempts_count.get(slot_id, 0), db_count) + 1
        _slot_attempts_count[slot_id] = current
        return current


def _resolve_slot_info(slot_id: int):
    try:
        data = ItemSlot.objects.filter(id=slot_id).values(
            'item_definition__name', 'set__set_number', 'set__ceg__title'
        ).first()
        if data:
            return (
                data['item_definition__name'],
                data['set__set_number'],
                data['set__ceg__title'],
            )
    except Exception:
        pass
    return (f"Slot #{slot_id}", 1, "CEG")


def _emit_claim_order_log(
    slot_id: int,
    item_name: str,
    set_number: int,
    ceg_title: str,
    attempt_number: int,
    name: str,
    phone: str,
    social_handle: str,
    won: bool,
    winner_info: str = None,
):
    """
    Exibe log visual formatado no terminal/console e registra no logger informando
    a ordem exata de quem deu claim no segundo zero.
    """
    handle_str = f" ({social_handle})" if social_handle else ""
    item_info = f"{item_name} (Set #{set_number})"
    timestamp_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    if won:
        medal = f"{attempt_number}º LUGAR 🏆 (VENCEU A DISPUTA - RESERVA GARANTIDA)"
        status_line = "SUCESSO: Slot reservado no banco de dados e Claim confirmado."
    else:
        medal = f"{attempt_number}º LUGAR ❌ (PERDEU A DISPUTA NO SEGUNDO ZERO)"
        status_line = f"RECUSADO: Slot já havia sido garantido por {winner_info or 'outro participante'}."

    log_box = (
        f"\n{'=' * 75}\n"
        f"⚡ [LOG DE CONCORRÊNCIA CEG] Disputa de Slot no Segundo Zero\n"
        f"{'-' * 75}\n"
        f"📦 Item: {item_info} — {ceg_title}\n"
        f"🎯 Ordem de Claim: {medal}\n"
        f"👤 Participante: {name}{handle_str} | WhatsApp: +{phone}\n"
        f"⏰ Horário da Tentativa: {timestamp_str}\n"
        f"📋 Status: {status_line}\n"
        f"{'=' * 75}\n"
    )

    try:
        print(log_box)
    except UnicodeEncodeError:
        safe_box = log_box.encode('ascii', 'ignore').decode('ascii')
        print(safe_box)

    logger.info(
        f"[CLAIM_ORDER] Slot #{slot_id} ({item_info}) | {attempt_number}º a dar claim | "
        f"{'VENCEU' if won else 'PERDEU'} | {name}{handle_str} (+{phone})"
    )

    LAST_CLAIM_DISPUTES.append({
        'slot_id': slot_id,
        'item_name': item_name,
        'set_number': set_number,
        'ceg_title': ceg_title,
        'attempt_number': attempt_number,
        'participant_name': name,
        'social_handle': social_handle,
        'phone': phone,
        'won': won,
        'winner_info': winner_info,
        'timestamp': timezone.now(),
    })


class CEGError(Exception):
    pass


class CEGNotOpenYetError(CEGError):
    pass


class SlotUnavailableError(CEGError):
    pass


class AddedToWaitingListError(SlotUnavailableError):
    def __init__(self, position: int, item_name: str, message: str = ""):
        self.position = position
        self.item_name = item_name
        self.message = message or (
            f"Todos os slots de '{item_name}' foram preenchidos! "
            f"Você foi adicionado(a) à Lista de Espera como #{position}º lugar."
        )
        super().__init__(self.message)


class ClaimService:
    @staticmethod
    def claim_slot(slot_id: int, name: str, phone: str, social_handle: str = "", notes: str = "", username: str = "", bypass_status_check: bool = False) -> Claim:
        """
        Executa a reserva atômica de um ItemSlot com proteção de concorrência.
        Garante que apenas 1 pessoa consiga reservar o slot físico no segundo zero
        e gera log output registrando a ordem exata de quem deu claim.
        bypass_status_check: se True (admin), ignora validações de status/data da CEG.
        """
        with _claim_mutex:
            return ClaimService._claim_slot_internal(
                slot_id=slot_id,
                name=name,
                phone=phone,
                social_handle=social_handle,
                notes=notes,
                username=username,
                bypass_status_check=bypass_status_check,
            )

    @staticmethod
    def _claim_slot_internal(slot_id: int, name: str, phone: str, social_handle: str = "", notes: str = "", username: str = "", bypass_status_check: bool = False) -> Claim:
        cleaned_phone = clean_phone_number(phone)
        if not cleaned_phone:
            raise CEGError("Número de WhatsApp inválido.")

        name_clean = name.strip()
        username_clean = username.strip()
        social_clean = social_handle.strip()
        attempt_number = _get_next_attempt_number(slot_id)

        item_name = f"Slot #{slot_id}"
        set_number = 1
        ceg_title = "CEG"

        max_retries = 8
        for attempt in range(max_retries):
            slot_already_taken = False
            lost_race = False
            winner_info = None

            try:
                # Prepara/localiza o participante dentro da transação e retry de concorrência
                participant, created = Participant.objects.get_or_create(
                    whatsapp=cleaned_phone,
                    defaults={
                        'name': name_clean,
                        'username': username_clean,
                        'social_handle': social_clean,
                    }
                )
                updated = False
                if name_clean and participant.name != name_clean:
                    participant.name = name_clean
                    updated = True
                if username_clean and participant.username != username_clean:
                    participant.username = username_clean
                    updated = True
                if social_clean and participant.social_handle != social_clean:
                    participant.social_handle = social_clean
                    updated = True
                if updated:
                    participant.save()

                # 1. Bloqueio seletivo de linha e transação atômica completa
                with transaction.atomic():
                    try:
                        slot = ItemSlot.objects.select_for_update().select_related(
                            'set__ceg', 'item_definition', 'claimed_by'
                        ).get(id=slot_id)
                    except ItemSlot.DoesNotExist:
                        raise CEGError("Slot de item não encontrado.")

                    ceg = slot.set.ceg
                    item_name = slot.item_definition.name
                    set_number = slot.set.set_number
                    ceg_title = ceg.title

                    # 2. Validação do Modo Standby / Abertura da CEG (admin bypass)
                    if not bypass_status_check:
                        if ceg.opens_at and timezone.now() < ceg.opens_at:
                            raise CEGNotOpenYetError(
                                f"A CEG ainda está em modo Standby! As reservas abrem em {ceg.opens_at.strftime('%d/%m/%Y às %H:%M:%S')}."
                            )

                        if ceg.status not in (CEG.Status.OPEN, CEG.Status.SCHEDULED):
                            raise CEGError("Esta CEG não está aceitando reservas no momento.")

                        if not slot.set.is_active:
                            raise CEGError("Este Set está desativado para reservas.")

                    # 3. Verificação de Concorrência inicial
                    if slot.status != ItemSlot.Status.AVAILABLE:
                        winner = slot.claimed_by
                        winner_info = f"{winner.display_name} ({winner.social_handle})" if (winner and winner.social_handle) else (winner.display_name if winner else "outro participante")
                        slot_already_taken = True
                    else:
                        now = timezone.now()

                        # 5. Atualização Atômica Condicional: apenas 1 processo consegue alterar de AVAILABLE para RESERVED
                        rows_updated = ItemSlot.objects.filter(
                            id=slot.id,
                            status=ItemSlot.Status.AVAILABLE
                        ).update(
                            status=ItemSlot.Status.RESERVED,
                            claimed_by=participant,
                            claimed_at=now
                        )

                        if rows_updated == 0:
                            slot.refresh_from_db()
                            winner = slot.claimed_by
                            winner_info = f"{winner.display_name} ({winner.social_handle})" if (winner and winner.social_handle) else (winner.display_name if winner else "outro participante")
                            lost_race = True
                        else:
                            # 6. Cria o registro de Claim para o vencedor (1º a conseguir o slot)
                            slot.refresh_from_db()
                            claim = Claim.objects.create(
                                slot=slot,
                                participant=participant,
                                status=Claim.Status.PENDING,
                                total_price=slot.price,
                                participant_notes=notes.strip(),
                                claimed_at=now
                            )

                            # 7. Registra tentativa vencedora no banco
                            try:
                                ClaimAttemptLog.objects.create(
                                    slot=slot,
                                    attempt_number=attempt_number,
                                    participant_name=name_clean,
                                    phone=cleaned_phone,
                                    social_handle=social_clean,
                                    result=ClaimAttemptLog.Result.SUCCESS,
                                    details="Reserva garantida com sucesso (1º a conseguir o slot)."
                                )
                            except Exception:
                                pass

                            # 8. Emite log output da ordem de chegada (vencedor)
                            _emit_claim_order_log(
                                slot_id=slot.id,
                                item_name=item_name,
                                set_number=set_number,
                                ceg_title=ceg_title,
                                attempt_number=attempt_number,
                                name=name_clean,
                                phone=cleaned_phone,
                                social_handle=social_clean,
                                won=True
                            )

                            return claim

                # Fora do transaction.atomic: se perdeu a corrida ou o slot já estava tomado,
                # tenta Auto-Fallback para os próximos sets ou adiciona à Lista de Espera por Item
                if slot_already_taken or lost_race:
                    # 1. TENTA AUTO-FALLBACK PARA O MESMO ITEM EM OUTROS SETS ATIVOS DA CEG
                    fallback_slots = list(
                        ItemSlot.objects.filter(
                            set__ceg=ceg,
                            set__is_active=True,
                            item_definition=slot.item_definition,
                            status=ItemSlot.Status.AVAILABLE
                        ).exclude(id=slot.id).order_by('set__set_number', 'id')
                    )

                    fallback_success = False
                    fallback_claim = None
                    fallback_target_slot = None

                    for candidate in fallback_slots:
                        now = timezone.now()
                        with transaction.atomic():
                            fb_updated = ItemSlot.objects.filter(
                                id=candidate.id,
                                status=ItemSlot.Status.AVAILABLE
                            ).update(
                                status=ItemSlot.Status.RESERVED,
                                claimed_by=participant,
                                claimed_at=now
                            )
                            if fb_updated == 1:
                                candidate.refresh_from_db()
                                fallback_claim = Claim.objects.create(
                                    slot=candidate,
                                    participant=participant,
                                    status=Claim.Status.PENDING,
                                    total_price=candidate.price,
                                    participant_notes=notes.strip(),
                                    claimed_at=now
                                )
                                fallback_success = True
                                fallback_target_slot = candidate
                                break

                    if fallback_success and fallback_claim and fallback_target_slot:
                        try:
                            ClaimAttemptLog.objects.create(
                                slot=fallback_target_slot,
                                attempt_number=attempt_number,
                                participant_name=name_clean,
                                phone=cleaned_phone,
                                social_handle=social_clean,
                                result=ClaimAttemptLog.Result.AUTO_FALLBACK,
                                details=(
                                    f"Reserva garantida via Auto-Fallback! "
                                    f"O Set #{set_number} estava ocupado, vaga alocada no Set #{fallback_target_slot.set.set_number}."
                                )
                            )
                        except Exception:
                            pass

                        _emit_claim_order_log(
                            slot_id=fallback_target_slot.id,
                            item_name=item_name,
                            set_number=fallback_target_slot.set.set_number,
                            ceg_title=ceg_title,
                            attempt_number=attempt_number,
                            name=name_clean,
                            phone=cleaned_phone,
                            social_handle=social_clean,
                            won=True,
                            winner_info=f"Auto-fallback a partir do Set #{set_number}"
                        )

                        fallback_claim.auto_fallback_from_set = set_number
                        fallback_claim.auto_fallback_to_set = fallback_target_slot.set.set_number
                        return fallback_claim

                    # 2. SE NENHUM SET TIVER O ITEM DISPONÍVEL (TODOS CHEIOS OU SÓ 1 SET EXISTE):
                    # Adiciona o participante à Lista de Espera por Item
                    with transaction.atomic():
                        existing_entry = ItemWaitingList.objects.filter(
                            item_definition=slot.item_definition,
                            participant=participant,
                            status=ItemWaitingList.Status.WAITING
                        ).first()

                        if existing_entry:
                            waiting_pos = existing_entry.position
                        else:
                            waiting_count = ItemWaitingList.objects.filter(
                                item_definition=slot.item_definition,
                                status=ItemWaitingList.Status.WAITING
                            ).count()
                            waiting_pos = waiting_count + 1
                            existing_entry = ItemWaitingList.objects.create(
                                item_definition=slot.item_definition,
                                participant=participant,
                                name=name_clean,
                                phone=cleaned_phone,
                                social_handle=social_clean,
                                position=waiting_pos,
                                status=ItemWaitingList.Status.WAITING,
                                notes=notes.strip()
                            )

                    detail_text = (
                        f"Todos os sets ocupados. Adicionado(a) à Lista de Espera como #{waiting_pos}º lugar. "
                        f"(Tentativa original no Set #{set_number}, ocupado por {winner_info})."
                    )

                    try:
                        ClaimAttemptLog.objects.create(
                            slot=slot,
                            attempt_number=attempt_number,
                            participant_name=name_clean,
                            phone=cleaned_phone,
                            social_handle=social_clean,
                            result=ClaimAttemptLog.Result.WAITING_LIST,
                            details=detail_text
                        )
                    except Exception:
                        pass

                    _emit_claim_order_log(
                        slot_id=slot.id,
                        item_name=item_name,
                        set_number=set_number,
                        ceg_title=ceg_title,
                        attempt_number=attempt_number,
                        name=name_clean,
                        phone=cleaned_phone,
                        social_handle=social_clean,
                        won=False,
                        winner_info=f"Lista de Espera #{waiting_pos} (Set #{set_number} ocupado por {winner_info})"
                    )

                    raise AddedToWaitingListError(
                        position=waiting_pos,
                        item_name=item_name,
                        message=(
                            f"Todos os slots de '{item_name}' foram preenchidos! "
                            f"Você foi adicionado(a) à Lista de Espera na posição #{waiting_pos}. "
                            f"Se houver desistência ou um novo Set for aberto, sua vaga será alocada prioritariamente."
                        )
                    )

            except OperationalError:
                if attempt < max_retries - 1:
                    time.sleep(0.04 * (attempt + 1))
                    continue

                res_item, res_set, res_ceg = _resolve_slot_info(slot_id)
                final_item = item_name if item_name != f"Slot #{slot_id}" else res_item
                final_set = set_number if set_number != 1 else res_set
                final_ceg = ceg_title if ceg_title != "CEG" else res_ceg

                _emit_claim_order_log(
                    slot_id=slot_id,
                    item_name=final_item,
                    set_number=final_set,
                    ceg_title=final_ceg,
                    attempt_number=attempt_number,
                    name=name_clean,
                    phone=cleaned_phone,
                    social_handle=social_clean,
                    won=False,
                    winner_info="outro participante (disputa simultânea no mesmo milissegundo)"
                )
                raise SlotUnavailableError(
                    "Este item está sob alta concorrência e acabou de ser reservado por outro participante."
                )

    @staticmethod
    def allocate_waiting_list_for_slots(slots) -> int:
        """
        Aloca participantes da lista de espera para os slots disponíveis fornecidos.
        Usado principalmente após a criação de um Set extra.
        Retorna o total de vagas preenchidas a partir da fila de espera.
        """
        with _claim_mutex:
            return ClaimService._allocate_waiting_list_for_slots_internal(slots)

    @staticmethod
    def _allocate_waiting_list_for_slots_internal(slots) -> int:
        promoted_count = 0
        now = timezone.now()
        for slot in slots:
            if slot.status != ItemSlot.Status.AVAILABLE:
                continue

            with transaction.atomic():
                waiting_entry = ItemWaitingList.objects.select_for_update().filter(
                    item_definition=slot.item_definition,
                    status=ItemWaitingList.Status.WAITING
                ).order_by('position', 'created_at').first()

                if not waiting_entry:
                    continue

                slot.status = ItemSlot.Status.RESERVED
                slot.claimed_by = waiting_entry.participant
                slot.claimed_at = now
                slot.save()

                Claim.objects.create(
                    slot=slot,
                    participant=waiting_entry.participant,
                    status=Claim.Status.PENDING,
                    total_price=slot.price,
                    participant_notes="Alocado automaticamente da Lista de Espera ao abrir novo Set.",
                    claimed_at=now
                )

                waiting_entry.status = ItemWaitingList.Status.PROMOTED
                waiting_entry.allocated_slot = slot
                waiting_entry.promoted_at = now
                waiting_entry.save()

                try:
                    ClaimAttemptLog.objects.create(
                        slot=slot,
                        attempt_number=1,
                        participant_name=waiting_entry.name,
                        phone=waiting_entry.phone,
                        social_handle=waiting_entry.social_handle,
                        result=ClaimAttemptLog.Result.SUCCESS,
                        details=f"Promovido da Fila de Espera #{waiting_entry.position} ao abrir o Set #{slot.set.set_number}."
                    )
                except Exception:
                    pass

                promoted_count += 1

        return promoted_count

    @staticmethod
    def promote_from_waiting_list_on_slot_released(slot) -> ItemWaitingList:
        """
        Quando uma reserva é cancelada/removida, verifica se há alguém aguardando
        na Lista de Espera para o mesmo item e aloca a vaga imediatamente.
        Retorna a entrada da lista de espera promovida, ou None se a fila estava vazia.
        """
        with _claim_mutex:
            return ClaimService._promote_from_waiting_list_on_slot_released_internal(slot)

    @staticmethod
    def _promote_from_waiting_list_on_slot_released_internal(slot) -> ItemWaitingList:
        now = timezone.now()
        with transaction.atomic():
            waiting_entry = ItemWaitingList.objects.select_for_update().filter(
                item_definition=slot.item_definition,
                status=ItemWaitingList.Status.WAITING
            ).order_by('position', 'created_at').first()

            if waiting_entry:
                slot.status = ItemSlot.Status.RESERVED
                slot.claimed_by = waiting_entry.participant
                slot.claimed_at = now
                slot.is_item_paid = False
                slot.is_frete_inter_paid = False
                slot.is_taxa_aduaneira_paid = False
                slot.is_frete_nacional_paid = False
                slot.save()

                Claim.objects.create(
                    slot=slot,
                    participant=waiting_entry.participant,
                    status=Claim.Status.PENDING,
                    total_price=slot.price,
                    participant_notes="Promovido da Lista de Espera por desistência anterior.",
                    claimed_at=now
                )

                waiting_entry.status = ItemWaitingList.Status.PROMOTED
                waiting_entry.allocated_slot = slot
                waiting_entry.promoted_at = now
                waiting_entry.save()

                try:
                    ClaimAttemptLog.objects.create(
                        slot=slot,
                        attempt_number=1,
                        participant_name=waiting_entry.name,
                        phone=waiting_entry.phone,
                        social_handle=waiting_entry.social_handle,
                        result=ClaimAttemptLog.Result.SUCCESS,
                        details=f"Promovido da Fila de Espera #{waiting_entry.position} após cancelamento/desistência no Set #{slot.set.set_number}."
                    )
                except Exception:
                    pass

                return waiting_entry
            else:
                slot.status = ItemSlot.Status.AVAILABLE
                slot.claimed_by = None
                slot.claimed_at = None
                slot.is_item_paid = False
                slot.is_frete_inter_paid = False
                slot.is_taxa_aduaneira_paid = False
                slot.is_frete_nacional_paid = False
                slot.save()
                return None

    @staticmethod
    def get_slot_dispute_history(slot_id: int):
        """Retorna o histórico ordenado de tentativas de reserva do slot."""
        return ClaimAttemptLog.objects.filter(slot_id=slot_id).order_by('attempt_number')

    @classmethod
    def reset_in_memory_counters(cls):
        """Reseta contadores em memória (usado para testes e reinicialização)."""
        with _slot_counter_lock:
            _slot_attempts_count.clear()
            LAST_CLAIM_DISPUTES.clear()


def enrich_cegs_with_availability(cegs_list):
    """
    Enriquece uma lista de objetos CEG com informações sobre vagas restantes,
    agrupamento por integrante/item e regras de preço para exibição no card.

    Adiciona a cada CEG:
      - available_slots_count: int (quantidade total de slots AVAILABLE nos sets ativos)
      - total_slots_count: int (quantidade total de slots nos sets ativos)
      - reserved_slots_count: int (quantidade reservada/paga nos sets ativos)
      - progress_percentage: int (0 a 100)
      - has_single_price: bool (True se todos os itens da CEG têm o mesmo valor)
      - single_price: Decimal ou None (valor único, se houver)
      - has_different_prices: bool (True se itens da CEG têm preços variados)
      - grouped_available_items: list de dicts com vagas por integrante e sets
    """
    if not cegs_list:
        return cegs_list

    cegs_list = list(cegs_list)
    ceg_ids = [c.id for c in cegs_list]

    slots = list(
        ItemSlot.objects.filter(
            set__ceg_id__in=ceg_ids,
            set__is_active=True
        ).select_related('item_definition__tipo_item', 'set')
        .order_by('set__set_number', 'item_definition__order_index', 'item_definition__name')
    )

    slots_by_ceg = defaultdict(list)
    for s in slots:
        slots_by_ceg[s.set.ceg_id].append(s)

    for ceg in cegs_list:
        ceg_slots = slots_by_ceg[ceg.id]
        total_slots = len(ceg_slots)
        reserved_slots = len([s for s in ceg_slots if s.status in (ItemSlot.Status.RESERVED, ItemSlot.Status.PAID)])
        available_slots = [s for s in ceg_slots if s.status == ItemSlot.Status.AVAILABLE]

        ceg.total_slots_count = total_slots
        ceg.reserved_slots_count = reserved_slots
        ceg.available_slots_count = len(available_slots)
        ceg.progress_percentage = int((reserved_slots / total_slots) * 100) if total_slots > 0 else 0

        # Regra de preços:
        # Se a CEG for de todos com o mesmo valor, mostrar o valor no card;
        # caso contrário (tenham valores diferentes na CEG), sinalizar para consultar preços.
        all_prices = {s.price for s in ceg_slots}
        has_single_price = (len(all_prices) == 1) if all_prices else False
        ceg.has_single_price = has_single_price
        ceg.single_price = list(all_prices)[0] if has_single_price else None
        ceg.has_different_prices = (len(all_prices) > 1)
        ceg.min_price = min(all_prices) if all_prices else Decimal('0.00')
        ceg.max_price = max(all_prices) if all_prices else Decimal('0.00')
        ceg.min_price_float = float(ceg.min_price)
        ceg.max_price_float = float(ceg.max_price)
        ceg.min_price_str = str(ceg.min_price)
        ceg.max_price_str = str(ceg.max_price)

        # Classificação por Tipo de Item (pool compartilhada TipoItem das Caixas)
        tipos_set = set()
        tipo_ids_set = set()
        tipo_names_set = set()

        for s in ceg_slots:
            item_def = s.item_definition
            t = item_def.tipo_item
            if t:
                tipos_set.add(t)
                tipo_ids_set.add(t.id)
                tipo_names_set.add(t.nome)
            else:
                label = item_def.get_item_type_display() if hasattr(item_def, 'get_item_type_display') else str(item_def.item_type)
                tipo_names_set.add(label)

        is_mista = (len(tipo_names_set) > 1) or (len(tipos_set) > 1)
        ceg.is_mista = is_mista
        ceg.tipo_ids_list = list(tipo_ids_set)
        ceg.tipo_ids_str = " ".join(str(tid) for tid in sorted(tipo_ids_set))
        ceg.tipo_names_str = ", ".join(sorted(tipo_names_set))

        if not is_mista and len(tipos_set) == 1:
            only_t = list(tipos_set)[0]
            ceg.exclusive_tipo_id = only_t.id
            ceg.primary_tipo_name = only_t.nome
        elif not is_mista and len(tipo_names_set) == 1:
            ceg.exclusive_tipo_id = None
            ceg.primary_tipo_name = list(tipo_names_set)[0]
        else:
            ceg.exclusive_tipo_id = None
            ceg.primary_tipo_name = "Mista" if is_mista else ""

        # Mapeamento para desambiguação de nomes se houver o mesmo member_name em múltiplos itens da CEG
        member_item_defs = defaultdict(set)
        for s in ceg_slots:
            if s.item_definition.member_name:
                member_item_defs[s.item_definition.member_name].add(s.item_definition_id)

        items_map = {}
        for s in available_slots:
            item_def = s.item_definition
            key = item_def.id
            if key not in items_map:
                if item_def.member_name:
                    if len(member_item_defs.get(item_def.member_name, set())) > 1:
                        display_name = f"{item_def.member_name} ({item_def.name})"
                    else:
                        display_name = item_def.member_name
                else:
                    display_name = item_def.name

                items_map[key] = {
                    'id': item_def.id,
                    'display_name': display_name,
                    'item_name': item_def.name,
                    'member_name': item_def.member_name,
                    'item_type': item_def.item_type,
                    'price': s.price,
                    'sets': [],
                }

            if s.set.set_number not in items_map[key]['sets']:
                items_map[key]['sets'].append(s.set.set_number)

        grouped_items = []
        for item_data in items_map.values():
            item_data['sets'].sort()
            sets_list = item_data['sets']
            if len(sets_list) == 1:
                item_data['sets_text'] = f"Set #{sets_list[0]}"
            elif len(sets_list) == 2:
                item_data['sets_text'] = f"Sets #{sets_list[0]} e #{sets_list[1]}"
            else:
                item_data['sets_text'] = f"Sets #{', #'.join(str(n) for n in sets_list[:-1])} e #{sets_list[-1]}"
            grouped_items.append(item_data)

        grouped_items.sort(key=lambda x: x['display_name'].lower())
        ceg.grouped_available_items = grouped_items

    return cegs_list

