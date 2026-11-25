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
    # Chaves Pix padrão por tipo de cobrança. Usadas quando a CEG/caixa não tem chave própria
    # (hierarquia em docs/BUSINESS_RULES.md §1). Frete/taxa/frete nacional vazios = usa a de itens.
    default_pix_key = models.CharField('Chave Pix padrão — itens', max_length=255, blank=True,
                                       help_text='Pagamento dos itens das CEGs sem chave própria.')
    default_pix_instructions = models.TextField('Instruções — itens', blank=True)
    default_pix_key_frete = models.CharField('Chave Pix padrão — frete internacional', max_length=255, blank=True)
    default_pix_instructions_frete = models.TextField('Instruções — frete internacional', blank=True)
    default_pix_key_taxa = models.CharField('Chave Pix padrão — taxa aduaneira', max_length=255, blank=True)
    default_pix_instructions_taxa = models.TextField('Instruções — taxa aduaneira', blank=True)
    default_pix_key_frete_nacional = models.CharField('Chave Pix padrão — frete nacional', max_length=255, blank=True)
    default_pix_instructions_frete_nacional = models.TextField('Instruções — frete nacional', blank=True)
    # Regras do GOM (C1, docs/GOM_CUSTOMIZATION_PLAN.md): só quem nunca participou do GOM precisa aceitar.
    regras = models.TextField('Regras do GOM', blank=True,
                              help_text='Cancelamento, prazos, o que acontece sem pagamento, caixinha…')
    regras_atualizadas_em = models.DateTimeField('Regras atualizadas em', null=True, blank=True)
    # Padrões de CEG (C2): só pré-preenchem o Criar; CEGs já criadas não mudam.
    padrao_prazo_item_dias = models.PositiveSmallIntegerField(
        'Prazo para pagar o item (dias depois do fechamento)', null=True, blank=True,
        help_text='Conta a partir do encerramento da CEG. Em branco: sem prazo automático.')
    padrao_horario_abertura = models.TimeField('Horário de abertura sugerido', null=True, blank=True,
                                               help_text='Nova CEG já vem marcada para amanhã neste horário.')
    padrao_descricao = models.TextField('Modelo de descrição', blank=True,
                                        help_text='Use {grupo} e {era}: viram o grupo e a era escolhidos.')
    padrao_caixa_aberta = models.BooleanField('Vincular à caixa aberta mais recente', default=False)
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

    PIX_KINDS = ('item', 'frete', 'taxa', 'frete_nacional')

    def pix_for(self, kind: str) -> tuple[str, str]:
        """(chave, instruções) padrão do GOM para o tipo; sem chave específica, usa a de itens."""
        if kind not in self.PIX_KINDS:
            raise ValueError(f'Tipo de Pix desconhecido: {kind}')
        suffix = '' if kind == 'item' else f'_{kind}'
        key = getattr(self, f'default_pix_key{suffix}')
        if key:
            return key, getattr(self, f'default_pix_instructions{suffix}')
        return self.default_pix_key, self.default_pix_instructions


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
    # Permissões do admin (apps.goms.permissions). None = acesso completo (admins antigos).
    permissions = models.JSONField('Permissões', null=True, blank=True, default=None)
    permissions_updated_at = models.DateTimeField('Permissões alteradas em', null=True, blank=True)
    permissions_updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                               null=True, blank=True, related_name='+')

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
    # Permissões iniciais do admin convidado (ignoradas para dono).
    permissions = models.JSONField('Permissões', null=True, blank=True, default=None)
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
    def create_with_token(cls, *, gom, role, name='', created_by=None, permissions=None):
        """Cria o convite e devolve (convite, token). O token não é recuperável depois."""
        token = secrets.token_urlsafe(32)
        invite = cls.objects.create(
            gom=gom, role=role, name=name, created_by=created_by, permissions=permissions,
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


class AceiteRegras(models.Model):
    """Aceite das regras de um GOM por um joiner (uma vez; quem já participou nunca é barrado)."""
    participant = models.ForeignKey('participants.Participant', on_delete=models.CASCADE,
                                    related_name='aceites_regras', verbose_name='Joiner')
    gom = models.ForeignKey(Gom, on_delete=models.CASCADE, related_name='aceites_regras')
    aceito_em = models.DateTimeField('Aceito em', auto_now_add=True)
    texto_hash = models.CharField('Hash do texto aceito', max_length=64, blank=True,
                                  help_text='SHA-256 das regras no momento do aceite (prova do que foi aceito).')

    class Meta:
        verbose_name = 'Aceite de regras'
        verbose_name_plural = 'Aceites de regras'
        constraints = [models.UniqueConstraint(fields=['participant', 'gom'], name='aceite_regras_unico')]

    def __str__(self):
        return f'{self.participant} aceitou as regras de {self.gom}'
