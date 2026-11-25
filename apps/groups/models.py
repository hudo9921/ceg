import unicodedata

from django.db import models
from django.db.models.functions import Lower
from django.utils.text import slugify


def normalize_name(value):
    """Chave de busca/duplicata: sem acento, sem maiúscula e só letras/números ("æspa" → "aespa", "LE SSERAFIM" → "lesserafim")."""
    text = unicodedata.normalize('NFKD', (value or '').replace('æ', 'ae').replace('Æ', 'AE'))
    return ''.join(c for c in text if c.isalnum() and not unicodedata.combining(c)).casefold()


class Source(models.TextChoices):
    MANUAL = 'MANUAL', 'Cadastro manual'
    IMPORTADO = 'IMPORTADO', 'Importado (Wikidata/MusicBrainz)'


class KpopGroupQuerySet(models.QuerySet):
    def matching(self, name):
        """Grupos cujo nome, nome em Hangul ou apelido é igual a `name` (sem acento/maiúscula/espaço)."""
        key = normalize_name(name)
        if not key:
            return self.none()
        return self.filter(models.Q(search_key=key) | models.Q(search_key__startswith=key + ' ')
                           | models.Q(search_key__endswith=' ' + key) | models.Q(search_key__contains=' ' + key + ' '))


class KpopGroup(models.Model):
    class Kind(models.TextChoices):
        GRUPO = 'GRUPO', 'Grupo'
        SOLISTA = 'SOLISTA', 'Solista'
        SUBUNIDADE = 'SUBUNIDADE', 'Subunidade'

    class Status(models.TextChoices):
        ATIVO = 'ATIVO', 'Ativo'
        ENCERRADO = 'ENCERRADO', 'Encerrado'

    name = models.CharField('Nome do Grupo / Solista', max_length=150, unique=True)
    slug = models.SlugField('Slug', max_length=160, unique=True, blank=True)
    image_url = models.URLField('URL da Imagem / Logo', max_length=500, blank=True)
    color_hex = models.CharField(
        'Cor Tema do Grupo (Hex)',
        max_length=7,
        blank=True,
        default='',
        help_text='Cor predominante do Grupo (ex: #EC4899), extraída automaticamente ou personalizada.'
    )
    description = models.TextField('Descrição', blank=True)
    # Catálogo (docs/CATALOG_IMPORT_PLAN.md)
    kind = models.CharField('Tipo', max_length=12, choices=Kind.choices, default=Kind.GRUPO)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='subunits',
                               verbose_name='Grupo principal (subunidade)')
    name_native = models.CharField('Nome em Hangul', max_length=150, blank=True)
    aliases = models.CharField('Outros nomes (separados por vírgula)', max_length=300, blank=True)
    search_key = models.CharField('Chave de busca', max_length=600, blank=True, db_index=True, editable=False)
    debut_date = models.DateField('Estreia', null=True, blank=True)
    agency = models.CharField('Agência', max_length=150, blank=True)
    status = models.CharField('Situação', max_length=10, choices=Status.choices, default=Status.ATIVO)
    popularity_rank = models.PositiveIntegerField('Posição no ranking', null=True, blank=True, db_index=True)
    image_credit = models.CharField('Crédito da imagem', max_length=300, blank=True)
    wikidata_id = models.CharField('Wikidata', max_length=20, null=True, blank=True, unique=True)
    musicbrainz_id = models.CharField('MusicBrainz', max_length=36, null=True, blank=True, unique=True)
    source = models.CharField('Origem', max_length=10, choices=Source.choices, default=Source.MANUAL)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    objects = KpopGroupQuerySet.as_manager()

    class Meta:
        verbose_name = 'Grupo / Solista'
        verbose_name_plural = 'Grupos e Solistas'
        ordering = ['name']
        constraints = [models.UniqueConstraint(Lower('name'), name='kpopgroup_name_ci_unique')]

    def __str__(self):
        return self.name

    @property
    def members_count(self):
        return self.members.count()

    def get_member_names(self):
        return list(self.members.values_list('name', flat=True))

    def build_search_key(self):
        names = [self.name, self.name_native, *(self.aliases or '').split(',')]
        return ' '.join(dict.fromkeys(k for k in (normalize_name(n) for n in names) if k))

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or f'grupo-{normalize_name(self.name)[:20] or "novo"}'
            slug, n = base, 2
            while KpopGroup.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f'{base}-{n}', n + 1
            self.slug = slug
        self.search_key = self.build_search_key()
        if self.image_url and not self.color_hex:
            try:
                from .color_utils import extract_dominant_color
                extracted = extract_dominant_color(self.image_url)
                if extracted:
                    self.color_hex = extracted
            except Exception:
                pass
        if not self.color_hex:
            palette = ['#EC4899', '#8B5CF6', '#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#06B6D4', '#84CC16']
            self.color_hex = palette[sum(ord(c) for c in (self.name or '')) % len(palette)]
        super().save(*args, **kwargs)


class GroupMember(models.Model):
    group = models.ForeignKey(KpopGroup, on_delete=models.CASCADE, related_name='members', verbose_name='Grupo')
    name = models.CharField('Nome do Integrante', max_length=100)
    order = models.PositiveIntegerField('Ordem', default=0)
    name_native = models.CharField('Nome em Hangul', max_length=100, blank=True)
    is_former = models.BooleanField('Ex-integrante', default=False)
    wikidata_id = models.CharField('Wikidata', max_length=20, blank=True, db_index=True)
    solo = models.ForeignKey(KpopGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='as_member',
                             verbose_name='Carreira solo')
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        verbose_name = 'Integrante / Membro'
        verbose_name_plural = 'Integrantes / Membros'
        ordering = ['order', 'id']
        unique_together = ('group', 'name')

    def __str__(self):
        return f"{self.group.name} - {self.name}"


class Era(models.Model):
    class Kind(models.TextChoices):
        ALBUM = 'ALBUM', 'Álbum'
        MINI = 'MINI', 'Mini álbum'
        SINGLE = 'SINGLE', 'Single'
        JAPONES = 'JAPONES', 'Japonês'
        OUTRO = 'OUTRO', 'Outro'

    group = models.ForeignKey(KpopGroup, on_delete=models.CASCADE, related_name='eras', verbose_name='Grupo')
    name = models.CharField('Nome da Era / Comeback', max_length=150)
    slug = models.SlugField('Slug', max_length=160, blank=True)
    release_date = models.DateField('Data de Lançamento', null=True, blank=True)
    banner_url = models.URLField('URL do Banner Promocional', max_length=500, blank=True)
    color_hex = models.CharField(
        'Cor Tema da Era (Hex)',
        max_length=7,
        blank=True,
        default='',
        help_text='Cor predominante da Era (ex: #EC4899), extraída automaticamente ou personalizada.'
    )
    description = models.TextField('Descrição', blank=True)
    kind = models.CharField('Tipo de lançamento', max_length=8, choices=Kind.choices, default=Kind.OUTRO)
    musicbrainz_id = models.CharField('MusicBrainz', max_length=36, null=True, blank=True, unique=True)
    source = models.CharField('Origem', max_length=10, choices=Source.choices, default=Source.MANUAL)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        verbose_name = 'Era / Comeback'
        verbose_name_plural = 'Eras e Comebacks'
        ordering = ['-release_date', 'name']
        unique_together = ('group', 'slug')

    def __str__(self):
        return f"{self.group.name} - {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'era'
            slug, n = base, 2
            while Era.objects.filter(group_id=self.group_id, slug=slug).exclude(pk=self.pk).exists():
                slug, n = f'{base}-{n}', n + 1
            self.slug = slug
        if not self.color_hex:
            if self.banner_url:
                try:
                    from .color_utils import extract_dominant_color
                    extracted = extract_dominant_color(self.banner_url)
                    if extracted:
                        self.color_hex = extracted
                except Exception:
                    pass
            elif self.group and (getattr(self.group, 'color_hex', None) or getattr(self.group, 'image_url', None)):
                if getattr(self.group, 'color_hex', None):
                    self.color_hex = self.group.color_hex
                elif getattr(self.group, 'image_url', None):
                    try:
                        from .color_utils import extract_dominant_color
                        extracted = extract_dominant_color(self.group.image_url)
                        if extracted:
                            self.color_hex = extracted
                    except Exception:
                        pass
        if not self.color_hex:
            palette = ['#EC4899', '#8B5CF6', '#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#06B6D4', '#84CC16']
            self.color_hex = palette[sum(ord(c) for c in (self.name or '')) % len(palette)]
        super().save(*args, **kwargs)
