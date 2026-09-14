import logging
import requests
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.decorators import method_decorator
from django.views import View

from .providers import get_whatsapp_provider

logger = logging.getLogger(__name__)


def get_evolution_config():
    api_url = getattr(settings, 'EVOLUTION_API_URL', 'http://valcegs-evolution:8080').rstrip('/')
    api_key = getattr(settings, 'EVOLUTION_API_KEY', 'valcegs-secret-evolution-api-key-2026')
    instance_name = getattr(settings, 'EVOLUTION_INSTANCE_NAME', 'ceg-bot')
    return api_url, api_key, instance_name


def fetch_instance_state():
    """
    Retorna o estado da conexão ('open', 'connecting', 'close', 'unknown')
    e os dados da instância.
    """
    api_url, api_key, instance_name = get_evolution_config()
    headers = {'apikey': api_key}
    try:
        resp = requests.get(f"{api_url}/instance/connectionState/{instance_name}", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            state = data.get('instance', {}).get('state') or data.get('state', 'unknown')
            return state, data
    except Exception as e:
        logger.error(f"Erro ao consultar connectionState na Evolution API: {e}")
    return 'offline', {}


def fetch_qr_code():
    """
    Busca o QR Code em base64 da Evolution API.
    """
    api_url, api_key, instance_name = get_evolution_config()
    headers = {'apikey': api_key}
    try:
        resp = requests.get(f"{api_url}/instance/connect/{instance_name}", headers=headers, timeout=10)
        if resp.status_code in (200, 201):
            data = resp.json()
            base64_img = data.get('base64') or data.get('qrcode', {}).get('base64')
            pairing_code = data.get('pairingCode') or data.get('qrcode', {}).get('pairingCode')
            code = data.get('code') or data.get('qrcode', {}).get('code')
            return {
                'base64': base64_img,
                'pairingCode': pairing_code,
                'code': code
            }
    except Exception as e:
        logger.error(f"Erro ao buscar QR Code na Evolution API: {e}")
    return {}


@method_decorator(staff_member_required, name='dispatch')
class WhatsAppManagerView(View):
    template_name = 'admin/whatsapp_manager.html'

    def get(self, request):
        state, instance_data = fetch_instance_state()
        qr_data = {}
        if state != 'open':
            qr_data = fetch_qr_code()

        context = {
            'state': state,
            'instance_data': instance_data,
            'qr_data': qr_data,
            'evolution_url': getattr(settings, 'EVOLUTION_API_URL', ''),
            'instance_name': getattr(settings, 'EVOLUTION_INSTANCE_NAME', 'ceg-bot'),
            'provider_name': getattr(settings, 'WHATSAPP_PROVIDER', 'evolution'),
        }
        return render(request, self.template_name, context)

    def post(self, request):
        action = request.POST.get('action')
        api_url, api_key, instance_name = get_evolution_config()
        headers = {'apikey': api_key}

        if action == 'send_test':
            phone = request.POST.get('phone', '').strip()
            message = request.POST.get('message', '').strip()
            if not phone or not message:
                messages.error(request, "Por favor, preencha o número de telefone e a mensagem.")
            else:
                provider = get_whatsapp_provider()
                success = provider.send_message(phone, message)
                if success:
                    messages.success(request, f"Mensagem de teste enviada com sucesso para {phone}!")
                else:
                    messages.error(request, f"Falha ao enviar mensagem para {phone}. Verifique os logs.")

        elif action == 'logout':
            try:
                resp = requests.delete(f"{api_url}/instance/logout/{instance_name}", headers=headers, timeout=10)
                if resp.status_code in (200, 204):
                    messages.success(request, "Instância desconectada com sucesso. Um novo QR Code pode ser gerado.")
                else:
                    messages.error(request, f"Erro ao desconectar: {resp.text}")
            except Exception as e:
                messages.error(request, f"Exceção ao desconectar: {e}")

        elif action == 'restart':
            try:
                resp = requests.post(f"{api_url}/instance/restart/{instance_name}", headers=headers, timeout=10)
                if resp.status_code in (200, 201):
                    messages.success(request, "Instância reiniciada.")
                else:
                    messages.error(request, f"Erro ao reiniciar: {resp.text}")
            except Exception as e:
                messages.error(request, f"Exceção ao reiniciar: {e}")

        return redirect('admin_whatsapp')


@method_decorator(staff_member_required, name='dispatch')
class WhatsAppStatusAPIView(View):
    """
    Endpoint JSON para polling em tempo real do status e QR Code.
    """
    def get(self, request):
        state, instance_data = fetch_instance_state()
        qr_data = {}
        if state != 'open':
            qr_data = fetch_qr_code()

        return JsonResponse({
            'state': state,
            'base64': qr_data.get('base64'),
            'pairingCode': qr_data.get('pairingCode'),
        })
