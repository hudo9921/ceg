import os
import io
import re
import base64
import logging
from typing import Optional
from PIL import Image

logger = logging.getLogger(__name__)


def extract_dominant_color(image_source, default_color: str = '#EC4899') -> str:
    """
    Extrai a cor predominante e vibrante de uma imagem usando Pillow.
    Suporta:
    - Bytes ou io.BytesIO
    - Arquivo aberto (UploadedFile do Django)
    - Data URI em Base64 (data:image/...;base64,...)
    - Caminho local no disco/storage
    - URL remota (http/https) com timeout seguro

    Retorna o código hexadecimal da cor (ex: '#8B5CF6').
    """
    if not image_source:
        return default_color

    try:
        pil_image = None

        # 1. Objeto PIL já instanciado
        if isinstance(image_source, Image.Image):
            pil_image = image_source

        # 2. String (Base64, Caminho ou URL)
        elif isinstance(image_source, str):
            clean_str = image_source.strip()
            if not clean_str:
                return default_color

            # Data URI ou Base64
            if clean_str.startswith('data:image') or (len(clean_str) > 100 and ';' in clean_str and 'base64' in clean_str):
                try:
                    if ',' in clean_str:
                        _, b64data = clean_str.split(',', 1)
                    else:
                        b64data = clean_str
                    image_bytes = base64.b64decode(b64data)
                    pil_image = Image.open(io.BytesIO(image_bytes))
                except Exception as e:
                    logger.warning(f"Erro ao decodificar base64 para cor: {e}")

            # URL externa HTTP/HTTPS
            elif clean_str.startswith(('http://', 'https://')):
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        clean_str,
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                    )
                    with urllib.request.urlopen(req, timeout=3.5) as resp:
                        image_bytes = resp.read()
                        pil_image = Image.open(io.BytesIO(image_bytes))
                except Exception as e:
                    logger.warning(f"Erro ao baixar imagem externa para cor ({clean_str[:60]}...): {e}")

            # Caminho de mídia do Django (/media/... ou relativo)
            else:
                try:
                    from django.conf import settings
                    from django.core.files.storage import default_storage

                    media_url = getattr(settings, 'MEDIA_URL', '/media/')
                    storage_path = clean_str
                    if clean_str.startswith(media_url):
                        storage_path = clean_str[len(media_url):]
                    elif clean_str.startswith('/'):
                        storage_path = clean_str.lstrip('/')

                    # 1. Tenta caminho no MEDIA_ROOT
                    if hasattr(settings, 'MEDIA_ROOT') and settings.MEDIA_ROOT:
                        full_local = os.path.join(settings.MEDIA_ROOT, storage_path)
                        if os.path.exists(full_local):
                            pil_image = Image.open(full_local)

                    # 2. Tenta no default_storage
                    if not pil_image and default_storage.exists(storage_path):
                        with default_storage.open(storage_path, 'rb') as f:
                            pil_image = Image.open(io.BytesIO(f.read()))
                except Exception as e:
                    logger.debug(f"Falha ao resolver caminho de mídia ({clean_str}): {e}")

                # 3. Caminho direto no filesystem
                if not pil_image and os.path.exists(clean_str):
                    try:
                        pil_image = Image.open(clean_str)
                    except Exception as e:
                        logger.warning(f"Erro ao abrir arquivo local para cor: {e}")

        # 3. File-like object (Django UploadedFile ou BytesIO)
        elif hasattr(image_source, 'read'):
            try:
                pos = image_source.tell() if hasattr(image_source, 'tell') else 0
                content = image_source.read()
                if hasattr(image_source, 'seek'):
                    image_source.seek(pos)
                pil_image = Image.open(io.BytesIO(content))
            except Exception as e:
                logger.warning(f"Erro ao ler stream de arquivo para cor: {e}")

        if not pil_image:
            return default_color

        # Processamento e amostragem de cores com Pillow
        return _calculate_vibrant_dominant_color(pil_image, default_color)

    except Exception as e:
        logger.error(f"Erro inesperado ao extrair cor dominante: {e}")
        return default_color


def _calculate_vibrant_dominant_color(img: Image.Image, default_color: str) -> str:
    """
    Redimensiona a imagem para análise rápida e pontua pixels para encontrar
    a cor com melhor equilíbrio entre dominância e saturação/vivacidade.
    """
    try:
        # Converte para RGB (descarta canal Alpha ou CMYK)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Redimensiona para miniatura de 60x60 para processamento instantâneo (< 10ms)
        img = img.resize((60, 60), Image.Resampling.BILINEAR)

        # Quantiza para 24 cores mais presentes
        quantized = img.quantize(colors=24)
        palette = quantized.getpalette()  # [r0, g0, b0, r1, g1, b1, ...]
        color_counts = quantized.getcolors(maxcolors=3600)  # [(count, palette_index), ...]

        if not color_counts or not palette:
            return default_color

        candidates = []
        for count, idx in color_counts:
            r = palette[idx * 3]
            g = palette[idx * 3 + 1]
            b = palette[idx * 3 + 2]

            max_c = max(r, g, b)
            min_c = min(r, g, b)
            saturation = (max_c - min_c) / 255.0  # 0.0 a 1.0
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0  # 0.0 a 1.0

            # Descarta brancos/muito claros e pretos/muito escuros
            if luminance > 0.92 or luminance < 0.10:
                continue

            # Descarta tons puramente cinzas sem saturação
            if saturation < 0.12:
                continue

            # Pontuação: favorece cores com boa saturação e presença, sem serem extremas
            lum_factor = 1.0 - abs(luminance - 0.50)
            score = count * (saturation ** 1.2) * lum_factor

            candidates.append((score, r, g, b))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            _, best_r, best_g, best_b = candidates[0]
            return f"#{best_r:02x}{best_g:02x}{best_b:02x}".upper()

        # Se todas forem neutras/cinzas, pega a cor mais frequente que não seja preto/branco extremo
        color_counts.sort(key=lambda x: x[0], reverse=True)
        for count, idx in color_counts:
            r = palette[idx * 3]
            g = palette[idx * 3 + 1]
            b = palette[idx * 3 + 2]
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            if 0.15 < lum < 0.85:
                return f"#{r:02x}{g:02x}{b:02x}".upper()

        return default_color
    except Exception as e:
        logger.warning(f"Erro na quantização da imagem: {e}")
        return default_color
