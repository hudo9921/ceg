"""Seguir grupos/integrantes: página e alternar, sem aviso de CEG nova, e personalização da home e da loja."""
import json
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot
from apps.goms.models import Gom
from apps.groups.models import Era, GroupMember, KpopGroup

from .models import Participant, ParticipantNotification, Seguindo
from .seguindo import preferencias, relevancia


class SeguirFixture(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja Seg', slug='loja-seg')
        self.aespa = KpopGroup.objects.create(name='aespa', slug='aespa-sg')
        self.karina = GroupMember.objects.create(group=self.aespa, name='Karina')
        GroupMember.objects.create(group=self.aespa, name='Winter')
        self.ive = KpopGroup.objects.create(name='IVE', slug='ive-sg')
        self.ana = Participant.objects.create(whatsapp='5511911110000', name='Ana')

    def ceg(self, grupo, membro, titulo, status=CEG.Status.OPEN):
        era = Era.objects.create(group=grupo, name=f'Era {titulo}', slug=f'era-{titulo}')
        ceg = CEG.objects.create(era=era, gom=self.gom, title=titulo, slug=titulo, status=CEG.Status.DRAFT)
        idef = CEGItemDefinition.objects.create(ceg=ceg, name=f'PC {membro}', member_name=membro, default_price=30)
        ItemSlot.objects.create(set=CEGSet.objects.create(ceg=ceg, set_number=1), item_definition=idef, price=Decimal('30'))
        if status != CEG.Status.DRAFT:
            ceg.status = status
            with self.captureOnCommitCallbacks(execute=True):
                ceg.save()
        return ceg

    def entrar(self):
        session = self.client.session
        session['participant_id'] = self.ana.id
        session.save()


class SeguirTests(SeguirFixture):
    def test_alternar_grupo_e_integrante(self):
        self.entrar()
        url = reverse('seguindo_alternar')
        res = self.client.post(url, json.dumps({'member_id': self.karina.id}), content_type='application/json').json()
        self.assertTrue(res['seguindo'])
        self.client.post(url, json.dumps({'group_id': self.ive.id}), content_type='application/json')
        prefs = preferencias(self.ana)
        self.assertEqual((prefs.grupos, set(prefs.membros)), ({self.ive.id}, {self.aespa.id}))
        res = self.client.post(url, json.dumps({'group_id': self.ive.id}), content_type='application/json').json()
        self.assertFalse(res['seguindo'])
        busca = self.client.get(reverse('seguindo_buscar'), {'q': 'aespa'}).json()['grupos'][0]
        self.assertEqual([(m['name'], m['seguindo']) for m in busca['members']], [('Karina', True), ('Winter', False)])

    def test_sem_login(self):
        res = self.client.post(reverse('seguindo_alternar'), json.dumps({'group_id': self.ive.id}), content_type='application/json')
        self.assertEqual(res.status_code, 401)
        self.assertRedirects(self.client.get(reverse('seguindo')), '/me/login/?next=/me/seguindo/', fetch_redirect_response=False)

    def test_criar_ceg_nao_notifica_quem_segue(self):
        Seguindo.objects.create(participant=self.ana, group=self.aespa, member=self.karina)
        self.ceg(self.aespa, 'Karina', 'sem-spam')
        self.assertFalse(ParticipantNotification.objects.filter(participant=self.ana).exists())


class PersonalizacaoTests(SeguirFixture):
    def test_relevancia_e_home(self):
        Seguindo.objects.create(participant=self.ana, group=self.aespa, member=self.karina)
        winter = self.ceg(self.aespa, 'Winter', 'winter')
        karina = self.ceg(self.aespa, 'Karina', 'karina')
        ive = self.ceg(self.ive, 'Wonyoung', 'wonyoung')
        prefs = preferencias(self.ana)
        self.assertEqual([relevancia(c, prefs)[0] for c in (karina, winter, ive)], [2, 1, 0])
        self.entrar()
        res = self.client.get(reverse('home'))
        self.assertEqual([c.slug for c in res.context['para_voce']], ['karina', 'winter'])
        self.assertContains(res, 'com Karina')

    def test_loja_mostra_quem_sigo_primeiro(self):
        self.ceg(self.aespa, 'Karina', 'karina-loja')
        self.ceg(self.ive, 'Wonyoung', 'ive-loja')  # mais recente
        url = reverse('gom_public', args=[self.gom.slug])
        self.assertEqual([c.slug for c in self.client.get(url).context['resultados']][0], 'ive-loja')
        Seguindo.objects.create(participant=self.ana, group=self.aespa, member=self.karina)
        self.entrar()
        self.assertEqual([c.slug for c in self.client.get(url).context['resultados']][0], 'karina-loja')
        itens = self.client.get(url, {'vista': 'itens'}).context['resultados']
        self.assertEqual(itens[0]['titulo'], 'Karina')
