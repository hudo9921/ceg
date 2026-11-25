from django.test import RequestFactory, TestCase

from apps.core.context_processors import frontend


class JoinerNavTests(TestCase):
    """Pagar, Meus itens e Envios só aparecem no menu para quem está logado."""

    def _keys(self, session):
        request = RequestFactory().get('/')
        request.session = session
        return [item['key'] for item in frontend(request)['joiner_nav']]

    def test_visitante_ve_so_cegs_e_vitrine(self):
        self.assertEqual(self._keys({}), ['cegs', 'vitrine'])

    def test_joiner_logado_ve_tudo(self):
        self.assertEqual(self._keys({'participant_id': 1}), ['cegs', 'vitrine', 'pagar', 'itens', 'envios'])
