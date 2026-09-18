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
                action_label=action_label,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else '',
                new_value=str(new_value) if new_value is not None else '',
                metadata=metadata or {},
            )
            if created_at:
                log_entry.created_at = created_at
            log_entry.save()
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
    def log_slot_assignment(slot, participant, action: str, actor=None, metadata: Optional[Dict[str, Any]] = None):
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
        )

    @classmethod
    def backfill_historical_logs(cls):
        """Popula o AuditLog com dados que já existiam antes (participantes e claims)."""
        from apps.participants.models import Participant
        from apps.cegs.models import ClaimAttemptLog, AuditLog

        count_accounts = 0
        count_claims = 0

        # 1. Participantes existentes
        existing_p_ids = set(
            AuditLog.objects.filter(event_type=AuditLog.EventType.ACCOUNT_CREATED)
            .values_list('participant_id', flat=True)
        )
        for p in Participant.objects.exclude(id__in=existing_p_ids).order_by('created_at'):
            cls.log_account_created(p, actor='Sistema (Legado)', created_at=p.created_at)
            count_accounts += 1

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
            count_claims += 1

        return count_accounts, count_claims
