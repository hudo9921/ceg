"""
Endereços do joiner (S2, docs/SITE_ONLY_PLAN.md): cadastrar, editar, excluir e buscar pelo CEP.
O CEP é consultado no ViaCEP pelo servidor (host fixo, só dígitos): a CSP do navegador continua só 'self'.
"""
import re

import requests
from django import forms
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from .models import Endereco
from .session_auth import get_session_participant

BACK = '/me/?tab=envios#enderecos'


class EnderecoForm(forms.ModelForm):
    class Meta:
        model = Endereco
        fields = ['apelido', 'nome_destinatario', 'cep', 'logradouro', 'numero', 'complemento', 'bairro', 'cidade',
                  'uf', 'padrao']

    def clean_cep(self):
        digits = re.sub(r'\D', '', self.cleaned_data.get('cep') or '')
        if len(digits) != 8:
            raise forms.ValidationError('CEP precisa ter 8 números.')
        return f'{digits[:5]}-{digits[5:]}'


def _participant_or_login(request):
    participant = get_session_participant(request)
    if participant is None:
        messages.error(request, 'Entre na sua conta para cuidar dos endereços.')
    return participant


@require_POST
def salvar(request):
    participant = _participant_or_login(request)
    if participant is None:
        return redirect('login_otp')
    instance = None
    if request.POST.get('id'):
        instance = get_object_or_404(Endereco, pk=request.POST['id'], participant=participant)
    form = EnderecoForm(request.POST, instance=instance)
    if not form.is_valid():
        erros = '; '.join(f'{form.fields[k].label}: {" ".join(v)}' for k, v in form.errors.items() if k in form.fields)
        messages.error(request, f'Confira o endereço: {erros or "dados incompletos"}.')
        return redirect(BACK)
    endereco = form.save(commit=False)
    endereco.participant = participant
    if endereco.padrao or not participant.enderecos.exclude(pk=endereco.pk).exists():
        endereco.padrao = True
        participant.enderecos.exclude(pk=endereco.pk).update(padrao=False)
    endereco.save()
    messages.success(request, 'Endereço salvo.')
    return redirect(BACK)


@require_POST
def excluir(request, endereco_id):
    participant = _participant_or_login(request)
    if participant is None:
        return redirect('login_otp')
    endereco = get_object_or_404(Endereco, pk=endereco_id, participant=participant)
    era_padrao = endereco.padrao
    endereco.delete()
    if era_padrao:
        primeiro = participant.enderecos.first()
        if primeiro:
            primeiro.padrao = True
            primeiro.save(update_fields=['padrao'])
    messages.success(request, 'Endereço excluído.')
    return redirect(BACK)


@require_GET
def cep(request, cep):
    """{logradouro, bairro, cidade, uf} do ViaCEP para preencher o formulário. Só para joiner logado."""
    if get_session_participant(request) is None:
        return JsonResponse({'success': False}, status=401)
    digits = re.sub(r'\D', '', cep)
    if len(digits) != 8:
        return JsonResponse({'success': False, 'message': 'CEP precisa ter 8 números.'}, status=400)
    try:
        resp = requests.get(f'https://viacep.com.br/ws/{digits}/json/', timeout=4,
                            headers={'User-Agent': 'ValCegs/1.0'})
        data = resp.json() if resp.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        data = {}
    if not data or data.get('erro'):
        return JsonResponse({'success': False, 'message': 'Não achamos esse CEP. Preencha à mão.'}, status=404)
    return JsonResponse({'success': True, 'logradouro': data.get('logradouro', ''), 'bairro': data.get('bairro', ''),
                         'cidade': data.get('localidade', ''), 'uf': data.get('uf', '')})
