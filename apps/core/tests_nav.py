from django.test import RequestFactory, TestCase

from apps.core.context_processors import frontend


class JoinerNavTests(TestCase):
    """Pagar, Meus itens e Envios só aparecem no menu para quem está logado."""

    def _keys(self, session):
        request = RequestFactory().get('/')
        request.session = session
        return [item['key'] for item in frontend(request)['joiner_nav']]

    def test_visitante_ve_so_as_secoes_publicas(self):
        self.assertEqual(self._keys({}), ['cegs', 'vitrine', 'caixinhas'])

    def test_joiner_logado_ve_tudo(self):
        self.assertEqual(self._keys({'participant_id': 1}), ['cegs', 'vitrine', 'caixinhas', 'pagar', 'itens', 'envios'])


class MenuMaisTests(TestCase):
    """No celular, "Mais" leva a Repasses e GOMs (que não cabem nas abas) para qualquer pessoa."""

    def test_visitante_ve_repasses_e_goms_no_mais(self):
        from django.urls import reverse
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('id="menu-mais-titulo"', html)
        self.assertIn(f'href="{reverse("gom_directory")}"', html)
        self.assertIn(f'href="{reverse("repasses_disponiveis")}"', html)
