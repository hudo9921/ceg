from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.participants.models import Participant
from apps.groups.models import KpopGroup, Era
from apps.cegs.models import (
    Caixa,
    CaixaItemRate,
    CEG,
    CEGSet,
    CEGItemDefinition,
    ItemSlot,
    TipoItem,
    ItemIndividual,
)

User = get_user_model()


class CascataCaixaTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='admin_staff',
            password='password123',
            is_staff=True
        )

        self.group = KpopGroup.objects.create(name='BIGBANG', slug='bigbang')
        self.era = Era.objects.create(group=self.group, name='Made Era')

        # Tipos de Item
        self.tipo_album, _ = TipoItem.objects.get_or_create(nome='Álbum')
        self.tipo_crocs, _ = TipoItem.objects.get_or_create(nome='Crocs')
        self.tipo_lightstick, _ = TipoItem.objects.get_or_create(nome='Lightstick')

        # Prazos da Caixa
        self.prazo_frete = timezone.now() + timedelta(days=5)
        self.prazo_taxa = timezone.now() + timedelta(days=10)

        # Caixa KR
        self.caixa = Caixa.objects.create(
            nome='Caixa KR 01',
            origem='KR',
            status='EMBALADA',
            prazo_frete=self.prazo_frete,
            prazo_taxa=self.prazo_taxa,
        )

        # Rates por tipo
        CaixaItemRate.objects.create(
            caixa=self.caixa,
            tipo_item=self.tipo_album,
            frete_unitario=Decimal('40.00'),
            taxa_unitaria=Decimal('2.00')
        )
        CaixaItemRate.objects.create(
            caixa=self.caixa,
            tipo_item=self.tipo_crocs,
            frete_unitario=Decimal('95.00'),
            taxa_unitaria=Decimal('3.00')
        )
        CaixaItemRate.objects.create(
            caixa=self.caixa,
            tipo_item=self.tipo_lightstick,
            frete_unitario=Decimal('140.00'),
            taxa_unitaria=Decimal('4.00')
        )

        # CEG com itens variados
        self.ceg = CEG.objects.create(
            era=self.era,
            title='Drop Teste Cascata',
            status=CEG.Status.OPEN,
            caixa=self.caixa
        )
        self.set1 = CEGSet.objects.create(ceg=self.ceg, set_number=1)

        # Definições de itens
        self.def_album = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Album 1',
            tipo_item=self.tipo_album,
            default_price=Decimal('45.00')
        )
        self.def_crocs = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Crocs',
            tipo_item=self.tipo_crocs,
            default_price=Decimal('45.00')
        )
        self.def_lightstick = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Lightstick',
            tipo_item=self.tipo_lightstick,
            default_price=Decimal('120.00')
        )

        # Slots
        self.slot_album = ItemSlot.objects.create(
            set=self.set1,
            item_definition=self.def_album,
            price=Decimal('45.00')
        )
        self.slot_crocs = ItemSlot.objects.create(
            set=self.set1,
            item_definition=self.def_crocs,
            price=Decimal('45.00')
        )
        self.slot_lightstick = ItemSlot.objects.create(
            set=self.set1,
            item_definition=self.def_lightstick,
            price=Decimal('120.00')
        )

        self.participant = Participant.objects.create(
            name='Comprador Mercari',
            whatsapp='5511999999999'
        )

        # Item individual Mercari
        self.item_mercari = ItemIndividual.objects.create(
            nome='Photocard Mercari',
            caixa=self.caixa,
            comprador=self.participant,
            tipo_item=self.tipo_album,
            preco_produto=Decimal('80.00')
        )

    def test_propagar_taxas_e_prazos_em_cascata(self):
        """Testa se a propagação distribui corretamente para CEG, slots e itens Mercari."""
        self.caixa.propagar_taxas_e_prazos_em_cascata()

        self.ceg.refresh_from_db()
        self.slot_album.refresh_from_db()
        self.slot_crocs.refresh_from_db()
        self.slot_lightstick.refresh_from_db()
        self.item_mercari.refresh_from_db()

        # Verifica prazos na CEG
        self.assertEqual(self.ceg.prazo_pagamento_frete_inter, self.prazo_frete)
        self.assertEqual(self.ceg.prazo_pagamento_taxa_aduaneira, self.prazo_taxa)

        # Verifica slots individuais
        self.assertEqual(self.slot_album.frete_inter, Decimal('40.00'))
        self.assertEqual(self.slot_album.taxa_aduaneira, Decimal('2.00'))
        self.assertEqual(self.slot_album.prazo_frete_inter, self.prazo_frete)
        self.assertEqual(self.slot_album.prazo_taxa_aduaneira, self.prazo_taxa)

        self.assertEqual(self.slot_crocs.frete_inter, Decimal('95.00'))
        self.assertEqual(self.slot_crocs.taxa_aduaneira, Decimal('3.00'))

        self.assertEqual(self.slot_lightstick.frete_inter, Decimal('140.00'))
        self.assertEqual(self.slot_lightstick.taxa_aduaneira, Decimal('4.00'))

        # Verifica resumo e propriedades da CEG
        self.assertTrue(self.ceg.has_multiple_frete_rates)
        self.assertEqual(self.ceg.min_frete_inter, Decimal('40.00'))
        self.assertEqual(self.ceg.max_frete_inter, Decimal('140.00'))

        self.assertTrue(self.ceg.has_multiple_taxa_rates)
        self.assertEqual(self.ceg.min_taxa_aduaneira, Decimal('2.00'))
        self.assertEqual(self.ceg.max_taxa_aduaneira, Decimal('4.00'))

        # Verifica Item Individual Mercari
        self.assertEqual(self.item_mercari.frete_inter, Decimal('40.00'))
        self.assertEqual(self.item_mercari.taxa_aduaneira, Decimal('2.00'))
        self.assertEqual(self.item_mercari.prazo_frete_inter, self.prazo_frete)
        self.assertEqual(self.item_mercari.prazo_taxa_aduaneira, self.prazo_taxa)

    def test_update_ceg_fees_view_triggers_cascata(self):
        """Testa se submeter update_ceg_fees com caixa vinculada dispara propagação em cascata."""
        # Cria outra CEG sem caixa inicialmente
        ceg2 = CEG.objects.create(
            era=self.era,
            title='CEG Desvinculada',
            status=CEG.Status.OPEN
        )
        set2 = CEGSet.objects.create(ceg=ceg2, set_number=1)
        def_album2 = CEGItemDefinition.objects.create(
            ceg=ceg2,
            name='Album 2',
            tipo_item=self.tipo_album,
            default_price=Decimal('50.00')
        )
        slot2 = ItemSlot.objects.create(
            set=set2,
            item_definition=def_album2,
            price=Decimal('50.00')
        )

        self.client.force_login(self.staff_user)
        url = reverse('update_ceg_fees', kwargs={'slug': ceg2.slug})
        response = self.client.post(url, {
            'caixa_id': str(self.caixa.id),
        })
        self.assertEqual(response.status_code, 302)

        ceg2.refresh_from_db()
        slot2.refresh_from_db()

        self.assertEqual(ceg2.caixa, self.caixa)
        self.assertEqual(slot2.frete_inter, Decimal('40.00'))
        self.assertEqual(slot2.taxa_aduaneira, Decimal('2.00'))
        self.assertEqual(ceg2.prazo_pagamento_frete_inter, self.prazo_frete)
