import os
import re
from datetime import datetime, timedelta
from decimal import Decimal
import openpyxl
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify
from django.contrib.auth.models import User
from django.db import transaction

from apps.groups.models import KpopGroup, Era
from apps.cegs.models import (
    CEG,
    CEGItemDefinition,
    CEGSet,
    ItemSlot,
    TipoItem,
    ClaimAttemptLog,
    ItemWaitingList,
    Caixa,
    CaixaItemRate,
    ItemIndividual,
)
from apps.participants.models import Participant, Claim, clean_phone_number, ParticipantNotification


class Command(BaseCommand):
    help = 'Limpa a base operacional e popula os dados completos de CEGs e Vagas a partir da planilha LE SSERAFIM Made My Night.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='planilhas/CEGs_Lessera_Made_My_Night_Reestruturada.xlsx',
            help='Caminho para o arquivo da planilha Excel (.xlsx)'
        )
        parser.add_argument(
            '--keep-data',
            action='store_true',
            default=False,
            help='Se fornecido, NÃO apaga os dados existentes antes de importar.'
        )

    def handle(self, *args, **options):
        excel_path = options['file']
        keep_data = options['keep_data']

        if not os.path.exists(excel_path):
            self.stderr.write(self.style.ERROR(f"Arquivo não encontrado: {excel_path}"))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("=== IMPORTAÇÃO DE DADOS: LE SSERAFIM (MADE MY NIGHT) ==="))

        with transaction.atomic():
            if not keep_data:
                self.stdout.write("1. Limpando massa operacional anterior (preservando administradores)...")
                ItemWaitingList.objects.all().delete()
                ClaimAttemptLog.objects.all().delete()
                Claim.objects.all().delete()
                ItemSlot.objects.all().delete()
                CEGSet.objects.all().delete()
                CEGItemDefinition.objects.all().delete()
                CaixaItemRate.objects.all().delete()
                ItemIndividual.objects.all().delete()
                CEG.objects.all().delete()
                Caixa.objects.all().delete()
                ParticipantNotification.objects.all().delete()
                Participant.objects.all().delete()
                Era.objects.all().delete()
                KpopGroup.objects.all().delete()
                self.stdout.write(self.style.SUCCESS("   Massa anterior excluída com sucesso."))

            # 2. Garante superusuário admin
            admin_user, created_admin = User.objects.get_or_create(
                username='admin',
                defaults={
                    'email': 'admin@example.com',
                    'is_staff': True,
                    'is_superuser': True,
                }
            )
            if created_admin:
                admin_user.set_password('admin123')
                admin_user.save()
                self.stdout.write(self.style.SUCCESS("   Superusuário criado: login 'admin' | senha 'admin123'"))

            # 3. Tipos de Item Padrão
            tipo_photocard, _ = TipoItem.objects.get_or_create(nome='Photocard')
            tipo_album, _ = TipoItem.objects.get_or_create(nome='Álbum')
            tipo_cd, _ = TipoItem.objects.get_or_create(nome='CD')

            # 4. Grupo e Era LE SSERAFIM
            lessera, _ = KpopGroup.objects.get_or_create(
                name='LE SSERAFIM',
                defaults={
                    'image_url': 'https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=600&auto=format&fit=crop',
                    'description': 'Girl group sul-coreano de 5 integrantes da Source Music / HYBE.'
                }
            )

            era_mmn, _ = Era.objects.get_or_create(
                group=lessera,
                name='Made My Night',
                defaults={
                    'release_date': datetime(2026, 9, 1).date(),
                    'description': 'Era Made My Night — compras em grupo de POBs, Broadcast, Lucky Draws e álbuns.'
                }
            )

            # 5. Carrega o Workbook Excel
            self.stdout.write(f"2. Lendo planilha: {excel_path}...")
            wb = openpyxl.load_workbook(excel_path, data_only=True)

            # --- ABA 1: CEGs_Cadastro ---
            cegs_sheet = wb['CEGs_Cadastro']
            ceg_meta = {}  # {ceg_id: {'nome': str, 'valor': Decimal, 'prazo': datetime, 'ceg_obj': CEG}}

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

                # Parse de prazo (ex: '12/09', '15/09', '20/09')
                prazo_dt = now + timedelta(days=7)
                if raw_prazo:
                    m = re.match(r'(\d{1,2})/(\d{1,2})', raw_prazo)
                    if m:
                        day, month = int(m.group(1)), int(m.group(2))
                        prazo_dt = datetime(2026, month, day, 23, 59, 59, tzinfo=tz)

                slug = f"ceg-{ceg_id.lower()}-{slugify(ceg_name)}"

                ceg_obj, _ = CEG.objects.get_or_create(
                    slug=slug,
                    defaults={
                        'era': era_mmn,
                        'title': f"LE SSERAFIM — {ceg_name} ({ceg_id})",
                        'description': (
                            f"Compra em Grupo oficial para a era Made My Night ({ceg_name}).\n"
                            f"• Prazo limite do pagamento do slot: {prazo_dt.strftime('%d/%m/%Y às %H:%M')}.\n"
                            "• Frete internacional e taxas serão lançados e rateados na chegada da caixa."
                        ),
                        'pix_key': 'lessera.ceg@kpopbrasil.com.br',
                        'pix_instructions': 'Chave Pix (E-mail). Por favor anexar comprovante no WhatsApp.',
                        'status': CEG.Status.OPEN,
                        'opens_at': now - timedelta(days=2),
                        'closes_at': None,
                        'prazo_pagamento_item': prazo_dt,
                    }
                )

                # Cria definições das 5 integrantes para esta CEG
                members = ['Chaewon', 'Sakura', 'Yunjin', 'Kazuha', 'Eunchae']
                is_album = 'compact' in ceg_name.lower() or 'álbum' in ceg_name.lower()
                chosen_tipo = tipo_album if is_album else tipo_photocard
                chosen_item_type = CEGItemDefinition.ItemType.ALBUM if is_album else (
                    CEGItemDefinition.ItemType.POB if 'pob' in ceg_name.lower() else CEGItemDefinition.ItemType.PHOTOCARD
                )

                item_defs = {}
                for idx, member in enumerate(members, 1):
                    item_def_name = f"Compact ver. {member}" if is_album else f"Photocard {member}"
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

            self.stdout.write(self.style.SUCCESS(f"   {len(ceg_meta)} CEGs e seus itens cadastrados com sucesso."))

            # --- ABA 2: Vagas_Operacional ---
            vagas_sheet = wb['Vagas_Operacional']

            # Cadastro prévio dos Participantes Únicos
            # Mapeia nomes do Excel para nomes completos formatados e telefones limpos
            participant_cache = {}

            def _normalize_phone(name_str, phone_val):
                if not phone_val:
                    # Gera placeholder único determinístico para quem não tem telefone
                    slug_name = slugify(name_str).replace('-', '')[:8]
                    hash_val = sum(ord(c) for c in slug_name) % 900 + 100
                    return f"551190000{hash_val:03d}"
                clean = str(phone_val).replace(' ', '').replace('-', '').replace('.', '')
                if len(clean) <= 9 and not clean.startswith('11'):
                    clean = '11' + clean
                return clean_phone_number(clean)

            # Primeira passagem: coleta e cria os participantes únicos
            for r in range(6, vagas_sheet.max_row + 1):
                part_raw = vagas_sheet.cell(r, 7).value
                phone_raw = vagas_sheet.cell(r, 8).value
                if not part_raw:
                    continue

                username_key = str(part_raw).strip()
                if username_key not in participant_cache:
                    cleaned_whatsapp = _normalize_phone(username_key, phone_raw)
                    display_name = username_key.title()
                    p_obj, _ = Participant.objects.get_or_create(
                        whatsapp=cleaned_whatsapp,
                        defaults={
                            'name': display_name,
                            'username': username_key.lower(),
                            'social_handle': f"@{username_key.lower()}",
                        }
                    )
                    participant_cache[username_key] = p_obj

            self.stdout.write(self.style.SUCCESS(f"   {len(participant_cache)} Participantes únicos cadastrados."))

            # Segunda passagem: cria os Sets e Slots
            sets_cache = {}  # (ceg_id, set_num) -> CEGSet
            slots_created = 0
            slots_reserved = 0
            claims_paid = 0
            claims_pending = 0

            for r in range(6, vagas_sheet.max_row + 1):
                ceg_id_val = vagas_sheet.cell(r, 1).value
                if not ceg_id_val:
                    continue
                ceg_id_str = str(ceg_id_val).strip()
                if ceg_id_str not in ceg_meta:
                    continue

                info = ceg_meta[ceg_id_str]
                ceg_obj = info['ceg_obj']

                set_raw = str(vagas_sheet.cell(r, 3).value or 'SET 01').strip().upper()
                set_match = re.search(r'\d+', set_raw)
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

                member_name = str(vagas_sheet.cell(r, 5).value or '').strip()
                item_def = info['item_defs'].get(member_name)
                if not item_def:
                    continue

                status_vaga = str(vagas_sheet.cell(r, 6).value or '').strip().lower()
                part_user = vagas_sheet.cell(r, 7).value
                part_user_str = str(part_user).strip() if part_user else None
                participant = participant_cache.get(part_user_str) if part_user_str else None

                pagamento_item = bool(vagas_sheet.cell(r, 9).value)

                # Cria ou recupera o ItemSlot
                slot, created_slot = ItemSlot.objects.get_or_create(
                    set=cset,
                    item_definition=item_def,
                    defaults={
                        'price': info['valor'],
                        'status': ItemSlot.Status.AVAILABLE,
                    }
                )

                if 'ocupado' in status_vaga and participant:
                    slot.status = ItemSlot.Status.RESERVED
                    slot.claimed_by = participant
                    slot.claimed_at = now - timedelta(hours=24)
                    slot.is_item_paid = pagamento_item
                    slot.save()

                    claim_status = Claim.Status.PAID if pagamento_item else Claim.Status.PENDING
                    claim_obj, _ = Claim.objects.get_or_create(
                        slot=slot,
                        defaults={
                            'participant': participant,
                            'status': claim_status,
                            'total_price': slot.price,
                            'claimed_at': slot.claimed_at,
                            'paid_at': (now - timedelta(hours=6)) if pagamento_item else None,
                            'participant_notes': 'Importado da planilha de controle MMN.',
                        }
                    )
                    if not _:
                        claim_obj.status = claim_status
                        claim_obj.participant = participant
                        claim_obj.save()

                    slots_reserved += 1
                    if pagamento_item:
                        claims_paid += 1
                    else:
                        claims_pending += 1
                else:
                    slot.status = ItemSlot.Status.AVAILABLE
                    slot.claimed_by = None
                    slot.claimed_at = None
                    slot.is_item_paid = False
                    slot.save()

                slots_created += 1

            self.stdout.write(self.style.SUCCESS("3. Carga concluída com sucesso!"))
            self.stdout.write(f"   • Total de CEGs: {CEG.objects.count()}")
            self.stdout.write(f"   • Total de Sets criados: {CEGSet.objects.count()}")
            self.stdout.write(f"   • Total de Slots criados: {slots_created}")
            self.stdout.write(f"     - Reservados (Claims): {slots_reserved}")
            self.stdout.write(f"       * Pagos (PAID): {claims_paid}")
            self.stdout.write(f"       * Aguardando Pagamento (PENDING): {claims_pending}")
            self.stdout.write(f"     - Disponíveis: {slots_created - slots_reserved}")
            self.stdout.write(f"   • Total de Participantes: {Participant.objects.count()}")
            self.stdout.write(self.style.MIGRATE_HEADING("========================================================="))
