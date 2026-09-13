import json
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from apps.groups.models import KpopGroup, Era
from apps.cegs.models import (
    Caixa, CEG, CEGItemDefinition, CEGSet, ItemSlot,
    ItemIndividual, TipoItem, CaixaItemRate
)
from apps.participants.models import Participant, Claim


class TaxasRateioTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username="admin", email="admin@test.com", password="password123"
        )
        self.client.login(username="admin", password="password123")

        # Grupos e Eras
        self.group = KpopGroup.objects.create(name="aespa", slug="aespa")
        self.era = Era.objects.create(group=self.group, name="Armageddon", slug="armageddon")

        # Tipos de Item (Photocard, Álbum já podem vir da seed migration ou criamos)
        self.tipo_pc, _ = TipoItem.objects.get_or_create(nome="Photocard")
        self.tipo_album, _ = TipoItem.objects.get_or_create(nome="Álbum")

        # Participante
        self.buyer = Participant.objects.create(
            name="Karina Fan",
            whatsapp="5511999991111",
            username="karinafan"
        )

        # Caixa mista (Coreia)
        self.caixa = Caixa.objects.create(
            nome="Caixa KR #50 - Armageddon",
            slug="caixa-kr-50-armageddon",
            origem=Caixa.Origem.KR,
            status=Caixa.Status.EM_CONSOLIDACAO
        )

        # CEG vinculada a esta Caixa
        self.ceg = CEG.objects.create(
            era=self.era,
            caixa=self.caixa,
            title="aespa Armageddon CEG",
            slug="aespa-armageddon-ceg",
            status=CEG.Status.OPEN
        )

        # Definições de itens: 2 photocards e 1 álbum
        self.item_pc1 = CEGItemDefinition.objects.create(
            ceg=self.ceg, name="Karina POB", tipo_item=self.tipo_pc, default_price=Decimal("50.00")
        )
        self.item_pc2 = CEGItemDefinition.objects.create(
            ceg=self.ceg, name="Winter POB", tipo_item=self.tipo_pc, default_price=Decimal("50.00")
        )
        self.item_alb = CEGItemDefinition.objects.create(
            ceg=self.ceg, name="Álbum Armageddon Selado", tipo_item=self.tipo_album, default_price=Decimal("130.00")
        )

        # Set 1 com slots
        self.ceg_set = CEGSet.objects.create(ceg=self.ceg, set_number=1, is_active=True)
        self.slot_pc1 = ItemSlot.objects.create(
            set=self.ceg_set, item_definition=self.item_pc1, price=Decimal("50.00"),
            claimed_by=self.buyer, status=ItemSlot.Status.RESERVED
        )
        self.slot_pc2 = ItemSlot.objects.create(
            set=self.ceg_set, item_definition=self.item_pc2, price=Decimal("50.00"),
            claimed_by=self.buyer, status=ItemSlot.Status.RESERVED
        )
        self.slot_alb = ItemSlot.objects.create(
            set=self.ceg_set, item_definition=self.item_alb, price=Decimal("130.00"),
            claimed_by=self.buyer, status=ItemSlot.Status.RESERVED
        )

    def test_dynamic_tipo_item_creation_ajax(self):
        """Testa criação de novo TipoItem via AJAX POST /tipos-item/criar/"""
        url = reverse("tipo_item_create")
        response = self.client.post(
            url,
            {"nome": "Labubu", "descricao": "Boneco de vinil colecionável"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["tipo"]["nome"], "Labubu")
        self.assertTrue(TipoItem.objects.filter(nome="Labubu").exists())

    def test_item_individual_with_tipo_item(self):
        """Testa criação e edição de ItemIndividual vinculando tipo_item_id e Caixa"""
        tipo_labubu = TipoItem.objects.create(nome="Labubu Exclusivo")

        # Criação de item individual mercari com tipo_item
        create_url = reverse("create_item_individual")
        post_data = {
            "nome": "Labubu Pop Mart Monters",
            "tipo_item_id": str(tipo_labubu.id),
            "caixa_id": str(self.caixa.id),
            "quantidade": "1",
            "preco_produto": "180.00",
            "comprador_nome": "Cliente Labubu",
            "whatsapp": "5511988887777",
            "status": "COMPRADO",
        }
        resp = self.client.post(create_url, post_data)
        self.assertEqual(resp.status_code, 302)

        item = ItemIndividual.objects.filter(nome="Labubu Pop Mart Monters").first()
        self.assertIsNotNone(item)
        self.assertEqual(item.tipo_item, tipo_labubu)
        self.assertEqual(item.caixa, self.caixa)

        # Edição para trocar de tipo_item
        update_url = reverse("update_item_individual", kwargs={"item_id": item.id})
        update_data = {
            "nome": "Labubu Pop Mart Monters Editado",
            "tipo_item_id": str(self.tipo_album.id),
            "caixa_id": str(self.caixa.id),
            "quantidade": "1",
            "preco_produto": "190.00",
            "status": "COMPRADO",
        }
        resp_up = self.client.post(update_url, update_data)
        self.assertEqual(resp_up.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.tipo_item, self.tipo_album)

    def test_caixa_distribute_rates_to_ceg_slots_and_mercari_items(self):
        """
        Testa o rateio inteligente por TipoItem na Caixa:
        - Na caixa temos:
          - 2 slots de Photocard (da CEG)
          - 1 slot de Álbum (da CEG)
          - 1 ItemIndividual de Photocard (Mercari)
          - 1 ItemIndividual de Labubu (Mercari)
        Ao lançar:
          - Photocard: frete 6.00, taxa 3.00
          - Álbum: frete 20.00, taxa 10.00
          - Labubu: frete 15.00, taxa 5.00
        Assert:
          - Cada slot e item individual recebe suas taxas unitárias respectivas
          - Prazos são atribuídos corretamente
          - Total da caixa é recalculado:
            Photocards: 3 x 6.00 = 18.00 frete, 3 x 3.00 = 9.00 taxa
            Álbum: 1 x 20.00 = 20.00 frete, 1 x 10.00 = 10.00 taxa
            Labubu: 1 x 15.00 = 15.00 frete, 1 x 5.00 = 5.00 taxa
            Total Frete Caixa = 53.00
            Total Taxa Caixa = 24.00
        """
        tipo_labubu = TipoItem.objects.create(nome="Labubu")

        # Itens Individuais na Caixa
        item_pc = ItemIndividual.objects.create(
            nome="Ningning Card JP",
            tipo_item=self.tipo_pc,
            caixa=self.caixa,
            comprador=self.buyer,
            quantidade=1,
            preco_produto=Decimal("40.00"),
            status=ItemIndividual.Status.COMPRADO
        )
        item_labubu = ItemIndividual.objects.create(
            nome="Labubu Blind Box JP",
            tipo_item=tipo_labubu,
            caixa=self.caixa,
            comprador=self.buyer,
            quantidade=1,
            preco_produto=Decimal("120.00"),
            status=ItemIndividual.Status.COMPRADO
        )

        # Lançar taxas na Caixa
        distribute_url = reverse("caixa_distribute_rates", kwargs={"slug": self.caixa.slug})
        payload = {
            "caixa_prazo_frete": "2026-10-15T18:00",
            "caixa_prazo_taxa": "2026-10-20T18:00",

            f"frete_unit_{self.tipo_pc.id}": "6.00",
            f"taxa_unit_{self.tipo_pc.id}": "3.00",

            f"frete_unit_{self.tipo_album.id}": "20.00",
            f"taxa_unit_{self.tipo_album.id}": "10.00",

            f"frete_unit_{tipo_labubu.id}": "15.00",
            f"taxa_unit_{tipo_labubu.id}": "5.00",
        }

        resp = self.client.post(distribute_url, payload)
        self.assertEqual(resp.status_code, 302)

        # 1. Verifica slots da CEG
        self.slot_pc1.refresh_from_db()
        self.slot_pc2.refresh_from_db()
        self.slot_alb.refresh_from_db()

        self.assertEqual(self.slot_pc1.frete_inter_valor, Decimal("6.00"))
        self.assertEqual(self.slot_pc1.taxa_aduaneira_valor, Decimal("3.00"))
        self.assertEqual(self.slot_pc1.frete_inter, Decimal("6.00"))
        self.assertEqual(self.slot_pc1.taxa_aduaneira, Decimal("3.00"))
        self.assertIsNotNone(self.slot_pc1.prazo_frete_inter)
        self.assertIsNotNone(self.slot_pc1.prazo_taxa_aduaneira)

        self.assertEqual(self.slot_pc2.frete_inter_valor, Decimal("6.00"))
        self.assertEqual(self.slot_pc2.taxa_aduaneira_valor, Decimal("3.00"))

        self.assertEqual(self.slot_alb.frete_inter_valor, Decimal("20.00"))
        self.assertEqual(self.slot_alb.taxa_aduaneira_valor, Decimal("10.00"))
        self.assertEqual(self.slot_alb.frete_inter, Decimal("20.00"))
        self.assertEqual(self.slot_alb.taxa_aduaneira, Decimal("10.00"))

        # 2. Verifica itens individuais
        item_pc.refresh_from_db()
        item_labubu.refresh_from_db()

        self.assertEqual(item_pc.frete_inter, Decimal("6.00"))
        self.assertEqual(item_pc.taxa_aduaneira, Decimal("3.00"))
        self.assertIsNotNone(item_pc.prazo_frete_inter)

        self.assertEqual(item_labubu.frete_inter, Decimal("15.00"))
        self.assertEqual(item_labubu.taxa_aduaneira, Decimal("5.00"))
        self.assertIsNotNone(item_labubu.prazo_taxa_aduaneira)

        # 3. Verifica totais recalculados da Caixa e os prazos da Caixa
        self.caixa.refresh_from_db()
        self.assertIsNotNone(self.caixa.prazo_frete)
        self.assertIsNotNone(self.caixa.prazo_taxa)
        # 3 photocards x 6 = 18; 1 álbum x 20 = 20; 1 labubu x 15 = 15 => Total Frete = 53.00
        self.assertEqual(self.caixa.frete_inter_total, Decimal("53.00"))
        # 3 photocards x 3 = 9; 1 álbum x 10 = 10; 1 labubu x 5 = 5 => Total Taxa = 24.00
        self.assertEqual(self.caixa.taxa_aduaneira_total, Decimal("24.00"))

        # 4. Verifica registros persistidos de CaixaItemRate
        self.assertEqual(CaixaItemRate.objects.filter(caixa=self.caixa).count(), 3)
        rate_pc = CaixaItemRate.objects.get(caixa=self.caixa, tipo_item=self.tipo_pc)
        self.assertEqual(rate_pc.frete_unitario, Decimal("6.00"))
        self.assertEqual(rate_pc.taxa_unitaria, Decimal("3.00"))

    def test_distribute_rates_legacy_payload_fallback(self):
        """Testa compatibilidade com payload antigo contendo prazo_frete_{id}"""
        distribute_url = reverse("caixa_distribute_rates", kwargs={"slug": self.caixa.slug})
        payload = {
            f"frete_unit_{self.tipo_pc.id}": "4.00",
            f"prazo_frete_{self.tipo_pc.id}": "2026-11-01T12:00",
            f"taxa_unit_{self.tipo_pc.id}": "2.00",
            f"prazo_taxa_{self.tipo_pc.id}": "2026-11-05T12:00",
        }
        resp = self.client.post(distribute_url, payload)
        self.assertEqual(resp.status_code, 302)
        self.caixa.refresh_from_db()
        self.assertIsNotNone(self.caixa.prazo_frete)
        self.assertIsNotNone(self.caixa.prazo_taxa)
        self.slot_pc1.refresh_from_db()
        self.assertEqual(self.slot_pc1.prazo_frete_inter, self.caixa.prazo_frete)

    def test_create_ceg_with_dynamic_tipo_item(self):
        """Testa criação de CEG enviando items com tipo_item_id no items_json"""
        tipo_labubu, _ = TipoItem.objects.get_or_create(nome="Labubu Especial")
        create_url = reverse("create_ceg")

        items_data = [
            {
                "name": "Labubu Box",
                "member_name": "Special",
                "tipo_item_id": str(tipo_labubu.id),
                "item_type": "OUTRO",
                "default_price": "99.00",
                "participant_id": ""
            }
        ]

        post_data = {
            "era_id": str(self.era.id),
            "title": "CEG Labubus Importados",
            "caixa_id": str(self.caixa.id),
            "status": "OPEN",
            "items_json": json.dumps(items_data),
            "initial_sets_count": "1"
        }

        resp = self.client.post(create_url, post_data)
        self.assertEqual(resp.status_code, 302)

        created_ceg = CEG.objects.filter(title="CEG Labubus Importados").first()
        self.assertIsNotNone(created_ceg)
        self.assertEqual(created_ceg.caixa, self.caixa)

        item_def = created_ceg.item_definitions.first()
        self.assertIsNotNone(item_def)
        self.assertEqual(item_def.tipo_item, tipo_labubu)

        # Slot gerado
        slot = ItemSlot.objects.filter(set__ceg=created_ceg).first()
        self.assertIsNotNone(slot)
        self.assertEqual(slot.item_definition.tipo_item, tipo_labubu)

    def test_delete_tipo_item(self):
        """Testa exclusão de TipoItem sem vínculo e bloqueio quando há vínculo"""
        unused_tipo = TipoItem.objects.create(nome="Tipo Descartável")
        del_url = reverse("tipo_item_delete", kwargs={"pk": unused_tipo.id})

        # Exclusão com sucesso
        resp = self.client.post(del_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TipoItem.objects.filter(id=unused_tipo.id).exists())

        # Tentativa de excluir tipo com itens vinculados
        del_url_pc = reverse("tipo_item_delete", kwargs={"pk": self.tipo_pc.id})
        resp_err = self.client.post(del_url_pc, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp_err.status_code, 400)
        self.assertTrue(TipoItem.objects.filter(id=self.tipo_pc.id).exists())
