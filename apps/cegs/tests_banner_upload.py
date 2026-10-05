import base64
import io
from PIL import Image
from django.test import TestCase, Client, RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import RequestDataTooBig
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.urls import reverse
from apps.groups.models import KpopGroup, Era
from apps.cegs.models import CEG
from apps.cegs.image_utils import process_image_upload
from apps.cegs.middleware import UploadSizeExceptionMiddleware


class BannerUploadTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser('admin_banner', 'admin@test.com', 'adminpass123')
        self.client.login(username='admin_banner', password='adminpass123')

        self.group = KpopGroup.objects.create(name='Aespa', slug='aespa')
        self.era = Era.objects.create(group=self.group, name='Armageddon', slug='armageddon')
        self.ceg = CEG.objects.create(
            era=self.era,
            title='CEG Armageddon Test',
            slug='ceg-armageddon-test',
            status=CEG.Status.OPEN,
            banner_url='https://example.com/initial.jpg'
        )

    def _create_sample_image_bytes(self, width=800, height=600, color='blue', fmt='PNG'):
        buf = io.BytesIO()
        img = Image.new('RGB', (width, height), color=color)
        img.save(buf, format=fmt)
        return buf.getvalue()

    def test_process_image_upload_with_file(self):
        img_bytes = self._create_sample_image_bytes(100, 100, 'red')
        uploaded = SimpleUploadedFile("banner.png", img_bytes, content_type="image/png")
        url = process_image_upload(file_obj=uploaded, folder='cegs/banners')
        self.assertTrue(url)
        self.assertTrue(url.startswith('/') or url.startswith('http'))

    def test_process_image_upload_with_base64_data_uri(self):
        img_bytes = self._create_sample_image_bytes(50, 50, 'green')
        b64 = "data:image/png;base64," + base64.b64encode(img_bytes).decode('utf-8')
        url = process_image_upload(base64_str=b64, folder='cegs/banners')
        self.assertTrue(url)
        self.assertTrue(url.startswith('/') or url.startswith('http'))
        self.assertNotIn('data:image', url)

    def test_process_image_upload_intercepts_data_uri_in_fallback_url(self):
        """Se o usuário colar um Data URI de 50.000 caracteres no campo de URL, converte para arquivo no storage"""
        img_bytes = self._create_sample_image_bytes(60, 60, 'purple')
        large_data_uri = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode('utf-8')
        url = process_image_upload(fallback_url=large_data_uri, folder='cegs/banners')
        self.assertTrue(url)
        self.assertNotIn('data:image', url)
        self.assertLess(len(url), 500)

    def test_process_image_upload_rejects_oversized_raw_url(self):
        long_url = "https://example.com/" + ("a" * 600)
        url = process_image_upload(fallback_url=long_url)
        self.assertEqual(url, '')

    def test_process_image_upload_with_corrupted_base64(self):
        url = process_image_upload(base64_str="not-a-valid-base64-string!!!")
        self.assertEqual(url, '')

    def test_update_ceg_view_with_file_upload(self):
        img_bytes = self._create_sample_image_bytes(200, 200, 'pink')
        banner_file = SimpleUploadedFile("new_banner.jpg", img_bytes, content_type="image/jpeg")

        response = self.client.post(
            reverse('update_ceg', kwargs={'slug': self.ceg.slug}),
            {
                'title': 'CEG Armageddon Updated',
                'era_id': self.era.id,
                'status': 'OPEN',
                'banner_file': banner_file,
            },
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.ceg.refresh_from_db()
        self.assertEqual(self.ceg.title, 'CEG Armageddon Updated')
        self.assertTrue(self.ceg.banner_url)
        self.assertNotEqual(self.ceg.banner_url, 'https://example.com/initial.jpg')

    def test_update_ceg_view_with_data_uri_in_url_field(self):
        """Garante que colar Data URI no input de banner_url não gera erro 500 e salva URL válida no banco"""
        img_bytes = self._create_sample_image_bytes(50, 50, 'yellow')
        data_uri = "data:image/png;base64," + base64.b64encode(img_bytes).decode('utf-8')

        response = self.client.post(
            reverse('update_ceg', kwargs={'slug': self.ceg.slug}),
            {
                'title': self.ceg.title,
                'era_id': self.era.id,
                'status': 'OPEN',
                'banner_url': data_uri,
            },
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.ceg.refresh_from_db()
        self.assertTrue(self.ceg.banner_url)
        self.assertNotIn('data:image', self.ceg.banner_url)
        self.assertLess(len(self.ceg.banner_url), 500)

    def test_update_ceg_view_remove_banner(self):
        response = self.client.post(
            reverse('update_ceg', kwargs={'slug': self.ceg.slug}),
            {
                'title': self.ceg.title,
                'era_id': self.era.id,
                'status': 'OPEN',
                'remove_banner': '1',
            },
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.ceg.refresh_from_db()
        self.assertEqual(self.ceg.banner_url, '')

    def test_upload_size_exception_middleware(self):
        rf = RequestFactory()
        request = rf.post('/ceg/test/update/')
        request.user = self.admin

        # Configura storage de messages na request simulada
        setattr(request, 'session', 'session')
        messages_storage = FallbackStorage(request)
        setattr(request, '_messages', messages_storage)

        def mock_get_response(req):
            raise RequestDataTooBig("Exceeded limit")

        middleware = UploadSizeExceptionMiddleware(mock_get_response)
        response = middleware.process_exception(request, RequestDataTooBig("Exceeded limit"))
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 302)

    def test_process_image_upload_rejects_file_over_5mb(self):
        # Cria arquivo fictício de 6 MB
        large_bytes = b"0" * (6 * 1024 * 1024)
        large_file = SimpleUploadedFile("too_heavy.jpg", large_bytes, content_type="image/jpeg")

        with self.assertRaises(ValueError) as ctx:
            process_image_upload(file_obj=large_file, folder='cegs/banners')

        self.assertIn("ultrapassa o limite", str(ctx.exception))
        self.assertIn("5 MB", str(ctx.exception))

    def test_update_ceg_view_rejects_file_over_5mb(self):
        large_bytes = b"0" * (6 * 1024 * 1024)
        large_file = SimpleUploadedFile("too_heavy.jpg", large_bytes, content_type="image/jpeg")

        response = self.client.post(
            reverse('update_ceg', kwargs={'slug': self.ceg.slug}),
            {
                'title': self.ceg.title,
                'era_id': self.era.id,
                'status': 'OPEN',
                'banner_file': large_file,
            },
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        messages_list = list(response.context['messages'])
        self.assertTrue(any("ultrapassa o limite" in str(m) for m in messages_list))

