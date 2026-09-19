import logging
from decimal import Decimal
from typing import List, Dict, Any, Optional
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from apps.cegs.models import (
    CEG,
    CEGSet,
    ItemSlot,
    CEGItemDefinition,
    CEGInterestVote,
    AuditLog,
)
from apps.participants.models import (
    Participant,
    Claim,
    ParticipantNotification,
    clean_phone_number,
)
from apps.cegs.audit_service import AuditService

logger = logging.getLogger(__name__)


class PollingError(Exception):
    """Exceção base para erros no fluxo de Enquete / Sondagem de Demanda."""
    pass


class PollingDemandService:
    @staticmethod
    def record_votes(
        ceg: CEG,
        item_def_ids: Optional[List[int]] = None,
        name: str = "",
        phone: str = "",
        username: str = "",
        social_handle: str = "",
        notes: str = "",
        actor=None,
        participant=None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Registra a intenção de voto (pré-claim) para múltiplos itens/integrantes em uma CEG em status POLLING.
        Timestamp registrado no banco com precisão de microssegundos para critério inquestionável de desempate.
        """
        if item_def_ids is None:
            item_def_ids = kwargs.get('item_definition_ids', [])

        if isinstance(name, Participant):
            participant = name
            name = participant.name
            phone = participant.whatsapp

        if participant:
            phone = phone or participant.whatsapp
            name = name or participant.name
            username = username or participant.username
            social_handle = social_handle or participant.social_handle

        if ceg.status != CEG.Status.POLLING:
            raise PollingError(f"Esta CEG não está em fase de Enquete/Sondagem (status atual: {ceg.get_status_display()}).")

        if ceg.is_standby:
            prazo = ceg.opens_at.strftime('%d/%m/%Y às %H:%M:%S') if ceg.opens_at else 'em breve'
            raise PollingError(f"A votação desta enquete ainda não abriu! Abertura oficial agendada para {prazo}.")

        if not item_def_ids:
            raise PollingError("Nenhum integrante/item selecionado para votar.")

        cleaned_phone = clean_phone_number(phone)
        if not cleaned_phone:
            raise PollingError("Número de WhatsApp inválido.")

        name_clean = (name or "").strip()
        username_clean = (username or "").strip()
        social_clean = (social_handle or "").strip()
        notes_clean = (notes or "").strip()

        with transaction.atomic():
            # 1. Localiza ou cria o participante
            participant, created = Participant.objects.get_or_create(
                whatsapp=cleaned_phone,
                defaults={
                    'name': name_clean or f"Participante {cleaned_phone[-4:]}",
                    'username': username_clean,
                    'social_handle': social_clean,
                }
            )

            # Atualiza dados cadastrais se fornecidos
            updated_fields = []
            if name_clean and participant.name != name_clean:
                participant.name = name_clean
                updated_fields.append('name')
            if username_clean and participant.username != username_clean:
                participant.username = username_clean
                updated_fields.append('username')
            if social_clean and participant.social_handle != social_clean:
                participant.social_handle = social_clean
                updated_fields.append('social_handle')
            if updated_fields:
                participant.save(update_fields=updated_fields)

            # 2. Valida itens pertencentes a esta CEG
            valid_items = list(
                CEGItemDefinition.objects.filter(ceg=ceg, id__in=item_def_ids)
            )
            if not valid_items:
                raise PollingError("Nenhum dos itens selecionados pertence a esta CEG.")

            votes_created = []
            now = timezone.now()

            for item_def in valid_items:
                # Idempotência: Se já votou neste mesmo item, não duplica
                vote, was_created = CEGInterestVote.objects.get_or_create(
                    ceg=ceg,
                    item_definition=item_def,
                    participant=participant,
                    defaults={
                        'notes': notes_clean,
                    }
                )
                if was_created:
                    votes_created.append(vote)

                    # Auditoria detalhada do voto com timestamp de microssegundos
                    AuditService.log_event(
                        event_type=AuditLog.EventType.POLLING_VOTE,
                        action_label=f"Voto em Enquete: {item_def.name}",
                        actor=actor,
                        participant=participant,
                        ceg=ceg,
                        field_name="interest_vote",
                        new_value=item_def.name,
                        metadata={
                            'item_definition_id': item_def.id,
                            'item_name': item_def.name,
                            'member_name': item_def.member_name,
                            'timestamp_iso': now.isoformat(),
                            'notes': notes_clean,
                        },
                        created_at=vote.created_at or now,
                    )

            created_item_ids = {v.item_definition_id for v in votes_created}
            existing_votes = [it for it in valid_items if it.id not in created_item_ids]

            return {
                'success': True,
                'participant': participant,
                'votes_registered': len(votes_created),
                'recorded_count': len(votes_created),
                'votes_created': votes_created,
                'created_votes': votes_created,
                'existing_votes': existing_votes,
                'total_selected': len(valid_items),
                'message': f"🎉 {len(votes_created)} voto(s) registrado(s) com sucesso na fila de interesse!",
            }

    @staticmethod
    def get_polling_summary(ceg: CEG) -> Dict[str, Any]:
        """
        Retorna o termômetro de votos da CEG para exibição tanto pública quanto no painel do organizador.
        """
        item_defs = list(
            ceg.item_definitions.all().order_by('order_index', 'name')
        )
        summary_items = []
        counts = []

        for it in item_defs:
            votes = list(
                it.interest_votes.select_related('participant').order_by('created_at')
            )
            count = len(votes)
            counts.append(count)

            voters = [
                {
                    'position': idx + 1,
                    'participant_id': v.participant.id,
                    'participant_name': v.participant.display_name,
                    'whatsapp_masked': f"****-{v.participant.whatsapp[-4:]}" if v.participant.whatsapp else '',
                    'voted_at': v.created_at.strftime('%d/%m/%Y %H:%M:%S.%f')[:-3] if v.created_at else '',
                    'is_converted': v.is_converted,
                }
                for idx, v in enumerate(votes)
            ]

            summary_items.append({
                'item_id': it.id,
                'item_definition_id': it.id,
                'name': it.name,
                'member_name': it.member_name,
                'sub_category': getattr(it, 'sub_category', ''),
                'tipo_nome': it.tipo_item_nome,
                'price': str(it.default_price),
                'image_url': it.image_url,
                'votes_count': count,
                'voters': voters,
            })

        viable_sets = min(counts) if counts else 0
        max_demand = max(counts) if counts else 0
        total_votes = sum(counts)

        return {
            'ceg_id': ceg.id,
            'ceg_title': ceg.title,
            'is_polling': ceg.is_polling,
            'total_votes': total_votes,
            'viable_sets': viable_sets,
            'viable_sets_count': viable_sets,
            'max_demand': max_demand,
            'max_demand_count': max_demand,
            'items': summary_items,
            'item_summaries': summary_items,
        }

    @staticmethod
    def consolidate_polling_to_sets(
        ceg: CEG,
        num_sets: int,
        actor=None,
        notify_whatsapp: bool = True
    ) -> Dict[str, Any]:
        """
        Consolida a enquete de demanda criando exatamente N sets:
        1. Cria os N CEGSets e gera seus slots físicos.
        2. Aloca os votos por ordem rigorosa de timestamp (1º colocado no Set 1, 2º no Set 2...).
        3. Se para determinado item houver menos votos que N, os slots restantes ficam AVAILABLE.
        4. Votos além de N sets NÃO ganham slot físico e NÃO são notificados (conforme solicitado).
        5. Notifica (no site e no WhatsApp) EXCLUSIVAMENTE quem teve slot garantido, com prazos e chave Pix.
        6. Registra auditoria completa de cada alocação e corte.
        7. Atualiza o status da CEG para OPEN (ou SCHEDULED se opens_at for no futuro).
        """
        if ceg.status != CEG.Status.POLLING:
            raise PollingError(f"A CEG não está em fase de Enquete (status atual: {ceg.get_status_display()}).")

        if num_sets < 1:
            raise PollingError("Você deve abrir pelo menos 1 Set ao consolidar a CEG.")

        with transaction.atomic():
            now = timezone.now()
            existing_sets_count = ceg.sets.count()

            # 1. Cria os novos Sets
            created_sets = []
            for i in range(1, num_sets + 1):
                set_num = existing_sets_count + i
                cset = CEGSet.objects.create(
                    ceg=ceg,
                    set_number=set_num,
                    is_active=True
                )
                cset.generate_slots()
                created_sets.append(cset)

            # Mapeia slots recém-gerados por (set_number, item_definition_id)
            slots_map = {}
            for cset in created_sets:
                for slot in cset.slots.select_related('item_definition').all():
                    slots_map[(cset.set_number, slot.item_definition_id)] = slot

            # 2. Distribui os votos ordenados por timestamp
            item_defs = ceg.item_definitions.all()
            allocated_claims = []
            allocated_participants = set()
            notifications_to_create = []
            whatsapp_messages_to_send = []
            unallocated_votes_count = 0

            for item_def in item_defs:
                votes = list(
                    item_def.interest_votes.select_related('participant')
                    .filter(is_converted=False)
                    .order_by('created_at')
                )

                for rank_idx, vote in enumerate(votes):
                    rank = rank_idx + 1
                    target_set_idx = rank_idx  # 0 -> Set 1, 1 -> Set 2, etc.

                    if target_set_idx < len(created_sets):
                        # Voto CONTEMPLADO: Ganha slot no set correspondente!
                        target_set = created_sets[target_set_idx]
                        slot = slots_map.get((target_set.set_number, item_def.id))

                        if slot and slot.status == ItemSlot.Status.AVAILABLE:
                            slot.status = ItemSlot.Status.RESERVED
                            slot.claimed_by = vote.participant
                            slot.claimed_at = now
                            slot.save(update_fields=['status', 'claimed_by', 'claimed_at'])

                            claim = Claim.objects.create(
                                slot=slot,
                                participant=vote.participant,
                                status=Claim.Status.PENDING,
                                total_price=slot.price,
                                participant_notes=vote.notes or "Convertido de Enquete de Demanda",
                                claimed_at=now
                            )

                            vote.is_converted = True
                            vote.converted_slot = slot
                            vote.save(update_fields=['is_converted', 'converted_slot'])

                            allocated_claims.append(claim)
                            allocated_participants.add(vote.participant)

                            # Auditoria cristalina da vitória do slot
                            voted_time_str = vote.created_at.strftime('%d/%m/%Y %H:%M:%S.%f')[:-3] if vote.created_at else ''
                            AuditService.log_event(
                                event_type=AuditLog.EventType.POLLING_CONVERTED,
                                action_label=f"Voto Contemplado: {item_def.name} ({rank}º Lugar -> Set #{target_set.set_number})",
                                actor=actor,
                                participant=vote.participant,
                                slot=slot,
                                ceg=ceg,
                                field_name="slot_reserved",
                                new_value=f"Set #{target_set.set_number}",
                                metadata={
                                    'item_name': item_def.name,
                                    'set_number': target_set.set_number,
                                    'rank_order': rank,
                                    'vote_timestamp': voted_time_str,
                                    'allocated_at': now.isoformat(),
                                    'slot_id': slot.id,
                                    'price': str(slot.price),
                                },
                            )

                            # Prepara notificação no site
                            prazo_str = ceg.prazo_pagamento_item.strftime('%d/%m/%Y às %H:%M') if ceg.prazo_pagamento_item else 'A definir pelo organizador'
                            title_notif = f"🎉 Vaga Garantida: {item_def.name} (Set #{target_set.set_number})"
                            msg_notif = (
                                f"Seu voto na enquete da CEG '{ceg.title}' foi contemplado com sucesso!\n"
                                f"Item: {item_def.name} (Set #{target_set.set_number})\n"
                                f"Valor: R$ {slot.price:.2f}\n"
                                f"Prazo de Pagamento: {prazo_str}\n"
                                f"Chave Pix: {ceg.pix_key or 'Ver no painel'}"
                            )
                            notifications_to_create.append(
                                ParticipantNotification(
                                    participant=vote.participant,
                                    title=title_notif,
                                    message=msg_notif,
                                    notification_type=ParticipantNotification.NotificationType.CLAIM_UPDATE,
                                )
                            )

                            # Prepara mensagem de WhatsApp (se tiver telefone)
                            if vote.participant.whatsapp:
                                pix_inst = f"\n*Instruções:* {ceg.pix_instructions}" if ceg.pix_instructions else ""
                                wa_text = (
                                    f"🎉 *Parabéns, {vote.participant.display_name}! Sua vaga na CEG foi confirmada!*\n\n"
                                    f"Com base na nossa enquete de demanda, seu voto garantiu o slot oficial na compra em grupo *{ceg.title}*:\n\n"
                                    f"📦 *Item:* {item_def.name} (Set #{target_set.set_number})\n"
                                    f"💰 *Valor:* R$ {slot.price:.2f}\n"
                                    f"🔑 *Chave Pix:* {ceg.pix_key or 'A definir'}{pix_inst}\n"
                                    f"⏰ *Prazo de Pagamento:* {prazo_str}\n\n"
                                    f"Acesse o site para acompanhar seu pedido e enviar o comprovante de pagamento!\n"
                                    f"Agradecemos pela participação! 💖"
                                )
                                whatsapp_messages_to_send.append({
                                    'phone': vote.participant.whatsapp,
                                    'message': wa_text,
                                    'name': vote.participant.display_name,
                                })
                    else:
                        unallocated_votes_count += 1
                        # Voto EXCEDENTE (além de num_sets): NÃO contemplado
                        # Registra na auditoria para transparência total, MAS NÃO NOTIFICA
                        voted_time_str = vote.created_at.strftime('%d/%m/%Y %H:%M:%S.%f')[:-3] if vote.created_at else ''
                        AuditService.log_event(
                            event_type=AuditLog.EventType.POLLING_CONVERTED,
                            action_label=f"Voto Excedente: {item_def.name} ({rank}º Lugar - Fora do corte de {num_sets} Sets)",
                            actor=actor,
                            participant=vote.participant,
                            ceg=ceg,
                            field_name="unallocated_vote",
                            old_value=f"{rank}º lugar",
                            new_value="Excedente",
                            metadata={
                                'item_name': item_def.name,
                                'rank_order': rank,
                                'max_sets_opened': num_sets,
                                'vote_timestamp': voted_time_str,
                            },
                        )

            # 3. Transiciona o status da CEG para OPEN (ou SCHEDULED se opens_at for futuro)
            if ceg.opens_at and ceg.opens_at > now:
                ceg.status = CEG.Status.SCHEDULED
            else:
                ceg.status = CEG.Status.OPEN
            ceg.save(update_fields=['status', 'updated_at'])

            # 4. Cria notificações internas no site em lote
            if notifications_to_create:
                ParticipantNotification.objects.bulk_create(notifications_to_create)

        # Fora da transação: dispara mensagens WhatsApp
        wa_sent_count = 0
        if notify_whatsapp and whatsapp_messages_to_send:
            try:
                from apps.auth_otp.providers import get_whatsapp_provider
                provider = get_whatsapp_provider()
                for wa in whatsapp_messages_to_send:
                    try:
                        provider.send_message(wa['phone'], wa['message'])
                        wa_sent_count += 1
                    except Exception as err:
                        logger.error(f"Erro ao enviar WhatsApp de consolidação de enquete para {wa['phone']}: {err}")
            except Exception as e:
                logger.error(f"Erro ao instanciar WhatsApp Provider: {e}")

        logger.info(
            f"CEG #{ceg.id} ({ceg.title}) consolidada em {num_sets} Sets. "
            f"{len(allocated_claims)} slots alocados. {wa_sent_count} WhatsApps enviados."
        )

        return {
            'success': True,
            'ceg_id': ceg.id,
            'num_sets_created': num_sets,
            'sets_created': num_sets,
            'allocated_slots_count': len(allocated_claims),
            'slots_allocated': len(allocated_claims),
            'allocated_participants_count': len(allocated_participants),
            'notifications_created_count': len(notifications_to_create),
            'whatsapp_messages_sent': wa_sent_count,
            'unallocated_votes': unallocated_votes_count,
            'unallocated_votes_count': unallocated_votes_count,
            'message': (
                f"🚀 Enquete consolidada com sucesso! {num_sets} Set(s) gerado(s), "
                f"{len(allocated_claims)} vaga(s) reservada(s) e "
                f"{len(allocated_participants)} participante(s) notificado(s)."
            ),
        }
