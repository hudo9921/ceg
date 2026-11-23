"""
GOMs: organizadores que vendem na plataforma (ver docs/MULTI_GOM_DESIGN.md).

- `Gom`: a organização (ValCegs é a primeira).
- `GomMembership`: quem trabalha em qual GOM e com qual papel (dono ou admin).
- `GomInvite`: convite de uso único, por link, para entrar na equipe de um GOM.
"""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

INVITE_VALID_DAYS = 7


class Gom(models.Model):
    name = models.CharField('Nome', max_length=80)
    slug = models.SlugField('Endereço da página', max_length=60, unique=True,
                            help_text='Usado em /gom/<slug>/.')
    logo_url = models.URLField('Logo', max_length=500, blank=True)
    banner_url = models.URLField('Banner', max_length=500, blank=True)
    bio = models.TextField('Apresentação', blank=True)
    whatsapp_contato = models.CharField('WhatsApp de contato', max_length=30, blank=True)
    instagram = models.CharField('Instagram / X', max_length=60, blank=True)
    default_pix_key = models.CharField('Chave Pix padrão', max_length=255, blank=True,
                                       help_text='Pré-preenche CEGs novas.')
    default_pix_instructions = models.TextField('Instruções Pix padrão', blank=True)
    is_active = models.BooleanField('Ativo', default=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        verbose_name = 'GOM'
        verbose_name_plural = 'GOMs'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:60] or 'gom'
        super().save(*args, **kwargs)


class GomMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = 'OWNER', 'GOM principal (dono)'
        ADMIN = 'ADMIN', 'Admin de GOM'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='gom_memberships')
    gom = models.ForeignKey(Gom, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField('Papel', max_length=10, choices=Role.choices, default=Role.ADMIN)
    is_active = models.BooleanField('Ativo', default=True)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField('Desde', auto_now_add=True)

    class Meta:
        verbose_name = 'Membro de GOM'
        verbose_name_plural = 'Membros de GOM'
        constraints = [models.UniqueConstraint(fields=['user', 'gom'], name='uniq_membership_user_gom')]
        ordering = ['gom', 'role', 'user__username']

    def __str__(self):
        return f'{self.user} — {self.gom} ({self.get_role_display()})'

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class GomInviteQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now())


class GomInvite(models.Model):
    """Convite por link. Só o hash do token fica no banco; o link aparece uma única vez."""
    gom = models.ForeignKey(Gom, on_delete=models.CASCADE, related_name='invites')
    role = models.CharField('Papel', max_length=10, choices=GomMembership.Role.choices,
                            default=GomMembership.Role.ADMIN)
    name = models.CharField('Para quem', max_length=80, blank=True)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField('Expira em')
    accepted_at = models.DateTimeField('Aceito em', null=True, blank=True)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='+')
    revoked_at = models.DateTimeField('Cancelado em', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = GomInviteQuerySet.as_manager()

    class Meta:
        verbose_name = 'Convite de GOM'
        verbose_name_plural = 'Convites de GOM'
        ordering = ['-created_at']

    def __str__(self):
        return f'Convite {self.get_role_display()} — {self.gom}'

    @classmethod
    def create_with_token(cls, *, gom, role, name='', created_by=None):
        """Cria o convite e devolve (convite, token). O token não é recuperável depois."""
        token = secrets.token_urlsafe(32)
        invite = cls.objects.create(
            gom=gom, role=role, name=name, created_by=created_by,
            token_hash=_hash_token(token),
            expires_at=timezone.now() + timedelta(days=INVITE_VALID_DAYS),
        )
        return invite, token

    @classmethod
    def find_pending(cls, token: str):
        if not token:
            return None
        return cls.objects.pending().select_related('gom').filter(token_hash=_hash_token(token)).first()

    @property
    def status(self):
        if self.accepted_at:
            return 'aceito'
        if self.revoked_at:
            return 'cancelado'
        if self.expires_at <= timezone.now():
            return 'expirado'
        return 'pendente'
