"""Permissões por admin de GOM (apps.goms.permissions; docs/MULTI_GOM_DESIGN.md §3.1)."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.cegs.models import AuditLog, Caixa
from apps.core.permissions import StaffRequiredMixin

from . import permissions as perms
from .models import Gom, GomInvite, GomMembership
from .services import TeamRuleError, accept_invite, set_permissions

User = get_user_model()
TEAM = reverse('gom_team')


def _all_view_classes(resolver=None):
    for p in (resolver or get_resolver()).url_patterns:
        if isinstance(p, URLResolver):
            yield from _all_view_classes(p)
        elif isinstance(p, URLPattern) and getattr(p.callback, 'view_class', None):
            yield p.callback.view_class


class CatalogTests(TestCase):
    def test_every_staff_view_declares_a_known_permission(self):
        missing = []
        for cls in set(_all_view_classes()):
            if not issubclass(cls, StaffRequiredMixin):
                continue
            declared = cls.gom_permission
            keys = declared if isinstance(declared, (tuple, list)) else (declared,)
            if declared is None or any(k != perms.ANY and k not in perms.ALL for k in keys):
                missing.append(f'{cls.__module__}.{cls.__name__}={declared!r}')
        self.assertEqual(missing, [], 'Views de staff sem gom_permission válida')

    def test_presets_only_use_known_keys_and_never_pix(self):
        for key, (_name, _help, keys) in perms.PRESETS.items():
            self.assertTrue(set(keys) <= perms.ALL, key)
            self.assertNotIn('pix.alterar', keys, key)


@override_settings(STAFF_2FA_REQUIRED=False)
class AdminPermissionTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja Perm', slug='loja-perm')
        self.owner = User.objects.create_user('dono-perm', password='x')
        self.owner_m = GomMembership.objects.create(user=self.owner, gom=self.gom, role='OWNER')
        self.admin = User.objects.create_user('logistica', password='x')
        self.admin_m = GomMembership.objects.create(
            user=self.admin, gom=self.gom, role='ADMIN', permissions=perms.PRESETS['logistica'][2])

    def test_admin_only_reaches_allowed_screens(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('caixas_dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('creations_hub')).status_code, 403)
        res = self.client.get(reverse('cegs_status_api'), HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 403)
        self.assertIn('Sem permissão', res.json()['message'])

    def test_sidebar_and_first_screen_follow_permissions(self):
        self.client.force_login(self.admin)
        home = self.client.get(reverse('backoffice_home')).content.decode()
        self.assertIn('pedidos de envio', home)       # logística vê a tarefa de envios
        self.assertNotIn('Vendido no mês', home)      # sem analytics.ver, sem números de venda
        page = self.client.get(reverse('caixas_dashboard')).content.decode()
        self.assertIn(reverse('envios_nacionais'), page)
        self.assertNotIn(reverse('creations_hub'), page)

    def test_legacy_admin_without_saved_list_keeps_everything(self):
        legacy = User.objects.create_user('antigo', password='x')
        GomMembership.objects.create(user=legacy, gom=self.gom, role='ADMIN')
        self.client.force_login(legacy)
        self.assertEqual(self.client.get(reverse('creations_hub')).status_code, 200)
        self.assertEqual(self.client.get(reverse('gom_settings_tab', args=['perfil'])).status_code, 200)

    def test_pix_fields_ignored_without_pix_permission(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('caixa_create'), {'nome': 'Caixa P', 'pix_key_frete': 'golpe@pix.com'})
        caixa = Caixa.objects.get(nome='Caixa P')
        self.assertEqual(caixa.pix_key_frete, '')

        set_permissions(self.admin_m, ['gom.perfil'], self.owner)
        page = self.client.get(reverse('gom_settings_tab', args=['perfil'])).content.decode()
        self.assertNotIn('default_pix_key', page)
        self.assertNotIn(reverse('gom_settings_tab', args=['pix']), page)
        self.assertEqual(self.client.get(reverse('gom_settings_tab', args=['pix'])).status_code, 403)
        self.client.post(reverse('gom_settings_tab', args=['perfil']), {'name': 'Loja Nova', 'default_pix_key': 'golpe@pix.com'})
        self.client.post(reverse('gom_settings_tab', args=['pix']), {'default_pix_key': 'golpe@pix.com'})
        self.gom.refresh_from_db()
        self.assertEqual((self.gom.name, self.gom.default_pix_key), ('Loja Nova', ''))

    def test_owner_saves_permissions_and_it_is_audited(self):
        self.client.force_login(self.owner)
        self.client.post(TEAM, {'action': 'perms', 'membership_id': self.admin_m.id,
                                'perms': ['ceg.editar', 'pix.alterar', 'nao.existe']})
        self.admin_m.refresh_from_db()
        self.assertEqual(self.admin_m.permissions, ['ceg.editar', 'pix.alterar'])
        self.assertEqual(self.admin_m.permissions_updated_by, self.owner)
        log = AuditLog.objects.filter(gom=self.gom, field_name='permissoes').get()
        self.assertIn('pix.alterar', log.metadata['adicionadas'])

    def test_admin_cannot_change_permissions_and_owner_is_always_full(self):
        self.client.force_login(self.admin)
        self.client.post(TEAM, {'action': 'perms', 'membership_id': self.admin_m.id, 'perms': list(perms.ALL)})
        self.admin_m.refresh_from_db()
        self.assertEqual(set(self.admin_m.permissions), set(perms.PRESETS['logistica'][2]))
        with self.assertRaises(TeamRuleError):
            set_permissions(self.owner_m, [], self.owner)
        self.assertEqual(perms.membership_permissions(self.owner_m), perms.ALL)

    def test_invite_preset_becomes_the_new_admin_permissions(self):
        self.client.force_login(self.owner)
        self.client.post(TEAM, {'action': 'invite', 'name': 'Bia', 'role': 'ADMIN', 'preset': 'pagamentos'})
        invite = GomInvite.objects.get(gom=self.gom, name='Bia')
        new_user = User.objects.create_user('bia', password='x')
        membership = accept_invite(invite.id, new_user)
        self.assertEqual(set(membership.permissions), set(perms.PRESETS['pagamentos'][2]))

    def test_team_page_renders_for_owner_and_admin(self):
        for user in (self.owner, self.admin):
            self.client.force_login(user)
            res = self.client.get(TEAM)
            self.assertContains(res, 'team-data')
            self.assertContains(res, 'Alterar chaves Pix')
