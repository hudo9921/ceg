"""
Repasse de item: o joiner passa a vaga (slot de CEG) para outra pessoa. Fluxo (docs/BUSINESS_RULES.md, "Repasse"):

- Para uma pessoa: A informa o WhatsApp de B → B aceita em /me/ → o GOM aprova → a vaga passa para B.
- Público: A deixa a vaga "disponível para repasse" → quem quiser pede (o pedido já é o aceite) → o GOM aprova.
  Se o GOM recusar quem pediu, a vaga volta a ficar disponível.
- O que ainda falta pagar (item, frete, taxa) vai junto. Acerto de dinheiro entre A e B é com eles.
Nada muda sem o GOM aprovar.
"""
from django.conf import settings
from django.db import models

from apps.goms.scoping import scoped_manager


class Repasse(models.Model):
    class Status(models.TextChoices):
        DISPONIVEL = 'DISPONIVEL', 'Disponível para quem quiser'
        AGUARDANDO_ACEITE = 'AGUARDANDO_ACEITE', 'Esperando a pessoa aceitar'
        AGUARDANDO_GOM = 'AGUARDANDO_GOM', 'Esperando o GOM aprovar'
        APROVADO = 'APROVADO', 'Repassado'
        RECUSADO_GOM = 'RECUSADO_GOM', 'O GOM recusou'
        RECUSADO_PESSOA = 'RECUSADO_PESSOA', 'A pessoa recusou'
        CANCELADO = 'CANCELADO', 'Cancelado'

    ATIVOS = (Status.DISPONIVEL, Status.AGUARDANDO_ACEITE, Status.AGUARDANDO_GOM)

    gom = models.ForeignKey('goms.Gom', on_delete=models.CASCADE, related_name='repasses', verbose_name='GOM')
    slot = models.ForeignKey('cegs.ItemSlot', on_delete=models.CASCADE, related_name='repasses', verbose_name='Vaga')
    de = models.ForeignKey('participants.Participant', on_delete=models.CASCADE, related_name='repasses_feitos',
                           verbose_name='Quem repassa')
    para = models.ForeignKey('participants.Participant', on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='repasses_recebidos', verbose_name='Quem recebe')
    # B ainda sem conta: guarda o número; quando B entrar com ele, vê o pedido.
    para_whatsapp = models.CharField('WhatsApp de quem recebe', max_length=30, blank=True, db_index=True)
    publico = models.BooleanField('Disponível para qualquer pessoa', default=False)
    recado = models.CharField('Recado', max_length=280, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, db_index=True)
    motivo = models.CharField('Motivo (recusa)', max_length=280, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    aceito_em = models.DateTimeField(null=True, blank=True)
    resolvido_em = models.DateTimeField(null=True, blank=True)
    resolvido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='+')
    objects = scoped_manager('gom')

    class Meta:
        verbose_name = 'Repasse'
        ordering = ['-criado_em']
        constraints = [
            models.UniqueConstraint(fields=['slot'], condition=models.Q(status__in=['DISPONIVEL', 'AGUARDANDO_ACEITE',
                                                                                     'AGUARDANDO_GOM']),
                                    name='repasse_um_ativo_por_vaga'),
        ]

    def __str__(self):
        return f'Repasse #{self.pk} · {self.slot_id} · {self.get_status_display()}'

    @property
    def ativo(self):
        return self.status in self.ATIVOS
