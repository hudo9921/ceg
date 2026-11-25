"""
Miniaturas das imagens hospedadas pela plataforma.

Fotos são guardadas com até 1920 px, mas listas e grades as exibem com ~200 px. Para cada
imagem do nosso storage existe uma miniatura WebP de até 640 px em um caminho previsível:

    uploads/cegs/ceg_ab12.jpg  ->  thumbs/640/uploads/cegs/ceg_ab12.webp

Por ser um caminho derivado, o template calcula a URL da miniatura sem consultar banco nem
storage (`{{ url|thumb }}`). Imagens externas (Mercari, redes sociais) ficam como estão.
Se uma miniatura não existir, o navegador volta para a original (`data-full` + listener em
base.html), então nada quebra enquanto `generate_thumbnails` não terminar.
"""
import io
import logging
import posixpath
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

THUMB_MAX_SIZE = (640, 640)
THUMB_QUALITY = 78
THUMB_PREFIX = 'thumbs/640/'


def storage_name_from_url(url: str) -> str | None:
    """Nome do arquivo no storage para URLs da nossa mídia; None para URLs externas."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    media_url = settings.MEDIA_URL or '/media/'
    if media_url.startswith('/'):
        # Mídia local: aceita '/media/x' e 'https://<host>/media/x'.
        path = urlparse(url).path if '://' in url else url
        if not path.startswith(media_url):
            return None
        name = path[len(media_url):]
    else:
        if not url.startswith(media_url):
            return None
        name = urlparse(url[len(media_url):]).path
    name = unquote(name).lstrip('/')
    if not name or '..' in name.split('/') or name.startswith(THUMB_PREFIX):
        return None
    return name


def thumbnail_name(storage_name: str) -> str:
    base, _ext = posixpath.splitext(storage_name)
    return f'{THUMB_PREFIX}{base}.webp'


def thumbnail_url(url: str) -> str:
    """URL da miniatura de uma imagem nossa; a própria URL para imagens externas."""
    name = storage_name_from_url(url)
    if not name:
        return url or ''
    return default_storage.url(thumbnail_name(name))


def build_thumbnail_bytes(raw: bytes) -> bytes:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(raw)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGBA' if 'transparency' in img.info or img.mode in ('LA', 'P') else 'RGB')
        img.thumbnail(THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format='WEBP', quality=THUMB_QUALITY, method=4)
        return out.getvalue()


def save_thumbnail(storage_name: str, raw: bytes | None = None, overwrite: bool = False) -> bool:
    """Gera a miniatura de um arquivo do storage. Retorna True se criou uma nova."""
    target = thumbnail_name(storage_name)
    if not overwrite and default_storage.exists(target):
        return False
    if raw is None:
        with default_storage.open(storage_name, 'rb') as fh:
            raw = fh.read()
    data = build_thumbnail_bytes(raw)
    if default_storage.exists(target):
        default_storage.delete(target)  # FileSystemStorage renomearia em vez de sobrescrever
    default_storage.save(target, ContentFile(data))
    return True


def ensure_thumbnail(url: str, raw: bytes | None = None) -> None:
    """Cria a miniatura de uma imagem recém-salva. Nunca interrompe o upload."""
    name = storage_name_from_url(url)
    if not name:
        return
    try:
        save_thumbnail(name, raw=raw)
    except Exception as exc:  # miniatura é otimização: o upload original já está salvo
        logger.warning("Miniatura não gerada para %s: %s", name, exc)
