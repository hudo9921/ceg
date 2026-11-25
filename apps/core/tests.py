"""
Matriz de permissões: percorre TODAS as rotas do projeto e garante que nenhuma rota
não pública responda com sucesso para visitantes anônimos ou joiners logados.

Os parâmetros de URL apontam para objetos reais, para que uma view sem proteção
responda 200/redirect de sucesso (e o teste falhe) em vez de 404.

Ao criar uma rota nova:
- exclusiva da GOM: proteja com `apps.core.permissions.StaffRequiredMixin` (nada a fazer aqui);
- pública ou do joiner: adicione o nome dela em PUBLIC_ROUTES ou PARTICIPANT_ROUTES.
"""
import re
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import get_resolver, URLPattern, URLResolver
from django.utils import timezone

from apps.cegs.models import (
    CEG, CEGItemDefinition, CEGSet, ItemSlot, Caixa, ItemIndividual, PacoteNacional,
    ItemVitrine, GOMNotification, TipoItem,
)
from apps.cegs.services import ClaimService
from apps.groups.models import KpopGroup, Era
from apps.participants.models import Participant, ParticipantNotification

# Rotas abertas a qualquer visitante (podem responder 200 para anônimos).
PUBLIC_ROUTES = {
    'health_check', 'home', 'ceg_detail', 'ceg_polling_summary_api', 'caixa_detail',
    'vitrine_list', 'login_otp', 'logout_participant', 'privacy_policy',
    'backoffice_login', 'gom_invite_accept', 'gom_public', 'gom_directory',
}
# Rotas do joiner: anônimo precisa ser mandado para o login OTP; joiner logado pode usar.
PARTICIPANT_ROUTES = {
    'my_claims', 'update_profile', 'mark_notification_read', 'mark_all_notifications_read',
    'confirmar_entrega_pacote', 'cancelar_solicitacao_envio', 'solicitar_envio_nacional',
    'claim_slot', 'bulk_claim', 'ceg_vote', 'export_my_data', 'request_data_deletion', 'gom_rules_accept',
    'pix_gerar', 'pix_ver', 'pix_paguei', 'pix_cancelar', 'endereco_salvar', 'endereco_excluir', 'endereco_cep',
    'joiner_mensagens', 'joiner_mensagem_nova', 'joiner_mensagem_enviar', 'joiner_mensagens_novas',
    'vitrine_reservar', 'joiner_reserva_cancelar',
}
LOGIN_PREFIXES_ANON = ('/entrar/', '/admin/login/', '/me/login/')
LOGIN_PREFIXES_STAFF = ('/entrar/', '/admin/login/')

PARAM_RE = re.compile(r'<(?:(?P<conv>\w+):)?(?P<name>\w+)>')


def iter_routes(patterns=None, prefix=''):
    """Gera (rota_completa, nome) para todas as rotas do projeto, exceto o Django admin."""
    if patterns is None:
        patterns = get_resolver().url_patterns
    for p in patterns:
        route = str(p.pattern)
        if isinstance(p, URLResolver):
            if getattr(p, 'namespace', None) == 'admin':
                continue
            yield from iter_routes(p.url_patterns, prefix + route)
        elif isinstance(p, URLPattern):
            yield prefix + route, p.name


class RouteFixtures:
    """Um objeto de cada tipo (no GOM padrão) e montagem de URLs para varrer todas as rotas."""

    def setUp(self):
        ClaimService.reset_in_memory_counters()
        group = KpopGroup.objects.create(name="tripleS")
        era = Era.objects.create(group=group, name="Assemble24")
        self.tipo = TipoItem.objects.create(nome='Photocard Matriz')
        self.caixa = Caixa.objects.create(nome='Caixa Matriz')
        self.ceg = CEG.objects.create(
            era=era, title="CEG Matriz", status=CEG.Status.OPEN,
            opens_at=timezone.now() - timedelta(minutes=1), pix_key="pix@test.com",
        )
        self.item_def = CEGItemDefinition.objects.create(
            ceg=self.ceg, name="PC Seoyeon", member_name="Seoyeon", default_price=Decimal("50.00"),
        )
        self.cset = CEGSet.objects.create(ceg=self.ceg, set_number=1, is_active=True)
        self.slot = ItemSlot.objects.create(
            set=self.cset, item_definition=self.item_def, price=Decimal("50.00"),
            status=ItemSlot.Status.AVAILABLE,
        )
        self.joiner = Participant.objects.create(name="Joiner", whatsapp="5511900000009")
        self.item_individual = ItemIndividual.objects.create(
            nome='PC Mercari', caixa=self.caixa, comprador=self.joiner,
            tipo_item=self.tipo, preco_produto=Decimal('80.00'),
        )
        self.pacote = PacoteNacional.objects.create(
            identificador='PAC-MATRIZ', participant=self.joiner,
            status=PacoteNacional.Status.SOLICITADO,
        )
        self.vitrine = ItemVitrine.objects.create(
            titulo='Item Matriz', tipo_item=self.tipo, group=group, era=era,
            preco=Decimal('55.00'), quantidade=1, status=ItemVitrine.Status.DISPONIVEL,
        )
        self.gom_notif = GOMNotification.objects.create(
            notification_type=GOMNotification.NotificationType.CLAIM,
            title='Matriz', message='Matriz', participant=self.joiner, ceg=self.ceg,
        )
        self.joiner_notif = ParticipantNotification.objects.create(
            participant=self.joiner, title='Matriz', message='Matriz',
            notification_type=ParticipantNotification.NotificationType.SET_CANCELLED,
        )

    def _value_for(self, route, name):
        if name == 'slug':
            if route.startswith('caixas/'):
                return self.caixa.slug
            if route.startswith('vitrine/'):
                return self.vitrine.slug
            return self.ceg.slug
        if name == 'notification_id':
            return self.joiner_notif.id if route.startswith('me/') else self.gom_notif.id
        return {
            'slot_id': self.slot.id, 'set_id': self.cset.id, 'item_def_id': self.item_def.id,
            'item_id': self.item_individual.id, 'ceg_id': self.ceg.id,
            'pacote_id': self.pacote.id, 'pk': self.tipo.id, 'token': 'token-invalido', 'tab': 'perfil', 'ref': 'VC-XXXXX',
            'participant_id': self.joiner.id, 'endereco_id': 1, 'cep': '01001000', 'conversa_id': 1, 'reserva_id': 1, 'acao': 'paga',
        }[name]

    def _build(self, route):
        return '/' + PARAM_RE.sub(lambda m: str(self._value_for(route, m.group('name'))), route)


class RoutePermissionMatrixTests(RouteFixtures, TestCase):
    def _protected_routes(self, skip):
        routes = [(r, n) for r, n in iter_routes() if n not in skip]
        self.assertGreater(len(routes), 50, "A varredura de rotas encontrou poucas rotas.")
        return routes

    def _assert_denied(self, allowed_login_prefixes):
        problems = []
        skip = PUBLIC_ROUTES | (PARTICIPANT_ROUTES if allowed_login_prefixes != LOGIN_PREFIXES_ANON else set())
        for route, name in self._protected_routes(skip):
            url = self._build(route)
            for method in ('get', 'post'):
                res = getattr(self.client, method)(url)
                if res.status_code in (401, 403, 405):
                    continue
                location = res.get('Location', '') if res.status_code in (301, 302) else ''
                if allowed_login_prefixes and location.startswith(allowed_login_prefixes):
                    continue
                problems.append(f"{method.upper()} {url} ({name}) -> {res.status_code} {location}")
        self.assertEqual(problems, [], "Rotas sem proteção:\n" + "\n".join(problems))

    def test_anonymous_cannot_use_non_public_routes(self):
        self._assert_denied(LOGIN_PREFIXES_ANON)

    def test_logged_joiner_cannot_use_staff_routes(self):
        session = self.client.session
        session['participant_id'] = self.joiner.id
        session.save()
        self._assert_denied(LOGIN_PREFIXES_STAFF)

    def test_logged_non_staff_user_gets_403_on_staff_routes(self):
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.create_user('comum', password='x'))
        self._assert_denied(allowed_login_prefixes=())

    @override_settings(STAFF_2FA_REQUIRED=True)
    def test_staff_without_2fa_cannot_use_any_route(self):
        """Staff que só passou pela senha não usa nenhuma rota além das telas de 2FA."""
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.create_user('gom', password='x', is_staff=True))
        exempt = {'staff_2fa_setup', 'staff_2fa_verify', 'health_check'}
        problems = []
        for route, name in iter_routes():
            if name in exempt:
                continue
            url = self._build(route)
            for method in ('get', 'post'):
                res = getattr(self.client, method)(url)
                if res.status_code in (401, 403, 405):
                    continue
                if res.status_code == 302 and res['Location'].startswith('/admin/seguranca/2fa/'):
                    continue
                problems.append(f"{method.upper()} {url} ({name}) -> {res.status_code}")
        self.assertEqual(problems, [], "Rotas acessíveis sem 2FA:\n" + "\n".join(problems))

    def test_every_public_and_participant_route_exists(self):
        names = {n for _, n in iter_routes()}
        self.assertEqual((PUBLIC_ROUTES | PARTICIPANT_ROUTES) - names, set())
