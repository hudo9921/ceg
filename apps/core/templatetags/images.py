from django import template

from apps.core.thumbnails import thumbnail_url

register = template.Library()


@register.filter
def thumb(url):
    """
    Miniatura (640 px, WebP) de uma imagem nossa; URLs externas passam intactas.
    Use junto com `data-full`, para o navegador voltar à original se faltar a miniatura:
        <img src="{{ url|thumb }}" data-full="{{ url }}" loading="lazy" ...>
    """
    return thumbnail_url(url)
