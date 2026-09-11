from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import User
from apps.groups.models import KpopGroup, Era
from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot
from apps.participants.models import Participant, Claim


class Command(BaseCommand):
    help = 'Popula o banco com dados de teste para grupos de K-pop, CEGs abertas e agendadas com countdown'

    def handle(self, *args, **options):
        self.stdout.write("Populando dados iniciais...")

        # 1. Superusuário Admin
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
            self.stdout.write(self.style.SUCCESS("Superusuário criado: login 'admin' | senha 'admin123'"))

        # 2. Grupos e Eras
        twice, _ = KpopGroup.objects.get_or_create(
            name='TWICE',
            defaults={
                'image_url': 'https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=600&auto=format&fit=crop',
                'description': 'Girl group sul-coreano de 9 integrantes da JYP Entertainment.'
            }
        )

        triples, _ = KpopGroup.objects.get_or_create(
            name='tripleS',
            defaults={
                'image_url': 'https://images.unsplash.com/photo-1470225620780-dba8ba36b745?w=600&auto=format&fit=crop',
                'description': 'Girl group revolucionário de 24 integrantes com formato flexível de units.'
            }
        )

        era_twice, _ = Era.objects.get_or_create(
            group=twice,
            name='With YOU-th',
            defaults={
                'release_date': timezone.now().date() - timedelta(days=60),
                'description': '13º Mini Álbum com as faixas ONE SPARK e I GOT YOU.'
            }
        )

        era_triples, _ = Era.objects.get_or_create(
            group=triples,
            name='ASSEMBLE24',
            defaults={
                'release_date': timezone.now().date() - timedelta(days=20),
                'description': 'Primeiro álbum de estúdio completo com todas as 24 integrantes juntas.'
            }
        )

        # 3. CEG 1: TWICE (Aberta para reservas)
        ceg_twice, _ = CEG.objects.get_or_create(
            slug='ceg-pob-makestar-with-you-th',
            defaults={
                'era': era_twice,
                'title': 'CEG POB Makestar 2.0 — With YOU-th',
                'description': (
                    "Regras da CEG:\n"
                    "1. Cada slot reservado garante o photocard oficial de pré-venda (POB Makestar).\n"
                    "2. Frete internacional (EMS) e taxas alfandegárias inclusas no rateio.\n"
                    "3. O pagamento do slot deve ser feito via Pix em até 24 horas após a reserva."
                ),
                'pix_key': 'ceg.twice@kpopbrasil.com.br',
                'pix_instructions': 'Chave Pix (E-mail). Por favor enviar comprovante no WhatsApp com seu nome e integrante.',
                'status': CEG.Status.OPEN,
                'opens_at': timezone.now() - timedelta(days=1),
                'closes_at': timezone.now() + timedelta(days=15),
            }
        )

        twice_members = ['Nayeon', 'Jeongyeon', 'Momo', 'Sana', 'Jihyo', 'Mina', 'Dahyun', 'Chaeyoung', 'Tzuyu']
        for i, member in enumerate(twice_members, 1):
            CEGItemDefinition.objects.get_or_create(
                ceg=ceg_twice,
                name=f'Photocard POB {member}',
                defaults={
                    'member_name': member,
                    'item_type': CEGItemDefinition.ItemType.POB,
                    'default_price': 45.00,
                    'order_index': i
                }
            )

        # Adiciona também uma inclusão avulsa para demonstrar flexibilidade
        CEGItemDefinition.objects.get_or_create(
            ceg=ceg_twice,
            name='Álbum Selado (Sem POB)',
            defaults={
                'member_name': '',
                'item_type': CEGItemDefinition.ItemType.ALBUM,
                'default_price': 120.00,
                'order_index': 10
            }
        )

        # Cria Sets para o TWICE
        set1, _ = CEGSet.objects.get_or_create(ceg=ceg_twice, set_number=1, defaults={'notes': 'Set 1 - Pedido Principal'})
        set2, _ = CEGSet.objects.get_or_create(ceg=ceg_twice, set_number=2, defaults={'notes': 'Set 2 - Pedido Extra'})

        set1.generate_slots()
        set2.generate_slots()

        # 4. Participantes e Reservas Simuladas no TWICE
        p1, _ = Participant.objects.get_or_create(
            whatsapp='5511988881111',
            defaults={'name': 'Beatriz Lima', 'social_handle': '@jihyolover'}
        )
        p2, _ = Participant.objects.get_or_create(
            whatsapp='5521977772222',
            defaults={'name': 'Lucas Santos', 'social_handle': '@sana_biased'}
        )
        p3, _ = Participant.objects.get_or_create(
            whatsapp='5531966663333',
            defaults={'name': 'Camila Ferreira', 'social_handle': '@momo_dancing'}
        )

        # Reserva Jihyo e Sana no Set 1
        slot_jihyo = set1.slots.filter(item_definition__member_name='Jihyo').first()
        if slot_jihyo and slot_jihyo.status == ItemSlot.Status.AVAILABLE:
            slot_jihyo.status = ItemSlot.Status.PAID
            slot_jihyo.claimed_by = p1
            slot_jihyo.claimed_at = timezone.now() - timedelta(hours=3)
            slot_jihyo.save()
            Claim.objects.get_or_create(
                slot=slot_jihyo,
                defaults={
                    'participant': p1,
                    'status': Claim.Status.PAID,
                    'total_price': slot_jihyo.price,
                    'paid_at': timezone.now() - timedelta(hours=2)
                }
            )

        slot_sana = set1.slots.filter(item_definition__member_name='Sana').first()
        if slot_sana and slot_sana.status == ItemSlot.Status.AVAILABLE:
            slot_sana.status = ItemSlot.Status.RESERVED
            slot_sana.claimed_by = p2
            slot_sana.claimed_at = timezone.now() - timedelta(minutes=45)
            slot_sana.save()
            Claim.objects.get_or_create(
                slot=slot_sana,
                defaults={
                    'participant': p2,
                    'status': Claim.Status.PENDING,
                    'total_price': slot_sana.price
                }
            )

        # 5. CEG 2: tripleS (Modo Standby / Countdown ativo!)
        ceg_triples, _ = CEG.objects.get_or_create(
            slug='ceg-pob-withmuu-assemble24',
            defaults={
                'era': era_triples,
                'title': 'CEG POB Withmuu — ASSEMBLE24 (24 Integrantes)',
                'description': (
                    "Abertura programada com contagem regressiva!\n"
                    "CEG massiva para todas as 24 integrantes de tripleS.\n"
                    "O cronômetro regressivo destrava as reservas no segundo zero."
                ),
                'pix_key': 'ceg.triples@kpopbrasil.com.br',
                'pix_instructions': 'Pagamento via chave Pix celular. Comprovante pelo WhatsApp.',
                'status': CEG.Status.SCHEDULED,
                'opens_at': timezone.now() + timedelta(hours=2, minutes=30),  # 2h30m no futuro!
                'closes_at': timezone.now() + timedelta(days=10),
            }
        )

        triples_members = [
            'SeoYeon', 'HyeRin', 'JiWoo', 'ChaeYeon', 'YooYeon', 'SooMin',
            'NaKyoung', 'YuBin', 'Kaede', 'DaHyun', 'Kotone', 'YeonJi',
            'Nien', 'SoHyun', 'Xinyu', 'Mayu', 'Lynn', 'JooBin',
            'HaYeon', 'ShiOn', 'ChaeWon', 'SulLin', 'SeoAh', 'JiYeon'
        ]

        for i, m in enumerate(triples_members, 1):
            CEGItemDefinition.objects.get_or_create(
                ceg=ceg_triples,
                name=f'POB Withmuu {m}',
                defaults={
                    'member_name': m,
                    'item_type': CEGItemDefinition.ItemType.POB,
                    'default_price': 38.00,
                    'order_index': i
                }
            )

        set_triples, _ = CEGSet.objects.get_or_create(ceg=ceg_triples, set_number=1, defaults={'notes': 'Set Completo 24 Membros'})
        set_triples.generate_slots()

        self.stdout.write(self.style.SUCCESS("Dados populados com sucesso!"))
        self.stdout.write(f"- CEG Aberta: '{ceg_twice.title}' (TWICE)")
        self.stdout.write(f"- CEG Standby (Countdown ativo): '{ceg_triples.title}' (tripleS)")
