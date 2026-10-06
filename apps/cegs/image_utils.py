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
    prefix = 'item_' if 'item' in folder else ('ceg_' if 'cegs' in folder else ('era_' if 'eras' in folder else ('group_' if 'groups' in folder else 'img_')))
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


def crop_image_from_coordinates(
    source_url_or_path: str = '',
    source_bytes: bytes = None,
    x: float = 0,
    y: float = 0,
    width: float = 0,
    height: float = 0,
    folder: str = 'items',
    quality: int = 85
) -> str:
    """
    Recorta uma sub-região retangular da imagem original informada usando Pillow.
    Aceita:
    - source_bytes: bytes diretos da imagem.
    - source_url_or_path: URL externa (http/https), Data URI Base64 ou caminho no storage/media.
    Retorna a URL da imagem recortada salva no storage.
    """
    if not HAS_PIL:
        logger.error("Pillow não está disponível para recortar imagem.")
        return ''

    raw_bytes = source_bytes

    if not raw_bytes and source_url_or_path:
        cleaned_src = str(source_url_or_path).strip()
        if cleaned_src.startswith('data:image/') or ';base64,' in cleaned_src:
            try:
                b64_part = cleaned_src.split(',', 1)[1] if ',' in cleaned_src else cleaned_src
                b64_part = b64_part.replace('\n', '').replace('\r', '').replace(' ', '')
                raw_bytes = base64.b64decode(b64_part)
            except Exception as e:
                logger.warning(f"Falha ao decodificar base64 em crop_image: {e}")
        elif cleaned_src.startswith('http://') or cleaned_src.startswith('https://'):
            try:
                import urllib.request
                import ssl
                req = urllib.request.Request(cleaned_src, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
                })
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                    raw_bytes = resp.read()
            except Exception as e:
                logger.warning(f"Falha ao baixar imagem remota para crop ({cleaned_src}): {e}")
        else:
            # Caminho no storage local ou default_storage
            storage_path = cleaned_src.lstrip('/')
            if storage_path.startswith('media/'):
                storage_path = storage_path[6:]
            try:
                if default_storage.exists(storage_path):
                    with default_storage.open(storage_path, 'rb') as f:
                        raw_bytes = f.read()
            except Exception as e:
                logger.warning(f"Falha ao abrir imagem no storage ({storage_path}): {e}")

    if not raw_bytes:
        logger.error("Bytes da imagem original não encontrados para efetuar o recorte.")
        return ''

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            img_w, img_h = img.size

            # Coordenadas seguras dentro das dimensões da imagem
            crop_x = max(0, min(int(round(x)), img_w - 1))
            crop_y = max(0, min(int(round(y)), img_h - 1))
            crop_w = max(10, int(round(width)))
            crop_h = max(10, int(round(height)))

            crop_right = min(crop_x + crop_w, img_w)
            crop_bottom = min(crop_y + crop_h, img_h)

            cropped = img.crop((crop_x, crop_y, crop_right, crop_bottom))

            has_alpha = cropped.mode in ('RGBA', 'LA') or (cropped.mode == 'P' and 'transparency' in cropped.info)
            out_io = io.BytesIO()

            if has_alpha:
                ext = '.webp'
                cropped.save(out_io, format='WEBP', quality=quality, method=4)
            else:
                ext = '.jpg'
                if cropped.mode != 'RGB':
                    cropped = cropped.convert('RGB')
                cropped.save(out_io, format='JPEG', quality=quality, optimize=True)

            prefix = 'item_'
            safe_filename = f"{folder}/{prefix}{uuid.uuid4().hex[:8]}_{int(time.time())}{ext}"
            saved_path = default_storage.save(safe_filename, ContentFile(out_io.getvalue()))
            return default_storage.url(saved_path)
    except Exception as e:
        logger.error(f"Erro ao recortar imagem com Pillow: {e}")
        return ''

