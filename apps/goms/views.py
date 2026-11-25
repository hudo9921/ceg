"""Backoffice de GOMs: login, convites, equipe, seletor de GOM e GOMs da plataforma."""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.participants.session_auth import safe_next_url

from .access import (
    ACTIVE_GOM_SESSION_KEY, accessible_goms, get_active_gom, gom_member_required, gom_owner_required,
    gom_role, has_gom_perm, is_gom_member, is_platform_admin, platform_admin_required,
)
from .forms import GomCreateForm, InviteForm, InviteSignupForm, _style
from .models import Gom, GomInvite, GomMembership
from .services import (
    TeamRuleError, accept_invite, change_role, create_gom, remove_member, revoke_invite, set_permissions,
)


def invite_link(request, token):
    return request.build_absolute_uri(reverse('gom_invite_accept', args=[token]))


class BackofficeLoginView(LoginView):
    """Login com senha da equipe (staff e membros de GOM). Em seguida vem o 2FA."""
    template_name = 'goms/login.html'
    redirect_authenticated_user = True

    def get_form(self, form_class=None):
        return _style(super().get_form(form_class))

    def get_default_redirect_url(self):
        return reverse('backoffice_home')


@never_cache
def backoffice_home(request):
    """Início do painel (P5): tarefas de hoje e números do mês, conforme as permissões do admin."""
    from apps.core.permissions import check_staff

    from .access import gom_permissions
    from .dashboard import build_dashboard
    from .permissions import ANY

    user = request.user
    if not user.is_authenticated:
        return redirect('backoffice_login')
    if not (user.is_superuser or is_gom_member(user)):
        raise PermissionDenied('Esta conta não faz parte da equipe de nenhum GOM.')
    if is_platform_admin(user) and get_active_gom(request) is None:
        return redirect('platform_goms')  # a plataforma escolhe o GOM antes de abrir um painel
    denied = check_staff(request, ANY)
    if denied is not None:
        return denied
    context = build_dashboard(request, gom_permissions(request))
    context['today'] = timezone.localtime()
    return render(request, 'goms/inicio.html', context)


@never_cache
@require_http_methods(['GET', 'POST'])
def invite_accept(request, token):
    invite = GomInvite.find_pending(token)
    if invite is None:
        return render(request, 'goms/invite_accept.html', {'invalid': True}, status=404)

    user = request.user if request.user.is_authenticated else None
    form = None if user else InviteSignupForm(request.POST or None)
    if request.method == 'POST':
        if user is None and form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        if user is not None:
            try:
                accept_invite(invite.pk, user)
            except TeamRuleError as exc:
                messages.error(request, str(exc))
                return redirect('home')
            request.session[ACTIVE_GOM_SESSION_KEY] = invite.gom_id
            messages.success(request, f'Bem-vindo(a) à equipe {invite.gom.name}! Ative a verificação em duas etapas.')
            return redirect('backoffice_home')  # o middleware de 2FA pede o cadastro antes
    return render(request, 'goms/invite_accept.html', {'invite': invite, 'form': form})


@require_POST
def switch_gom(request):
    if not request.user.is_authenticated:
        return redirect('backoffice_login')
    if not accessible_goms(request.user):
        raise PermissionDenied('Esta conta não faz parte da equipe de nenhum GOM.')
    wanted = request.POST.get('gom_id', '')
    if wanted == '' and is_platform_admin(request.user):
        old = get_active_gom(request)
        request.session.pop(ACTIVE_GOM_SESSION_KEY, None)
        if old is not None:
            messages.success(request, f'Você saiu do painel de {old.name}.')
        return redirect('platform_goms')
    gom = next((g for g in accessible_goms(request.user) if str(g.id) == wanted), None)
    if gom is not None:
        request.session[ACTIVE_GOM_SESSION_KEY] = gom.id
        messages.success(request, f'Agora você está atuando em {gom.name}.')
    return redirect(safe_next_url(request, request.POST.get('next'), reverse('backoffice_home')))


@never_cache
@gom_member_required
@require_http_methods(['GET', 'POST'])
def team(request):
    gom = request.active_gom
    is_owner = gom_role(request.user, gom) == GomMembership.Role.OWNER
    form, new_link = InviteForm(), None
    if request.method == 'POST':
        if not is_owner:
            messages.error(request, 'Só o GOM principal gerencia a equipe.')
            return redirect('gom_team')
        if request.POST.get('action') != 'invite':
            _handle_member_action(request, gom)
            return redirect('gom_team')
        form = InviteForm(request.POST)
        if form.is_valid():
            _invite, token = GomInvite.create_with_token(
                gom=gom, role=form.cleaned_data['role'], name=form.cleaned_data['name'],
                created_by=request.user, permissions=form.invite_permissions())
            new_link, form = invite_link(request, token), InviteForm()
    memberships = list(gom.memberships.filter(is_active=True)
                       .select_related('user', 'permissions_updated_by').order_by('-role', 'user__username'))
    return render(request, 'goms/team.html', {
        'gom': gom,
        'is_owner': is_owner,
        'memberships': memberships,
        'team_data': _team_data(request, memberships, is_owner),
        'invites': gom.invites.pending(),
        'form': form,
        'new_link': new_link,
        'roles': GomMembership.Role.choices,
    })


def _team_data(request, memberships, is_owner):
    """Dados da tela de equipe (Alpine): membros, catálogo de permissões e modelos."""
    from django.utils import timezone

    from . import permissions as perms

    members = []
    for m in memberships:
        changed = ''
        if m.permissions_updated_at:
            who = m.permissions_updated_by.get_username() if m.permissions_updated_by else 'alguém'
            changed = f"{who} em {timezone.localtime(m.permissions_updated_at):%d/%m às %H:%M}"
        members.append({
            'id': m.id, 'name': m.user.get_username(), 'is_owner': m.is_owner, 'is_me': m.user_id == request.user.id,
            'since': f'{timezone.localtime(m.created_at):%d/%m/%Y}', 'perms': sorted(perms.membership_permissions(m)),
            'changed': changed,
        })
    return {
        'can_edit': is_owner,
        'members': members,
        'areas': perms.areas(),
        'presets': [{'key': k, 'name': v[0], 'help': v[1], 'perms': v[2]} for k, v in perms.PRESETS.items()],
        'total': len(perms.ALL),
        'menu': [{'name': name, 'perms': keys} for name, keys in perms.MENU],
    }


def _handle_member_action(request, gom):
    """Cancelar convite, trocar papel ou remover membro (só o dono chega aqui)."""
    action = request.POST.get('action')
    try:
        if action == 'revoke':
            revoke_invite(get_object_or_404(GomInvite, pk=request.POST.get('invite_id'), gom=gom), request.user)
            messages.success(request, 'Convite cancelado.')
        elif action in ('role', 'remove', 'perms'):
            membership = get_object_or_404(GomMembership, pk=request.POST.get('membership_id'),
                                           gom=gom, is_active=True)
            if action == 'perms':
                set_permissions(membership, request.POST.getlist('perms'), request.user)
                messages.success(request, f'Permissões de {membership.user.get_username()} salvas.')
            elif action == 'role':
                change_role(membership, request.POST.get('role'), request.user)
                messages.success(request, 'Papel atualizado.')
            else:
                remove_member(membership, request.user)
                messages.success(request, f'{membership.user.get_username()} saiu da equipe.')
    except TeamRuleError as exc:
        messages.error(request, str(exc))


@never_cache
@platform_admin_required
@require_http_methods(['GET', 'POST'])
def platform_goms(request):
    form = GomCreateForm(request.POST or None)
    new_link = None
    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        if action == 'create' and form.is_valid():
            try:
                gom, token = create_gom(name=form.cleaned_data['name'], slug=form.cleaned_data['slug'],
                                        created_by=request.user)
                new_link = invite_link(request, token)
                messages.success(request, f'GOM {gom.name} criado. Envie o link ao GOM principal.')
                form = GomCreateForm()
            except TeamRuleError as exc:
                messages.error(request, str(exc))
        elif action in ('owner_invite', 'toggle'):
            gom = get_object_or_404(Gom, pk=request.POST.get('gom_id'))
            if action == 'owner_invite':
                _invite, token = GomInvite.create_with_token(
                    gom=gom, role=GomMembership.Role.OWNER, name='GOM principal', created_by=request.user)
                new_link = invite_link(request, token)
            else:
                gom.is_active = not gom.is_active
                gom.save(update_fields=['is_active'])
                messages.success(request, f'{gom.name} {"ativado" if gom.is_active else "desativado"}.')
                return redirect('platform_goms')
    from django.db.models import Count, Q
    goms = Gom.objects.prefetch_related('memberships__user').annotate(
        cegs_total=Count('cegs', distinct=True),
        cegs_abertas=Count('cegs', filter=Q(cegs__status='OPEN'), distinct=True),
        membros=Count('memberships', filter=Q(memberships__is_active=True), distinct=True),
    ).order_by('name')
    from apps.participants.models import Claim

    pend = dict(Claim.objects.filter(status=Claim.Status.PENDING).order_by().values_list('slot__set__ceg__gom_id').annotate(n=Count('id')))
    joiners = dict(Claim.objects.order_by().values_list('slot__set__ceg__gom_id').annotate(n=Count('participant', distinct=True)))
    goms = list(goms)
    for g in goms:
        g.a_pagar, g.joiners = pend.get(g.id, 0), joiners.get(g.id, 0)
    return render(request, 'goms/platform_goms.html', {'goms': goms, 'form': form, 'new_link': new_link,
                                                       'is_platform_admin': is_platform_admin(request.user)})


def gom_public_page(request, slug):
    """Página pública do GOM (/gom/<slug>/): perfil, CEGs abertas/agendadas e pronta entrega."""
    from django.db.models import Q
    from django.utils import timezone

    from apps.cegs.models import CEG, ItemVitrine
    from apps.cegs.services import enrich_cegs_with_availability

    gom = get_object_or_404(Gom, slug=slug, is_active=True)
    now = timezone.now()
    base = CEG.objects.for_gom(gom).select_related('era__group')
    abertas = list(base.filter(Q(status=CEG.Status.OPEN) | Q(status=CEG.Status.SCHEDULED, opens_at__lte=now))
                   .order_by('-created_at'))
    agendadas = list(base.filter(status=CEG.Status.SCHEDULED, opens_at__gt=now).order_by('opens_at'))
    enrich_cegs_with_availability(abertas + agendadas)
    vitrine = list(ItemVitrine.objects.for_gom(gom).filter(status=ItemVitrine.Status.DISPONIVEL)
                   .order_by('-destaque', '-created_at')[:12])
    return render(request, 'goms/public_page.html', {
        'gom': gom, 'abertas': abertas, 'agendadas': agendadas, 'vitrine': vitrine,
    })


@never_cache
@gom_member_required
@require_http_methods(['GET', 'POST'])
def gom_profile(request):
    """Perfil do GOM ativo: página pública, contatos e chave Pix padrão (dono e admins)."""
    from apps.cegs.image_utils import ImageSizeError, process_image_upload

    from .forms import GomProfileForm

    gom = request.active_gom
    can_profile, can_pix = has_gom_perm(request, 'gom.perfil'), has_gom_perm(request, 'pix.alterar')
    if not (can_profile or can_pix):
        raise PermissionDenied('Sem permissão para isso. Fale com o dono do GOM.')
    form = GomProfileForm(request.POST or None, instance=gom, can_edit_profile=can_profile, can_edit_pix=can_pix)
    context = {'gom': gom, 'form': form, 'can_edit_profile': can_profile, 'can_edit_pix': can_pix}
    if request.method == 'POST' and form.is_valid():
        profile = form.save(commit=False)
        try:
            for field, folder in (('logo', 'goms/logos'), ('banner', 'goms/banners')):
                upload = request.FILES.get(f'{field}_file')
                if upload and can_profile:
                    setattr(profile, f'{field}_url', process_image_upload(file_obj=upload, folder=folder))
        except ImageSizeError as exc:
            messages.error(request, str(exc))
            return render(request, 'goms/profile.html', context)
        profile.save()
        messages.success(request, 'Perfil do GOM atualizado.')
        return redirect('gom_profile')
    return render(request, 'goms/profile.html', context)
