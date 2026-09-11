from django.db import transaction, OperationalError
from django.utils import timezone
from apps.cegs.models import ItemSlot, CEG
from apps.participants.models import Participant, Claim, clean_phone_number


class CEGError(Exception):
    pass


class CEGNotOpenYetError(CEGError):
    pass


class SlotUnavailableError(CEGError):
    pass


class ClaimService:
    @staticmethod
    def claim_slot(slot_id: int, name: str, phone: str, social_handle: str = "", notes: str = "") -> Claim:
        """
        Executa a reserva atômica de um ItemSlot com proteção de concorrência.
        Garante que apenas 1 pessoa consiga reservar o slot físico no segundo zero.
        """
        # 1. Limpeza do telefone
        cleaned_phone = clean_phone_number(phone)
        if not cleaned_phone:
            raise CEGError("Número de WhatsApp inválido.")

        try:
            # 2. Transação Atômica com bloqueio seletivo de linha (select_for_update)
            with transaction.atomic():
                try:
                    slot = ItemSlot.objects.select_for_update().select_related(
                        'set__ceg', 'item_definition'
                    ).get(id=slot_id)
                except ItemSlot.DoesNotExist:
                    raise CEGError("Slot de item não encontrado.")

            ceg = slot.set.ceg

            # 3. Validação do Modo Standby / Abertura da CEG
            if ceg.opens_at and timezone.now() < ceg.opens_at:
                raise CEGNotOpenYetError(
                    f"A CEG ainda está em modo Standby! As reservas abrem em {ceg.opens_at.strftime('%d/%m/%Y às %H:%M:%S')}."
                )

            if ceg.status not in (CEG.Status.OPEN, CEG.Status.SCHEDULED):
                raise CEGError("Esta CEG não está aceitando reservas no momento.")

            if not slot.set.is_active:
                raise CEGError("Este Set está desativado para reservas.")

            # 4. Verificação de Concorrência
            if slot.status != ItemSlot.Status.AVAILABLE:
                raise SlotUnavailableError(
                    f"O item '{slot.item_definition.name}' do Set {slot.set.set_number} "
                    f"já foi pego por outro participante!"
                )

            # 5. Localiza ou cria o participante
            participant, created = Participant.objects.get_or_create(
                whatsapp=cleaned_phone,
                defaults={
                    'name': name.strip(),
                    'social_handle': social_handle.strip(),
                }
            )
            # Se o participante já existia mas atualizou nome/@, atualizamos
            updated = False
            if name.strip() and participant.name != name.strip():
                participant.name = name.strip()
                updated = True
            if social_handle.strip() and participant.social_handle != social_handle.strip():
                participant.social_handle = social_handle.strip()
                updated = True
            if updated:
                participant.save()

            # 6. Atualiza o Slot
            now = timezone.now()
            slot.status = ItemSlot.Status.RESERVED
            slot.claimed_by = participant
            slot.claimed_at = now
            slot.save(update_fields=['status', 'claimed_by', 'claimed_at'])

            # 7. Cria o registro de Claim
            claim = Claim.objects.create(
                slot=slot,
                participant=participant,
                status=Claim.Status.PENDING,
                total_price=slot.price,
                participant_notes=notes.strip(),
                claimed_at=now
            )

            return claim
        except OperationalError:
            raise SlotUnavailableError(
                "Este item está sob alta concorrência e acabou de ser reservado por outro participante."
            )
