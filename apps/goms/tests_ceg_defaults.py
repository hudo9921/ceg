"""Padrões de CEG (C2): pré-preenchem o Criar e completam prazo/descrição no salvamento."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cegs.models import CEG, Caixa
from apps.groups.models import Era, KpopGroup

from .models import Gom, GomMembership

User = get_user_model()


class CegDefaultsTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja D', slug='loja-d')
        self.owner = User.objects.create_user('dono-d', password='x')
        GomMembership.objects.create(user=self.owner, gom=self.gom, role='OWNER')
        self.client.force_login(self.owner)
        self.era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa-d'), name='Rich Man', slug='rich-d')

    def _create(self, **extra):
        data = {'era_id': self.era.id, 'title': 'CEG D', 'status': 'OPEN', 'initial_sets_count': 1,
                'items_json': '[{"name": "PC Karina", "price": "40"}]'}
        data.update(extra)
        self.client.post(reverse('create_ceg'), data)
        return CEG.objects.for_gom(self.gom).get(title='CEG D')

    def test_settings_tab_saves_defaults(self):
        self.client.post(reverse('gom_settings_tab', args=['padroes']), {
            'padrao_prazo_item_dias': '3', 'padrao_horario_abertura': '20:00',
            'padrao_descricao': 'CEG de {grupo}', 'padrao_caixa_aberta': 'on'})
        self.gom.refresh_from_db()
        self.assertEqual((self.gom.padrao_prazo_item_dias, self.gom.padrao_horario_abertura.hour, self.gom.padrao_caixa_aberta),
                         (3, 20, True))

    def test_create_fills_prazo_from_closing_and_description_placeholders(self):
        self.gom.padrao_prazo_item_dias = 3
        self.gom.save()
        ceg = self._create(closes_at='2030-01-10T20:00', description='CEG de {grupo} — {era}')
        self.assertEqual(ceg.description, 'CEG de aespa — Rich Man')
        self.assertEqual(timezone.localtime(ceg.prazo_pagamento_item).strftime('%d/%m %H:%M'), '13/01 20:00')

    def test_explicit_prazo_wins_and_no_closing_means_no_prazo(self):
        self.gom.padrao_prazo_item_dias = 3
        self.gom.save()
        self.assertIsNone(self._create().prazo_pagamento_item)

    def test_criar_form_is_prefilled(self):
        caixa = Caixa.objects.create(nome='Caixa Nov', gom=self.gom)
        self.gom.padrao_horario_abertura = timezone.datetime(2000, 1, 1, 20, 0).time()
        self.gom.padrao_descricao = 'Modelo {grupo}'
        self.gom.padrao_caixa_aberta = True
        self.gom.save()
        page = self.client.get(reverse('creations_hub')).content.decode()
        tomorrow = (timezone.localdate() + timedelta(days=1)).strftime('%Y-%m-%d')
        self.assertIn(f'value="{tomorrow}T20:00"', page)
        self.assertIn('>Modelo {grupo}</textarea>', page)
        self.assertIn(f'<option value="{caixa.id}" selected>', page)
