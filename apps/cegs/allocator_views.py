import json
from django.views import View
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from apps.cegs.models import CEG
from apps.participants.models import Participant
from .services_allocator import BulkJoinerAllocatorService


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class CEGBulkAllocatorView(StaffRequiredMixin, View):
    """
    Tela principal do Alocador de Joiners em Massa para CEGs.
    Pode ser acessada com uma CEG pré-selecionada (/ceg/<slug>/alocar-massa/)
    ou de forma geral (/cegs/alocar-joiners/), selecionando a CEG desejada.
    """
    def get(self, request, slug=None):
        cegs_qs = CEG.objects.all().order_by('-created_at')
        ceg = None

        if slug:
            ceg = get_object_or_404(CEG, slug=slug)
        else:
            ceg_id = request.GET.get('ceg_id')
            if ceg_id and ceg_id.isdigit():
                ceg = CEG.objects.filter(id=int(ceg_id)).first()

            if not ceg:
                # Prioriza CEGs abertas ou em andamento
                ceg = cegs_qs.filter(status=CEG.Status.OPEN).first() or cegs_qs.first()

        if not ceg:
            return render(request, 'cegs/bulk_allocator.html', {
                'ceg': None,
                'cegs_list': [],
                'matrix_data': None,
                'matrix_json': '{}',
                'participants_json': '[]',
            })

        matrix_data = BulkJoinerAllocatorService.get_ceg_matrix(ceg)

        participants_qs = Participant.objects.all().order_by('name')
        participants_data = [
            {
                'id': p.id,
                'name': p.name,
                'display_name': p.display_name,
                'whatsapp': p.whatsapp or '',
                'formatted_phone': p.formatted_phone,
                'social_handle': p.social_handle or '',
            }
            for p in participants_qs
        ]

        cegs_list = [
            {
                'id': c.id,
                'title': c.title,
                'slug': c.slug,
                'status': c.status,
                'status_display': c.get_status_display(),
                'sets_count': c.sets.count(),
                'items_count': c.item_definitions.count(),
            }
            for c in cegs_qs
        ]

        return render(request, 'cegs/bulk_allocator.html', {
            'ceg': ceg,
            'cegs_list': cegs_list,
            'matrix_data': matrix_data,
            'matrix_json': json.dumps(matrix_data),
            'participants_json': json.dumps(participants_data),
        })


class CEGBulkAllocatorAPIView(StaffRequiredMixin, View):
    """
    Endpoints AJAX JSON para processamento de colagem, execução em lote e gravação da matriz.
    """
    def post(self, request, slug):
        ceg = get_object_or_404(CEG, slug=slug)

        try:
            if request.content_type == 'application/json':
                data = json.loads(request.body.decode('utf-8') or '{}')
            else:
                data = request.POST
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Requisição inválida: {e}'}, status=400)

        action = data.get('action')

        # 1. Parse de texto colado
        if action == 'parse_text':
            raw_text = data.get('raw_text', '')
            options = {
                'overwrite': bool(data.get('overwrite', False)),
                'auto_next_set': bool(data.get('auto_next_set', True)),
                'default_is_paid': bool(data.get('default_is_paid', False)),
            }
            result = BulkJoinerAllocatorService.parse_allocation_text(ceg, raw_text, options)
            return JsonResponse(result)

        # 2. Executar alocação em lote
        elif action == 'execute_bulk':
            rows = data.get('rows', [])
            if not rows:
                return JsonResponse({'success': False, 'message': 'Nenhuma linha para processar.'}, status=400)

            options = {
                'overwrite': bool(data.get('overwrite', False)),
                'auto_create_participants': bool(data.get('auto_create_participants', True)),
            }
            result = BulkJoinerAllocatorService.execute_bulk_allocations(ceg, rows, options)
            # Retorna também a matriz atualizada
            result['updated_matrix'] = BulkJoinerAllocatorService.get_ceg_matrix(ceg)
            return JsonResponse(result)

        # 3. Salvar matriz interativa (célula a célula ou em lote)
        elif action == 'save_matrix':
            updates = data.get('updates', [])
            if not updates:
                return JsonResponse({'success': False, 'message': 'Nenhuma alteração na matriz para salvar.'}, status=400)

            result = BulkJoinerAllocatorService.save_matrix_allocations(ceg, updates)
            result['updated_matrix'] = BulkJoinerAllocatorService.get_ceg_matrix(ceg)
            return JsonResponse(result)

        # 4. Obter matriz atualizada
        elif action == 'get_matrix':
            matrix = BulkJoinerAllocatorService.get_ceg_matrix(ceg)
            return JsonResponse({'success': True, 'matrix': matrix})

        return JsonResponse({'success': False, 'message': f'Ação desconhecida: {action}'}, status=400)
