"""Quadro de Envios: uma coluna por etapa com a próxima ação; a lista continua disponível."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import PacoteNacional
from apps.participants.models import Participant


class EnviosQuadroTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser('gom-q', 'q@x.com', 'x'))
        self.joiner = Participant.objects.create(whatsapp='5511944443333', name='Joiner Quadro')
        S = PacoteNacional.Status
        self.pac = {st: PacoteNacional.objects.create(participant=self.joiner, status=st) for st in
                    (S.SOLICITADO, S.EM_PREPARACAO, S.ENVIADO, S.ENTREGUE)}
        self.url = reverse('envios_nacionais')

    def test_board_is_default_with_one_lane_per_stage_and_next_action(self):
        res = self.client.get(self.url)
        lanes = res.context['lanes']
        self.assertEqual([lane['count'] for lane in lanes], [1, 1, 1, 1])
        page = res.content.decode()
        for text in ('Cotar frete', 'Despachar', 'Marcar entregue', 'aria-label="Pacotes por etapa"'):
            self.assertIn(text, page)

    def test_list_view_keeps_old_cards_and_metrics(self):
        res = self.client.get(self.url + '?view=lista')
        self.assertEqual(res.context['view_mode'], 'lista')
        self.assertNotContains(res, 'aria-label="Pacotes por etapa"')

    def test_delivered_lane_shows_only_recent_ones(self):
        for _ in range(13):
            PacoteNacional.objects.create(participant=self.joiner, status=PacoteNacional.Status.ENTREGUE)
        lane = self.client.get(self.url).context['lanes'][3]
        self.assertEqual((lane['count'], len(lane['pacotes']), lane['hidden']), (14, 12, 2))

    def test_mark_delivered_ignores_external_next(self):
        res = self.client.post(reverse('marcar_pacote_entregue', args=[self.pac['ENVIADO'].id]),
                               {'next': 'https://evil.example/'})
        self.assertNotIn('evil.example', res.url)
