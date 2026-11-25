"""Opções da página pública do GOM: seções visíveis e CEG fixada no topo."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cegs.models import CEG
from apps.groups.models import Era, KpopGroup

from .models import Gom, GomMembership

User = get_user_model()


class PublicPageOptionsTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja P2', slug='loja-p2')
        era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa-p2'), name='Rich', slug='rich-p2')
        self.era = era
        self.aberta = CEG.objects.create(era=era, gom=self.gom, title='CEG Aberta', slug='ceg-aberta-p2', status=CEG.Status.OPEN)
        self.agendada = CEG.objects.create(era=era, gom=self.gom, title='CEG Agendada', slug='ceg-agendada-p2',
                                           status=CEG.Status.SCHEDULED, opens_at=timezone.now() + timedelta(days=1))
        self.url = reverse('gom_public', args=['loja-p2'])
        self.owner = User.objects.create_user('dono-p2', password='x')
        GomMembership.objects.create(user=self.owner, gom=self.gom, role='OWNER')

    def test_hide_scheduled_section(self):
        self.gom.pagina_mostrar_agendadas = False
        self.gom.save()
        res = self.client.get(self.url)
        self.assertContains(res, 'CEG Aberta')
        self.assertNotContains(res, 'CEG Agendada')

    def test_pinned_ceg_shows_on_top(self):
        self.gom.pagina_ceg_destaque = self.agendada
        self.gom.save()
        page = self.client.get(self.url).content.decode()
        self.assertIn('Em destaque', page)
        self.assertLess(page.index('Em destaque'), page.index('CEGs abertas'))

    def test_closed_pinned_ceg_is_ignored(self):
        self.aberta.status = CEG.Status.CLOSED
        self.aberta.save()
        self.gom.pagina_ceg_destaque = self.aberta
        self.gom.save()
        self.assertNotContains(self.client.get(self.url), 'Em destaque')

    def test_settings_save_options_and_only_own_cegs(self):
        other = CEG.objects.create(era=self.era, gom=Gom.objects.create(name='X', slug='x-p2'), title='Alheia',
                                   slug='alheia-p2', status=CEG.Status.OPEN)
        self.client.force_login(self.owner)
        tab = reverse('gom_settings_tab', args=['perfil'])
        base = {'name': 'Loja P2', 'bio': '', 'whatsapp_contato': '', 'instagram': '', 'logo_url': '', 'banner_url': '',
                'pagina_form': '1', 'pagina_mostrar_agendadas': 'on'}
        self.client.post(tab, {**base, 'pagina_ceg_destaque': other.id})
        self.gom.refresh_from_db()
        self.assertIsNone(self.gom.pagina_ceg_destaque)
        self.client.post(tab, {**base, 'pagina_ceg_destaque': self.aberta.id})
        self.gom.refresh_from_db()
        self.assertEqual((self.gom.pagina_ceg_destaque, self.gom.pagina_mostrar_vitrine), (self.aberta, False))

    def test_profile_post_without_block_keeps_options(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('gom_settings_tab', args=['perfil']), {'name': 'Loja P2 Nova'})
        self.gom.refresh_from_db()
        self.assertTrue(self.gom.pagina_mostrar_vitrine)
