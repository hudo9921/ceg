"""
Retenção de dados pessoais (LGPD). Rodar diariamente (cron no servidor):

    docker exec valcegs-web python manage.py purge_personal_data

- Apaga endereço/CEP/observações de pacotes ENTREGUES há mais de PII_RETENTION_DAYS.
- Apaga códigos OTP (com número de WhatsApp) com mais de OTP_RETENTION_DAYS.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone


class Command(BaseCommand):
    help = "Apaga dados pessoais vencidos conforme a política de retenção (LGPD)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Apenas mostra o que seria apagado.')

    def handle(self, *args, dry_run=False, **options):
        from apps.auth_otp.models import WhatsAppOTP
        from apps.cegs.models import PacoteNacional

        now = timezone.now()
        pii_cutoff = now - timedelta(days=settings.PII_RETENTION_DAYS)
        otp_cutoff = now - timedelta(days=settings.OTP_RETENTION_DAYS)

        pacotes = PacoteNacional.objects.filter(
            status=PacoteNacional.Status.ENTREGUE,
        ).filter(
            Q(data_entrega__lt=pii_cutoff) | Q(data_entrega__isnull=True, updated_at__lt=pii_cutoff)
        ).filter(
            ~Q(endereco_destinatario='') | ~Q(cep_destinatario='') | ~Q(observacoes_joiner='')
        )
        otps = WhatsAppOTP.objects.filter(created_at__lt=otp_cutoff)

        n_pacotes, n_otps = pacotes.count(), otps.count()
        if not dry_run:
            # update() não chama save(): passamos '' (vazio não é criptografado), seguro.
            pacotes.update(endereco_destinatario='', cep_destinatario='', observacoes_joiner='')
            otps.delete()

        prefix = '[dry-run] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Endereços apagados de {n_pacotes} pacote(s) entregue(s) há mais de "
            f"{settings.PII_RETENTION_DAYS} dias; {n_otps} código(s) OTP antigo(s) removido(s)."
        ))
