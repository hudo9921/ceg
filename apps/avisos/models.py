"""
Inscrição de push (S4, docs/SITE_ONLY_PLAN.md): um navegador/celular que aceitou receber notificações.
Pertence a um joiner (avisos de /me/) ou a alguém da equipe de um GOM (avisos do painel). Sem dados pessoais além
do endereço que o próprio navegador gera (endpoint + chaves de criptografia).
"""
from django.conf import settings
from django.db import models


class Inscricao(models.Model):
    participant = models.ForeignKey('participants.Participant', on_delete=models.CASCADE, null=True, blank=True,
                                    related_name='inscricoes_push')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                             related_name='inscricoes_push')
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    aparelho = models.CharField('Aparelho', max_length=120, blank=True)
    criada_em = models.DateTimeField(auto_now_add=True)
    ultimo_envio = models.DateTimeField(null=True, blank=True)
    falhas = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Inscrição de notificação'
        verbose_name_plural = 'Inscrições de notificação'

    def __str__(self):
        return f'{self.participant or self.user} · {self.aparelho or "navegador"}'

    def como_webpush(self):
        return {'endpoint': self.endpoint, 'keys': {'p256dh': self.p256dh, 'auth': self.auth}}
