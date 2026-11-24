from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Gom, GomMembership
from .permissions import DEFAULT_PRESET, PRESETS

INPUT_CLASS = ('w-full px-3.5 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 '
               'dark:border-slate-700 rounded-xl text-sm text-slate-900 dark:text-white '
               'focus:outline-none focus:ring-2 focus:ring-pink-500/30 focus:border-pink-500')


def _style(form):
    for field in form.fields.values():
        field.widget.attrs.setdefault('class', INPUT_CLASS)
    return form


class GomCreateForm(forms.Form):
    name = forms.CharField(label='Nome do GOM', max_length=80)
    slug = forms.SlugField(label='Endereço da página (opcional)', max_length=60, required=False,
                           help_text='Ex.: valcegs → /gom/valcegs/. Em branco, é gerado pelo nome.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class GomProfileForm(forms.ModelForm):
    """Perfil do GOM (página pública e padrões). Endereço (slug) só a plataforma muda."""

    class Meta:
        model = Gom
        fields = ['name', 'bio', 'whatsapp_contato', 'instagram', 'logo_url', 'banner_url',
                  'default_pix_key', 'default_pix_instructions',
                  'default_pix_key_frete', 'default_pix_instructions_frete',
                  'default_pix_key_taxa', 'default_pix_instructions_taxa',
                  'default_pix_key_frete_nacional', 'default_pix_instructions_frete_nacional']
        widgets = {'bio': forms.Textarea(attrs={'rows': 3}),
                   **{f'default_pix_instructions{s}': forms.Textarea(attrs={'rows': 2})
                      for s in ('', '_frete', '_taxa', '_frete_nacional')}}

    PROFILE_FIELDS = ('name', 'bio', 'whatsapp_contato', 'instagram', 'logo_url', 'banner_url')

    def __init__(self, *args, can_edit_profile=True, can_edit_pix=True, **kwargs):
        super().__init__(*args, **kwargs)
        # Permissões do admin (apps.goms.permissions): campos sem permissão nem entram no form.
        for name in list(self.fields):
            is_pix = name.startswith('default_pix_')
            if (is_pix and not can_edit_pix) or (not is_pix and not can_edit_profile):
                del self.fields[name]
        _style(self)


class InviteForm(forms.Form):
    name = forms.CharField(label='Para quem (apelido)', max_length=80, required=False)
    role = forms.ChoiceField(label='Papel', choices=GomMembership.Role.choices,
                             initial=GomMembership.Role.ADMIN)
    preset = forms.ChoiceField(label='Começa com o modelo', required=False,
                               choices=[(k, v[0]) for k, v in PRESETS.items()], initial=DEFAULT_PRESET)

    def invite_permissions(self):
        """Permissões iniciais do convite: o modelo escolhido (dono não usa)."""
        if self.cleaned_data['role'] == GomMembership.Role.OWNER:
            return None
        return list(PRESETS[self.cleaned_data.get('preset') or DEFAULT_PRESET][2])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class InviteSignupForm(UserCreationForm):
    """Cria a conta de quem recebeu o convite (senha validada pelos validadores do Django)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Usuário para entrar'
        self.fields['username'].help_text = 'Letras, números e @/./+/-/_ . Ex.: bia.valcegs'
        _style(self)
