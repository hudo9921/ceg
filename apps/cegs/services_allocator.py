import re
import unicodedata
from django.db import transaction
from django.utils import timezone

from apps.cegs.models import CEG, CEGSet, CEGItemDefinition, ItemSlot
from apps.participants.models import Participant, Claim, clean_phone_number


def _normalize(text: str) -> str:
    """Normaliza texto para comparação (minúsculo, sem acentos, sem espaços extras)."""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text)
    without_accents = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return re.sub(r'\s+', ' ', without_accents).strip().lower()


class BulkJoinerAllocatorService:
    """
    Serviço especializado na alocação rápida e em massa de joiners/participantes em slots de CEGs.
    Oferece suporte à:
    - Matriz completa de Sets x Itens da CEG
    - Parser inteligente de colagem (Excel / Sheets / CSV / Pipes) com alocação automática no próximo Set livre
    - Autocadastro de participantes com normalização canônica de telefone
    - Atualização transacional de ItemSlot e Claim
    """

    @classmethod
    def get_ceg_matrix(cls, ceg: CEG) -> dict:
        """
        Retorna a estrutura completa da matriz de uma CEG para renderização visual da grade.
        """
        sets = list(ceg.sets.all().order_by('set_number'))
        item_defs = list(ceg.item_definitions.all().order_by('id'))
        slots = list(
            ItemSlot.objects.filter(set__ceg=ceg)
            .select_related('set', 'item_definition', 'claimed_by')
            .order_by('set__set_number', 'item_definition__id')
        )

        slots_by_def_and_set = {}
        for s in slots:
            slots_by_def_and_set[(s.item_definition_id, s.set_id)] = s

        items_matrix = []
        total_slots = len(slots)
        occupied_slots = 0
        paid_slots = 0

        for idef in item_defs:
            row_slots = {}
            for cset in sets:
                s = slots_by_def_and_set.get((idef.id, cset.id))
                if s:
                    if s.claimed_by:
                        occupied_slots += 1
                    if s.is_item_paid:
                        paid_slots += 1

                    row_slots[cset.id] = {
                        'slot_id': s.id,
                        'set_id': cset.id,
                        'set_number': cset.set_number,
                        'price': f"{s.price:.2f}",
                        'status': s.status,
                        'status_display': s.get_status_display(),
                        'is_item_paid': s.is_item_paid,
                        'claimed_by': {
                            'id': s.claimed_by.id,
                            'name': s.claimed_by.name,
                            'display_name': s.claimed_by.display_name,
                            'social_handle': s.claimed_by.social_handle or '',
                            'whatsapp': s.claimed_by.whatsapp or '',
                            'formatted_phone': s.claimed_by.formatted_phone,
                        } if s.claimed_by else None,
                    }
                else:
                    row_slots[cset.id] = None

            items_matrix.append({
                'id': idef.id,
                'name': idef.name,
                'member_name': idef.member_name or '',
                'item_type': idef.item_type,
                'item_type_display': idef.get_item_type_display(),
                'tipo_item_nome': idef.tipo_item_nome,
                'default_price': f"{idef.default_price:.2f}",
                'slots': row_slots,
            })

        return {
            'ceg': {
                'id': ceg.id,
                'title': ceg.title,
                'slug': ceg.slug,
                'status': ceg.status,
                'status_display': ceg.get_status_display(),
            },
            'sets': [
                {'id': s.id, 'set_number': s.set_number, 'is_active': s.is_active}
                for s in sets
            ],
            'items': items_matrix,
            'total_slots': total_slots,
            'occupied_slots': occupied_slots,
            'paid_slots': paid_slots,
        }

    @classmethod
    def parse_allocation_text(cls, ceg: CEG, raw_text: str, options: dict = None) -> dict:
        """
        Analisa texto livre ou colado de planilhas.
        Opções:
        - overwrite (bool): Se True, permite sobrescrever slots já ocupados.
        - auto_next_set (bool): Se True, quando a linha não definir o Set, aloca no próximo Set livre daquele item.
        - default_is_paid (bool): Se True, marca como pago mesmo se não houver coluna de pagamento explícita.
        """
        if options is None:
            options = {}

        overwrite = options.get('overwrite', False)
        auto_next_set = options.get('auto_next_set', True)
        default_is_paid = options.get('default_is_paid', False)

        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if not lines:
            return {'success': True, 'rows': [], 'summary': {'total': 0, 'ready': 0, 'conflicts': 0, 'errors': 0}}

        sets = list(ceg.sets.all().order_by('set_number'))
        sets_by_num = {s.set_number: s for s in sets}
        item_defs = list(ceg.item_definitions.all().order_by('id'))

        # Mapeia itens com chaves normalizadas
        items_by_norm = {}
        for idef in item_defs:
            if idef.member_name:
                items_by_norm[_normalize(idef.member_name)] = idef
            items_by_norm[_normalize(idef.name)] = idef

        slots = list(
            ItemSlot.objects.filter(set__ceg=ceg)
            .select_related('set', 'item_definition', 'claimed_by')
        )
        slots_map = {(s.item_definition_id, s.set_id): s for s in slots}

        all_participants = list(Participant.objects.all())
        parts_by_phone = {p.whatsapp: p for p in all_participants if p.whatsapp}
        parts_by_handle = {_normalize(p.social_handle): p for p in all_participants if p.social_handle}
        parts_by_name = {_normalize(p.name): p for p in all_participants if p.name}

        claimed_in_batch = set()

        parsed_rows = []
        ready_count = 0
        conflicts_count = 0
        errors_count = 0

        for line_idx, line in enumerate(lines, start=1):
            if '\t' in line:
                tokens = [t.strip() for t in line.split('\t') if t.strip()]
            elif '|' in line:
                tokens = [t.strip() for t in line.split('|') if t.strip()]
            elif ';' in line:
                tokens = [t.strip() for t in line.split(';') if t.strip()]
            elif ',' in line:
                tokens = [t.strip() for t in line.split(',') if t.strip()]
            else:
                tokens = [t.strip() for t in re.split(r'\s{2,}', line) if t.strip()]
                if len(tokens) == 1:
                    tokens = line.split()

            norm_joined = _normalize(" ".join(tokens))
            if any(h in norm_joined for h in ['set', 'integrante', 'membro', 'item']) and any(h in norm_joined for h in ['telefone', 'whatsapp', 'participante', 'joiner', 'twitter']):
                continue

            row_result = {
                'line_number': line_idx,
                'raw_line': line,
                'status': 'PENDING',
                'message': '',
                'target_set_number': None,
                'target_set_id': None,
                'target_item_id': None,
                'target_item_name': '',
                'target_slot_id': None,
                'participant_id': None,
                'participant_name': '',
                'participant_phone': '',
                'participant_handle': '',
                'participant_is_new': False,
                'is_paid': default_is_paid,
                'current_claimant': None,
            }

            # 1. Identificar Set explícito
            set_num_candidate = None
            remaining_tokens = []
            for token in tokens:
                m_set = re.match(r'^(?:set|s)?\s*#?\s*(\d+)$', token, re.IGNORECASE)
                if m_set and set_num_candidate is None and int(m_set.group(1)) in sets_by_num:
                    set_num_candidate = int(m_set.group(1))
                else:
                    remaining_tokens.append(token)

            # 2. Identificar Item / Integrante
            found_item_def = None
            item_token_idx = None

            for idx, token in enumerate(remaining_tokens):
                n_tok = _normalize(token)
                if n_tok in items_by_norm:
                    found_item_def = items_by_norm[n_tok]
                    item_token_idx = idx
                    break

            if not found_item_def:
                for idx, token in enumerate(remaining_tokens):
                    n_tok = _normalize(token)
                    for idef in item_defs:
                        norm_m = _normalize(idef.member_name) if idef.member_name else ""
                        norm_n = _normalize(idef.name)
                        if (norm_m and norm_m in n_tok) or (norm_n and norm_n in n_tok):
                            found_item_def = idef
                            item_token_idx = idx
                            break
                    if found_item_def:
                        break

            if not found_item_def:
                row_result['status'] = 'ERROR'
                row_result['message'] = 'Item ou integrante não identificado nesta linha.'
                errors_count += 1
                parsed_rows.append(row_result)
                continue

            row_result['target_item_id'] = found_item_def.id
            row_result['target_item_name'] = found_item_def.name
            if item_token_idx is not None:
                remaining_tokens.pop(item_token_idx)

            # 3. Identificar Pagamento
            pay_token_idx = None
            for idx, token in enumerate(remaining_tokens):
                n_tok = _normalize(token)
                if n_tok in ['pago', 'paid', 'sim', 'yes', 'ok', 'confirmado', 'pg']:
                    row_result['is_paid'] = True
                    pay_token_idx = idx
                    break
                elif n_tok in ['pendente', 'pend', 'nao', 'no', 'aberto']:
                    row_result['is_paid'] = False
                    pay_token_idx = idx
                    break

            if pay_token_idx is not None:
                remaining_tokens.pop(pay_token_idx)

            # 4. Identificar Participante
            phone_found = ""
            handle_found = ""
            name_found = ""

            for token in remaining_tokens:
                digits = re.sub(r'\D', '', token)
                if len(digits) >= 8 and (token.startswith('+') or len(digits) >= 10 or '-' in token or '(' in token):
                    try:
                        cleaned = clean_phone_number(token)
                        if len(cleaned) >= 8:
                            phone_found = cleaned
                            continue
                    except Exception:
                        pass

                if token.startswith('@') or ('@' in token and len(token) > 1 and not token.endswith('.com')):
                    handle_found = token if token.startswith('@') else f"@{token}"
                    continue

                if not name_found:
                    name_found = token
                else:
                    name_found += f" {token}"

            matched_participant = None
            if phone_found and phone_found in parts_by_phone:
                matched_participant = parts_by_phone[phone_found]
            elif handle_found and _normalize(handle_found) in parts_by_handle:
                matched_participant = parts_by_handle[_normalize(handle_found)]
            elif name_found and _normalize(name_found) in parts_by_name:
                matched_participant = parts_by_name[_normalize(name_found)]

            if matched_participant:
                row_result['participant_id'] = matched_participant.id
                row_result['participant_name'] = matched_participant.name
                row_result['participant_phone'] = matched_participant.whatsapp
                row_result['participant_handle'] = matched_participant.social_handle or ''
                row_result['participant_is_new'] = False
            else:
                if phone_found or name_found or handle_found:
                    row_result['participant_is_new'] = True
                    row_result['participant_name'] = name_found or (handle_found if handle_found else f"Joiner {phone_found[-4:]}")
                    row_result['participant_phone'] = phone_found
                    row_result['participant_handle'] = handle_found
                else:
                    row_result['status'] = 'ERROR'
                    row_result['message'] = 'Nenhum dado de participante (telefone/nome/@) encontrado.'
                    errors_count += 1
                    parsed_rows.append(row_result)
                    continue

            # 5. Resolver Slot
            target_slot = None
            if set_num_candidate is not None:
                target_set = sets_by_num.get(set_num_candidate)
                if not target_set:
                    row_result['status'] = 'ERROR'
                    row_result['message'] = f"Set #{set_num_candidate} não existe nesta CEG."
                    errors_count += 1
                    parsed_rows.append(row_result)
                    continue

                target_slot = slots_map.get((found_item_def.id, target_set.id))
            elif auto_next_set:
                for cset in sets:
                    candidate_slot = slots_map.get((found_item_def.id, cset.id))
                    if candidate_slot and candidate_slot.id not in claimed_in_batch:
                        if candidate_slot.claimed_by is None or overwrite:
                            target_slot = candidate_slot
                            break

                if not target_slot and overwrite and sets:
                    target_slot = slots_map.get((found_item_def.id, sets[0].id))

            if not target_slot:
                row_result['status'] = 'ERROR'
                row_result['message'] = f"Não há slots disponíveis nos sets da CEG para '{found_item_def.name}'."
                errors_count += 1
                parsed_rows.append(row_result)
                continue

            row_result['target_set_id'] = target_slot.set_id
            row_result['target_set_number'] = target_slot.set.set_number
            row_result['target_slot_id'] = target_slot.id

            claimed_in_batch.add(target_slot.id)

            if target_slot.claimed_by:
                row_result['current_claimant'] = {
                    'id': target_slot.claimed_by.id,
                    'name': target_slot.claimed_by.name,
                    'social_handle': target_slot.claimed_by.social_handle or '',
                    'is_item_paid': target_slot.is_item_paid,
                }
                if not overwrite:
                    row_result['status'] = 'CONFLICT'
                    row_result['message'] = (
                        f"Slot já ocupado por {target_slot.claimed_by.name} "
                        f"({'Pago' if target_slot.is_item_paid else 'Pendente'}). Ative 'Sobrescrever' para substituir."
                    )
                    conflicts_count += 1
                else:
                    row_result['status'] = 'READY'
                    row_result['message'] = f"Substituirá reserva existente de {target_slot.claimed_by.name}."
                    ready_count += 1
            else:
                row_result['status'] = 'READY'
                row_result['message'] = 'Pronto para alocar.'
                ready_count += 1

            parsed_rows.append(row_result)

        return {
            'success': True,
            'rows': parsed_rows,
            'summary': {
                'total': len(parsed_rows),
                'ready': ready_count,
                'conflicts': conflicts_count,
                'errors': errors_count,
            }
        }

    @classmethod
    def execute_bulk_allocations(cls, ceg: CEG, rows: list, options: dict = None) -> dict:
        """
        Executa a gravação atômica das alocações parseadas.
        """
        if options is None:
            options = {}

        overwrite = options.get('overwrite', False)
        auto_create = options.get('auto_create_participants', True)

        allocated_count = 0
        new_participants_count = 0
        skipped_conflicts_count = 0
        errors = []

        with transaction.atomic():
            for row in rows:
                slot_id = row.get('target_slot_id')
                if not slot_id:
                    continue

                slot = ItemSlot.objects.select_for_update().filter(id=slot_id, set__ceg=ceg).first()
                if not slot:
                    errors.append(f"Linha {row.get('line_number')}: Slot #{slot_id} não encontrado.")
                    continue

                if slot.claimed_by and not overwrite:
                    skipped_conflicts_count += 1
                    continue

                participant = None
                p_id = row.get('participant_id')
                if p_id:
                    participant = Participant.objects.filter(id=p_id).first()

                if not participant and auto_create:
                    phone = row.get('participant_phone') or ''
                    name = row.get('participant_name') or 'Participante Sem Nome'
                    handle = row.get('participant_handle') or ''

                    if phone:
                        cleaned = clean_phone_number(phone)
                        participant = Participant.objects.filter(whatsapp=cleaned).first()

                    if not participant:
                        participant = Participant.objects.create(
                            name=name.strip(),
                            whatsapp=phone.strip() if phone else '',
                            social_handle=handle.strip() if handle else '',
                        )
                        new_participants_count += 1

                if not participant:
                    errors.append(f"Linha {row.get('line_number')}: Impossível resolver participante.")
                    continue

                is_paid = bool(row.get('is_paid', False))
                slot.claimed_by = participant
                slot.claimed_at = timezone.now()
                slot.status = ItemSlot.Status.PAID if is_paid else ItemSlot.Status.RESERVED
                slot.is_item_paid = is_paid
                slot.save(update_fields=['claimed_by', 'claimed_at', 'status', 'is_item_paid'])

                Claim.objects.update_or_create(
                    slot=slot,
                    defaults={
                        'participant': participant,
                        'total_price': slot.price,
                        'status': Claim.Status.PAID if is_paid else Claim.Status.PENDING,
                        'paid_at': timezone.now() if is_paid else None,
                    }
                )

                try:
                    from apps.cegs.audit_service import AuditService
                    AuditService.log_slot_assignment(
                        slot=slot,
                        participant=participant,
                        action='assign',
                        actor=options.get('actor') if options else 'Bulk Allocator (Planilha/GOM)',
                        metadata={'is_paid': is_paid, 'batch': True}
                    )
                    if is_paid:
                        AuditService.log_payment_change(
                            slot=slot,
                            field_name='is_item_paid',
                            old_value=False,
                            new_value=True,
                            actor=options.get('actor') if options else 'Bulk Allocator (Planilha/GOM)',
                        )
                except Exception:
                    pass

                allocated_count += 1

        return {
            'success': True,
            'allocated_count': allocated_count,
            'new_participants_count': new_participants_count,
            'skipped_conflicts_count': skipped_conflicts_count,
            'errors': errors,
        }

    @classmethod
    def save_matrix_allocations(cls, ceg: CEG, updates: list) -> dict:
        """
        Salva atualizações vindas diretamente da Matriz Interativa (grade da CEG).
        Cada item em `updates`:
        {
            'slot_id': int,
            'action': 'assign' | 'release' | 'toggle_payment',
            'participant_id': int or None,
            'is_paid': bool (opcional)
        }
        """
        updated_count = 0
        released_count = 0
        errors = []

        with transaction.atomic():
            for up in updates:
                slot_id = up.get('slot_id')
                action = up.get('action', 'assign')
                slot = ItemSlot.objects.select_for_update().filter(id=slot_id, set__ceg=ceg).first()
                if not slot:
                    errors.append(f"Slot #{slot_id} não encontrado.")
                    continue

                if action == 'release':
                    old_participant = slot.claimed_by
                    slot.claimed_by = None
                    slot.claimed_at = None
                    slot.status = ItemSlot.Status.AVAILABLE
                    slot.is_item_paid = False
                    slot.save(update_fields=['claimed_by', 'claimed_at', 'status', 'is_item_paid'])

                    if hasattr(slot, 'claim') and slot.claim:
                        slot.claim.delete()

                    if old_participant:
                        try:
                            from apps.cegs.audit_service import AuditService
                            AuditService.log_slot_assignment(
                                slot=slot,
                                participant=old_participant,
                                action='release',
                                actor='Bulk Allocator (Grade Interativa)',
                            )
                        except Exception:
                            pass

                    released_count += 1

                elif action == 'toggle_payment':
                    old_paid = slot.is_item_paid
                    new_paid = bool(up.get('is_paid', not slot.is_item_paid))
                    slot.is_item_paid = new_paid
                    if slot.claimed_by:
                        slot.status = ItemSlot.Status.PAID if new_paid else ItemSlot.Status.RESERVED
                    slot.save(update_fields=['is_item_paid', 'status'])

                    if hasattr(slot, 'claim') and slot.claim:
                        slot.claim.status = Claim.Status.PAID if new_paid else Claim.Status.PENDING
                        slot.claim.paid_at = timezone.now() if new_paid else None
                        slot.claim.save(update_fields=['status', 'paid_at'])

                    try:
                        from apps.cegs.audit_service import AuditService
                        AuditService.log_payment_change(
                            slot=slot,
                            field_name='is_item_paid',
                            old_value=old_paid,
                            new_value=new_paid,
                            actor='Bulk Allocator (Grade Interativa)',
                        )
                    except Exception:
                        pass

                    updated_count += 1

                elif action == 'assign':
                    p_id = up.get('participant_id')
                    if not p_id:
                        continue
                    participant = Participant.objects.filter(id=p_id).first()
                    if not participant:
                        errors.append(f"Participante #{p_id} não encontrado.")
                        continue

                    is_paid = bool(up.get('is_paid', False))
                    slot.claimed_by = participant
                    slot.claimed_at = timezone.now()
                    slot.status = ItemSlot.Status.PAID if is_paid else ItemSlot.Status.RESERVED
                    slot.is_item_paid = is_paid
                    slot.save(update_fields=['claimed_by', 'claimed_at', 'status', 'is_item_paid'])

                    Claim.objects.update_or_create(
                        slot=slot,
                        defaults={
                            'participant': participant,
                            'total_price': slot.price,
                            'status': Claim.Status.PAID if is_paid else Claim.Status.PENDING,
                            'paid_at': timezone.now() if is_paid else None,
                        }
                    )

                    try:
                        from apps.cegs.audit_service import AuditService
                        AuditService.log_slot_assignment(
                            slot=slot,
                            participant=participant,
                            action='assign',
                            actor='Bulk Allocator (Grade Interativa)',
                            metadata={'is_paid': is_paid}
                        )
                        if is_paid:
                            AuditService.log_payment_change(
                                slot=slot,
                                field_name='is_item_paid',
                                old_value=False,
                                new_value=True,
                                actor='Bulk Allocator (Grade Interativa)',
                            )
                    except Exception:
                        pass

                    updated_count += 1

        return {
            'success': True,
            'updated_count': updated_count,
            'released_count': released_count,
            'errors': errors,
        }
