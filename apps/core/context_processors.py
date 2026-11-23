from django.conf import settings


def frontend(request):
    """Como o CSS é carregado: Tailwind compilado (produção) ou Play CDN (desenvolvimento)."""
    return {'tailwind_cdn': settings.TAILWIND_MODE == 'cdn'}
