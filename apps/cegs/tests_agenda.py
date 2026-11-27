"""Agenda de aberturas: só agendadas no futuro de GOMs ativos, por dia, filtro "só quem eu sigo" e o .ics."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cegs.models import CEG
from apps.goms.models import Gom
from apps.groups.models import Era, KpopGroup
from apps.participants.models import Participant, Seguindo


class AgendaTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja G', slug='loja-g')
        self.ive = KpopGroup.objects.create(name='IVE', slug='ive')
        aespa = KpopGroup.objects.create(name='aespa', slug='aespa')
        now = timezone.now()
        self.ive_ceg = CEG.objects.create(gom=self.gom, era=Era.objects.create(group=self.ive, name='SECRET'), title='IVE abre',
                                          slug='ive-abre', status=CEG.Status.SCHEDULED, opens_at=now + timedelta(days=1))
        CEG.objects.create(gom=self.gom, era=Era.objects.create(group=aespa, name='Rich Man'), title='aespa abre',
                           slug='aespa-abre', status=CEG.Status.SCHEDULED, opens_at=now + timedelta(days=2))
        CEG.objects.create(gom=self.gom, era=self.ive_ceg.era, title='IVE aberta', slug='ive-aberta', status=CEG.Status.OPEN)
        inativo = Gom.objects.create(name='Parado', slug='parado', is_active=False)
        CEG.objects.create(gom=inativo, era=self.ive_ceg.era, title='GOM parado', slug='gom-parado',
                           status=CEG.Status.SCHEDULED, opens_at=now + timedelta(days=1))

    def _titulos(self, res):
        return [c.title for d in res.context['dias'] for c in d['cegs']]

    def test_lista_so_agendadas_de_goms_ativos_em_ordem(self):
        res = self.client.get(reverse('agenda'))
        self.assertEqual(self._titulos(res), ['IVE abre', 'aespa abre'])
        self.assertTrue(res.context['dias'][0]['amanha'])

    def test_so_quem_eu_sigo(self):
        joiner = Participant.objects.create(whatsapp='5511933334444', name='Fã')
        Seguindo.objects.create(participant=joiner, group=self.ive)
        session = self.client.session
        session['participant_id'] = joiner.id
        session.save()
        res = self.client.get(reverse('agenda'), {'seguindo': '1'})
        self.assertEqual(self._titulos(res), ['IVE abre'])
        self.assertContains(res, 'você segue')

    def test_ics(self):
        res = self.client.get(reverse('agenda_ics', args=['ive-abre']))
        self.assertEqual(res['Content-Type'], 'text/calendar; charset=utf-8')
        corpo = res.content.decode()
        inicio = self.ive_ceg.opens_at.astimezone(timezone.get_fixed_timezone(0)).strftime('%Y%m%dT%H%M%SZ')
        self.assertIn(f'DTSTART:{inicio}', corpo)
        self.assertIn('TRIGGER:-PT15M', corpo)
        self.assertIn('SUMMARY:Abre: IVE abre', corpo)

    def test_ics_de_ceg_aberta_nao_existe(self):
        self.assertEqual(self.client.get(reverse('agenda_ics', args=['ive-aberta'])).status_code, 404)
