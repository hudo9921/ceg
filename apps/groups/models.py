from django.db import models
from django.utils.text import slugify


class KpopGroup(models.Model):
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
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        verbose_name = 'Grupo / Solista'
        verbose_name_plural = 'Grupos e Solistas'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def members_count(self):
        return self.members.count()

    def get_member_names(self):
        return list(self.members.values_list('name', flat=True))

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
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
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        verbose_name = 'Integrante / Membro'
        verbose_name_plural = 'Integrantes / Membros'
        ordering = ['order', 'id']
        unique_together = ('group', 'name')

    def __str__(self):
        return f"{self.group.name} - {self.name}"


class Era(models.Model):
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
            self.slug = slugify(self.name)
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
