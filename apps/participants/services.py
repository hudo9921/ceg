import re
import csv
import io
import logging
from django.db import transaction
from .models import Participant, clean_phone_number

logger = logging.getLogger(__name__)


class BulkParticipantService:
    """
    Serviço para importação e cadastro inteligente de participantes em massa.
    Suporta formatos colados do Excel/Sheets (tabulação), CSV, pipes (|) e vírgulas.
    Detecta automaticamente campos de Nome, Telefone e Twitter / Rede Social.
    """

    @staticmethod
    def _is_header_row(tokens: list[str]) -> bool:
        """Verifica se a linha é um cabeçalho descritivo (ex: 'Nome', 'Telefone', 'Twitter')."""
        header_keywords = {'nome', 'name', 'telefone', 'phone', 'whatsapp', 'celular', 'twitter', 'social', 'handle', 'rede social', 'user', 'usuario'}
        match_count = sum(1 for t in tokens if t.lower().strip() in header_keywords)
        return match_count >= 1

    @staticmethod
    def _smart_categorize_tokens(tokens: list[str]) -> dict:
        """
        Analisa os pedaços de texto da linha para mapear de forma inteligente:
        - Telefone (contém múltiplos dígitos ou começa com +)
        - Twitter (começa com @ ou tem formato de handle)
        - Nome (texto alfanumérico principal)
        - Apelido / Username (opcional)
        """
        result = {
            'name': '',
            'raw_phone': '',
            'social_handle': '',
            'username': '',
        }

        if not tokens:
            return result

        unassigned = []
        found_phone = False
        found_handle = False

        for token in tokens:
            t = token.strip()
            if not t:
                continue

            # Detecta se é telefone: começa com + ou possui 8+ dígitos
            digits_count = len(re.sub(r'\D', '', t))
            if not found_phone and (t.startswith('+') or digits_count >= 8):
                result['raw_phone'] = t
                found_phone = True
                continue

            # Detecta se é @ de rede social
            if not found_handle and (t.startswith('@') or (re.match(r'^[a-zA-Z0-9_\.]{3,30}$', t) and len(unassigned) >= 1)):
                result['social_handle'] = t
                found_handle = True
                continue

            unassigned.append(t)

        # Se não achou telefone pela regra acima, tenta pegar o token com mais dígitos
        if not found_phone and unassigned:
            best_phone_idx = -1
            max_digits = 0
            for idx, u in enumerate(unassigned):
                d = len(re.sub(r'\D', '', u))
                if d > max_digits and d >= 7:
                    max_digits = d
                    best_phone_idx = idx
            if best_phone_idx != -1:
                result['raw_phone'] = unassigned.pop(best_phone_idx)

        # Se não achou handle, mas tem token começando com @
        if not found_handle and unassigned:
            for idx, u in enumerate(unassigned):
                if u.startswith('@'):
                    result['social_handle'] = unassigned.pop(idx)
                    break

        # O primeiro unassigned é o Nome
        if unassigned:
            result['name'] = unassigned.pop(0)

        # Se sobrou mais algum token, atribui a username ou social_handle se este estiver vazio
        if unassigned:
            leftover = unassigned.pop(0)
            if not result['social_handle']:
                result['social_handle'] = leftover
            elif not result['username']:
                result['username'] = leftover

        return result

    @classmethod
    def parse_raw_line(cls, line: str, default_ddi: str = '55') -> dict:
        """
        Processa uma única linha de texto e extrai os campos normalizados.
        """
        line_clean = line.strip()
        if not line_clean:
            return None

        # Identifica delimitador
        if '\t' in line_clean:
            tokens = [c.strip() for c in line_clean.split('\t') if c.strip()]
        elif '|' in line_clean:
            tokens = [c.strip() for c in line_clean.split('|') if c.strip()]
        elif ';' in line_clean:
            tokens = [c.strip() for c in line_clean.split(';') if c.strip()]
        elif ',' in line_clean:
            # Usa csv reader para respeitar aspas se houver
            try:
                reader = csv.reader(io.StringIO(line_clean))
                tokens = [c.strip() for c in next(reader) if c.strip()]
            except Exception:
                tokens = [c.strip() for c in line_clean.split(',') if c.strip()]
        else:
            # Linha com separação por 2 ou mais espaços
            tokens = [c.strip() for c in re.split(r'\s{2,}', line_clean) if c.strip()]
            if len(tokens) <= 1:
                # Tenta separar por espaço se tiver exatamente 2 ou 3 partes
                parts = line_clean.split()
                tokens = parts

        if not tokens:
            return None

        if cls._is_header_row(tokens):
            return None

        mapped = cls._smart_categorize_tokens(tokens)

        # Validação e Limpeza
        name = mapped['name']
        raw_phone = mapped['raw_phone']
        social = mapped['social_handle']
        username = mapped['username']

        if social and not social.startswith('@'):
            social = f"@{social}"

        clean_phone = clean_phone_number(raw_phone, default_country=default_ddi)
        is_valid = bool(name and clean_phone and len(clean_phone) >= 8)

        error_msg = ""
        if not name:
            error_msg = "Nome não informado."
        elif not clean_phone:
            error_msg = "Telefone inválido ou não informado."
        elif len(clean_phone) < 8:
            error_msg = f"Telefone muito curto ({clean_phone})."

        return {
            'name': name,
            'whatsapp': clean_phone,
            'raw_phone': raw_phone,
            'social_handle': social,
            'username': username,
            'is_valid': is_valid,
            'error': error_msg,
            'original_line': line_clean,
        }

    @classmethod
    def parse_pasted_text(cls, text: str, default_ddi: str = '55') -> list[dict]:
        """
        Recebe um texto multilinhas (ex: copiado do Excel/Sheets ou bloco de notas)
        e retorna lista de participantes parseados.
        """
        if not text:
            return []

        lines = text.splitlines()
        parsed_items = []

        for idx, line in enumerate(lines, start=1):
            item = cls.parse_raw_line(line, default_ddi=default_ddi)
            if item:
                item['line_number'] = idx
                parsed_items.append(item)

        return parsed_items

    @classmethod
    def bulk_create_or_update(
        cls,
        items: list[dict],
        update_existing: bool = True,
        default_ddi: str = '55'
    ) -> dict:
        """
        Cadastra ou atualiza participantes no banco em uma transação atômica.
        Retorna relatório de sucesso, criados, atualizados e erros.
        """
        created = []
        updated = []
        skipped = []
        errors = []

        with transaction.atomic():
            for item in items:
                name = item.get('name', '').strip()
                raw_phone = item.get('whatsapp') or item.get('raw_phone', '')
                cleaned_phone = clean_phone_number(raw_phone, default_country=default_ddi)
                social = item.get('social_handle', '').strip()
                username = item.get('username', '').strip()

                if social and not social.startswith('@'):
                    social = f"@{social}"

                if not name or not cleaned_phone or len(cleaned_phone) < 8:
                    errors.append({
                        'item': item,
                        'reason': 'Nome ausente ou telefone inválido (< 8 dígitos).'
                    })
                    continue

                existing = Participant.objects.filter(whatsapp=cleaned_phone).first()

                if existing:
                    if update_existing:
                        existing.name = name
                        if social:
                            existing.social_handle = social
                        if username:
                            existing.username = username
                        existing.save()
                        updated.append(existing)
                    else:
                        skipped.append(existing)
                else:
                    new_p = Participant.objects.create(
                        name=name,
                        whatsapp=cleaned_phone,
                        social_handle=social,
                        username=username,
                    )
                    created.append(new_p)

        return {
            'success': True,
            'created_count': len(created),
            'updated_count': len(updated),
            'skipped_count': len(skipped),
            'errors_count': len(errors),
            'created': created,
            'updated': updated,
            'skipped': skipped,
            'errors': errors,
        }
