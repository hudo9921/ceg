from django.conf import settings


def frontend(request):
    """Assets compilados (produção) ou Play CDN + Lucide completo (desenvolvimento)."""
    return {'frontend_build': settings.FRONTEND_MODE == 'build'}
