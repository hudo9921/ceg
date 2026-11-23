"""
Quem pode o quê em cada GOM. Ponto único de decisão (docs/MULTI_GOM_DESIGN.md §3).

- Superusuário = administrador da plataforma: atua em qualquer GOM como dono.
- `get_active_gom(request)` = GOM em que o usuário está atuando (seletor guardado na sessão).
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import Gom, GomMembership

ACTIVE_GOM_SESSION_KEY = 'active_gom_id'
BACKOFFICE_LOGIN_URL = '/entrar/'


def active_memberships(user):
    """Vínculos ativos do usuário (com GOM ativo), cacheados no objeto do usuário."""
    if not (user and user.is_authenticated):
        return []
    cached = getattr(user, '_active_gom_memberships', None)
    if cached is None:
        cached = list(GomMembership.objects.filter(user=user, is_active=True, gom__is_active=True)
                      .select_related('gom').order_by('gom__name'))
        user._active_gom_memberships = cached
    return cached


def is_platform_admin(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


def is_gom_member(user) -> bool:
    return bool(active_memberships(user))


def gom_role(user, gom):
    """'OWNER', 'ADMIN' ou None. O administrador da plataforma conta como dono de qualquer GOM."""
    if gom is None or not (user and user.is_authenticated and user.is_active):
        return None
    if is_platform_admin(user):
        return GomMembership.Role.OWNER
    for membership in active_memberships(user):
        if membership.gom_id == gom.id:
            return membership.role
    return None


def accessible_goms(user):
    if is_platform_admin(user):
        return list(Gom.objects.filter(is_active=True).order_by('name'))
    return [m.gom for m in active_memberships(user)]


def get_active_gom(request):
    """GOM em que o usuário está atuando (seletor da sessão), calculado uma vez por requisição."""
    if not hasattr(request, '_active_gom'):
        user = getattr(request, 'user', None)
        goms = accessible_goms(user) if user and user.is_authenticated else []
        wanted = request.session.get(ACTIVE_GOM_SESSION_KEY) if goms else None
        request._active_gom = next((g for g in goms if g.id == wanted), goms[0] if goms else None)
    return request._active_gom


def _deny(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), BACKOFFICE_LOGIN_URL)
    raise PermissionDenied('Acesso restrito à equipe do GOM.')


def gom_member_required(view):
    """Qualquer papel no GOM ativo (dono ou admin)."""
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        gom = get_active_gom(request)
        if not gom or not gom_role(request.user, gom):
            return _deny(request)
        request.active_gom = gom
        return view(request, *args, **kwargs)
    return _wrapped


def gom_owner_required(view):
    """Só o GOM principal (dono) do GOM ativo — ex.: gerenciar a equipe."""
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        gom = get_active_gom(request)
        if not gom or gom_role(request.user, gom) != GomMembership.Role.OWNER:
            return _deny(request)
        request.active_gom = gom
        return view(request, *args, **kwargs)
    return _wrapped


def platform_admin_required(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not is_platform_admin(request.user):
            return _deny(request)
        return view(request, *args, **kwargs)
    return _wrapped
