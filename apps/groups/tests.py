from django.test import TestCase

# Create your tests here.


class CatalogoNomeTests(TestCase):
    def test_normalize_name(self):
        from apps.groups.models import normalize_name
        self.assertEqual(normalize_name('æspa'), 'aespa')
        self.assertEqual(normalize_name('LE SSERAFIM'), normalize_name('Le Sserafim'))
        self.assertEqual(normalize_name('(G)I-DLE'), 'gidle')

    def test_matching_por_nome_hangul_e_apelido(self):
        from apps.groups.models import KpopGroup
        g = KpopGroup.objects.create(name='aespa', name_native='에스파', aliases='æspa', color_hex='#000000')
        self.assertEqual(list(KpopGroup.objects.matching('AESPA')), [g])
        self.assertEqual(list(KpopGroup.objects.matching('에스파')), [g])
        self.assertEqual(list(KpopGroup.objects.matching('æspa')), [g])
        self.assertFalse(KpopGroup.objects.matching('aes').exists())

    def test_nome_unico_sem_diferenciar_maiuscula(self):
        from django.db import IntegrityError, transaction
        from apps.groups.models import KpopGroup
        KpopGroup.objects.create(name='aespa', color_hex='#000000')
        with self.assertRaises(IntegrityError), transaction.atomic():
            KpopGroup.objects.create(name='AESPA', slug='aespa-2', color_hex='#000000')

    def test_slug_repetido_ganha_sufixo(self):
        from apps.groups.models import Era, KpopGroup
        a = KpopGroup.objects.create(name='Apink', color_hex='#000000')
        b = KpopGroup.objects.create(name='A-pink', color_hex='#000000')
        self.assertNotEqual(a.slug, b.slug)
        e1 = Era.objects.create(group=a, name='Pink Blossom', color_hex='#000000')
        e2 = Era.objects.create(group=a, name='Pink Blossom', color_hex='#000000')
        self.assertNotEqual(e1.slug, e2.slug)

    def test_gom_nao_duplica_grupo_existente(self):
        from django.contrib.auth.models import User
        from apps.groups.models import KpopGroup
        KpopGroup.objects.create(name='aespa', color_hex='#000000')
        self.client.force_login(User.objects.create_superuser('plat', password='x'))
        res = self.client.post('/creations/group/create/', {'name': 'Aespa'})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(KpopGroup.objects.count(), 1)
