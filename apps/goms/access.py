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


def active_membership(user, gom):
    """Vínculo ativo do usuário neste GOM (ou None)."""
    if gom is None:
        return None
    return next((m for m in active_memberships(user) if m.gom_id == gom.id), None)


def gom_permissions(request):
    """Permissões efetivas no GOM ativo (apps.goms.permissions), calculadas uma vez por requisição."""
    from . import permissions as perms

    if not hasattr(request, '_gom_permissions'):
        user = getattr(request, 'user', None)
        gom = get_active_gom(request) if user and user.is_authenticated else None
        if gom is None or gom_role(user, gom) is None:
            result = frozenset()
        elif is_platform_admin(user):
            result = perms.ALL
        else:
            result = perms.membership_permissions(active_membership(user, gom))
        request._gom_permissions = result
    return request._gom_permissions


def has_gom_perm(request, *keys) -> bool:
    """True se a pessoa tem QUALQUER uma das permissões no GOM ativo. `ANY` = qualquer membro."""
    from .permissions import ANY

    granted = gom_permissions(request)
    if not granted:
        return False
    return any(key == ANY or key in granted for key in keys)


def accessible_goms(user):
    """GOMs em que o usuário pode atuar; os da própria equipe vêm primeiro (GOM padrão)."""
    own = [m.gom for m in active_memberships(user)]
    if is_platform_admin(user):
        own_ids = {g.id for g in own}
        return own + [g for g in Gom.objects.filter(is_active=True).order_by('name') if g.id not in own_ids]
    return own


def get_active_gom(request):
    """GOM em que o usuário está atuando (seletor da sessão), calculado uma vez por requisição.

    Membro de equipe cai no primeiro GOM dele. O administrador da plataforma não entra em GOM nenhum
    sozinho: precisa escolher em "GOMs da plataforma" (Abrir painel), e sai com "Sair do painel".
    """
    if not hasattr(request, '_active_gom'):
        user = getattr(request, 'user', None)
        goms = accessible_goms(user) if user and user.is_authenticated else []
        wanted = request.session.get(ACTIVE_GOM_SESSION_KEY) if goms else None
        gom = next((g for g in goms if g.id == wanted), None)
        if gom is None and goms and not is_platform_admin(user):
            gom = goms[0]
        request._active_gom = gom
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


def has_backoffice_access(request) -> bool:
    """Membro do GOM ativo (ou plataforma) com o 2FA da sessão já verificado."""
    from apps.core.two_factor import is_two_factor_verified, requires_two_factor

    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated and user.is_active):
        return False
    gom = get_active_gom(request)
    if gom is None or gom_role(user, gom) is None:
        return False
    return not requires_two_factor(user) or is_two_factor_verified(user)


def can_manage(request, obj) -> bool:
    """Pode gerenciar este objeto: equipe do GOM ativo E o objeto pertence a esse GOM."""
    if not getattr(request, 'is_gom_staff', False):
        return False
    gom_id = getattr(obj, 'gom_id', None)
    if gom_id is None and obj is not None and hasattr(obj, 'pk') and obj.__class__.__name__ == 'Gom':
        gom_id = obj.pk
    return gom_id is not None and gom_id == request.active_gom.id


class GomStaffMiddleware:
    """Define `request.active_gom` e `request.is_gom_staff` (depois do 2FA e da sessão)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            request.active_gom = get_active_gom(request)
            request.is_gom_staff = has_backoffice_access(request)
        else:
            request.active_gom, request.is_gom_staff = None, False
        return self.get_response(request)
