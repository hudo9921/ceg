"""Reaproveitar fotos de CEGs anteriores da mesma era (de qualquer GOM) na Nova CEG."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.goms.models import Gom, GomMembership
from apps.groups.models import Era, KpopGroup

from .models import CEG, CEGItemDefinition


class EraFotosTests(TestCase):
    def setUp(self):
        self.group = KpopGroup.objects.create(name='aespa', color_hex='#000000')
        self.era = Era.objects.create(group=self.group, name='Rich Man', color_hex='#000000')
        self.outra_era = Era.objects.create(group=self.group, name='Armageddon', color_hex='#000000')
        self.gom_a = Gom.objects.create(name='Loja A', slug='loja-a')
        self.gom_b = Gom.objects.create(name='Loja B', slug='loja-b')
        self.membro_b = get_user_model().objects.create_user('membro-b', password='x')
        GomMembership.objects.create(user=self.membro_b, gom=self.gom_b, role='OWNER')

    def _ceg(self, gom, era, status, banner, fotos):
        ceg = CEG.objects.create(gom=gom, era=era, title=f'CEG {gom.name} {status}', status=status, banner_url=banner)
        for membro, url in fotos:
            CEGItemDefinition.objects.create(ceg=ceg, name='Pob', member_name=membro, sub_category='Pob',
                                             default_price=45, image_url=url)
        return ceg

    def _get(self, era=None):
        self.client.force_login(self.membro_b)
        return self.client.get(reverse('era_fotos', args=[(era or self.era).id]))

    def test_outro_gom_ve_fotos_publicadas_da_mesma_era(self):
        self._ceg(self.gom_a, self.era, CEG.Status.OPEN, 'https://img.test/capa-a.jpg',
                  [('Karina', 'https://img.test/karina.jpg'), ('Winter', 'https://img.test/winter.jpg')])
        data = self._get().json()
        self.assertEqual([c['url'] for c in data['capas']], ['https://img.test/capa-a.jpg'])
        self.assertEqual(data['capas'][0]['gom'], 'Loja A')
        self.assertEqual({(f['integrante'], f['url']) for f in data['itens']},
                         {('Karina', 'https://img.test/karina.jpg'), ('Winter', 'https://img.test/winter.jpg')})

    def test_rascunho_e_outra_era_ficam_de_fora(self):
        self._ceg(self.gom_a, self.era, CEG.Status.DRAFT, 'https://img.test/rascunho.jpg', [('Karina', 'https://img.test/r.jpg')])
        self._ceg(self.gom_a, self.outra_era, CEG.Status.OPEN, 'https://img.test/outra.jpg', [('Karina', 'https://img.test/o.jpg')])
        data = self._get().json()
        self.assertEqual(data, {'capas': [], 'itens': []})

    def test_capa_da_era_e_sem_repetir_links(self):
        self.era.banner_url = 'https://img.test/era.jpg'
        self.era.save()
        self._ceg(self.gom_a, self.era, CEG.Status.OPEN, 'https://img.test/era.jpg', [('Karina', 'https://img.test/k.jpg')])
        self._ceg(self.gom_b, self.era, CEG.Status.CLOSED, 'https://img.test/b.jpg', [('Karina', 'https://img.test/k.jpg')])
        data = self._get().json()
        self.assertEqual([c['url'] for c in data['capas']], ['https://img.test/era.jpg', 'https://img.test/b.jpg'])
        self.assertEqual(len(data['itens']), 1)

    def test_joiner_ou_anonimo_nao_acessa(self):
        res = self.client.get(reverse('era_fotos', args=[self.era.id]))
        self.assertIn(res.status_code, (302, 403))

    def test_nova_ceg_usa_o_mesmo_link(self):
        """A foto escolhida vai como URL: a CEG nova guarda o mesmo link, sem novo upload."""
        self.client.force_login(self.membro_b)
        session = self.client.session
        session['active_gom_id'] = self.gom_b.id
        session.save()
        self.client.post(reverse('create_ceg'), {
            'era_id': self.era.id, 'title': 'CEG reaproveitada', 'status': 'DRAFT',
            'banner_url': 'https://img.test/capa-a.jpg',
            'items_json': '[{"name": "Pob", "member_name": "Karina", "default_price": "45", "image_url": "https://img.test/karina.jpg"}]',
        })
        ceg = CEG.objects.get(title='CEG reaproveitada')
        self.assertEqual(ceg.gom, self.gom_b)
        self.assertEqual(ceg.banner_url, 'https://img.test/capa-a.jpg')
        self.assertEqual(ceg.item_definitions.get().image_url, 'https://img.test/karina.jpg')
