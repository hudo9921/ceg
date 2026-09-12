import logging
import threading
import time
from collections import defaultdict
from django.db import transaction, OperationalError
from django.utils import timezone
from apps.cegs.models import ItemSlot, CEG, ClaimAttemptLog
from apps.participants.models import Participant, Claim, clean_phone_number

logger = logging.getLogger('cegs.concurrency')

_slot_counter_lock = threading.Lock()
_slot_attempts_count = defaultdict(int)
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


class ClaimService:
    @staticmethod
    def claim_slot(slot_id: int, name: str, phone: str, social_handle: str = "", notes: str = "", username: str = "") -> Claim:
        """
        Executa a reserva atômica de um ItemSlot com proteção de concorrência.
        Garante que apenas 1 pessoa consiga reservar o slot físico no segundo zero
        e gera log output registrando a ordem exata de quem deu claim.
        """
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

                    # 2. Validação do Modo Standby / Abertura da CEG
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
                # persiste o log de auditoria sem sofrer rollback e levanta SlotUnavailableError
                if slot_already_taken or lost_race:
                    detail_text = f"Slot já reservado por {winner_info}." if slot_already_taken else f"Perdeu por concorrência para {winner_info}."
                    try:
                        ClaimAttemptLog.objects.create(
                            slot=slot,
                            attempt_number=attempt_number,
                            participant_name=name_clean,
                            phone=cleaned_phone,
                            social_handle=social_clean,
                            result=ClaimAttemptLog.Result.LOST_RACE,
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
                        winner_info=winner_info
                    )

                    raise SlotUnavailableError(
                        f"O item '{item_name}' do Set {set_number} "
                        f"já foi pego por outro participante ({winner_info})!"
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
        ).select_related('item_definition', 'set')
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

