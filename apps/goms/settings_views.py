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
            return form, False
        profile.save()
        return form, True
    return form, False


def _pix(request, gom):
    form = GomProfileForm(request.POST or None, instance=gom, can_edit_profile=False, can_edit_pix=True)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return form, True
    return form, False


def _envio(request, gom):
    from apps.cegs.models import ConfiguracaoEnvio

    form = EnvioConfigForm(request.POST or None, instance=ConfiguracaoEnvio.get_for_gom(gom))
    if request.method == 'POST' and form.is_valid():
        form.save()
        return form, True
    return form, False


HANDLERS = {'perfil': _perfil, 'pix': _pix, 'envio': _envio}
SAVED = {'perfil': 'Perfil do GOM atualizado.', 'pix': 'Chaves Pix atualizadas.', 'envio': 'Configuração de envio atualizada.'}


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
    form, saved = HANDLERS[tab](request, gom)
    if saved:
        messages.success(request, SAVED[tab])
        return redirect('gom_settings_tab', tab=tab)
    tabs = visible_tabs(request, current=tab)
    return render(request, 'goms/settings.html', {
        'gom': gom, 'form': form, 'tab': tab, 'tabs': tabs,
        'current_tab': next(t for t in tabs if t['active']),
    })



@gom_member_required
def old_profile_url(request):
    """Link antigo (/gom/perfil/) para as Configurações; só para a equipe, como as outras rotas do painel."""
    return redirect('gom_settings')
