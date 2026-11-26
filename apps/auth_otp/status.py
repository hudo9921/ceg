"""
Estado do bot do WhatsApp para o administrador da plataforma: aviso no menu ("off") e resumo na página do bot.
A consulta à Evolution API fica 60 s no cache para o menu não chamar a API a cada página.
"""
from datetime import timedelta

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

CHAVE_CACHE = 'whatsapp:estado'
MOTIVOS = {
    401: 'O WhatsApp desconectou este aparelho (removido de "Aparelhos conectados" ou celular muito tempo offline).',
    403: 'O WhatsApp bloqueou o número.',
    408: 'A conexão caiu por falta de resposta.',
    428: 'A conexão foi fechada.',
    440: 'Outra sessão do WhatsApp Web substituiu esta.',
    500: 'A sessão ficou inválida.',
    515: 'O WhatsApp pediu para reiniciar a conexão.',
}


def usa_evolution():
    return getattr(settings, 'WHATSAPP_PROVIDER', 'console') == 'evolution'


def _consultar():
    from .views import get_evolution_config

    api_url, api_key, nome = get_evolution_config()
    info = {'estado': 'offline', 'conectado': False, 'desde': None, 'motivo': ''}
    try:
        resp = requests.get(f'{api_url}/instance/fetchInstances', headers={'apikey': api_key},
                            params={'instanceName': nome}, timeout=4)
        dados = resp.json() if resp.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return info
    inst = next((i for i in dados if isinstance(i, dict) and i.get('name') == nome), None)
    if not inst:
        info['estado'] = 'sem_instancia'
        return info
    info['estado'] = inst.get('connectionStatus') or 'unknown'
    info['conectado'] = info['estado'] == 'open'
    if not info['conectado']:
        quando = parse_datetime(inst.get('disconnectionAt') or '')
        info['desde'] = quando
        codigo = inst.get('disconnectionReasonCode')
        info['motivo'] = MOTIVOS.get(codigo, f'Código {codigo}.' if codigo else '')
    return info


def estado_do_bot(usar_cache=True):
    """{'estado', 'conectado', 'desde', 'motivo'}; None quando o provedor não é a Evolution (console, Z-API)."""
    if not usa_evolution():
        return None
    info = cache.get(CHAVE_CACHE) if usar_cache else None
    if info is None:
        info = _consultar()
        cache.set(CHAVE_CACHE, info, 60)
    return info


def resumo_codigos():
    """Códigos de login pedidos e usados (24 h e 7 dias) e os últimos pedidos, com o telefone mascarado."""
    from .models import WhatsAppOTP

    agora = timezone.now()
    resumo = []
    for rotulo, delta in (('24 horas', timedelta(hours=24)), ('7 dias', timedelta(days=7))):
        qs = WhatsAppOTP.objects.filter(created_at__gte=agora - delta)
        resumo.append({'rotulo': rotulo, 'pedidos': qs.count(), 'usados': qs.filter(is_used=True).count()})
    ultimos = [{'fone': '•••• ' + (o.phone or '')[-4:], 'quando': o.created_at, 'usado': o.is_used}
               for o in WhatsAppOTP.objects.order_by('-created_at')[:8]]
    return resumo, ultimos
