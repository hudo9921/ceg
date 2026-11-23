"""SSRF (fetch de URLs informadas por usuários) e validação de uploads de imagem."""
import io
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.core.net import UnsafeURLError, assert_public_url, _SafeRedirectHandler
from apps.cegs.image_utils import InvalidImageError, ImageSizeError, process_image_upload


class SSRFGuardTests(TestCase):
    BLOCKED = [
        'http://127.0.0.1/admin/',
        'http://localhost:8000/',
        'http://169.254.169.254/latest/meta-data/',   # metadados de nuvem
        'http://10.0.0.5/',
        'http://192.168.0.1/',
        'http://172.17.0.2:8080/',                    # rede do Docker
        'http://[::1]/',
        'http://[::ffff:127.0.0.1]/',
        'http://0.0.0.0/',
        'file:///etc/passwd',
        'ftp://93.184.215.14/x.jpg',
        'gopher://93.184.215.14/',
        'http://host-que-nao-existe.invalid/x.jpg',
    ]

    def test_internal_and_non_http_destinations_are_blocked(self):
        for url in self.BLOCKED:
            with self.subTest(url=url):
                with self.assertRaises(UnsafeURLError):
                    assert_public_url(url)

    def test_public_ip_is_allowed(self):
        assert_public_url('https://93.184.215.14/foto.jpg')

    def test_redirect_to_internal_address_is_blocked(self):
        handler = _SafeRedirectHandler()
        with self.assertRaises(UnsafeURLError):
            handler.redirect_request(None, None, 302, 'Found', {}, 'http://169.254.169.254/')


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage',
                'OPTIONS': {'location': tempfile.mkdtemp()}},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class ImageUploadValidationTests(TestCase):
    def _png_bytes(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (4, 4), 'pink').save(buf, format='PNG')
        return buf.getvalue()

    def test_non_image_file_is_rejected_not_stored(self):
        fake = SimpleUploadedFile('foto.png', b'<html><script>alert(1)</script></html>', content_type='image/png')
        with self.assertRaises(InvalidImageError):
            process_image_upload(file_obj=fake, folder='items')

    def test_non_image_base64_is_rejected(self):
        import base64
        payload = 'data:image/png;base64,' + base64.b64encode(b'not an image').decode()
        with self.assertRaises(InvalidImageError):
            process_image_upload(base64_str=payload, folder='items')

    def test_invalid_image_error_is_handled_like_size_error(self):
        self.assertTrue(issubclass(InvalidImageError, ImageSizeError))

    def test_real_image_is_converted_and_stored(self):
        url = process_image_upload(
            file_obj=SimpleUploadedFile('foto.png', self._png_bytes(), content_type='image/png'),
            folder='items',
        )
        self.assertTrue(url.endswith('.jpg'))
