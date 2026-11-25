"""Tela Configurações do GOM (C0): /gom/configuracoes/<aba>/. Cada aba salva só os próprios campos."""
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .access import gom_member_required, has_gom_perm
from .forms import GomProfileForm, _style
from .settings_tabs import tab_permission, visible_tabs

DENIED = 'Sem permissão para isso. Fale com o dono do GOM.'


class EnvioConfigForm(forms.ModelForm):
    class Meta:
        from apps.cegs.models import ConfiguracaoEnvio
        model = ConfiguracaoEnvio
        fields = ['link_formulario_google', 'instrucoes_envio']
        labels = {'link_formulario_google': 'Formulário de endereço (link)',
                  'instrucoes_envio': 'Instruções para o joiner'}
        widgets = {'instrucoes_envio': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['link_formulario_google'].required = False
        _style(self)


@never_cache
@gom_member_required
def gom_settings_index(request):
    """Abre a primeira aba que a pessoa pode usar."""
    tabs = visible_tabs(request)
    if not tabs:
        raise PermissionDenied(DENIED)
    return redirect(tabs[0]['url'])


def _perfil(request, gom):
    from apps.cegs.image_utils import ImageSizeError, process_image_upload

    form = GomProfileForm(request.POST or None, instance=gom, can_edit_profile=True, can_edit_pix=False)
    if request.method == 'POST' and form.is_valid():
        profile = form.save(commit=False)
        try:
            for field, folder in (('logo', 'goms/logos'), ('banner', 'goms/banners')):
                upload = request.FILES.get(f'{field}_file')
                if upload:
                    setattr(profile, f'{field}_url', process_image_upload(file_obj=upload, folder=folder))
        except ImageSizeError as exc:
            messages.error(request, str(exc))
            return form, False, {}
        profile.save()
        return form, True, {}
    return form, False, {}


def _pix(request, gom):
    form = GomProfileForm(request.POST or None, instance=gom, can_edit_profile=False, can_edit_pix=True)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return form, True, {}
    return form, False, {}


class CaixinhaPrazoForm(forms.ModelForm):
    class Meta:
        from .models import Gom
        model = Gom
        fields = ['caixinha_prazo_dias']
        widgets = {'caixinha_prazo_dias': forms.NumberInput(attrs={'min': 1, 'max': 365})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


def metodos_formset(data, gom):
    from apps.cegs.models import MetodoEnvio

    FormSet = forms.modelformset_factory(
        MetodoEnvio, fields=['nome', 'descricao', 'pede_endereco', 'ativo', 'ordem'], extra=1, can_delete=True,
        widgets={'ordem': forms.HiddenInput()})
    formset = FormSet(data, queryset=MetodoEnvio.objects.for_gom(gom), prefix='metodos')
    for f in formset.forms:
        for name in ('nome', 'descricao'):
            f.fields[name].widget.attrs['class'] = 'ui-input w-full'
        f.fields['nome'].widget.attrs['placeholder'] = 'Ex.: Correios PAC'
        f.fields['descricao'].widget.attrs['placeholder'] = 'Ex.: 5 a 10 dias úteis'
        f.fields['nome'].required = False  # linha extra em branco é ignorada
        f.fields['ordem'].required = False  # recalculada na ordem da tela
        for name in ('ativo', 'pede_endereco', 'DELETE'):
            if name in f.fields:
                f.fields[name].widget.attrs['class'] = 'w-5 h-5 accent-[var(--ui-accent)]'
        if f.instance.pk is None:
            f.initial.setdefault('ativo', True)
            f.initial.setdefault('pede_endereco', True)
    return formset


def _envio(request, gom):
    from apps.cegs.models import ConfiguracaoEnvio

    data = request.POST or None
    form = EnvioConfigForm(data, instance=ConfiguracaoEnvio.get_for_gom(gom))
    prazo = CaixinhaPrazoForm(data, instance=gom)
    # Só mexe nas formas quando o formset veio no POST (o formulário da aba sempre manda).
    metodos = metodos_formset(data if data is None or 'metodos-TOTAL_FORMS' in data else None, gom)
    extra = {'prazo_form': prazo, 'metodos': metodos}
    if request.method == 'POST' and form.is_valid() and prazo.is_valid() and (not metodos.is_bound or metodos.is_valid()):
        form.save()
        prazo.save()
        for i, f in enumerate(metodos.forms if metodos.is_bound else []):
            if f in metodos.deleted_forms:
                if f.instance.pk:
                    f.instance.delete()
                continue
            if not f.cleaned_data.get('nome'):
                continue  # linha em branco
            metodo = f.save(commit=False)
            metodo.gom = gom
            metodo.ordem = i
            metodo.save()
        return form, True, extra
    return form, False, extra


class RegrasForm(forms.ModelForm):
    class Meta:
        from .models import Gom
        model = Gom
        fields = ['regras']
        labels = {'regras': 'Regras do GOM'}
        widgets = {'regras': forms.Textarea(attrs={'rows': 14})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


def _regras(request, gom):
    from django.utils import timezone

    before = gom.regras
    form = RegrasForm(request.POST or None, instance=gom)
    if request.method == 'POST' and form.is_valid():
        gom = form.save(commit=False)
        if gom.regras.strip() != (before or '').strip():
            gom.regras_atualizadas_em = timezone.now()
        gom.save(update_fields=['regras', 'regras_atualizadas_em'])
        return form, True, {}
    return form, False, {}


class PadroesForm(forms.ModelForm):
    class Meta:
        from .models import Gom
        model = Gom
        fields = ['padrao_prazo_item_dias', 'padrao_horario_abertura', 'padrao_descricao', 'padrao_caixa_aberta']
        widgets = {'padrao_horario_abertura': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
                   'padrao_descricao': forms.Textarea(attrs={'rows': 5}),
                   'padrao_prazo_item_dias': forms.NumberInput(attrs={'min': 0, 'max': 60})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)
        self.fields['padrao_caixa_aberta'].widget.attrs['class'] = 'w-5 h-5 accent-[var(--ui-accent)]'


def _padroes(request, gom):
    form = PadroesForm(request.POST or None, instance=gom)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return form, True, {}
    return form, False, {}


HANDLERS = {'perfil': _perfil, 'pix': _pix, 'regras': _regras, 'padroes': _padroes, 'envio': _envio}
SAVED = {'perfil': 'Perfil do GOM atualizado.', 'pix': 'Chaves Pix atualizadas.', 'regras': 'Regras salvas.',
         'padroes': 'Padrões de CEG salvos.', 'envio': 'Configuração de envio atualizada.'}


@never_cache
@gom_member_required
@require_http_methods(['GET', 'POST'])
def gom_settings(request, tab):
    perm = tab_permission(tab)
    if perm is None or tab not in HANDLERS:
        raise Http404
    if not has_gom_perm(request, perm):
        raise PermissionDenied(DENIED)
    gom = request.active_gom
    form, saved, extra = HANDLERS[tab](request, gom)
    if saved:
        messages.success(request, SAVED[tab])
        return redirect('gom_settings_tab', tab=tab)
    tabs = visible_tabs(request, current=tab)
    if tab == 'regras':
        extra.update(_regras_stats(gom))
    if tab == 'padroes':
        from .ceg_defaults import newest_open_caixa
        extra['caixa_aberta'] = newest_open_caixa(gom)
    return render(request, 'goms/settings.html', {
        'gom': gom, 'form': form, 'tab': tab, 'tabs': tabs,
        'current_tab': next(t for t in tabs if t['active']), **extra,
    })


def _regras_stats(gom):
    """Quantos joiners já participaram (não precisam aceitar) e quantos aceitaram."""
    from apps.participants.models import Claim

    veteranos = Claim.objects.for_gom(gom).order_by().values('participant').distinct().count()
    return {'veteranos': veteranos, 'aceites': gom.aceites_regras.count()}



@gom_member_required
def old_profile_url(request):
    """Link antigo (/gom/perfil/) para as Configurações; só para a equipe, como as outras rotas do painel."""
    return redirect('gom_settings')
