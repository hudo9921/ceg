"""
Isolamento entre GOMs (docs/MULTI_GOM_DESIGN.md §3): um membro do GOM B percorre TODAS
as rotas usando objetos do GOM A e não pode ver nem alterar nada dele.

Os objetos vêm de `RouteFixtures` (um de cada tipo, no GOM A = ValCegs). Se uma rota nova
vazar dados, este teste falha mostrando a rota.
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.cegs.models import CEG, Caixa, GOMNotification, ItemIndividual, ItemSlot, ItemVitrine, PacoteNacional
from apps.core.tests import PARTICIPANT_ROUTES, PUBLIC_ROUTES, RouteFixtures, iter_routes
from apps.participants.models import Claim, Participant

from .models import Gom, GomMembership

# Textos que só existem nos dados do GOM A.
SECRETS = ('CEG Matriz', 'Caixa Matriz', 'PC Mercari', 'PAC-MATRIZ', 'Joana SegredoA', '900000009')
# Rotas da plataforma/joiner ou que não carregam dados de GOM.
NOT_GOM_DATA = PUBLIC_ROUTES | PARTICIPANT_ROUTES | {
    'gom_team', 'gom_switch', 'platform_goms', 'platform_catalogo', 'platform_catalogo_grupo', 'backoffice_home', 'staff_2fa_manage',
    'staff_2fa_setup', 'staff_2fa_verify', 'admin_whatsapp_manager', 'admin_whatsapp_status',
}
ALLOWED_DENIALS = (400, 401, 403, 404, 405)


class CrossGomIsolationTests(RouteFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.gom_a = self.ceg.gom
        # Dados do GOM A com marcas fáceis de procurar
        self.joiner.name = 'Joana SegredoA'
        self.joiner.save()
        self.slot.claimed_by = self.joiner
        self.slot.status = ItemSlot.Status.RESERVED
        self.slot.save()
        Claim.objects.create(slot=self.slot, participant=self.joiner, total_price=self.slot.price)
        self.caixa.gom = self.gom_a
        self.caixa.save()
        self.ceg.caixa = self.caixa
        self.ceg.save()

        self.gom_b = Gom.objects.create(name='Loja B', slug='loja-b')
        self.member_b = get_user_model().objects.create_user('membro-b', password='x')
        GomMembership.objects.create(user=self.member_b, gom=self.gom_b, role='OWNER')
        self.client.force_login(self.member_b)

    def _snapshot(self):
        return {
            'ceg': CEG.objects.filter(pk=self.ceg.pk).values('title', 'status', 'caixa_id', 'gom_id').first(),
            'slot': ItemSlot.objects.filter(pk=self.slot.pk).values(
                'status', 'claimed_by_id', 'is_item_paid', 'price', 'pacote_nacional_id').first(),
            'caixa': Caixa.objects.filter(pk=self.caixa.pk).values('nome', 'status', 'gom_id').first(),
            'item': ItemIndividual.objects.filter(pk=self.item_individual.pk).values(
                'nome', 'caixa_id', 'produto_pago', 'pacote_nacional_id').first(),
            'pacote': PacoteNacional.objects.filter(pk=self.pacote.pk).values('status', 'gom_id').first(),
            'vitrine': ItemVitrine.objects.filter(pk=self.vitrine.pk).values('titulo', 'status').first(),
            'notif': GOMNotification.objects.filter(pk=self.gom_notif.pk).values('is_read').first(),
            'joiner': Participant.objects.filter(pk=self.joiner.pk).values('name', 'social_handle').first(),
        }

    def _leaks(self, response):
        if response.status_code != 200:
            return []
        body = response.content.decode('utf-8', 'ignore')
        return [secret for secret in SECRETS if secret in body]

    def test_list_pages_of_gom_b_show_nothing_from_gom_a(self):
        problems = []
        for route, name in iter_routes():
            if name in NOT_GOM_DATA or '<' in route:
                continue
            res = self.client.get('/' + route)
            leaked = self._leaks(res)
            if leaked:
                problems.append(f"GET /{route} ({name}) mostra {leaked}")
        self.assertEqual(problems, [], "Telas do GOM B com dados do GOM A:\n" + "\n".join(problems))

    def test_gom_b_cannot_read_or_change_objects_of_gom_a(self):
        before = self._snapshot()
        problems = []
        for route, name in iter_routes():
            if name in NOT_GOM_DATA or '<' not in route:
                continue
            url = self._build(route)
            for method in ('get', 'post'):
                res = getattr(self.client, method)(url)
                leaked = self._leaks(res)
                if leaked:
                    problems.append(f"{method.upper()} {url} ({name}) mostra {leaked}")
                elif res.status_code == 200 and 'application/json' in res.get('Content-Type', ''):
                    data = json.loads(res.content or b'{}')
                    if isinstance(data, dict) and data.get('success') is True:
                        problems.append(f"{method.upper()} {url} ({name}) executou: {str(data)[:120]}")
                elif res.status_code not in ALLOWED_DENIALS + (200, 302):
                    problems.append(f"{method.upper()} {url} ({name}) -> {res.status_code}")
        self.assertEqual(problems, [], "Rotas que expõem o GOM A:\n" + "\n".join(problems))
        self.assertEqual(self._snapshot(), before, "O GOM B alterou dados do GOM A.")

    def test_public_ceg_page_hides_joiner_contacts_and_staff_tools_from_other_gom(self):
        res = self.client.get(f'/ceg/{self.ceg.slug}/')
        self.assertEqual(res.status_code, 200)
        body = res.content.decode()
        self.assertNotIn('900000009', body)
        self.assertFalse(res.context['is_gom_staff'])
        self.assertEqual(res.context['all_participants'], [])

    def test_joiner_lookup_and_participant_lists_are_scoped(self):
        res = self.client.get('/api/participants/lookup/', {'phone': self.joiner.whatsapp})
        self.assertFalse(res.json()['found'])
        self.assertFalse(Participant.objects.for_gom(self.gom_b).filter(pk=self.joiner.pk).exists())
        self.assertTrue(Participant.objects.for_gom(self.gom_a).filter(pk=self.joiner.pk).exists())

    def test_objects_created_by_gom_b_belong_to_gom_b(self):
        res = self.client.post('/caixas/create/', {'nome': 'Caixa da Loja B', 'origem': 'KR', 'status': 'EM_CONSOLIDACAO'})
        self.assertIn(res.status_code, (200, 302))
        caixa_b = Caixa.objects.get(nome='Caixa da Loja B')
        self.assertEqual(caixa_b.gom, self.gom_b)
        self.assertEqual(self.client.get('/caixas/').status_code, 200)
        self.assertContains(self.client.get('/caixas/'), 'Caixa da Loja B')
