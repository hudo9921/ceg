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
        import json
        response = self.client.post(reverse('create_group'), {
            'name': 'Stray Kids',
            'description': 'JYP Boy Group',
            'image_url': 'https://example.com/skz.jpg',
            'members_json': json.dumps(['Bang Chan', 'Lee Know', 'Changbin', 'Hyunjin', 'Han', 'Felix', 'Seungmin', 'I.N'])
        })
        self.assertRedirects(response, '/creations/?tab=era')
        self.assertTrue(KpopGroup.objects.filter(name='Stray Kids').exists())
        skz = KpopGroup.objects.get(name='Stray Kids')
        self.assertEqual(skz.image_url, 'https://example.com/skz.jpg')
        self.assertEqual(skz.members_count, 8)
        self.assertEqual(skz.get_member_names(), ['Bang Chan', 'Lee Know', 'Changbin', 'Hyunjin', 'Han', 'Felix', 'Seungmin', 'I.N'])

    def test_create_group_with_comma_separated_text(self):
        response = self.client.post(reverse('create_group'), {
            'name': 'aespa',
            'description': 'SM Girl Group',
            'members_text': 'Karina, Giselle, Winter, Ningning'
        })
        self.assertRedirects(response, '/creations/?tab=era')
        aespa = KpopGroup.objects.get(name='aespa')
        self.assertEqual(aespa.members_count, 4)
        self.assertEqual(aespa.get_member_names(), ['Karina', 'Giselle', 'Winter', 'Ningning'])

    def test_update_group_synchronizes_members(self):
        import json
        from apps.groups.models import GroupMember

        GroupMember.objects.create(group=self.group, name='Sakura', order=0)
        GroupMember.objects.create(group=self.group, name='Chaewon', order=1)
        GroupMember.objects.create(group=self.group, name='Garam', order=2)
        self.assertEqual(self.group.members_count, 3)

        # Atualiza removendo Garam e adicionando Yunjin, Kazuha, Eunchae
        response = self.client.post(reverse('update_group'), {
            'group_id': self.group.id,
            'name': 'LE SSERAFIM (OT5)',
            'description': 'Updated description',
            'members_json': json.dumps(['Sakura', 'Chaewon', 'Yunjin', 'Kazuha', 'Eunchae'])
        })
        self.assertRedirects(response, '/creations/?tab=group')
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, 'LE SSERAFIM (OT5)')
        self.assertEqual(self.group.members_count, 5)
        self.assertEqual(self.group.get_member_names(), ['Sakura', 'Chaewon', 'Yunjin', 'Kazuha', 'Eunchae'])
        self.assertFalse(self.group.members.filter(name='Garam').exists())

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

    def test_update_group_photo_base64(self):
        import base64
        # 1x1 transparent PNG base64
        dummy_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        response = self.client.post(reverse('update_group'), {
            'group_id': self.group.id,
            'name': self.group.name,
            'image_base64': dummy_b64,
            'image_url': '',
        })
        self.assertRedirects(response, '/creations/?tab=group')
        self.group.refresh_from_db()
        self.assertTrue('group_' in self.group.image_url)
        self.assertNotEqual(self.group.image_url, "https://example.com/lesserafim.jpg")

    def test_update_group_photo_file_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        tiny_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        uploaded = SimpleUploadedFile("new_logo.png", tiny_png, content_type="image/png")
        response = self.client.post(reverse('update_group'), {
            'group_id': self.group.id,
            'name': self.group.name,
            'image_file': uploaded,
            'image_url': '',
        })
        self.assertRedirects(response, '/creations/?tab=group')
        self.group.refresh_from_db()
        self.assertTrue('group_' in self.group.image_url)

    def test_update_group_clearing_photo(self):
        response = self.client.post(reverse('update_group'), {
            'group_id': self.group.id,
            'name': self.group.name,
            'image_url': '',
        })
        self.assertRedirects(response, '/creations/?tab=group')
        self.group.refresh_from_db()
        self.assertEqual(self.group.image_url, '')

    def test_update_group_with_uncommitted_member_input(self):
        import json
        from apps.groups.models import GroupMember

        GroupMember.objects.create(group=self.group, name='Sakura', order=0)
        # O usuário já tinha Sakura no JSON e digitou "Chaewon, Kazuha" no input antes de enviar
        response = self.client.post(reverse('update_group'), {
            'group_id': self.group.id,
            'name': self.group.name,
            'members_json': json.dumps(['Sakura']),
            'editGroupMemberInput': 'Chaewon, Kazuha',
        })
        self.assertRedirects(response, '/creations/?tab=group')
        self.group.refresh_from_db()
        self.assertEqual(self.group.members_count, 3)
        self.assertEqual(self.group.get_member_names(), ['Sakura', 'Chaewon', 'Kazuha'])
