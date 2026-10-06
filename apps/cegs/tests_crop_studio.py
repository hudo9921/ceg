import io
import json
import base64
from decimal import Decimal
from PIL import Image
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from apps.groups.models import KpopGroup, Era
from apps.cegs.models import CEG, CEGItemDefinition, CEGSet, ItemSlot
from apps.cegs.image_utils import crop_image_from_coordinates, process_image_upload


class CropStudioBackendTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser('admin_crop', 'crop@test.com', 'crop123')
        self.group = KpopGroup.objects.create(name='aespa', slug='aespa')
        self.era = Era.objects.create(group=self.group, name='Armageddon', slug='armageddon')
        self.ceg = CEG.objects.create(
            era=self.era,
            title='aespa Armageddon POB',
            slug='aespa-armageddon-pob',
            status=CEG.Status.OPEN,
            banner_url='/media/cegs/banner_test.jpg'
        )
        self.item_karina = CEGItemDefinition.objects.create(
            ceg=self.ceg,
            name='Photocard Karina',
            member_name='Karina',
            default_price=Decimal('50.00'),
            order_index=1
        )

        # Imagem sintética de teste em memória
        img = Image.new('RGB', (200, 200), color='purple')
        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        self.img_bytes = buf.getvalue()
        self.img_b64 = 'data:image/jpeg;base64,' + base64.b64encode(self.img_bytes).decode('utf-8')

    def test_crop_image_from_coordinates_direct(self):
        """Testa a função auxiliar de recorte direto usando Pillow."""
        url = crop_image_from_coordinates(source_bytes=self.img_bytes, x=10, y=20, width=80, height=120)
        self.assertTrue(url)
        self.assertIn('/media/items/item_', url)

    def test_crop_item_photo_view_anonymous_denied(self):
        """Visitante anônimo não pode recortar ou alterar fotos de itens."""
        url = reverse('crop_ceg_item_photo', kwargs={'slug': self.ceg.slug, 'item_def_id': self.item_karina.id})
        res = self.client.post(url, {'base64_data': self.img_b64}, content_type='application/json')
        self.assertEqual(res.status_code, 403)

    def test_crop_item_photo_view_staff_base64_success(self):
        """Organizador staff envia recorte Base64 e atualiza a imagem do item com sucesso."""
        self.client.login(username='admin_crop', password='crop123')
        url = reverse('crop_ceg_item_photo', kwargs={'slug': self.ceg.slug, 'item_def_id': self.item_karina.id})
        res = self.client.post(url, {'base64_data': self.img_b64}, content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['image_url'])

        self.item_karina.refresh_from_db()
        self.assertEqual(self.item_karina.image_url, data['image_url'])

    def test_crop_item_photo_view_staff_coordinates_fallback(self):
        """Organizador staff envia coordenadas e o backend faz o recorte com Pillow."""
        self.client.login(username='admin_crop', password='crop123')
        url = reverse('crop_ceg_item_photo', kwargs={'slug': self.ceg.slug, 'item_def_id': self.item_karina.id})
        res = self.client.post(url, {
            'source_url': self.img_b64,
            'x': 10,
            'y': 10,
            'width': 50,
            'height': 75
        }, content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['image_url'])

        self.item_karina.refresh_from_db()
        self.assertEqual(self.item_karina.image_url, data['image_url'])

    def test_create_ceg_view_with_cropped_item_image(self):
        """Ao criar uma CEG no Hub de Criações, itens com foto recortada em Base64 são salvos no storage."""
        self.client.login(username='admin_crop', password='crop123')
        url = reverse('create_ceg')
        items_payload = [
            {
                'name': 'Photocard Winter',
                'member_name': 'Winter',
                'default_price': '55.00',
                'image_base64': self.img_b64,
                'order_index': 1
            }
        ]
        res = self.client.post(url, {
            'era_id': self.era.id,
            'title': 'aespa Whiplash POB',
            'status': CEG.Status.OPEN,
            'items_json': json.dumps(items_payload),
            'initial_sets_count': 1,
            'pix_key': 'pix@test.com'
        })
        self.assertEqual(res.status_code, 302)
        created_ceg = CEG.objects.get(title='aespa Whiplash POB')
        winter_def = created_ceg.item_definitions.first()
        self.assertIsNotNone(winter_def)
        self.assertEqual(winter_def.member_name, 'Winter')
        self.assertTrue(winter_def.image_url)
        self.assertIn('/media/items/item_', winter_def.image_url)
