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


class ImprimirPacotesTests(EnviosQuadroTests):
    def test_print_selected_package_shows_address_and_logs(self):
        from apps.cegs.models import AuditLog
        pac = self.pac['EM_PREPARACAO']
        pac.endereco_destinatario = 'Ana Souza\nRua A, 1\nCentro — SP/SP\nCEP 01001-000'
        pac.save()
        page = self.client.get(reverse('imprimir_pacotes') + f'?ids={pac.id}').content.decode()
        self.assertIn('Rua A, 1', page)
        self.assertIn(pac.identificador, page)
        self.assertTrue(AuditLog.objects.filter(event_type=AuditLog.EventType.PII_ACCESS, pacote_nacional=pac).exists())

    def test_print_whole_stage(self):
        res = self.client.get(reverse('imprimir_pacotes') + '?status=EM_PREPARACAO')
        self.assertEqual(len(res.context['pacotes']), 1)

    def test_no_filter_prints_nothing(self):
        self.assertEqual(len(self.client.get(reverse('imprimir_pacotes')).context['pacotes']), 0)


class ExportarPacotesTests(TestCase):
    """Planilha de envios: endereço em colunas, só a etapa pedida, e cada endereço registrado na Auditoria."""
    setUp = EnviosQuadroTests.setUp

    def _linhas(self, query):
        import csv
        import io
        res = self.client.get(reverse('exportar_pacotes') + query)
        self.assertEqual(res['Content-Type'], 'text/csv; charset=utf-8')
        return list(csv.reader(io.StringIO(res.content.decode('utf-8-sig')), delimiter=';'))

    def test_endereco_em_colunas_e_auditoria(self):
        from apps.cegs.models import AuditLog
        from apps.participants.models import Endereco
        pac = self.pac['EM_PREPARACAO']
        end = Endereco(nome_destinatario='Ana Souza', cep='01001000', logradouro='Rua A', numero='10',
                       complemento='Apto 2', bairro='Centro', cidade='São Paulo', uf='SP')
        pac.endereco_destinatario = end.texto_completo()
        pac.save()
        linhas = self._linhas('?etapa=EM_PREPARACAO')
        self.assertEqual(len(linhas), 2)
        cab, linha = linhas
        dados = dict(zip(cab, linha))
        self.assertEqual((dados['Destinatário'], dados['CEP'], dados['Rua'], dados['Número'], dados['Complemento'],
                          dados['Bairro'], dados['Cidade'], dados['UF']),
                         ('Ana Souza', '01001000', 'Rua A', '10', 'Apto 2', 'Centro', 'São Paulo', 'SP'))
        self.assertTrue(AuditLog.objects.filter(event_type=AuditLog.EventType.PII_ACCESS, pacote_nacional=pac).exists())

    def test_abertos_traz_solicitados_e_em_preparacao(self):
        self.assertEqual(len(self._linhas('?etapa=abertos')), 3)

    def test_endereco_antigo_fica_no_texto_completo(self):
        pac = self.pac['SOLICITADO']
        pac.endereco_destinatario = 'Rua qualquer 123 Recife'
        pac.save()
        dados = dict(zip(*self._linhas('?etapa=SOLICITADO')))
        self.assertEqual((dados['Rua'], dados['Endereço completo']), ('', 'Rua qualquer 123 Recife'))

    def test_outro_gom_nao_aparece(self):
        from apps.goms.models import Gom
        outro = Gom.objects.create(name='Outro', slug='outro')
        PacoteNacional.objects.create(gom=outro, participant=self.joiner, status=PacoteNacional.Status.SOLICITADO)
        self.assertEqual(len(self._linhas('?etapa=SOLICITADO')), 2)
