"""Chaves Pix padrão do GOM por tipo de cobrança e a hierarquia de resolução."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG, Caixa, PacoteNacional
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Participant

from .models import Gom, GomMembership


class GomDefaultPixTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(
            name='Loja Pix', slug='loja-pix',
            default_pix_key='gom-itens', default_pix_instructions='Banco A',
            default_pix_key_frete='gom-frete', default_pix_key_taxa='gom-taxa',
            default_pix_key_frete_nacional='gom-nacional', default_pix_instructions_frete_nacional='Envie o comprovante',
        )
        self.era = Era.objects.create(group=KpopGroup.objects.create(name='NMIXX'), name='Fe3O4')

    def _ceg(self, **kw):
        return CEG.objects.create(gom=self.gom, era=self.era, title='CEG Pix', **kw)

    def test_ceg_without_keys_uses_gom_default_for_each_kind(self):
        ceg = self._ceg()
        self.assertEqual(ceg.get_pix_key_item(), 'gom-itens')
        self.assertEqual(ceg.get_pix_instructions_item(), 'Banco A')
        self.assertEqual(ceg.get_pix_key_frete(), 'gom-frete')
        self.assertEqual(ceg.get_pix_key_taxa(), 'gom-taxa')

    def test_specific_keys_win_over_gom_defaults(self):
        caixa = Caixa.objects.create(gom=self.gom, nome='Caixa Pix', pix_key_frete='caixa-frete')
        ceg = self._ceg(pix_key='ceg-itens', pix_key_taxa='ceg-taxa', caixa=caixa)
        self.assertEqual(ceg.get_pix_key_item(), 'ceg-itens')
        self.assertEqual(ceg.get_pix_key_frete(), 'caixa-frete')   # caixa > tudo
        self.assertEqual(ceg.get_pix_key_taxa(), 'ceg-taxa')        # CEG (do tipo) > GOM
        self.assertEqual(caixa.get_pix_key_frete(), 'caixa-frete')
        self.assertEqual(caixa.get_pix_key_taxa(), 'ceg-taxa')

    def test_gom_kind_default_beats_ceg_general_key(self):
        ceg = self._ceg(pix_key='ceg-itens')
        self.assertEqual(ceg.get_pix_key_frete(), 'gom-frete')

    def test_kind_without_gom_key_falls_back_to_ceg_then_gom_items(self):
        self.gom.default_pix_key_frete = ''
        self.gom.save()
        self.assertEqual(self._ceg(pix_key='ceg-itens').get_pix_key_frete(), 'ceg-itens')
        self.assertEqual(self._ceg().get_pix_key_frete(), 'gom-itens')

    def test_same_key_for_frete_and_items_is_still_respected(self):
        self.gom.default_pix_key_frete = 'gom-itens'
        self.gom.save()
        self.assertEqual(self._ceg(pix_key='ceg-itens').get_pix_key_frete(), 'gom-itens')

    def test_national_shipping_uses_gom_key(self):
        joiner = Participant.objects.create(name='J', whatsapp='5511955554444')
        pacote = PacoteNacional.objects.create(gom=self.gom, participant=joiner, identificador='PAC-PIX')
        self.assertEqual(pacote.pix_key_frete_nacional, 'gom-nacional')
        self.assertEqual(pacote.pix_instructions_frete_nacional, 'Envie o comprovante')
        self.gom.default_pix_key_frete_nacional = ''
        self.gom.save()
        self.assertEqual(PacoteNacional.objects.get(pk=pacote.pk).pix_key_frete_nacional, 'gom-itens')

    def test_admin_sets_all_four_keys_in_profile(self):
        admin = get_user_model().objects.create_user('adm-pix', password='x')
        GomMembership.objects.create(user=admin, gom=self.gom, role='ADMIN')
        self.client.force_login(admin)
        data = {'name': 'Loja Pix', 'bio': '', 'whatsapp_contato': '', 'instagram': '', 'logo_url': '', 'banner_url': ''}
        for suffix, value in (('', 'k-item'), ('_frete', 'k-frete'), ('_taxa', 'k-taxa'), ('_frete_nacional', 'k-nac')):
            data[f'default_pix_key{suffix}'] = value
            data[f'default_pix_instructions{suffix}'] = f'inst{suffix}'
        self.client.post(reverse('gom_profile'), data)
        self.gom.refresh_from_db()
        self.assertEqual(
            [self.gom.pix_for(k)[0] for k in Gom.PIX_KINDS], ['k-item', 'k-frete', 'k-taxa', 'k-nac'])
