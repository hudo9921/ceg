"""
Cobranças Pix (S1, docs/SITE_ONLY_PLAN.md): o joiner escolhe o que pagar, o site gera o Pix com o valor exato e uma
referência, o joiner avisa "Já paguei" e o GOM confirma com "Recebi". Uma cobrança = um GOM e uma chave Pix.
"""
import secrets

from django.conf import settings
from django.db import models

from apps.goms.scoping import scoped_manager

REF_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # sem 0/O/1/I para ditar sem erro


def new_reference():
    return 'VC-' + ''.join(secrets.choice(REF_ALPHABET) for _ in range(5))


class Cobranca(models.Model):
    class Status(models.TextChoices):
        AGUARDANDO = 'AGUARDANDO', 'Pix gerado'
        INFORMADA = 'INFORMADA', 'Joiner avisou que pagou'
        CONFIRMADA = 'CONFIRMADA', 'Recebida'
        RECUSADA = 'RECUSADA', 'Não recebida'
        CANCELADA = 'CANCELADA', 'Cancelada'

    OPEN = (Status.AGUARDANDO, Status.INFORMADA, Status.RECUSADA)

    gom = models.ForeignKey('goms.Gom', on_delete=models.PROTECT, related_name='cobrancas', verbose_name='GOM')
    participant = models.ForeignKey('participants.Participant', on_delete=models.PROTECT, related_name='cobrancas',
                                    verbose_name='Joiner')
    referencia = models.CharField('Referência', max_length=12, unique=True, default=new_reference)
    chave_pix = models.CharField('Chave Pix', max_length=120)
    valor_total = models.DecimalField('Valor', max_digits=10, decimal_places=2)
    copia_e_cola = models.TextField('Pix copia e cola')
    status = models.CharField('Situação', max_length=12, choices=Status.choices, default=Status.AGUARDANDO,
                              db_index=True)
    recado = models.CharField('Recado do GOM', max_length=255, blank=True)
    criada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', help_text='Equipe que gerou para um joiner fora do site.')
    criada_em = models.DateTimeField('Gerada em', auto_now_add=True, db_index=True)
    informada_em = models.DateTimeField('Joiner avisou em', null=True, blank=True)
    resolvida_em = models.DateTimeField('Confirmada/recusada em', null=True, blank=True)
    resolvida_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='+')
    objects = scoped_manager('gom')

    class Meta:
        verbose_name = 'Cobrança Pix'
        verbose_name_plural = 'Cobranças Pix'
        ordering = ['-criada_em']

    def __str__(self):
        return f'{self.referencia} · {self.participant} · R$ {self.valor_total}'

    @property
    def is_open(self):
        return self.status in self.OPEN


class CobrancaLinha(models.Model):
    """O que a cobrança paga: uma unidade (vaga, item avulso ou pacote) e o tipo (item, frete, taxa, nacional)."""

    class Tipo(models.TextChoices):
        ITEM = 'item', 'Item'
        FRETE = 'frete', 'Frete internacional'
        TAXA = 'taxa', 'Taxa aduaneira'
        NACIONAL = 'frete_nacional', 'Frete nacional'

    cobranca = models.ForeignKey(Cobranca, on_delete=models.CASCADE, related_name='linhas')
    tipo = models.CharField(max_length=16, choices=Tipo.choices)
    descricao = models.CharField(max_length=200)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    slot = models.ForeignKey('cegs.ItemSlot', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    item_individual = models.ForeignKey('cegs.ItemIndividual', on_delete=models.CASCADE, null=True, blank=True,
                                        related_name='+')
    pacote = models.ForeignKey('cegs.PacoteNacional', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    reserva_vitrine = models.ForeignKey('conversas.ReservaVitrine', on_delete=models.CASCADE, null=True, blank=True,
                                        related_name='+')

    class Meta:
        verbose_name = 'Linha da cobrança'
        verbose_name_plural = 'Linhas da cobrança'

    def __str__(self):
        return f'{self.get_tipo_display()} · {self.descricao}'

    @property
    def unit_key(self):
        """Identifica a unidade + tipo (a mesma unidade não entra em duas cobranças abertas)."""
        target = (f'slot:{self.slot_id}' if self.slot_id else
                  f'avulso:{self.item_individual_id}' if self.item_individual_id else
                  f'vitrine:{self.reserva_vitrine_id}' if self.reserva_vitrine_id else f'pacote:{self.pacote_id}')
        return f'{self.tipo}:{target}'


class Comprovante(models.Model):
    """Comprovante enviado pelo joiner. Fica no banco (dado financeiro não vai para a mídia pública)."""
    cobranca = models.OneToOneField(Cobranca, on_delete=models.CASCADE, related_name='comprovante')
    conteudo = models.BinaryField()
    content_type = models.CharField(max_length=40)
    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Comprovante'
