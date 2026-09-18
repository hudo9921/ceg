from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.groups.models import KpopGroup, Era


class GroupAndEraCreationsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='admin_group_era_test',
            email='admin_ge@test.com',
            password='password123'
        )
        self.client.force_login(self.admin_user)

        self.group = KpopGroup.objects.create(
            name="LE SSERAFIM",
            description="Group description",
            image_url="https://example.com/lesserafim.jpg"
        )
        self.era = Era.objects.create(
            group=self.group,
            name="CRAZY",
            release_date="2024-08-30",
            description="4th Mini Album",
            banner_url="https://example.com/crazy_banner.jpg"
        )

    def test_creations_hub_view_renders_group_and_era_data(self):
        response = self.client.get(reverse('creations_hub'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "LE SSERAFIM")
        self.assertContains(response, "CRAZY")

    def test_create_group(self):
        response = self.client.post(reverse('create_group'), {
            'name': 'Stray Kids',
            'description': 'JYP Boy Group',
            'image_url': 'https://example.com/skz.jpg',
        })
        self.assertRedirects(response, '/creations/?tab=era')
        self.assertTrue(KpopGroup.objects.filter(name='Stray Kids').exists())
        skz = KpopGroup.objects.get(name='Stray Kids')
        self.assertEqual(skz.image_url, 'https://example.com/skz.jpg')

    def test_update_group(self):
        response = self.client.post(reverse('update_group'), {
            'group_id': self.group.id,
            'name': 'LE SSERAFIM (Updated)',
            'description': 'Updated description',
            'image_url': 'https://example.com/lesserafim_v2.jpg',
        })
        self.assertRedirects(response, '/creations/?tab=group')
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, 'LE SSERAFIM (Updated)')
        self.assertEqual(self.group.description, 'Updated description')
        self.assertEqual(self.group.image_url, 'https://example.com/lesserafim_v2.jpg')

    def test_create_era(self):
        response = self.client.post(reverse('create_era'), {
            'group_id': self.group.id,
            'name': 'EASY',
            'release_date': '2024-02-19',
            'description': '3rd Mini Album',
            'banner_url': 'https://example.com/easy_banner.jpg',
        })
        self.assertRedirects(response, '/creations/?tab=ceg')
        self.assertTrue(Era.objects.filter(name='EASY', group=self.group).exists())

    def test_update_era(self):
        new_group = KpopGroup.objects.create(name="aespa")
        response = self.client.post(reverse('update_era'), {
            'era_id': self.era.id,
            'group_id': new_group.id,
            'name': 'CRAZY (Remix)',
            'release_date': '2024-09-01',
            'description': 'Special edition',
            'banner_url': 'https://example.com/crazy_remix.jpg',
        })
        self.assertRedirects(response, '/creations/?tab=era')
        self.era.refresh_from_db()
        self.assertEqual(self.era.name, 'CRAZY (Remix)')
        self.assertEqual(self.era.group, new_group)
        self.assertEqual(self.era.banner_url, 'https://example.com/crazy_remix.jpg')
