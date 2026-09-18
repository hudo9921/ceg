from io import BytesIO
from unittest.mock import patch
from PIL import Image
from django.test import TestCase
from django.urls import reverse
from apps.groups.models import KpopGroup, Era
from apps.groups.color_utils import extract_dominant_color
from apps.cegs.models import CEG, CEGSet, CEGItemDefinition


class ColorExtractionTestCase(TestCase):
    def test_extract_dominant_color_magenta(self):
        # Create a synthetic 100x100 magenta image
        img = Image.new('RGB', (100, 100), color=(220, 20, 120))
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        color = extract_dominant_color(buf)
        self.assertIsNotNone(color)
        self.assertTrue(color.startswith('#'))
        self.assertEqual(len(color), 7)
        # Should be predominantly reddish/magenta
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        self.assertGreater(r, g)
        self.assertGreater(b, g)

    def test_extract_dominant_color_filters_white_and_black(self):
        # Create an image mostly white, but with a vivid cyan square
        img = Image.new('RGB', (100, 100), color=(255, 255, 255))
        # Draw a 30x30 cyan box
        for x in range(10, 40):
            for y in range(10, 40):
                img.putpixel((x, y), (0, 180, 210))
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        color = extract_dominant_color(buf)
        self.assertIsNotNone(color)
        # The cyan should be preferred over plain white
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        self.assertGreater(b, r)
        self.assertGreater(g, r)

    @patch('apps.groups.color_utils.extract_dominant_color')
    def test_era_auto_color_extraction_on_save(self, mock_extract):
        mock_extract.return_value = '#10B981'
        group = KpopGroup.objects.create(name='Test Group')

        era = Era.objects.create(
            group=group,
            name='Test Era',
            banner_url='https://example.com/banner.jpg'
        )

        mock_extract.assert_called_once_with('https://example.com/banner.jpg')
        self.assertEqual(era.color_hex, '#10B981')

    def test_era_preserves_custom_color(self):
        group = KpopGroup.objects.create(name='Custom Group')
        era = Era.objects.create(
            group=group,
            name='Manual Color Era',
            banner_url='https://example.com/banner.jpg',
            color_hex='#FF5500'
        )
        self.assertEqual(era.color_hex, '#FF5500')

    def test_ceg_theme_color_property_and_template_rendering(self):
        group = KpopGroup.objects.create(name='Theme Group')
        era = Era.objects.create(group=group, name='Theme Era', color_hex='#9333EA')
        ceg = CEG.objects.create(
            title='CEG Theme Test',
            slug='ceg-theme-test',
            era=era,
            status=CEG.Status.OPEN
        )

        CEGItemDefinition.objects.create(ceg=ceg, name='Photocard Test', default_price=10.00)
        cset = CEGSet.objects.create(ceg=ceg, set_number=1, is_active=True)
        cset.generate_slots()

        # Check theme_color property
        self.assertEqual(ceg.theme_color, '#9333EA')

        # Check home template rendering
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Verify dynamic styling is in rendered home page
        self.assertIn('#9333EA', content)
        self.assertIn('border-left: 6px solid #9333EA', content)
        self.assertIn('background: linear-gradient(125deg, #9333EA20', content)

    @patch('apps.groups.color_utils.extract_dominant_color')
    def test_update_era_auto_reextracts_color_when_empty(self, mock_extract):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        staff_user = User.objects.create_user(username='staffuser', password='password123', is_staff=True)
        self.client.force_login(staff_user)

        mock_extract.return_value = '#10B981'
        group = KpopGroup.objects.create(name='Update Test Group')
        era = Era.objects.create(
            group=group,
            name='Era To Update',
            banner_url='/media/eras/some_banner.png',
            color_hex='#FF0000'  # Currently red
        )

        # POST with empty color_hex (leaving it blank for auto)
        response = self.client.post(reverse('update_era'), {
            'era_id': era.id,
            'group_id': group.id,
            'name': 'Era To Update',
            'banner_url': '/media/eras/some_banner.png',
            'color_hex': ''  # blank -> auto mode
        })
        self.assertEqual(response.status_code, 302)

        era.refresh_from_db()
        # Should have re-extracted and updated from #FF0000 to #10B981
        mock_extract.assert_called_with('/media/eras/some_banner.png')
        self.assertEqual(era.color_hex, '#10B981')

    def test_update_era_saves_custom_color_with_or_without_hash(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        staff_user = User.objects.create_user(username='staffuser2', password='password123', is_staff=True)
        self.client.force_login(staff_user)

        group = KpopGroup.objects.create(name='Update Test Group 2')
        era = Era.objects.create(
            group=group,
            name='Era Custom Color',
            color_hex='#FF0000'
        )

        response = self.client.post(reverse('update_era'), {
            'era_id': era.id,
            'group_id': group.id,
            'name': 'Era Custom Color',
            'color_hex': '8B5CF6'  # without hash
        })
        self.assertEqual(response.status_code, 302)

        era.refresh_from_db()
        self.assertEqual(era.color_hex, '#8B5CF6')

    @patch('apps.groups.color_utils.extract_dominant_color')
    def test_kpopgroup_auto_color_extraction_on_save(self, mock_extract):
        mock_extract.return_value = '#0878DA'
        group = KpopGroup.objects.create(
            name='Group With Logo',
            image_url='https://example.com/logo.jpg'
        )
        mock_extract.assert_called_once_with('https://example.com/logo.jpg')
        self.assertEqual(group.color_hex, '#0878DA')

    @patch('apps.groups.color_utils.extract_dominant_color')
    def test_ceg_theme_color_falls_back_to_group_when_era_has_no_color(self, mock_extract):
        mock_extract.return_value = '#0878DA'
        group = KpopGroup.objects.create(
            name='Fallback Group',
            color_hex='#0878DA'
        )
        # Era without banner or color
        era = Era.objects.create(group=group, name='Era Without Banner', banner_url='', color_hex='')
        ceg = CEG.objects.create(
            title='CEG Fallback Test',
            slug='ceg-fallback-test',
            era=era,
            status=CEG.Status.OPEN
        )
        # CEG theme_color should fall back to group color (#0878DA)
        self.assertEqual(ceg.theme_color, '#0878DA')


