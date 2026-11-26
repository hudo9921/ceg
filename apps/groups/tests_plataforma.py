"""Catálogo da plataforma (/plataforma/catalogo/) e aviso do bot do WhatsApp no menu do superusuário."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.auth_otp.models import WhatsAppOTP
from apps.auth_otp.status import CHAVE_CACHE, resumo_codigos
from apps.goms.models import Gom, GomMembership

from .models import Era, GroupMember, KpopGroup


class CatalogoPlataformaTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('root-cat', 'r@example.com', 'Senha-Forte-123')
        self.aespa = KpopGroup.objects.create(name='aespa', slug='aespa-p', image_url='https://example.com/a.jpg',
                                              popularity_rank=3, agency='SM Entertainment')
        Era.objects.create(group=self.aespa, name='Rich Man', slug='rich-p', banner_url='https://example.com/r.jpg')
        Era.objects.create(group=self.aespa, name='Dirty Work', slug='dirty-p')
        GroupMember.objects.create(group=self.aespa, name='Karina')
        self.sem_nada = KpopGroup.objects.create(name='Grupo Vazio', slug='vazio-p')
        self.url = reverse('platform_catalogo')

    def nomes(self, res):
        return [g.name for g in res.context['pagina'].object_list]

    def test_so_superusuario(self):
        gom = Gom.objects.create(name='G', slug='g-cat')
        dono = User.objects.create_user('dono-cat', password='Senha-Forte-123')
        GomMembership.objects.create(gom=gom, user=dono, role=GomMembership.Role.OWNER)
        self.client.force_login(dono)
        self.assertIn(self.client.get(self.url).status_code, (302, 403))

    def test_lista_busca_e_filtros(self):
        self.client.force_login(self.root)
        res = self.client.get(self.url)
        self.assertEqual(self.nomes(res), ['aespa', 'Grupo Vazio'])  # ranking primeiro, sem posição no fim
        self.assertEqual(self.nomes(self.client.get(self.url, {'q': 'SM Ent'})), ['aespa'])
        self.assertEqual(self.nomes(self.client.get(self.url, {'problema': 'sem_foto'})), ['Grupo Vazio'])
        self.assertEqual(self.nomes(self.client.get(self.url, {'problema': 'sem_eras'})), ['Grupo Vazio'])
        self.assertEqual(self.nomes(self.client.get(self.url, {'problema': 'eras_sem_capa'})), ['aespa'])
        self.assertContains(res, 'Eras sem capa')

    def test_pagina_do_grupo(self):
        self.client.force_login(self.root)
        res = self.client.get(reverse('platform_catalogo_grupo', args=[self.aespa.pk]))
        self.assertContains(res, 'Karina')
        self.assertContains(res, 'Dirty Work')
        self.assertEqual(res.context['eras_sem_capa'], 1)
        self.assertContains(res, reverse('admin:groups_kpopgroup_change', args=[self.aespa.pk]))


class EdicaoCatalogoTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('root-ed', 'e@example.com', 'Senha-Forte-123')
        self.grupo = KpopGroup.objects.create(name='aespa', slug='aespa-ed')
        self.era = Era.objects.create(group=self.grupo, name='Rich Man', slug='rich-ed')

    def test_salva_grupo_e_volta(self):
        self.client.force_login(self.root)
        volta = reverse('platform_catalogo') + '?q=aespa'
        res = self.client.post(reverse('platform_catalogo_grupo_salvar', args=[self.grupo.pk]), {
            'name': 'aespa', 'name_native': '에스파', 'aliases': 'æspa', 'kind': 'GRUPO', 'status': 'ATIVO',
            'agency': 'SM', 'debut_date': '2020-11-17', 'popularity_rank': '4', 'image_url': 'https://example.com/a.jpg',
            'next': volta})
        self.assertRedirects(res, volta, fetch_redirect_response=False)
        self.grupo.refresh_from_db()
        self.assertEqual((self.grupo.name_native, self.grupo.popularity_rank, self.grupo.image_url),
                         ('에스파', 4, 'https://example.com/a.jpg'))

    def test_salva_capa_da_era_e_ignora_next_externo(self):
        self.client.force_login(self.root)
        res = self.client.post(reverse('platform_catalogo_era_salvar', args=[self.era.pk]), {
            'name': 'Rich Man', 'kind': 'MINI', 'release_date': '', 'image_url': 'https://example.com/r.jpg',
            'next': 'https://evil.example.com/'})
        self.assertEqual(res['Location'], reverse('platform_catalogo'))
        self.era.refresh_from_db()
        self.assertEqual((self.era.kind, self.era.banner_url), ('MINI', 'https://example.com/r.jpg'))

    def test_dono_de_gom_nao_edita(self):
        dono = User.objects.create_user('dono-ed', password='Senha-Forte-123')
        self.client.force_login(dono)
        self.client.post(reverse('platform_catalogo_era_salvar', args=[self.era.pk]), {'name': 'Hack', 'kind': 'OUTRO'})
        self.era.refresh_from_db()
        self.assertEqual(self.era.name, 'Rich Man')


class MarcaTests(TestCase):
    def test_plataforma_e_pagina_do_gom(self):
        Gom.objects.create(name='Loja Marca', slug='loja-marca')
        self.assertContains(self.client.get(reverse('gom_directory')), '>CegManager</a>')
        res = self.client.get(reverse('gom_public', args=['loja-marca']))
        self.assertContains(res, 'title="Página de Loja Marca">Loja Marca</a>')


@override_settings(WHATSAPP_PROVIDER='evolution')
class AvisoBotTests(TestCase):
    def setUp(self):
        cache.delete(CHAVE_CACHE)
        self.root = User.objects.create_superuser('root-wa', 'w@example.com', 'Senha-Forte-123')
        self.client.force_login(self.root)

    def tearDown(self):
        cache.delete(CHAVE_CACHE)

    def _instancias(self, status, codigo=None):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = [{'name': 'ceg-bot', 'connectionStatus': status, 'disconnectionReasonCode': codigo,
                                   'disconnectionAt': '2026-10-25T23:28:14.606Z'}]
        return resp

    def test_menu_mostra_off_quando_desconectado(self):
        with mock.patch('apps.auth_otp.status.requests.get', return_value=self._instancias('close', 401)):
            res = self.client.get(reverse('platform_catalogo'))
        self.assertContains(res, 'O bot está desconectado')

    def test_menu_sem_aviso_quando_conectado(self):
        with mock.patch('apps.auth_otp.status.requests.get', return_value=self._instancias('open')):
            res = self.client.get(reverse('platform_catalogo'))
        self.assertNotContains(res, 'O bot está desconectado')

    def test_resumo_mascara_telefone(self):
        agora = timezone.now()
        WhatsAppOTP.objects.create(phone='5511987654321', code='123456', expires_at=agora + timedelta(minutes=10))
        WhatsAppOTP.objects.create(phone='5511911112222', code='654321', expires_at=agora, is_used=True)
        resumo, ultimos = resumo_codigos()
        self.assertEqual(resumo[0], {'rotulo': '24 horas', 'pedidos': 2, 'usados': 1})
        self.assertEqual({u['fone'] for u in ultimos}, {'•••• 4321', '•••• 2222'})
