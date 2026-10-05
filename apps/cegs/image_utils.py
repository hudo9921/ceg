import os
import time
import uuid
import base64
import logging
import io
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

try:
    from PIL import Image, ImageOps
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

logger = logging.getLogger(__name__)


class ImageSizeError(ValueError):
    """Lançada quando uma imagem enviada ou colada ultrapassa o limite máximo permitido."""
    pass


def _optimize_image_bytes(raw_bytes: bytes, max_dimension: int = 1920, quality: int = 85) -> tuple[bytes, str]:
    """
    Otimiza e redimensiona imagem usando Pillow.
    - Corrige rotação/orientação com EXIF (fotos tiradas em celular de lado/de cabeça para baixo).
    - Redimensiona proporcionalmente fotos gigantes (máx 1920px no maior lado).
    - Converte para JPEG ou WebP com compressão de alta qualidade.
    - Se falhar ou Pillow indisponível, devolve os bytes originais com extensão segura.
    """
    if not HAS_PIL or not raw_bytes:
        return raw_bytes, '.png'

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img = ImageOps.exif_transpose(img)

            has_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
            if has_alpha:
                ext = '.webp'
                fmt = 'WEBP'
            else:
                ext = '.jpg'
                fmt = 'JPEG'
                if img.mode != 'RGB':
                    img = img.convert('RGB')

            w, h = img.size
            if w > max_dimension or h > max_dimension:
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

            out_io = io.BytesIO()
            if fmt == 'JPEG':
                img.save(out_io, format='JPEG', quality=quality, optimize=True)
            else:
                img.save(out_io, format='WEBP', quality=quality, method=4)

            return out_io.getvalue(), ext
    except Exception as e:
        logger.warning(f"Otimização Pillow falhou, preservando bytes originais: {e}")
        return raw_bytes, '.png'


def process_image_upload(file_obj=None, base64_str=None, folder='uploads', fallback_url='', max_size_mb: int = 5) -> str:
    """
    Processa upload de imagem com suporte universal para:
    1. Arquivo direto via multipart form (request.FILES)
    2. Dados brutos ou Data URI em Base64 vindos de Ctrl+V (clipboard paste)
    3. URL externa já informada (fallback_url) ou Data URI colada no campo de URL

    Valida o limite máximo de tamanho (padrão 5 MB) e avisa se exceder.
    Otimiza a imagem para diminuir o tempo de carregamento da página e economizar tráfego.
    Garante que nunca ocorra erro 500 ou estouro de tamanho de URL no banco de dados (máx 500 chars).
    Retorna a URL final da imagem salva no storage (R2/S3) ou uma URL externa válida.
    """
    prefix = 'ceg_' if 'cegs' in folder else ('era_' if 'eras' in folder else ('group_' if 'groups' in folder else 'img_'))
    max_bytes = max_size_mb * 1024 * 1024

    # Se o usuário colou um Data URI no campo de URL (ex: "data:image/jpeg;base64,..."),
    # redireciona automaticamente para processamento Base64 em vez de salvar 50.000 caracteres no varchar(500)
    if not base64_str and fallback_url and isinstance(fallback_url, str):
        cleaned_url = fallback_url.strip()
        if cleaned_url.startswith('data:image/') or ';base64,' in cleaned_url:
            base64_str = cleaned_url
            fallback_url = ''

    # 1. Arquivo direto multipart
    if file_obj and getattr(file_obj, 'size', 0) > 0:
        if file_obj.size > max_bytes:
            size_mb = file_obj.size / (1024 * 1024)
            logger.warning(f"Upload rejeitado por tamanho: {size_mb:.1f} MB (máx: {max_size_mb} MB)")
            raise ImageSizeError(f"O arquivo selecionado ({size_mb:.1f} MB) ultrapassa o limite máximo permitido de {max_size_mb} MB. Por favor, escolha uma imagem menor.")

        try:
            raw_bytes = file_obj.read()
            optimized_bytes, ext = _optimize_image_bytes(raw_bytes)
            safe_filename = f"{folder}/{prefix}{uuid.uuid4().hex[:8]}_{int(time.time())}{ext}"
            saved_path = default_storage.save(safe_filename, ContentFile(optimized_bytes))
            return default_storage.url(saved_path)
        except Exception as e:
            logger.error(f"Erro ao salvar arquivo de imagem no storage: {e}")

    # 2. String Base64 vinda do clipboard (Ctrl+V) ou Data URI
    if base64_str and isinstance(base64_str, str) and base64_str.strip():
        clean_b64 = base64_str.strip()
        try:
            if ',' in clean_b64:
                _, data_str = clean_b64.split(',', 1)
            else:
                data_str = clean_b64

            # Remove espaços em branco ou quebras de linha acidentais
            data_str = data_str.replace('\n', '').replace('\r', '').replace(' ', '')
            decoded_bytes = base64.b64decode(data_str)

            if decoded_bytes:
                if len(decoded_bytes) > max_bytes:
                    size_mb = len(decoded_bytes) / (1024 * 1024)
                    logger.warning(f"Upload Base64 rejeitado por tamanho: {size_mb:.1f} MB (máx: {max_size_mb} MB)")
                    raise ImageSizeError(f"A imagem colada ({size_mb:.1f} MB) ultrapassa o limite máximo permitido de {max_size_mb} MB. Por favor, escolha uma imagem menor.")

                optimized_bytes, ext = _optimize_image_bytes(decoded_bytes)
                safe_filename = f"{folder}/{prefix}{uuid.uuid4().hex[:8]}_{int(time.time())}{ext}"
                saved_path = default_storage.save(safe_filename, ContentFile(optimized_bytes))
                return default_storage.url(saved_path)
        except ImageSizeError:
            raise
        except Exception as e:
            logger.warning(f"Erro ao decodificar e salvar imagem base64: {e}")

    # 3. Fallback para URL externa
    if fallback_url and isinstance(fallback_url, str):
        cleaned_fallback = fallback_url.strip()
        # Garante que a URL externa não seja um Data URI gigante nem exceda 500 caracteres (limite do URLField)
        if cleaned_fallback and not cleaned_fallback.startswith('data:') and len(cleaned_fallback) <= 500:
            return cleaned_fallback

    return ''
