"""Regras da equipe de um GOM: convites, papéis e remoção (sempre deixando um dono)."""
import logging

from django.utils.text import slugify

from django.db import transaction
from django.utils import timezone

from .models import Gom, GomInvite, GomMembership

security_logger = logging.getLogger('security')

RESERVED_SLUGS = {'equipe', 'trocar', 'entrar', 'convite', 'plataforma', 'admin', 'painel', 'novo'}


class TeamRuleError(ValueError):
    """Ação de equipe que deixaria o GOM sem dono ou é inválida."""


def _active_owner_count(gom, exclude_membership=None):
    qs = GomMembership.objects.filter(gom=gom, role=GomMembership.Role.OWNER, is_active=True)
    if exclude_membership is not None:
        qs = qs.exclude(pk=exclude_membership.pk)
    return qs.count()


def create_gom(*, name, slug, created_by):
    """Cria o GOM e o convite do dono. Devolve (gom, token do convite)."""
    name = (name or '').strip()
    if not name:
        raise TeamRuleError('Informe o nome do GOM.')
    slug = slugify((slug or '').strip() or name)[:60]
    if not slug or slug in RESERVED_SLUGS:
        raise TeamRuleError(f'O endereço "{slug}" é reservado. Escolha outro.')
    if Gom.objects.filter(slug=slug).exists():
        raise TeamRuleError(f'Já existe um GOM com o endereço "{slug}".')
    with transaction.atomic():
        gom = Gom.objects.create(name=name, slug=slug)
        _invite, token = GomInvite.create_with_token(
            gom=gom, role=GomMembership.Role.OWNER, name='GOM principal', created_by=created_by)
    security_logger.info("GOM criado: %s (por %s)", gom.slug, created_by)
    return gom, token


def accept_invite(invite_id, user):
    """Aceita o convite (uso único) e cria ou reativa o vínculo do usuário."""
    with transaction.atomic():
        invite = GomInvite.objects.select_for_update().select_related('gom').get(pk=invite_id)
        if invite.status != 'pendente':
            raise TeamRuleError('Este convite não é mais válido.')
        membership, created = GomMembership.objects.get_or_create(
            user=user, gom=invite.gom,
            defaults={'role': invite.role, 'invited_by': invite.created_by})
        if not created:
            # Reentrada de quem tinha saído; nunca rebaixa um dono por convite de admin.
            membership.is_active = True
            if invite.role == GomMembership.Role.OWNER:
                membership.role = GomMembership.Role.OWNER
            membership.save(update_fields=['is_active', 'role'])
        invite.accepted_at = timezone.now()
        invite.accepted_by = user
        invite.save(update_fields=['accepted_at', 'accepted_by'])
    security_logger.info("Convite aceito: %s entrou em %s como %s",
                         user.get_username(), invite.gom.slug, membership.role)
    return membership


def change_role(membership, new_role, actor):
    if new_role not in GomMembership.Role.values:
        raise TeamRuleError('Papel inválido.')
    if (membership.role == GomMembership.Role.OWNER and new_role != GomMembership.Role.OWNER
            and _active_owner_count(membership.gom, exclude_membership=membership) == 0):
        raise TeamRuleError('O GOM precisa de pelo menos um GOM principal.')
    membership.role = new_role
    membership.save(update_fields=['role'])
    security_logger.info("Papel alterado: %s em %s -> %s (por %s)", membership.user.get_username(),
                         membership.gom.slug, new_role, actor.get_username())


def remove_member(membership, actor):
    if (membership.role == GomMembership.Role.OWNER
            and _active_owner_count(membership.gom, exclude_membership=membership) == 0):
        raise TeamRuleError('Não é possível remover o único GOM principal.')
    membership.is_active = False
    membership.save(update_fields=['is_active'])
    security_logger.info("Membro removido: %s de %s (por %s)", membership.user.get_username(),
                         membership.gom.slug, actor.get_username())


def revoke_invite(invite, actor):
    if invite.status == 'pendente':
        invite.revoked_at = timezone.now()
        invite.save(update_fields=['revoked_at'])
        security_logger.info("Convite cancelado em %s (por %s)", invite.gom.slug, actor.get_username())
