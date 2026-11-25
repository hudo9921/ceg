"""
Conversas entre joiner e GOM (S5, docs/SITE_ONLY_PLAN.md): substituem o "chama no WhatsApp".
Uma conversa por assunto (geral, pacote, CEG ou item da Vitrine) entre um joiner e um GOM.
"""
from django.conf import settings
from django.db import models

from apps.goms.scoping import scoped_manager


class Conversa(models.Model):
    class Tipo(models.TextChoices):
        GERAL = 'geral', 'Geral'
        PACOTE = 'pacote', 'Pacote'
        CEG = 'ceg', 'CEG'
        VITRINE = 'vitrine', 'Vitrine'

    gom = models.ForeignKey('goms.Gom', on_delete=models.CASCADE, related_name='conversas', verbose_name='GOM')
    participant = models.ForeignKey('participants.Participant', on_delete=models.CASCADE, related_name='conversas',
                                    verbose_name='Joiner')
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.GERAL)
    pacote = models.ForeignKey('cegs.PacoteNacional', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    ceg = models.ForeignKey('cegs.CEG', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    item_vitrine = models.ForeignKey('cegs.ItemVitrine', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    assunto = models.CharField('Assunto', max_length=160)
    nao_lidas_joiner = models.PositiveIntegerField(default=0)
    nao_lidas_gom = models.PositiveIntegerField(default=0)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now_add=True, db_index=True)
    objects = scoped_manager('gom')

    class Meta:
        verbose_name = 'Conversa'
        ordering = ['-atualizada_em']

    def __str__(self):
        return f'{self.assunto} · {self.participant} ↔ {self.gom}'


class Mensagem(models.Model):
    class Autor(models.TextChoices):
        JOINER = 'joiner', 'Joiner'
        GOM = 'gom', 'GOM'
        SISTEMA = 'sistema', 'Aviso'

    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name='mensagens')
    autor = models.CharField(max_length=8, choices=Autor.choices)
    autor_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', help_text='Quem da equipe respondeu.')
    texto = models.TextField(max_length=2000)
    criada_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Mensagem'
        verbose_name_plural = 'Mensagens'
        ordering = ['criada_em', 'id']

    def __str__(self):
        return f'{self.get_autor_display()}: {self.texto[:40]}'


class ReservaVitrine(models.Model):
    """
    Reserva de uma unidade da Vitrine por um joiner (S5b): substitui o "Tenho interesse" no WhatsApp.
    O joiner paga pelo Pix em Pagar; o GOM cancela ou marca como pago na conversa da reserva. Nada é automático.
    """

    class Status(models.TextChoices):
        RESERVADA = 'RESERVADA', 'Reservada (falta pagar)'
        PAGA = 'PAGA', 'Paga'
        CANCELADA = 'CANCELADA', 'Cancelada'

    item = models.ForeignKey('cegs.ItemVitrine', on_delete=models.CASCADE, related_name='reservas')
    participant = models.ForeignKey('participants.Participant', on_delete=models.CASCADE, related_name='reservas_vitrine')
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RESERVADA, db_index=True)
    criada_em = models.DateTimeField(auto_now_add=True)
    resolvida_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Reserva da Vitrine'
        verbose_name_plural = 'Reservas da Vitrine'
        ordering = ['-criada_em']

    def __str__(self):
        return f'{self.item} · {self.participant} · {self.get_status_display()}'
