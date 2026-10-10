import logging
from typing import Optional, Dict, Any
from django.utils import timezone
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)


class AuditService:
    @staticmethod
    def log_event(
        event_type: str,
        action_label: str,
        actor=None,
        participant=None,
        participant_name: str = '',
        participant_phone: str = '',
        slot=None,
        ceg=None,
        item_individual=None,
        pacote_nacional=None,
        field_name: str = '',
        old_value: str = '',
        new_value: str = '',
        metadata: Optional[Dict[str, Any]] = None,
        created_at=None,
    ):
        """Registra um evento de auditoria no sistema."""
        from apps.cegs.models import AuditLog

        # Normaliza actor / operador
        actor_user = None
        actor_name = 'Sistema'
        if actor:
            if hasattr(actor, 'is_authenticated') and actor.is_authenticated:
                actor_user = actor
                actor_name = actor.get_full_name() or actor.username or str(actor)
            elif isinstance(actor, str):
                actor_name = actor

        # Normaliza participante e dados em cache
        p_name = participant_name or ''
        p_phone = participant_phone or ''
        if participant:
            p_name = p_name or getattr(participant, 'name', '') or str(participant)
            p_phone = p_phone or getattr(participant, 'whatsapp', '')
        elif slot and getattr(slot, 'claimed_by', None):
            participant = slot.claimed_by
            p_name = p_name or participant.name
            p_phone = p_phone or participant.whatsapp
        elif item_individual and getattr(item_individual, 'comprador', None):
            participant = item_individual.comprador
            p_name = p_name or participant.name
            p_phone = p_phone or participant.whatsapp
        elif pacote_nacional and getattr(pacote_nacional, 'participant', None):
            participant = pacote_nacional.participant
            p_name = p_name or participant.name
            p_phone = p_phone or participant.whatsapp

        # Normaliza CEG
        if not ceg and slot and hasattr(slot, 'set') and getattr(slot.set, 'ceg', None):
            ceg = slot.set.ceg

        try:
            log_entry = AuditLog(
                event_type=event_type,
                actor=actor_user,
                actor_name=actor_name,
                participant=participant,
                participant_name=p_name,
                participant_phone=p_phone,
                ceg=ceg,
                slot=slot,
                item_individual=item_individual,
                pacote_nacional=pacote_nacional,
                action_label=action_label,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else '',
                new_value=str(new_value) if new_value is not None else '',
                metadata=metadata or {},
            )
            if created_at:
                log_entry.created_at = created_at
            log_entry.save()

            # Dispara notificação operacional correspondente para a GOM
            try:
                AuditService.create_gom_notification_from_event(log_entry)
            except Exception:
                pass

            return log_entry
        except Exception as e:
            logger.error(f"Erro ao registrar AuditLog ({event_type}): {e}", exc_info=True)
            return None

    @staticmethod
    def log_payment_change(
        slot=None,
        item_individual=None,
        field_name: str = '',
        old_value=None,
        new_value=None,
        actor=None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Registra alteração de status de pagamento em um ItemSlot ou ItemIndividual."""
        from apps.cegs.models import AuditLog

        field_clean = field_name.lower().strip()
        label_map = {
            'item': ('Pagamento do Item', AuditLog.EventType.PAYMENT_ITEM),
            'is_item_paid': ('Pagamento do Item', AuditLog.EventType.PAYMENT_ITEM),
            'produto_pago': ('Pagamento do Item', AuditLog.EventType.PAYMENT_ITEM),
            'inter': ('Frete Internacional', AuditLog.EventType.PAYMENT_FRETE_INTER),
            'frete_inter': ('Frete Internacional', AuditLog.EventType.PAYMENT_FRETE_INTER),
            'is_frete_inter_paid': ('Frete Internacional', AuditLog.EventType.PAYMENT_FRETE_INTER),
            'frete_inter_pago': ('Frete Internacional', AuditLog.EventType.PAYMENT_FRETE_INTER),
            'taxa': ('Taxa Aduaneira', AuditLog.EventType.PAYMENT_TAXA),
            'taxa_aduaneira': ('Taxa Aduaneira', AuditLog.EventType.PAYMENT_TAXA),
            'is_taxa_aduaneira_paid': ('Taxa Aduaneira', AuditLog.EventType.PAYMENT_TAXA),
            'taxa_aduaneira_paga': ('Taxa Aduaneira', AuditLog.EventType.PAYMENT_TAXA),
            'nacional': ('Frete Nacional', AuditLog.EventType.PAYMENT_FRETE_NACIONAL),
            'frete_nacional': ('Frete Nacional', AuditLog.EventType.PAYMENT_FRETE_NACIONAL),
            'is_frete_nacional_paid': ('Frete Nacional', AuditLog.EventType.PAYMENT_FRETE_NACIONAL),
        }

        display_name, ev_type = label_map.get(field_clean, ('Pagamento', AuditLog.EventType.OTHER))

        def format_val(v):
            if v is True or v == '1' or v == 1 or str(v).lower() == 'true':
                return 'Pago ✔'
            elif v is False or v == '0' or v == 0 or str(v).lower() == 'false':
                return 'Pendente ⏳'
            return str(v)

        old_str = format_val(old_value) if old_value is not None else ''
        new_str = format_val(new_value)

        item_desc = ""
        if slot:
            item_name = slot.item_definition.name if hasattr(slot, 'item_definition') else f"Slot #{slot.id}"
            set_num = f"Set {slot.set.set_number} - " if hasattr(slot, 'set') else ""
            item_desc = f"{set_num}{item_name}"
        elif item_individual:
            item_desc = f"{item_individual.nome}"

        action_label = f"{display_name} alterado para [{new_str}] em '{item_desc}'"

        meta = metadata or {}
        if slot:
            meta['slot_id'] = slot.id
            if hasattr(slot, 'price'):
                meta['price'] = str(slot.price)
        if item_individual:
            meta['item_individual_id'] = item_individual.id

        return AuditService.log_event(
            event_type=ev_type,
            action_label=action_label,
            actor=actor,
            participant=getattr(slot, 'claimed_by', None) or getattr(item_individual, 'comprador', None),
            slot=slot,
            item_individual=item_individual,
            field_name=field_name,
            old_value=old_str,
            new_value=new_str,
            metadata=meta,
        )

    @staticmethod
    def log_account_created(participant, actor=None, metadata: Optional[Dict[str, Any]] = None, created_at=None):
        """Registra cadastro de um participante."""
        from apps.cegs.models import AuditLog

        handle = f" ({participant.social_handle})" if participant.social_handle else ""
        action_label = f"Novo cadastro: {participant.name}{handle} [{participant.formatted_phone}]"

        meta = metadata or {}
        meta.update({
            'participant_id': participant.id,
            'whatsapp': participant.whatsapp,
            'username': participant.username,
            'social_handle': participant.social_handle,
        })

        return AuditService.log_event(
            event_type=AuditLog.EventType.ACCOUNT_CREATED,
            action_label=action_label,
            actor=actor,
            participant=participant,
            new_value=participant.display_name,
            metadata=meta,
            created_at=created_at,
        )

    @staticmethod
    def log_claim_attempt(claim_log, actor=None, metadata: Optional[Dict[str, Any]] = None, created_at=None):
        """Registra tentativa ou sucesso de claim baseado em ClaimAttemptLog."""
        from apps.cegs.models import AuditLog

        is_success = claim_log.result in ('SUCCESS', 'AUTO_FALLBACK')
        ev_type = AuditLog.EventType.CLAIM_SUCCESS if is_success else AuditLog.EventType.CLAIM_ATTEMPT

        slot = claim_log.slot
        slot_name = f"Set {slot.set.set_number} | {slot.item_definition.name}" if slot else "Slot Desconhecido"
        action_label = f"Tentativa de Claim: {claim_log.participant_name} no {slot_name} [{claim_log.get_result_display()}]"

        # Tenta achar o participante pelo WhatsApp
        from apps.participants.models import Participant
        participant = Participant.objects.filter(whatsapp=claim_log.phone).first()

        meta = metadata or {}
        meta.update({
            'claim_attempt_log_id': claim_log.id,
            'attempt_number': claim_log.attempt_number,
            'result': claim_log.result,
            'result_display': claim_log.get_result_display(),
            'details': claim_log.details,
            'social_handle': claim_log.social_handle,
            'phone': claim_log.phone,
        })

        return AuditService.log_event(
            event_type=ev_type,
            action_label=action_label,
            actor=actor,
            participant=participant,
            participant_name=claim_log.participant_name,
            participant_phone=claim_log.phone,
            slot=slot,
            old_value=f"Tentativa #{claim_log.attempt_number}",
            new_value=claim_log.get_result_display(),
            metadata=meta,
            created_at=created_at or claim_log.created_at,
        )

    @staticmethod
    def log_claim_success_from_claim(claim, actor=None, metadata: Optional[Dict[str, Any]] = None, created_at=None):
        """Registra um claim com sucesso/reserva garantida a partir do modelo Claim."""
        from apps.cegs.models import AuditLog

        slot = claim.slot
        participant = claim.participant
        slot_name = f"Set {slot.set.set_number} | {slot.item_definition.name}" if slot and hasattr(slot, 'set') else "Slot de Item"
        p_name = participant.name if participant else "Participante"
        p_handle = f" ({participant.social_handle})" if participant and participant.social_handle else ""
        action_label = f"Claim Garantido: {p_name}{p_handle} no {slot_name}"

        meta = metadata or {}
        meta.update({
            'claim_id': claim.id,
            'slot_id': slot.id if slot else None,
            'total_price': str(claim.total_price),
            'status': claim.status,
            'participant_notes': claim.participant_notes or '',
        })

        claim_date = created_at or claim.claimed_at or (slot.claimed_at if slot else None) or claim.paid_at or timezone.now()

        return AuditService.log_event(
            event_type=AuditLog.EventType.CLAIM_SUCCESS,
            action_label=action_label,
            actor=actor or 'Sistema (Claim)',
            participant=participant,
            slot=slot,
            old_value="Disponível",
            new_value=p_name,
            metadata=meta,
            created_at=claim_date,
        )

    @staticmethod
    def log_slot_assignment(slot, participant, action: str, actor=None, metadata: Optional[Dict[str, Any]] = None, created_at=None):
        """Registra alocação manual ou desvinculação de slot."""
        from apps.cegs.models import AuditLog

        slot_name = f"Set {slot.set.set_number} | {slot.item_definition.name}"
        if action == 'assign':
            ev_type = AuditLog.EventType.SLOT_ASSIGNED
            p_name = participant.name if participant else "Participante"
            action_label = f"Slot '{slot_name}' alocado manualmente para {p_name}"
            new_val = p_name
            old_val = "Disponível"
        else:
            ev_type = AuditLog.EventType.SLOT_RELEASED
            p_name = participant.name if participant else "Participante"
            action_label = f"Slot '{slot_name}' liberado/desvinculado de {p_name}"
            new_val = "Disponível"
            old_val = p_name

        meta = metadata or {}
        meta['slot_id'] = slot.id

        return AuditService.log_event(
            event_type=ev_type,
            action_label=action_label,
            actor=actor,
            participant=participant,
            slot=slot,
            old_value=old_val,
            new_value=new_val,
            metadata=meta,
            created_at=created_at,
        )

    @classmethod
    def backfill_historical_logs(cls):
        """
        Popula o AuditLog com todos os dados que já existiam antes:
        1. Participantes (contas criadas)
        2. Tentativas de Claim (ClaimAttemptLog)
        3. Claims garantidas (Claim)
        4. Slots com participantes vinculados (ItemSlot.claimed_by)
        5. Itens avulsos Mercari (ItemIndividual.comprador)
        6. Pagamentos quitados (Item, Frete Inter, Taxa Aduaneira, Frete Nacional)
        7. Pacotes de Envio Nacional (solicitados, despachados, entregues)
        """
        from apps.participants.models import Participant, Claim
        from apps.cegs.models import ClaimAttemptLog, ItemSlot, ItemIndividual, PacoteNacional, AuditLog

        counts = {
            'accounts': 0,
            'claim_logs': 0,
            'claims': 0,
            'slots_assigned': 0,
            'mercari_assigned': 0,
            'payments': 0,
            'packages': 0,
            'total': 0,
        }

        # 1. Participantes existentes (ACCOUNT_CREATED)
        existing_p_ids = set(
            AuditLog.objects.filter(event_type=AuditLog.EventType.ACCOUNT_CREATED)
            .values_list('participant_id', flat=True)
        )
        for p in Participant.objects.exclude(id__in=existing_p_ids).order_by('created_at'):
            cls.log_account_created(p, actor='Sistema (Histórico)', created_at=p.created_at)
            counts['accounts'] += 1

        # 2. ClaimAttemptLogs existentes
        existing_claim_log_ids = set()
        for al in AuditLog.objects.filter(
            event_type__in=[AuditLog.EventType.CLAIM_ATTEMPT, AuditLog.EventType.CLAIM_SUCCESS]
        ):
            c_id = al.metadata.get('claim_attempt_log_id')
            if c_id:
                existing_claim_log_ids.add(c_id)

        for cl in ClaimAttemptLog.objects.select_related('slot__set__ceg', 'slot__item_definition').exclude(id__in=existing_claim_log_ids).order_by('created_at'):
            cls.log_claim_attempt(cl, actor='Sistema (Claim Engine)', created_at=cl.created_at)
            counts['claim_logs'] += 1

        # 3. Claims existentes (Claim)
        for claim in Claim.objects.select_related('slot__set__ceg', 'slot__item_definition', 'participant').order_by('claimed_at', 'id'):
            if not claim.slot or not claim.participant:
                continue
            has_log = AuditLog.objects.filter(
                slot=claim.slot,
                participant=claim.participant,
                event_type__in=[AuditLog.EventType.CLAIM_SUCCESS, AuditLog.EventType.SLOT_ASSIGNED]
            ).exists()
            if not has_log:
                cls.log_claim_success_from_claim(claim, actor='Sistema (Histórico Claim)')
                counts['claims'] += 1

        # 4. Slots que têm claimed_by mas não têm log de sucesso ou alocação
        for slot in ItemSlot.objects.filter(claimed_by__isnull=False).select_related('claimed_by', 'set__ceg', 'item_definition').order_by('id'):
            has_log = AuditLog.objects.filter(
                slot=slot,
                participant=slot.claimed_by,
                event_type__in=[AuditLog.EventType.CLAIM_SUCCESS, AuditLog.EventType.SLOT_ASSIGNED]
            ).exists()
            if not has_log:
                created_date = slot.claimed_at or (slot.set.ceg.created_at if hasattr(slot, 'set') and slot.set and slot.set.ceg else timezone.now())
                cls.log_slot_assignment(
                    slot=slot,
                    participant=slot.claimed_by,
                    action='assign',
                    actor='Sistema (Histórico Alocação)',
                    created_at=created_date,
                )
                counts['slots_assigned'] += 1

        # 5. Itens individuais Mercari com comprador
        for item in ItemIndividual.objects.filter(comprador__isnull=False).select_related('comprador', 'caixa').order_by('id'):
            has_log = AuditLog.objects.filter(
                item_individual=item,
                participant=item.comprador,
            ).exists()
            if not has_log:
                cls.log_event(
                    event_type=AuditLog.EventType.OTHER,
                    action_label=f"Compra Individual (Mercari) '{item.nome}' vinculada para {item.comprador.name}",
                    actor='Sistema (Histórico Mercari)',
                    participant=item.comprador,
                    item_individual=item,
                    new_value=item.comprador.name,
                    created_at=item.created_at,
                    metadata={'item_individual_id': item.id, 'preco': str(item.preco_produto or 0)},
                )
                counts['mercari_assigned'] += 1

        # 6. Pagamentos históricos em ItemSlot
        for slot in ItemSlot.objects.filter(claimed_by__isnull=False).select_related('claimed_by', 'set__ceg', 'item_definition'):
            base_date = slot.claimed_at or (slot.set.ceg.created_at if hasattr(slot, 'set') and slot.set and slot.set.ceg else timezone.now())

            # Item pago
            if slot.is_item_paid and not AuditLog.objects.filter(slot=slot, event_type=AuditLog.EventType.PAYMENT_ITEM).exists():
                cls.log_event(
                    event_type=AuditLog.EventType.PAYMENT_ITEM,
                    action_label=f"Pagamento do Item alterado para [Pago ✔] em 'Set {slot.set.set_number} - {slot.item_definition.name}'",
                    actor='Sistema (Histórico Pagamento)',
                    participant=slot.claimed_by,
                    slot=slot,
                    field_name='is_item_paid',
                    old_value='Pendente ⏳',
                    new_value='Pago ✔',
                    created_at=base_date,
                    metadata={'slot_id': slot.id, 'price': str(slot.price)},
                )
                counts['payments'] += 1

            # Frete Inter pago
            if slot.is_frete_inter_paid and not AuditLog.objects.filter(slot=slot, event_type=AuditLog.EventType.PAYMENT_FRETE_INTER).exists():
                cls.log_event(
                    event_type=AuditLog.EventType.PAYMENT_FRETE_INTER,
                    action_label=f"Frete Internacional alterado para [Pago ✔] em 'Set {slot.set.set_number} - {slot.item_definition.name}'",
                    actor='Sistema (Histórico Pagamento)',
                    participant=slot.claimed_by,
                    slot=slot,
                    field_name='is_frete_inter_paid',
                    old_value='Pendente ⏳',
                    new_value='Pago ✔',
                    created_at=base_date,
                    metadata={'slot_id': slot.id},
                )
                counts['payments'] += 1

            # Taxa Aduaneira paga
            if slot.is_taxa_aduaneira_paid and not AuditLog.objects.filter(slot=slot, event_type=AuditLog.EventType.PAYMENT_TAXA).exists():
                cls.log_event(
                    event_type=AuditLog.EventType.PAYMENT_TAXA,
                    action_label=f"Taxa Aduaneira alterada para [Pago ✔] em 'Set {slot.set.set_number} - {slot.item_definition.name}'",
                    actor='Sistema (Histórico Pagamento)',
                    participant=slot.claimed_by,
                    slot=slot,
                    field_name='is_taxa_aduaneira_paid',
                    old_value='Pendente ⏳',
                    new_value='Pago ✔',
                    created_at=base_date,
                    metadata={'slot_id': slot.id},
                )
                counts['payments'] += 1

            # Frete Nacional pago
            if slot.is_frete_nacional_paid and not AuditLog.objects.filter(slot=slot, event_type=AuditLog.EventType.PAYMENT_FRETE_NACIONAL).exists():
                cls.log_event(
                    event_type=AuditLog.EventType.PAYMENT_FRETE_NACIONAL,
                    action_label=f"Frete Nacional alterado para [Pago ✔] em 'Set {slot.set.set_number} - {slot.item_definition.name}'",
                    actor='Sistema (Histórico Pagamento)',
                    participant=slot.claimed_by,
                    slot=slot,
                    field_name='is_frete_nacional_paid',
                    old_value='Pendente ⏳',
                    new_value='Pago ✔',
                    created_at=base_date,
                    metadata={'slot_id': slot.id},
                )
                counts['payments'] += 1

        # Pagamentos históricos em ItemIndividual
        for item in ItemIndividual.objects.filter(comprador__isnull=False).select_related('comprador'):
            base_date = item.created_at

            if item.produto_pago and not AuditLog.objects.filter(item_individual=item, event_type=AuditLog.EventType.PAYMENT_ITEM).exists():
                cls.log_event(
                    event_type=AuditLog.EventType.PAYMENT_ITEM,
                    action_label=f"Pagamento do Item alterado para [Pago ✔] em '{item.nome}'",
                    actor='Sistema (Histórico Pagamento)',
                    participant=item.comprador,
                    item_individual=item,
                    field_name='produto_pago',
                    old_value='Pendente ⏳',
                    new_value='Pago ✔',
                    created_at=base_date,
                    metadata={'item_individual_id': item.id},
                )
                counts['payments'] += 1

            if item.frete_inter_pago and not AuditLog.objects.filter(item_individual=item, event_type=AuditLog.EventType.PAYMENT_FRETE_INTER).exists():
                cls.log_event(
                    event_type=AuditLog.EventType.PAYMENT_FRETE_INTER,
                    action_label=f"Frete Internacional alterado para [Pago ✔] em '{item.nome}'",
                    actor='Sistema (Histórico Pagamento)',
                    participant=item.comprador,
                    item_individual=item,
                    field_name='frete_inter_pago',
                    old_value='Pendente ⏳',
                    new_value='Pago ✔',
                    created_at=base_date,
                    metadata={'item_individual_id': item.id},
                )
                counts['payments'] += 1

            if item.taxa_aduaneira_paga and not AuditLog.objects.filter(item_individual=item, event_type=AuditLog.EventType.PAYMENT_TAXA).exists():
                cls.log_event(
                    event_type=AuditLog.EventType.PAYMENT_TAXA,
                    action_label=f"Taxa Aduaneira alterada para [Pago ✔] em '{item.nome}'",
                    actor='Sistema (Histórico Pagamento)',
                    participant=item.comprador,
                    item_individual=item,
                    field_name='taxa_aduaneira_paga',
                    old_value='Pendente ⏳',
                    new_value='Pago ✔',
                    created_at=base_date,
                    metadata={'item_individual_id': item.id},
                )
                counts['payments'] += 1

            if item.frete_nacional_pago and not AuditLog.objects.filter(item_individual=item, event_type=AuditLog.EventType.PAYMENT_FRETE_NACIONAL).exists():
                cls.log_event(
                    event_type=AuditLog.EventType.PAYMENT_FRETE_NACIONAL,
                    action_label=f"Frete Nacional alterado para [Pago ✔] em '{item.nome}'",
                    actor='Sistema (Histórico Pagamento)',
                    participant=item.comprador,
                    item_individual=item,
                    field_name='frete_nacional_pago',
                    old_value='Pendente ⏳',
                    new_value='Pago ✔',
                    created_at=base_date,
                    metadata={'item_individual_id': item.id},
                )
                counts['payments'] += 1

        # 7. Pacotes Nacionais históricos
        for pacote in PacoteNacional.objects.select_related('participant').order_by('created_at'):
            total_it = pacote.total_itens
            # Solicitação
            if not AuditLog.objects.filter(pacote_nacional=pacote, event_type=AuditLog.EventType.PACKAGE_REQUESTED).exists():
                cls.log_event(
                    event_type=AuditLog.EventType.PACKAGE_REQUESTED,
                    action_label=f"Solicitação de envio nacional ({total_it} itens) via Minha Caixinha",
                    actor='Sistema (Histórico)',
                    participant=pacote.participant,
                    pacote_nacional=pacote,
                    new_value=pacote.identificador,
                    created_at=pacote.solicitado_em or pacote.created_at,
                    metadata={'pacote_id': pacote.id, 'total_itens': total_it},
                )
                counts['packages'] += 1

            # Despacho / Enviado
            if pacote.status in [PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE]:
                if not AuditLog.objects.filter(pacote_nacional=pacote, event_type=AuditLog.EventType.PACKAGE_SENT).exists():
                    cls.log_event(
                        event_type=AuditLog.EventType.PACKAGE_SENT,
                        action_label=f"Pacote {pacote.identificador} despachado via {pacote.transportadora}",
                        actor='Sistema (Histórico)',
                        participant=pacote.participant,
                        pacote_nacional=pacote,
                        field_name='status',
                        old_value='EM_PREPARACAO',
                        new_value='ENVIADO',
                        created_at=pacote.data_envio or pacote.created_at,
                        metadata={'pacote_id': pacote.id, 'codigo_rastreio': pacote.codigo_rastreio},
                    )
                    counts['packages'] += 1

            # Entregue
            if pacote.status == PacoteNacional.Status.ENTREGUE:
                if not AuditLog.objects.filter(pacote_nacional=pacote, event_type=AuditLog.EventType.PACKAGE_DELIVERED).exists():
                    cls.log_event(
                        event_type=AuditLog.EventType.PACKAGE_DELIVERED,
                        action_label=f"Pacote {pacote.identificador} confirmado como entregue ({pacote.entregue_por})",
                        actor='Sistema (Histórico)',
                        participant=pacote.participant,
                        pacote_nacional=pacote,
                        field_name='status',
                        old_value='ENVIADO',
                        new_value='ENTREGUE',
                        created_at=pacote.data_entrega or pacote.updated_at or pacote.created_at,
                        metadata={'pacote_id': pacote.id, 'feedback_rating': pacote.feedback_rating},
                    )
                    counts['packages'] += 1

        counts['total'] = (
            counts['accounts']
            + counts['claim_logs']
            + counts['claims']
            + counts['slots_assigned']
            + counts['mercari_assigned']
            + counts['payments']
            + counts['packages']
        )
        return counts

    @staticmethod
    def create_gom_notification_from_event(log_entry):
        """
        Cria automaticamente uma GOMNotification operacional a partir de um AuditLog registrado.
        """
        try:
            from apps.cegs.models import AuditLog, GOMNotification

            ev = log_entry.event_type
            notif_type = None
            title = ""
            message = ""
            action_url = ""
            action_label = "Ver Detalhes"

            p_name = log_entry.participant_name or "Participante"
            p_phone = log_entry.participant_phone or ""
            ceg_title = log_entry.ceg.title if log_entry.ceg else ""

            if ev == AuditLog.EventType.CLAIM_SUCCESS:
                notif_type = GOMNotification.NotificationType.CLAIM
                slot_info = ""
                if log_entry.slot and hasattr(log_entry.slot, 'item_definition'):
                    slot_info = f" ({log_entry.slot.item_definition.name})"
                title = f"Novo Claim: {p_name}{slot_info}"
                message = f"{p_name} garantiu um photocard/slot na CEG '{ceg_title}'."
                action_url = f"/cegs/{log_entry.ceg.slug}/" if log_entry.ceg and log_entry.ceg.slug else "/creations/"
                action_label = "Ver na CEG"

            elif ev == AuditLog.EventType.CLAIM_CANCELLED:
                notif_type = GOMNotification.NotificationType.CLAIM_CANCELLED
                title = f"Claim Liberado / Cancelado: {ceg_title}"
                message = f"Um slot foi cancelado ou liberado para repescagem na CEG '{ceg_title}'."
                action_url = f"/cegs/{log_entry.ceg.slug}/" if log_entry.ceg and log_entry.ceg.slug else "/creations/"
                action_label = "Ver na CEG"

            elif ev == AuditLog.EventType.PACKAGE_REQUESTED:
                notif_type = GOMNotification.NotificationType.PACKAGE_REQUEST
                pkg_id = log_entry.pacote_nacional.identificador if log_entry.pacote_nacional else ""
                title = f"Solicitação de Envio: {p_name}"
                message = f"{p_name} solicitou o envio nacional de seus itens da caixinha (Pacote {pkg_id})."
                action_url = "/cegs/envios/nacionais/"
                action_label = "Ver Envios Nacionais"

            elif ev in (
                AuditLog.EventType.PAYMENT_ITEM,
                AuditLog.EventType.PAYMENT_FRETE_INTER,
                AuditLog.EventType.PAYMENT_TAXA,
                AuditLog.EventType.PAYMENT_FRETE_NACIONAL,
            ):
                notif_type = GOMNotification.NotificationType.PAYMENT
                title = f"Pagamento Atualizado: {log_entry.action_label[:50]}"
                message = f"{log_entry.action_label} — Participante: {p_name}"
                query_param = p_phone or p_name
                action_url = f"/cegs/consulta-joiner/?q={query_param}"
                action_label = "Ver no Joiner 360º"

            elif ev in (AuditLog.EventType.POLLING_VOTE, AuditLog.EventType.POLLING_CONVERTED):
                notif_type = GOMNotification.NotificationType.POLLING
                title = "Voto de Interesse em Demanda" if ev == AuditLog.EventType.POLLING_VOTE else "Enquete Convertida em Set"
                message = log_entry.action_label
                action_url = f"/cegs/{log_entry.ceg.slug}/" if log_entry.ceg and log_entry.ceg.slug else "/creations/"
                action_label = "Ver Enquete"

            elif ev == AuditLog.EventType.ACCOUNT_CREATED:
                notif_type = GOMNotification.NotificationType.ACCOUNT
                title = f"Novo Joiner: {p_name}"
                message = f"{p_name} ({p_phone}) cadastrou-se na plataforma."
                action_url = f"/cegs/consulta-joiner/?q={p_phone or p_name}"
                action_label = "Ver Joiner"

            if notif_type:
                return GOMNotification.objects.create(
                    notification_type=notif_type,
                    title=title,
                    message=message,
                    participant=log_entry.participant,
                    ceg=log_entry.ceg,
                    slot=log_entry.slot,
                    pacote_nacional=log_entry.pacote_nacional,
                    audit_log=log_entry,
                    action_url=action_url,
                    action_label=action_label,
                    created_at=log_entry.created_at,
                    metadata=log_entry.metadata or {},
                )
        except Exception as e:
            logger.warning(f"Erro ao gerar GOMNotification a partir do AuditLog: {e}")
        return None

    @classmethod
    def sync_recent_gom_notifications(cls, limit=50):
        """
        Gera notificações retroativas para a GOM a partir dos AuditLogs existentes
        caso a tabela de GOMNotification esteja vazia.
        """
        try:
            from apps.cegs.models import AuditLog, GOMNotification
            if GOMNotification.objects.exists():
                return 0

            actionable_events = [
                AuditLog.EventType.CLAIM_SUCCESS,
                AuditLog.EventType.CLAIM_CANCELLED,
                AuditLog.EventType.PACKAGE_REQUESTED,
                AuditLog.EventType.PAYMENT_ITEM,
                AuditLog.EventType.PAYMENT_FRETE_INTER,
                AuditLog.EventType.PAYMENT_TAXA,
                AuditLog.EventType.PAYMENT_FRETE_NACIONAL,
                AuditLog.EventType.POLLING_VOTE,
                AuditLog.EventType.ACCOUNT_CREATED,
            ]
            logs = AuditLog.objects.filter(event_type__in=actionable_events).order_by('-created_at')[:limit]
            created_count = 0
            for log in reversed(list(logs)):
                if cls.create_gom_notification_from_event(log):
                    created_count += 1
            return created_count
        except Exception as e:
            logger.warning(f"Erro ao sincronizar notificações retroativas da GOM: {e}")
            return 0
