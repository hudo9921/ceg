import os
import time
import uuid
import base64
import logging
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)


def process_image_upload(file_obj=None, base64_str=None, folder='uploads', fallback_url='') -> str:
    """
    Processa upload de imagem com suporte universal para:
    1. Arquivo direto via multipart form (request.FILES)
    2. Dados brutos ou Data URI em Base64 vindos de Ctrl+V (clipboard paste)
    3. URL externa já informada (fallback_url)

    Retorna a URL final da imagem salva no storage (R2/S3) ou a fallback_url.
    """
    prefix = 'ceg_' if 'cegs' in folder else ('era_' if 'eras' in folder else ('group_' if 'groups' in folder else 'img_'))

    # 1. Arquivo direto multipart
    if file_obj:
        try:
            ext = os.path.splitext(getattr(file_obj, 'name', ''))[1].lower()
            if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
                ext = '.png'
            safe_filename = f"{folder}/{prefix}{uuid.uuid4().hex[:8]}_{int(time.time())}{ext}"
            saved_path = default_storage.save(safe_filename, file_obj)
            return default_storage.url(saved_path)
        except Exception as e:
            logger.error(f"Erro ao salvar arquivo de imagem no storage: {e}")

    # 2. String Base64 vinda do clipboard (Ctrl+V)
    if base64_str and isinstance(base64_str, str) and base64_str.strip():
        clean_b64 = base64_str.strip()
        try:
            header = ''
            if ',' in clean_b64:
                header, data_str = clean_b64.split(',', 1)
            else:
                data_str = clean_b64

            decoded_bytes = base64.b64decode(data_str)
            ext = '.png'
            header_lower = header.lower()
            if 'jpeg' in header_lower or 'jpg' in header_lower:
                ext = '.jpg'
            elif 'webp' in header_lower:
                ext = '.webp'
            elif 'gif' in header_lower:
                ext = '.gif'

            safe_filename = f"{folder}/{prefix}{uuid.uuid4().hex[:8]}_{int(time.time())}{ext}"
            saved_path = default_storage.save(safe_filename, ContentFile(decoded_bytes))
            return default_storage.url(saved_path)
        except Exception as e:
            logger.warning(f"Erro ao decodificar e salvar imagem base64: {e}")

    # 3. Fallback para URL externa
    if fallback_url and isinstance(fallback_url, str):
        return fallback_url.strip()

    return ''
