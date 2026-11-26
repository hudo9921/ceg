"""
Push no navegador (S4): service worker (/sw.js), manifesto do app (/manifest.webmanifest) e inscrever/cancelar/testar.
Quem está logado como joiner recebe os avisos de /me/; quem é da equipe de um GOM recebe os do painel. Um aparelho
pode ser os dois (mesma inscrição).
"""
import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.participants.session_auth import get_session_participant

from .models import Inscricao
from .push import enviar
from .vapid import chave_publica


def _dono(request):
    """(participant, user) a quem o aparelho pertence; user só se for da equipe de algum GOM ou da plataforma."""
    participant = get_session_participant(request)
    user = request.user if request.user.is_authenticated and (
        request.user.is_superuser or request.user.gom_memberships.exists()) else None
    return participant, user


def _corpo(request):
    try:
        return json.loads(request.body or '{}')
    except ValueError:
        return {}


@require_GET
@cache_control(no_cache=True, max_age=0)
def service_worker(request):
    resposta = render(request, 'avisos/sw.js', content_type='application/javascript')
    resposta['Service-Worker-Allowed'] = '/'
    return resposta


@require_GET
@cache_control(max_age=86400)
def manifesto(request):
    return render(request, 'avisos/manifest.webmanifest', content_type='application/manifest+json')


@require_POST
def inscrever(request):
    participant, user = _dono(request)
    if participant is None and user is None:
        return JsonResponse({'success': False, 'requires_auth': True, 'message': 'Entre na sua conta para ativar.'}, status=401)
    body = _corpo(request)
    sub = body.get('subscription') or {}
    keys = sub.get('keys') or {}
    endpoint = (sub.get('endpoint') or '')[:1000]
    if not endpoint.startswith('https://') or not keys.get('p256dh') or not keys.get('auth'):
        return JsonResponse({'success': False, 'message': 'Inscrição inválida.'}, status=400)
    Inscricao.objects.update_or_create(endpoint=endpoint, defaults={
        'participant': participant, 'user': user, 'p256dh': keys['p256dh'][:200], 'auth': keys['auth'][:100],
        'aparelho': (body.get('aparelho') or '')[:120], 'falhas': 0})
    return JsonResponse({'success': True, 'message': 'Pronto! Você vai receber os avisos neste aparelho.'})


@require_POST
def cancelar(request):
    participant, user = _dono(request)
    endpoint = (_corpo(request).get('endpoint') or '')[:1000]
    # Quem conhece o endpoint é o próprio navegador; ainda assim, só apaga o que é deste joiner/usuário.
    from django.db.models import Q
    dono = (Q(participant=participant) if participant else Q(pk__in=[])) | (Q(user=user) if user else Q(pk__in=[]))
    Inscricao.objects.filter(dono, endpoint=endpoint).delete()
    return JsonResponse({'success': True, 'message': 'Avisos desligados neste aparelho.'})


@require_POST
@never_cache
def testar(request):
    participant, user = _dono(request)
    endpoint = (_corpo(request).get('endpoint') or '')[:1000]
    qs = Inscricao.objects.filter(endpoint=endpoint)
    qs = qs.filter(participant=participant) if participant else qs.filter(user=user) if user else qs.none()
    if not qs.exists():
        return JsonResponse({'success': False, 'message': 'Ative os avisos neste aparelho primeiro.'}, status=400)
    enviar(qs, 'Avisos ligados', 'É assim que os avisos do CegManager vão chegar.', '/me/' if participant else '/notificacoes/')
    return JsonResponse({'success': True, 'message': 'Enviamos um aviso de teste.'})


@require_GET
def chave(request):
    return JsonResponse({'chave': chave_publica()})
