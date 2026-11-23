from .access import accessible_goms, get_active_gom, gom_role, is_platform_admin
from .models import GomMembership


def gom_context(request):
    """GOM ativo, papel e lista para o seletor. Só consulta o banco para usuários logados."""
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return {}
    gom = get_active_gom(request)
    role = gom_role(user, gom)
    return {
        'active_gom': gom,
        'gom_role': role,
        'is_gom_member': role is not None,
        'is_gom_owner': role == GomMembership.Role.OWNER,
        'is_platform_admin': is_platform_admin(user),
        'switchable_goms': accessible_goms(user),
    }
