from django.db import models
from django.utils.text import slugify


class KpopGroup(models.Model):
    name = models.CharField('Nome do Grupo / Solista', max_length=150, unique=True)
    slug = models.SlugField('Slug', max_length=160, unique=True, blank=True)
    image_url = models.URLField('URL da Imagem / Logo', max_length=500, blank=True)
    description = models.TextField('Descrição', blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        verbose_name = 'Grupo / Solista'
        verbose_name_plural = 'Grupos e Solistas'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Era(models.Model):
    group = models.ForeignKey(KpopGroup, on_delete=models.CASCADE, related_name='eras', verbose_name='Grupo')
    name = models.CharField('Nome da Era / Comeback', max_length=150)
    slug = models.SlugField('Slug', max_length=160, blank=True)
    release_date = models.DateField('Data de Lançamento', null=True, blank=True)
    banner_url = models.URLField('URL do Banner Promocional', max_length=500, blank=True)
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
        super().save(*args, **kwargs)
