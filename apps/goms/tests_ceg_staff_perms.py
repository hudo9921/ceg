"""Página da CEG mostra a cada admin só as ferramentas da permissão dele; o lote confere a permissão por ação."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot
from apps.groups.models import Era, KpopGroup

from .models import Gom, GomMembership
from .services import set_permissions

User = get_user_model()


class CegStaffPermissionTests(TestCase):
    def setUp(self):
        self.gom = Gom.objects.create(name='Loja S', slug='loja-s')
        self.owner = User.objects.create_user('dono-s', password='x')
        GomMembership.objects.create(user=self.owner, gom=self.gom, role='OWNER')
        era = Era.objects.create(group=KpopGroup.objects.create(name='aespa', slug='aespa-s'), name='Rich', slug='rich-s')
        self.ceg = CEG.objects.create(era=era, gom=self.gom, title='CEG S', slug='ceg-s', status=CEG.Status.OPEN)
        CEGItemDefinition.objects.create(ceg=self.ceg, name='PC Karina', default_price=40)
        cset = CEGSet.objects.create(ceg=self.ceg, set_number=1)
        cset.generate_slots()
        self.slot = cset.slots.first()

    def _admin(self, perms):
        user = User.objects.create_user(f'adm-{len(perms)}-{"-".join(perms)}', password='x')
        set_permissions(GomMembership.objects.create(user=user, gom=self.gom, role='ADMIN'), perms, self.owner)
        self.client.force_login(user)

    def _page(self):
        return self.client.get(reverse('ceg_detail', args=['ceg-s'])).content.decode()

    def _bulk(self, action, **extra):
        return self.client.post(reverse('bulk_manage_ceg_items', args=['ceg-s']),
                                data=json.dumps({'action': action, 'slot_ids': [self.slot.id], **extra}),
                                content_type='application/json')

    def test_payments_only_admin_sees_payment_tools_not_edit_or_delete(self):
        self._admin(['pag.confirmar'])
        page = self._page()
        self.assertIn("toggle('item')", page)
        self.assertNotIn('<span>Editar</span>', page)
        self.assertNotIn('Excluir esta CEG', page)
        self.assertNotIn('<span>Preço em Massa</span>', page)

    def test_edit_only_admin_does_not_see_payment_toggles_or_delete(self):
        self._admin(['ceg.editar'])
        page = self._page()
        self.assertIn('<span>Editar</span>', page)
        self.assertNotIn("toggle('item')", page)
        self.assertNotIn('Excluir esta CEG', page)

    def test_owner_sees_everything(self):
        self.client.force_login(self.owner)
        page = self._page()
        for text in ('<span>Editar</span>', "toggle('item')", 'Excluir esta CEG', 'Fila e logs', 'Alocar joiners'):
            self.assertIn(text, page)

    def test_bulk_payment_needs_payment_permission(self):
        self._admin(['ceg.editar'])
        self.assertEqual(self._bulk('bulk_payment', field='item', value=True).status_code, 403)

    def test_bulk_delete_needs_delete_permission(self):
        self._admin(['ceg.editar', 'pag.confirmar'])
        self.assertEqual(self._bulk('delete_slots').status_code, 403)
        self.assertTrue(ItemSlot.objects.filter(pk=self.slot.pk).exists())
