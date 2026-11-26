"""Seguir grupos e integrantes (/me/seguindo/): página, busca de grupos e seguir/deixar de seguir (JSON)."""
import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.core.thumbnails import thumbnail_url
from apps.groups.models import GroupMember, KpopGroup

from .models import Seguindo
from .seguindo import alternar
from .session_auth import get_session_participant


def _precisa_entrar():
    return JsonResponse({'success': False, 'requires_auth': True, 'redirect_url': '/me/login/?next=/me/seguindo/',
                         'message': 'Entre na sua conta para seguir.'}, status=401)


def grupo_dados(g, seguidos_grupo=(), seguidos_membro=()):
    """Formato da página: grupo com integrantes atuais e o que o joiner já segue."""
    return {
        'id': g.id, 'name': g.name, 'name_native': g.name_native, 'kind': g.get_kind_display(),
        'thumb': thumbnail_url(g.image_url) if g.image_url else '', 'image': g.image_url or '',
        'seguindo': g.id in seguidos_grupo,
        'members': [{'id': m.id, 'name': m.name, 'seguindo': m.id in seguidos_membro}
                    for m in g.members.all() if not m.is_former],
    }


@never_cache
def pagina(request):
    participant = get_session_participant(request)
    if participant is None:
        return redirect('/me/login/?next=/me/seguindo/')
    seguindo = list(Seguindo.objects.filter(participant=participant))
    grupos_ids = {s.group_id for s in seguindo}
    seg_grupo = {s.group_id for s in seguindo if not s.member_id}
    seg_membro = {s.member_id for s in seguindo if s.member_id}
    grupos = KpopGroup.objects.filter(id__in=grupos_ids).prefetch_related('members').order_by('name')
    return render(request, 'participants/seguindo.html', {
        'participant': participant,
        'grupos': [grupo_dados(g, seg_grupo, seg_membro) for g in grupos],
    })


@require_GET
def buscar(request):
    from apps.cegs.catalogo_views import buscar_grupos

    participant = get_session_participant(request)
    if participant is None:
        return _precisa_entrar()
    ids = [g['id'] for g in buscar_grupos(request.GET.get('q', ''), limite=8)]
    seguindo = list(Seguindo.objects.filter(participant=participant, group_id__in=ids))
    seg_grupo = {s.group_id for s in seguindo if not s.member_id}
    seg_membro = {s.member_id for s in seguindo if s.member_id}
    por_id = {g.id: g for g in KpopGroup.objects.filter(id__in=ids).prefetch_related('members')}
    return JsonResponse({'grupos': [grupo_dados(por_id[i], seg_grupo, seg_membro) for i in ids if i in por_id]})


@require_POST
def alternar_view(request):
    """{group_id} segue/deixa o grupo; {member_id} segue/deixa o integrante."""
    participant = get_session_participant(request)
    if participant is None:
        return _precisa_entrar()
    try:
        body = json.loads(request.body or '{}')
    except ValueError:
        body = {}
    if body.get('member_id'):
        member = get_object_or_404(GroupMember.objects.select_related('group'), pk=body['member_id'])
        seguindo = alternar(participant, member.group, member)
        nome = member.name
    else:
        group = get_object_or_404(KpopGroup, pk=body.get('group_id') or 0)
        seguindo = alternar(participant, group)
        nome = group.name
    return JsonResponse({'success': True, 'seguindo': seguindo,
                         'message': f'Seguindo {nome}.' if seguindo else f'Você deixou de seguir {nome}.'})
