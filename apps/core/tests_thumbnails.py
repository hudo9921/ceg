import io
import shutil
import tempfile
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.template import Context, Template
from django.test import TestCase, override_settings
from PIL import Image

from apps.cegs.image_utils import process_image_upload
from apps.core.thumbnails import (
    THUMB_PREFIX, storage_name_from_url, thumbnail_name, thumbnail_url,
)


def big_jpeg(size=(1600, 2400)):
    buf = io.BytesIO()
    Image.new('RGB', size, 'pink').save(buf, format='JPEG')
    return buf.getvalue()


class ThumbnailUrlTests(TestCase):
    @override_settings(MEDIA_URL='/media/')
    def test_local_media_urls_map_to_storage_names(self):
        self.assertEqual(storage_name_from_url('/media/cegs/a.jpg'), 'cegs/a.jpg')
        self.assertEqual(storage_name_from_url('https://valcegs.duckdns.org/media/cegs/a.jpg'), 'cegs/a.jpg')
        self.assertEqual(thumbnail_url('/media/cegs/a.jpg'), f'/media/{THUMB_PREFIX}cegs/a.webp')

    @override_settings(MEDIA_URL='https://cdn.valcegs.example/')
    def test_r2_custom_domain_urls_map_to_storage_names(self):
        self.assertEqual(storage_name_from_url('https://cdn.valcegs.example/items/x.png'), 'items/x.png')
        self.assertIsNone(storage_name_from_url('/media/items/x.png'))

    def test_external_and_unsafe_urls_are_left_alone(self):
        for url in ('https://static.mercdn.net/item/1.jpg', '', None,
                    f'/media/{THUMB_PREFIX}cegs/a.webp', '/media/../etc/passwd'):
            self.assertIsNone(storage_name_from_url(url), url)
        self.assertEqual(thumbnail_url('https://static.mercdn.net/item/1.jpg'),
                         'https://static.mercdn.net/item/1.jpg')
        self.assertEqual(thumbnail_url(None), '')

    def test_template_filter(self):
        out = Template('{{ u|thumb }}').render(Context({'u': '/media/items/p.jpg'}))
        self.assertEqual(out, f'/media/{THUMB_PREFIX}items/p.webp')


class ThumbnailGenerationTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media, MEDIA_URL='/media/')
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def _thumb_size(self, url):
        with default_storage.open(thumbnail_name(storage_name_from_url(url)), 'rb') as fh:
            with Image.open(fh) as img:
                return img.format, img.size

    def test_upload_creates_small_webp_thumbnail(self):
        url = process_image_upload(base64_str='data:image/jpeg;base64,' + __import__('base64').b64encode(big_jpeg()).decode(),
                                   folder='items')
        fmt, size = self._thumb_size(url)
        self.assertEqual(fmt, 'WEBP')
        self.assertLessEqual(max(size), 640)

    def test_backfill_command_is_idempotent_and_survives_missing_files(self):
        from apps.cegs.models import CEG
        from apps.groups.models import Era, KpopGroup

        name = default_storage.save('cegs/banners/legacy.jpg', ContentFile(big_jpeg()))
        era = Era.objects.create(group=KpopGroup.objects.create(name='G'), name='E',
                                 banner_url='/media/eras/apagado.jpg')
        CEG.objects.create(title='Legada', era=era, banner_url=default_storage.url(name))

        out = StringIO()
        call_command('generate_thumbnails', stdout=out, stderr=StringIO())
        self.assertIn('1 criadas', out.getvalue())
        self.assertIn('1 falharam', out.getvalue())
        self.assertTrue(default_storage.exists(thumbnail_name(name)))

        out = StringIO()
        call_command('generate_thumbnails', stdout=out, stderr=StringIO())
        self.assertIn('0 criadas, 1 já existiam', out.getvalue())

    def test_uploaded_file_field_gets_thumbnail_only_when_photo_changes(self):
        from apps.cegs.models import ItemVitrine, TipoItem

        item = ItemVitrine.objects.create(
            titulo='PC', tipo_item=TipoItem.objects.get_or_create(nome='Photocard')[0],
            preco=Decimal('10.00'), quantidade=1)
        with mock.patch('apps.core.thumbnails.save_thumbnail', return_value=True) as save:
            item.foto_arquivo.save('pc.jpg', ContentFile(big_jpeg()), save=True)
            self.assertEqual(save.call_count, 1)
            item.preco = Decimal('12.00')
            item.save()
            self.assertEqual(save.call_count, 1)
