from django.test import TestCase, Client
from django.contrib.auth.models import User
from apps.participants.models import Participant, clean_phone_number
from apps.participants.services import BulkParticipantService


class BulkParticipantTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_superuser(
            username='staff_test',
            password='password123',
            email='staff@test.com'
        )
        self.client = Client()

    def test_clean_phone_number_brazilian(self):
        """Testa números brasileiros com e sem DDI 55, incluindo DDDs variados."""
        # 11 dígitos com DDD (celular SP)
        self.assertEqual(clean_phone_number('11 91234-5678'), '5511912345678')
        self.assertEqual(clean_phone_number('11912345678'), '5511912345678')
        self.assertEqual(clean_phone_number('(11) 91234-5678'), '5511912345678')

        # 10 dígitos com DDD (telefone fixo)
        self.assertEqual(clean_phone_number('11 3456-7890'), '551134567890')

        # Celular do RS com DDD 55 (sem DDI inicialmente)
        self.assertEqual(clean_phone_number('55 99999-8888'), '5555999998888')

        # Com DDI explícito +55
        self.assertEqual(clean_phone_number('+55 11 91234-5678'), '5511912345678')
        self.assertEqual(clean_phone_number('5511912345678'), '5511912345678')

        # Com zero ou operadora antes do DDD
        self.assertEqual(clean_phone_number('011 91234-5678'), '5511912345678')
        self.assertEqual(clean_phone_number('011912345678'), '5511912345678')
        self.assertEqual(clean_phone_number('015 11 91234-5678'), '5511912345678')
        self.assertEqual(clean_phone_number('+55 (011) 91234-5678'), '5511912345678')

    def test_phone_format_unification_and_login(self):
        """
        Garante que todas as variações de entrada (com traço, sem traço, com espaços,
        parênteses, com ou sem +55) sejam salvas no MESMO padrão canônico e que
        o login encontre o mesmo participante independente de como ele digitar.
        """
        # Formatos diversos digitados pelo usuário
        variations = [
            '11 91234-5678',
            '11912345678',
            '1191234-5678',
            '11 912345678',
            '(11) 91234-5678',
            '(11)91234-5678',
            '(11) 912345678',
            '+55 11 91234-5678',
            '+55 (11) 91234-5678',
            '+5511912345678',
            '55 11 91234-5678',
            '5511912345678',
            '011 91234-5678',
            '011912345678',
        ]

        # 1. Todas as variações convertem para o mesmo canônico
        canonical = '5511912345678'
        for v in variations:
            self.assertEqual(clean_phone_number(v), canonical, f"Falha na conversão de '{v}'")

        # 2. Salva participante com o primeiro formato
        p = Participant.objects.create(name='Bia Silva', whatsapp='11 91234-5678', social_handle='@biasilva')
        self.assertEqual(p.whatsapp, canonical)

        # 3. Testa login OTP usando diferentes variações de escrita do número
        from apps.auth_otp.services import OTPService
        # Solicita OTP usando formato com parênteses e traço
        success, msg, code = OTPService.send_otp('(11) 91234-5678')
        self.assertTrue(success)
        self.assertIsNotNone(code)

        # Confirma OTP usando formato colado '11912345678'
        success_v, msg_v, logged_p = OTPService.verify_otp('11912345678', code)
        self.assertTrue(success_v)
        self.assertEqual(logged_p.id, p.id)
        self.assertEqual(logged_p.name, 'Bia Silva')

        # 4. Testa via requisição HTTP do navegador
        # Envia formulário com '1191234-5678'
        res_send = self.client.post('/me/login/', {'action': 'send_otp', 'phone': '1191234-5678'})
        self.assertEqual(res_send.status_code, 302)

        # Recupera código gerado no banco para o canônico
        from apps.auth_otp.models import WhatsAppOTP
        otp_entry = WhatsAppOTP.objects.filter(phone=canonical, is_used=False).first()
        self.assertIsNotNone(otp_entry)

        # Confirma código digitando '+55 (11) 91234-5678'
        res_verify = self.client.post('/me/login/', {'action': 'verify_otp', 'phone': '+55 (11) 91234-5678', 'code': otp_entry.code})
        self.assertEqual(res_verify.status_code, 302)
        # Sessão autenticada aponta para o participante correto
        self.assertEqual(self.client.session.get('participant_id'), p.id)

    def test_clean_phone_number_international(self):
        """Testa números internacionais de diversos países com prefixo '+' ou '00'."""
        # EUA / Canadá (+1)
        self.assertEqual(clean_phone_number('+1 202 555 0199'), '12025550199')
        self.assertEqual(clean_phone_number('+1 (202) 555-0199'), '12025550199')

        # Coreia do Sul (+82)
        self.assertEqual(clean_phone_number('+82 10 1234 5678'), '821012345678')

        # Portugal (+351)
        self.assertEqual(clean_phone_number('+351 912 345 678'), '351912345678')

        # Reino Unido (+44)
        self.assertEqual(clean_phone_number('+44 7911 123456'), '447911123456')

        # Japão (+81)
        self.assertEqual(clean_phone_number('+81 90 1234 5678'), '819012345678')

        # Prefixo internacional com '00'
        self.assertEqual(clean_phone_number('001 202 555 0199'), '12025550199')
        self.assertEqual(clean_phone_number('0082 10 1234 5678'), '821012345678')

        # Com DDI padrão diferente de 55
        self.assertEqual(clean_phone_number('1012345678', default_country='82'), '821012345678')

    def test_participant_model_formatting_and_handles(self):
        """Testa a normalização automática de @ Twitter e formatação amigável de exibição."""
        # Twitter sem @ deve ganhar @
        p1 = Participant.objects.create(
            name='Maria Silva',
            whatsapp='11 98888-7777',
            social_handle='mariasilva'
        )
        self.assertEqual(p1.social_handle, '@mariasilva')
        self.assertEqual(p1.whatsapp, '5511988887777')
        self.assertEqual(p1.formatted_phone, '+55 (11) 98888-7777')

        # Twitter já com @ deve ser mantido
        p2 = Participant.objects.create(
            name='John Walker',
            whatsapp='+1 202 555 0199',
            social_handle='@jwalker'
        )
        self.assertEqual(p2.social_handle, '@jwalker')
        self.assertEqual(p2.whatsapp, '12025550199')
        self.assertEqual(p2.formatted_phone, '+1 (202) 555-0199')

        # Participante coreano
        p3 = Participant.objects.create(
            name='Kim Minji',
            whatsapp='+82 10 1234 5678',
            social_handle='minji_kpop'
        )
        self.assertEqual(p3.social_handle, '@minji_kpop')
        self.assertEqual(p3.whatsapp, '821012345678')
        self.assertEqual(p3.formatted_phone, '+82 10 1234-5678')

    def test_parse_pasted_text_various_formats(self):
        """Testa parsing de linhas com tabulações, vírgulas, pipes e cabeçalhos."""
        raw_text = """
Nome	Telefone	Twitter
Beatriz Lima	11 98888-7777	@bialima
John Walker	+1 202 555 0199	@jwalker
Kim Minji | +82 10 1234 5678 | @minjikim
Carlos Silva, 21977776666, carlossilva
        """
        items = BulkParticipantService.parse_pasted_text(raw_text, default_ddi='55')
        self.assertEqual(len(items), 4)

        # Item 1 (Brasil tabulado)
        self.assertEqual(items[0]['name'], 'Beatriz Lima')
        self.assertEqual(items[0]['whatsapp'], '5511988887777')
        self.assertEqual(items[0]['social_handle'], '@bialima')
        self.assertTrue(items[0]['is_valid'])

        # Item 2 (EUA com +1)
        self.assertEqual(items[1]['name'], 'John Walker')
        self.assertEqual(items[1]['whatsapp'], '12025550199')
        self.assertEqual(items[1]['social_handle'], '@jwalker')
        self.assertTrue(items[1]['is_valid'])

        # Item 3 (Coreia com pipe)
        self.assertEqual(items[2]['name'], 'Kim Minji')
        self.assertEqual(items[2]['whatsapp'], '821012345678')
        self.assertEqual(items[2]['social_handle'], '@minjikim')
        self.assertTrue(items[2]['is_valid'])

        # Item 4 (Brasil com vírgula e handle sem @)
        self.assertEqual(items[3]['name'], 'Carlos Silva')
        self.assertEqual(items[3]['whatsapp'], '5521977776666')
        self.assertEqual(items[3]['social_handle'], '@carlossilva')
        self.assertTrue(items[3]['is_valid'])

    def test_bulk_create_or_update_service(self):
        """Testa criação em lote e upsert de participantes existentes."""
        # Cria participante inicial
        Participant.objects.create(
            name='Nome Antigo',
            whatsapp='5511999990001',
            social_handle='@antigo'
        )

        items = [
            # Novo participante BR
            {'name': 'Novo BR', 'raw_phone': '11 99999-0002', 'social_handle': '@novobr'},
            # Novo participante Internacional
            {'name': 'Novo US', 'raw_phone': '+1 312 555 0100', 'social_handle': '@novous'},
            # Participante existente para atualizar
            {'name': 'Nome Atualizado', 'raw_phone': '11 99999-0001', 'social_handle': '@novo_handle'},
        ]

        report = BulkParticipantService.bulk_create_or_update(
            items=items,
            update_existing=True,
            default_ddi='55'
        )

        self.assertEqual(report['created_count'], 2)
        self.assertEqual(report['updated_count'], 1)
        self.assertEqual(report['errors_count'], 0)

        # Verifica se o existente foi devidamente atualizado
        updated_p = Participant.objects.get(whatsapp='5511999990001')
        self.assertEqual(updated_p.name, 'Nome Atualizado')
        self.assertEqual(updated_p.social_handle, '@novo_handle')

        # Verifica novos
        self.assertTrue(Participant.objects.filter(whatsapp='5511999990002').exists())
        self.assertTrue(Participant.objects.filter(whatsapp='13125550100').exists())

    def test_bulk_participant_views_auth_and_actions(self):
        """Testa o acesso à view BulkParticipantCreateView e os endpoints AJAX de parse e save."""
        url = '/me/participantes/em-massa/'

        # Sem login deve redirecionar para o login de admin
        res_anon = self.client.get(url)
        self.assertEqual(res_anon.status_code, 302)

        # Com login de staff deve retornar 200 OK
        self.client.force_login(self.staff_user)
        res_staff = self.client.get(url)
        self.assertEqual(res_staff.status_code, 200)
        self.assertContains(res_staff, 'Cadastro de Participantes em Massa')

        # POST AJAX action 'parse'
        res_parse = self.client.post(
            url,
            data={
                'action': 'parse',
                'raw_text': 'Lucas Silva\t11 98888-0000\t@lucas\nAna Fox\t+1 212 555 0188\t@ana',
                'default_ddi': '55'
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_parse.status_code, 200)
        parse_json = res_parse.json()
        self.assertTrue(parse_json['success'])
        self.assertEqual(len(parse_json['items']), 2)
        self.assertEqual(parse_json['items'][0]['whatsapp'], '5511988880000')
        self.assertEqual(parse_json['items'][1]['whatsapp'], '12125550188')

        # POST AJAX action 'save'
        res_save = self.client.post(
            url,
            data={
                'action': 'save',
                'items': parse_json['items'],
                'default_ddi': '55',
                'update_existing': True
            },
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_save.status_code, 200)
        save_json = res_save.json()
        self.assertTrue(save_json['success'])
        self.assertEqual(save_json['created_count'], 2)

        # Verifica criação no banco de dados
        self.assertTrue(Participant.objects.filter(whatsapp='5511988880000', name='Lucas Silva').exists())
        self.assertTrue(Participant.objects.filter(whatsapp='12125550188', name='Ana Fox').exists())
