from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import GomMembership

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


class InviteForm(forms.Form):
    name = forms.CharField(label='Para quem (apelido)', max_length=80, required=False)
    role = forms.ChoiceField(label='Papel', choices=GomMembership.Role.choices,
                             initial=GomMembership.Role.ADMIN)

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
