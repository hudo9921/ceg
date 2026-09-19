from django.core.management.base import BaseCommand
from apps.cegs.audit_service import AuditService


class Command(BaseCommand):
    help = "Executa o backfill completo de eventos históricos (participantes, claims, slots, pagamentos, pacotes) para o AuditLog."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Força reprocessamento de itens históricos.'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Iniciando backfill histórico de auditoria..."))

        stats = AuditService.backfill_historical_logs()

        self.stdout.write(self.style.SUCCESS("[OK] Backfill concluido com sucesso!"))
        self.stdout.write(f"  - Contas de participantes: {stats['accounts']}")
        self.stdout.write(f"  - Logs de tentativas de claim: {stats['claim_logs']}")
        self.stdout.write(f"  - Claims garantidos historicos: {stats['claims']}")
        self.stdout.write(f"  - Slots vinculados: {stats['slots_assigned']}")
        self.stdout.write(f"  - Compras Mercari vinculadas: {stats['mercari_assigned']}")
        self.stdout.write(f"  - Status de pagamentos quitados: {stats['payments']}")
        self.stdout.write(f"  - Pacotes nacionais (solicitacao/envio/entrega): {stats['packages']}")
        self.stdout.write(self.style.SUCCESS(f"Total de novos logs gerados: {stats['total']}"))
