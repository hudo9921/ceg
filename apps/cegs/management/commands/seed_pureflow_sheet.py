import os
import re
from datetime import datetime, timedelta
from decimal import Decimal
import openpyxl
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from django.db import transaction

from apps.groups.models import KpopGroup, Era
from apps.cegs.models import (
    CEG,
    CEGItemDefinition,
    CEGSet,
    ItemSlot,
    TipoItem,
)
from apps.participants.models import Participant, Claim, clean_phone_number


class Command(BaseCommand):
    help = 'Adiciona a era Pureflow (LE SSERAFIM) à massa de dados a partir da planilha Excel.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='planilhas/CEGs_Lessera_Pureflow_Reestruturada.xlsx',
            help='Caminho para o arquivo da planilha Excel Pureflow (.xlsx)'
        )

    def handle(self, *args, **options):
        excel_path = options['file']

        if not os.path.exists(excel_path):
            self.stderr.write(self.style.ERROR(f"Arquivo não encontrado: {excel_path}"))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("=== IMPORTAÇÃO DE DADOS: LE SSERAFIM (PUREFLOW) ==="))

        with transaction.atomic():
            # 1. Obter Grupo LE SSERAFIM
            group, _ = KpopGroup.objects.get_or_create(
                name='LE SSERAFIM',
                defaults={
                    'slug': 'le-sserafim',
                    'description': 'Grupo feminino formado por Chaewon, Sakura, Yunjin, Kazuha e Eunchae.'
                }
            )

            # 2. Criar Era Pureflow
            era_pf, created_era = Era.objects.get_or_create(
                group=group,
                name='Pureflow',
                defaults={
                    'slug': 'pureflow',
                    'description': 'Álbum e Especiais Pureflow de LE SSERAFIM.',
                    'release_date': '2026-05-30',
                }
            )
            self.stdout.write(f"1. Era vinculada: {era_pf.name} ({'Criada' if created_era else 'Existente'}).")

            # 3. Tipos de Item
            tipo_photocard, _ = TipoItem.objects.get_or_create(
                nome='Photocard',
                defaults={'descricao': 'Cards promocionais, POB ou de álbum'}
            )
            tipo_album, _ = TipoItem.objects.get_or_create(
                nome='Álbum',
                defaults={'descricao': 'Álbuns completos ou compactos'}
            )

            # 4. Leitura do Workbook
            self.stdout.write(f"2. Lendo planilha: {excel_path}...")
            wb = openpyxl.load_workbook(excel_path, data_only=True)

            # --- Pre-scan de Vagas_Operacional para descobrir itens por CEG e participantes ---
            vagas_sheet = wb['Vagas_Operacional']
            ceg_items_map = {}  # {ceg_id: [member_name, ...]} (preservando ordem)
            vagas_rows = []

            for r in range(6, vagas_sheet.max_row + 1):
                ceg_id_val = vagas_sheet.cell(r, 1).value
                if not ceg_id_val:
                    continue
                ceg_id_str = str(ceg_id_val).strip()
                member_name = str(vagas_sheet.cell(r, 5).value or '').strip()

                if ceg_id_str not in ceg_items_map:
                    ceg_items_map[ceg_id_str] = []
                if member_name and member_name not in ceg_items_map[ceg_id_str]:
                    ceg_items_map[ceg_id_str].append(member_name)

                vagas_rows.append({
                    'row': r,
                    'ceg_id': ceg_id_str,
                    'ceg_name': str(vagas_sheet.cell(r, 2).value or '').strip(),
                    'set_raw': str(vagas_sheet.cell(r, 3).value or 'SET 01').strip().upper(),
                    'status_set': str(vagas_sheet.cell(r, 4).value or '').strip(),
                    'member_name': member_name,
                    'status_vaga': str(vagas_sheet.cell(r, 6).value or '').strip().lower(),
                    'participante': vagas_sheet.cell(r, 7).value,
                    'telefone': vagas_sheet.cell(r, 8).value,
                    'pagamento_item': bool(vagas_sheet.cell(r, 9).value),
                    'inter': bool(vagas_sheet.cell(r, 10).value),
                    'taxa': bool(vagas_sheet.cell(r, 11).value),
                    'nacional': bool(vagas_sheet.cell(r, 12).value),
                })

            # --- ABA 1: CEGs_Cadastro ---
            cegs_sheet = wb['CEGs_Cadastro']
            ceg_meta = {}

            tz = timezone.get_current_timezone()
            now = timezone.now()

            for r in range(6, cegs_sheet.max_row + 1):
                ceg_id = cegs_sheet.cell(r, 1).value
                if not ceg_id:
                    continue
                ceg_id = str(ceg_id).strip()
                ceg_name = str(cegs_sheet.cell(r, 3).value or '').strip()
                raw_valor = cegs_sheet.cell(r, 4).value
                valor_item = Decimal(str(raw_valor or '0.00'))
                raw_prazo = str(cegs_sheet.cell(r, 5).value or '').strip()

                # Parse de prazo do item (ex: '31/05', '06/06', '15/06', etc.)
                prazo_dt = now + timedelta(days=7)
                if raw_prazo:
                    m = re.match(r'(\d{1,2})/(\d{1,2})', raw_prazo)
                    if m:
                        day, month = int(m.group(1)), int(m.group(2))
                        prazo_dt = datetime(2026, month, day, 23, 59, 59, tzinfo=tz)

                # Valores e prazos adicionais (Inter, Taxa)
                raw_valor_inter = cegs_sheet.cell(r, 6).value
                valor_inter = Decimal(str(raw_valor_inter)) if raw_valor_inter is not None else Decimal('0.00')

                raw_prazo_inter = str(cegs_sheet.cell(r, 7).value or '').strip()
                prazo_inter_dt = None
                if raw_prazo_inter:
                    m_inter = re.match(r'(\d{1,2})/(\d{1,2})', raw_prazo_inter)
                    if m_inter:
                        d_i, m_i = int(m_inter.group(1)), int(m_inter.group(2))
                        prazo_inter_dt = datetime(2026, m_i, d_i, 23, 59, 59, tzinfo=tz)

                slug = f"ceg-{ceg_id.lower()}-{slugify(ceg_name)}"

                ceg_obj, created_ceg = CEG.objects.get_or_create(
                    slug=slug,
                    defaults={
                        'era': era_pf,
                        'title': f"LE SSERAFIM — {ceg_name} ({ceg_id})",
                        'description': (
                            f"Compra em Grupo oficial para a era Pureflow ({ceg_name}).\n"
                            f"• Prazo limite do pagamento do slot: {prazo_dt.strftime('%d/%m/%Y às %H:%M')}.\n"
                            "• Frete internacional e taxas serão lançados e rateados na chegada da caixa."
                        ),
                        'pix_key': 'lessera.ceg@kpopbrasil.com.br',
                        'pix_instructions': 'Chave Pix (E-mail). Por favor anexar comprovante no WhatsApp.',
                        'status': CEG.Status.OPEN,
                        'opens_at': prazo_dt - timedelta(days=14),
                        'closes_at': prazo_dt,
                        'prazo_pagamento_item': prazo_dt,
                        'frete_inter': valor_inter,
                        'prazo_pagamento_frete_inter': prazo_inter_dt,
                    }
                )

                # Cria definições dos itens/membros descobertos para esta CEG
                is_album = 'compact' in ceg_name.lower() or 'álbum' in ceg_name.lower()
                chosen_tipo = tipo_album if is_album else tipo_photocard
                chosen_item_type = CEGItemDefinition.ItemType.ALBUM if is_album else (
                    CEGItemDefinition.ItemType.POB if 'pob' in ceg_name.lower() else CEGItemDefinition.ItemType.PHOTOCARD
                )

                discovered_items = ceg_items_map.get(ceg_id, ['Chaewon', 'Sakura', 'Yunjin', 'Kazuha', 'Eunchae'])
                item_defs = {}

                for idx, member in enumerate(discovered_items, 1):
                    if is_album:
                        item_def_name = f"Compact ver. {member}"
                    elif 'pob' in ceg_name.lower():
                        item_def_name = f"POB {member}"
                    elif 'fansign' in ceg_name.lower():
                        item_def_name = f"Fansign {member}"
                    elif 'ld' in ceg_name.lower():
                        item_def_name = f"Lucky Draw {member}"
                    else:
                        item_def_name = f"Photocard {member}"

                    item_def, _ = CEGItemDefinition.objects.get_or_create(
                        ceg=ceg_obj,
                        member_name=member,
                        defaults={
                            'name': item_def_name,
                            'item_type': chosen_item_type,
                            'tipo_item': chosen_tipo,
                            'default_price': valor_item,
                            'order_index': idx,
                        }
                    )
                    item_defs[member] = item_def

                ceg_meta[ceg_id] = {
                    'nome': ceg_name,
                    'valor': valor_item,
                    'prazo': prazo_dt,
                    'ceg_obj': ceg_obj,
                    'item_defs': item_defs,
                }

            self.stdout.write(self.style.SUCCESS(f"   {len(ceg_meta)} CEGs da era Pureflow registradas com sucesso."))

            # --- Resolução / Cadastro Unificado de Participantes ---
            existing_by_user = {p.username.lower(): p for p in Participant.objects.all() if p.username}
            existing_by_name = {p.name.lower(): p for p in Participant.objects.all()}
            existing_by_phone = {p.whatsapp: p for p in Participant.objects.all()}

            participant_cache = {}

            def _resolve_participant(name_raw, phone_raw):
                if not name_raw:
                    return None
                name_clean = str(name_raw).strip()
                name_lower = name_clean.lower()

                if name_lower in participant_cache:
                    return participant_cache[name_lower]

                # 1. Match por usuário/apelido já cadastrado (ex: nataly rocha, naju, hudo...)
                if name_lower == 'nataly' and 'nataly rocha' in existing_by_user:
                    p = existing_by_user['nataly rocha']
                    participant_cache[name_lower] = p
                    return p
                if name_lower in existing_by_user:
                    p = existing_by_user[name_lower]
                    participant_cache[name_lower] = p
                    return p
                if name_lower in existing_by_name:
                    p = existing_by_name[name_lower]
                    participant_cache[name_lower] = p
                    return p

                # 2. Normalização de Telefone
                if phone_raw is not None:
                    raw_str = str(phone_raw).split('.')[0]
                    digits = re.sub(r'\D', '', raw_str)
                    if len(digits) == 9 and digits.startswith('62'):
                        digits = '55' + digits
                    elif len(digits) in (8, 9) and not digits.startswith('11'):
                        digits = '5511' + digits
                    elif len(digits) in (10, 11) and not digits.startswith('55'):
                        digits = '55' + digits
                    norm_phone = clean_phone_number(digits)
                else:
                    digits_hash = sum(ord(c) for c in name_lower) % 900 + 100
                    norm_phone = f"551190000{digits_hash:03d}"

                # 3. Match por telefone existente
                if norm_phone in existing_by_phone:
                    p = existing_by_phone[norm_phone]
                    participant_cache[name_lower] = p
                    return p

                # 4. Criação de novo Participante
                display_name = name_clean.title()
                p_obj, _ = Participant.objects.get_or_create(
                    whatsapp=norm_phone,
                    defaults={
                        'name': display_name,
                        'username': name_lower,
                        'social_handle': f"@{name_lower}",
                    }
                )
                existing_by_phone[norm_phone] = p_obj
                existing_by_user[name_lower] = p_obj
                participant_cache[name_lower] = p_obj
                return p_obj

            for row in vagas_rows:
                if row['participante']:
                    _resolve_participant(row['participante'], row['telefone'])

            self.stdout.write(self.style.SUCCESS(f"   Participantes resolvidos/cadastrados: {len(participant_cache)} únicos nesta planilha."))

            # --- Criação de Sets, Slots e Claims ---
            sets_cache = {}
            slots_created = 0
            slots_reserved = 0
            claims_created = 0
            claims_paid = 0

            for row in vagas_rows:
                ceg_id_str = row['ceg_id']
                if ceg_id_str not in ceg_meta:
                    continue

                info = ceg_meta[ceg_id_str]
                ceg_obj = info['ceg_obj']

                set_match = re.search(r'\d+', row['set_raw'])
                set_num = int(set_match.group()) if set_match else 1

                set_key = (ceg_id_str, set_num)
                if set_key not in sets_cache:
                    cset, _ = CEGSet.objects.get_or_create(
                        ceg=ceg_obj,
                        set_number=set_num,
                        defaults={'is_active': True}
                    )
                    sets_cache[set_key] = cset
                cset = sets_cache[set_key]

                member_name = row['member_name']
                item_def = info['item_defs'].get(member_name)
                if not item_def:
                    continue

                status_vaga = row['status_vaga']
                part_user_str = str(row['participante']).strip().lower() if row['participante'] else None
                participant = participant_cache.get(part_user_str) if part_user_str else None

                slot, created_slot = ItemSlot.objects.get_or_create(
                    set=cset,
                    item_definition=item_def,
                    defaults={
                        'price': info['valor'],
                        'status': ItemSlot.Status.AVAILABLE,
                    }
                )
                if created_slot:
                    slots_created += 1

                # Atualiza flags financeiras no slot
                slot.is_item_paid = row['pagamento_item']
                slot.is_frete_inter_paid = row['inter']
                slot.is_taxa_aduaneira_paid = row['taxa']
                slot.is_frete_nacional_paid = row['nacional']

                if 'ocupado' in status_vaga and participant:
                    slot.status = ItemSlot.Status.RESERVED
                    slot.claimed_by = participant
                    slot.claimed_at = now - timedelta(days=10)
                    slot.save()
                    slots_reserved += 1

                    claim_status = Claim.Status.PAID if row['pagamento_item'] else Claim.Status.PENDING
                    claim_obj, created_claim = Claim.objects.get_or_create(
                        slot=slot,
                        defaults={
                            'participant': participant,
                            'status': claim_status,
                            'total_price': slot.price,
                            'claimed_at': slot.claimed_at,
                            'paid_at': slot.claimed_at if row['pagamento_item'] else None,
                        }
                    )
                    if created_claim:
                        claims_created += 1
                    if claim_status == Claim.Status.PAID:
                        claims_paid += 1
                else:
                    slot.status = ItemSlot.Status.AVAILABLE
                    slot.claimed_by = None
                    slot.claimed_at = None
                    slot.save()

            self.stdout.write(self.style.SUCCESS(
                f"\n=== IMPORTAÇÃO PUREFLOW CONCLUÍDA COM SUCESSO ===\n"
                f"• CEGs da era Pureflow: {len(ceg_meta)}\n"
                f"• Sets criados/processados: {len(sets_cache)}\n"
                f"• Slots processados: {len(vagas_rows)} ({slots_reserved} ocupados, {len(vagas_rows) - slots_reserved} disponíveis)\n"
                f"• Claims registrados: {claims_created} (Pagos: {claims_paid}, Pendentes: {claims_created - claims_paid})\n"
                f"• Total consolidado de Participantes ativos no banco: {Participant.objects.count()}"
            ))
