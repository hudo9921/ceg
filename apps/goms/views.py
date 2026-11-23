"""Backoffice de GOMs: login, convites, equipe, seletor de GOM e GOMs da plataforma."""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from apps.participants.session_auth import safe_next_url

from .access import (
    ACTIVE_GOM_SESSION_KEY, accessible_goms, gom_member_required, gom_owner_required,
    gom_role, is_gom_member, is_platform_admin, platform_admin_required,
)
from .forms import GomCreateForm, InviteForm, InviteSignupForm, _style
from .models import Gom, GomInvite, GomMembership
from .services import (
    TeamRuleError, accept_invite, change_role, create_gom, remove_member, revoke_invite,
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
    """Primeira tela depois do login, conforme o papel."""
    user = request.user
    if not user.is_authenticated:
        return redirect('backoffice_login')
    if user.is_staff or user.is_superuser:
        return redirect('creations_hub')
    if is_gom_member(user):
        return redirect('gom_team')
    raise PermissionDenied('Esta conta não faz parte da equipe de nenhum GOM.')


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
                created_by=request.user)
            new_link, form = invite_link(request, token), InviteForm()
    return render(request, 'goms/team.html', {
        'gom': gom,
        'is_owner': is_owner,
        'memberships': gom.memberships.filter(is_active=True).select_related('user'),
        'invites': gom.invites.pending(),
        'form': form,
        'new_link': new_link,
        'roles': GomMembership.Role.choices,
    })


def _handle_member_action(request, gom):
    """Cancelar convite, trocar papel ou remover membro (só o dono chega aqui)."""
    action = request.POST.get('action')
    try:
        if action == 'revoke':
            revoke_invite(get_object_or_404(GomInvite, pk=request.POST.get('invite_id'), gom=gom), request.user)
            messages.success(request, 'Convite cancelado.')
        elif action in ('role', 'remove'):
            membership = get_object_or_404(GomMembership, pk=request.POST.get('membership_id'),
                                           gom=gom, is_active=True)
            if action == 'role':
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
    goms = Gom.objects.prefetch_related('memberships__user').order_by('name')
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
