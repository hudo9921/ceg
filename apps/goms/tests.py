from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.two_factor import requires_two_factor

from .models import Gom, GomInvite, GomMembership
from .services import TeamRuleError, change_role, create_gom, remove_member

User = get_user_model()
TEAM = reverse('gom_team')


def accept_url(token):
    return reverse('gom_invite_accept', args=[token])


class DataMigrationTests(TestCase):
    def test_valcegs_gom_exists(self):
        self.assertTrue(Gom.objects.filter(slug='valcegs', is_active=True).exists())


class InviteFlowTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('root', 'r@x.com', 'Senha-Forte-123')
        self.gom, self.owner_token = create_gom(name='Kpop Store', slug='', created_by=self.root)

    def _signup(self, token, username):
        return self.client.post(accept_url(token), {
            'username': username, 'password1': 'Uma-Senha-Boa-987', 'password2': 'Uma-Senha-Boa-987'})

    def test_owner_invite_creates_account_and_membership_once(self):
        res = self._signup(self.owner_token, 'dona')
        self.assertRedirects(res, reverse('backoffice_home'), fetch_redirect_response=False)
        user = User.objects.get(username='dona')
        self.assertFalse(user.is_staff)  # membros não recebem is_staff: o acesso vem do vínculo
        self.assertEqual(GomMembership.objects.get(user=user, gom=self.gom).role, 'OWNER')

        self.client.logout()
        self.assertEqual(self.client.get(accept_url(self.owner_token)).status_code, 404)
        self._signup(self.owner_token, 'outra')
        self.assertFalse(User.objects.filter(username='outra').exists())

    def test_expired_revoked_and_unknown_tokens_are_rejected(self):
        expired, t1 = GomInvite.create_with_token(gom=self.gom, role='ADMIN')
        GomInvite.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        revoked, t2 = GomInvite.create_with_token(gom=self.gom, role='ADMIN')
        GomInvite.objects.filter(pk=revoked.pk).update(revoked_at=timezone.now())
        for token in (t1, t2, 'nao-existe'):
            self.assertEqual(self.client.get(accept_url(token)).status_code, 404, token)

    def test_token_is_not_stored_in_plain_text(self):
        self.assertFalse(GomInvite.objects.filter(token_hash=self.owner_token).exists())

    def test_weak_password_is_refused(self):
        self.client.post(accept_url(self.owner_token),
                         {'username': 'fraca', 'password1': '123', 'password2': '123'})
        self.assertFalse(User.objects.filter(username='fraca').exists())

    def test_reserved_and_duplicate_slugs(self):
        with self.assertRaises(TeamRuleError):
            create_gom(name='Equipe', slug='equipe', created_by=self.root)
        with self.assertRaises(TeamRuleError):
            create_gom(name='Kpop Store', slug='', created_by=self.root)


class TeamRulesTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja A', slug='loja-a')
        self.owner = User.objects.create_user('dono', password='x')
        self.admin = User.objects.create_user('ajudante', password='x')
        self.owner_m = GomMembership.objects.create(user=self.owner, gom=self.gom, role='OWNER')
        self.admin_m = GomMembership.objects.create(user=self.admin, gom=self.gom, role='ADMIN')

    def test_last_owner_cannot_be_removed_or_demoted(self):
        with self.assertRaises(TeamRuleError):
            remove_member(self.owner_m, self.owner)
        with self.assertRaises(TeamRuleError):
            change_role(self.owner_m, 'ADMIN', self.owner)
        change_role(self.admin_m, 'OWNER', self.owner)
        change_role(self.owner_m, 'ADMIN', self.owner)  # agora há outro dono

    def test_owner_manages_team_admin_cannot(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(TEAM).status_code, 200)
        self.client.post(TEAM, {'action': 'invite', 'role': 'ADMIN', 'name': 'x'})
        self.client.post(TEAM, {'action': 'remove', 'membership_id': self.owner_m.pk})
        self.assertFalse(GomInvite.objects.filter(gom=self.gom).exists())
        self.assertTrue(GomMembership.objects.get(pk=self.owner_m.pk).is_active)

        self.client.force_login(self.owner)
        res = self.client.post(TEAM, {'action': 'invite', 'role': 'ADMIN', 'name': 'Bia'})
        self.assertContains(res, '/convite/')
        self.client.post(TEAM, {'action': 'remove', 'membership_id': self.admin_m.pk})
        self.assertFalse(GomMembership.objects.get(pk=self.admin_m.pk).is_active)

    def test_member_of_one_gom_cannot_act_on_another(self):
        other = Gom.objects.create(name='Loja B', slug='loja-b')
        other_m = GomMembership.objects.create(
            user=User.objects.create_user('dono-b', password='x'), gom=other, role='ADMIN')
        self.client.force_login(self.owner)
        # trocar para um GOM do qual não faz parte é ignorado
        self.client.post(reverse('gom_switch'), {'gom_id': other.pk})
        self.assertContains(self.client.get(TEAM), 'Loja A')
        # ações com ids de outro GOM não encontram nada
        self.assertEqual(self.client.post(TEAM, {'action': 'remove', 'membership_id': other_m.pk}).status_code, 404)
        self.assertTrue(GomMembership.objects.get(pk=other_m.pk).is_active)

    def test_member_without_is_staff_uses_operational_screens_of_own_gom(self):
        # M2: o acesso vem do vínculo com o GOM, não do is_staff do Django.
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('creations_hub')).status_code, 200)
        self.assertEqual(self.client.get('/admin/').status_code, 302)  # /admin/ é só da plataforma

    def test_platform_screen_is_superuser_only(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('platform_goms')).status_code, 403)

    def test_backoffice_login_accepts_gom_members(self):
        self.owner.set_password('Senha-Forte-123')
        self.owner.save()
        res = self.client.post(reverse('backoffice_login'), {'username': 'dono', 'password': 'Senha-Forte-123'})
        self.assertRedirects(res, reverse('backoffice_home'), fetch_redirect_response=False)
        # Depois do login: o Início do painel.
        self.assertContains(self.client.get(reverse('backoffice_home')), 'Olá, dono')


@override_settings(STAFF_2FA_REQUIRED=True)
class MemberTwoFactorTests(TestCase):
    def test_gom_members_must_use_2fa(self):
        gom = Gom.objects.create(name='Loja C', slug='loja-c')
        user = User.objects.create_user('membro', password='x')
        self.assertFalse(requires_two_factor(user))
        GomMembership.objects.create(user=user, gom=gom, role='ADMIN')
        user = User.objects.get(pk=user.pk)  # descarta cache de vínculos
        self.assertTrue(requires_two_factor(user))
        self.client.force_login(user)
        self.assertTrue(self.client.get(TEAM)['Location'].startswith(reverse('staff_2fa_setup')))


class GomProfileTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja P', slug='loja-p')
        self.admin = User.objects.create_user('adm-p', password='x')
        GomMembership.objects.create(user=self.admin, gom=self.gom, role='ADMIN')
        self.client.force_login(self.admin)

    def test_admin_edits_profile_and_default_pix_prefills_new_cegs(self):
        res = self.client.post(reverse('gom_profile'), {
            'name': 'Loja P Oficial', 'bio': 'Oi', 'whatsapp_contato': '', 'instagram': '@lojap',
            'logo_url': '', 'banner_url': '', 'default_pix_key': 'pix@lojap.com', 'default_pix_instructions': 'Itaú',
        })
        self.assertRedirects(res, reverse('gom_profile'), fetch_redirect_response=False)
        self.gom.refresh_from_db()
        self.assertEqual((self.gom.name, self.gom.default_pix_key), ('Loja P Oficial', 'pix@lojap.com'))
        self.assertContains(self.client.get(reverse('gom_public', args=['loja-p'])), 'Loja P Oficial')

    def test_profile_cannot_change_slug_or_other_gom(self):
        other = Gom.objects.create(name='Outra', slug='outra')
        self.client.post(reverse('gom_profile'), {'name': 'X', 'slug': 'hack', 'default_pix_key': 'k'})
        self.gom.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.gom.slug, 'loja-p')
        self.assertEqual(other.name, 'Outra')

    def test_platform_overview_counts(self):
        root = User.objects.create_superuser('root2', 'r@x.com', 'Senha-Forte-123')
        self.client.force_login(root)
        res = self.client.get(reverse('platform_goms'))
        self.assertContains(res, 'Loja P')
        self.assertContains(res, '1 na equipe')
