import base64
import json
import logging
import uuid
from decimal import Decimal, InvalidOperation
from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils.dateparse import parse_datetime

from apps.cegs.models import Caixa, ItemIndividual, TipoItem
from apps.participants.models import Participant, clean_phone_number

logger = logging.getLogger(__name__)


class StaffRequiredMixin(AccessMixin):
    """Garante que apenas usuários autenticados e com permissão de staff (admin/organizador) tenham acesso."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': 'Acesso restrito ao organizador.'}, status=403)
            messages.error(request, "Acesso restrito: Você precisa estar autenticado como Administrador/Organizador.")
            return redirect(f"/admin/login/?next={request.path}")
        return super().dispatch(request, *args, **kwargs)


def parse_optional_decimal(v_str):
    if not v_str:
        return None
    try:
        val_clean = str(v_str).replace('R$', '').replace(' ', '').replace(',', '.').strip()
        if not val_clean:
            return None
        val = Decimal(val_clean)
        if val < 0 or val > Decimal('9999999999.99'):
            return None
        return val
    except (InvalidOperation, ValueError):
        return None


class ParticipantLookupAPIView(StaffRequiredMixin, View):
    """Retorna dados de participante existente pelo telefone para preenchimento ágil."""

    def get(self, request):
        phone_raw = request.GET.get('phone', '').strip()
        if not phone_raw:
            return JsonResponse({'found': False})

        cleaned = clean_phone_number(phone_raw)
        p = None
        if cleaned:
            p = Participant.objects.filter(whatsapp=cleaned).first()
            if not p and len(cleaned) >= 8:
                p = Participant.objects.filter(whatsapp__endswith=cleaned[-8:]).first()

        if p:
            return JsonResponse({
                'found': True,
                'id': p.id,
                'name': p.name,
                'username': p.username,
                'whatsapp': p.whatsapp,
                'formatted_phone': p.formatted_phone,
                'social_handle': p.social_handle,
            })
        return JsonResponse({'found': False})


class CreateItemIndividualView(StaffRequiredMixin, View):
    """Cadastra um novo Item Individual (Mercari, Surugaya, etc.)."""

    def post(self, request):
        nome = request.POST.get('nome', '').strip()
        link_pedido = request.POST.get('link_pedido', '').strip()
        quantidade_str = request.POST.get('quantidade', '1').strip()
        caixa_id = request.POST.get('caixa_id', '').strip()
        status = request.POST.get('status', ItemIndividual.Status.COMPRADO).strip()

        whatsapp = request.POST.get('whatsapp', '').strip()
        comprador_nome = request.POST.get('comprador_nome', '').strip()
        comprador_username = request.POST.get('comprador_username', '').strip()
        comprador_social = request.POST.get('comprador_social', '').strip()

        preco_produto = parse_optional_decimal(request.POST.get('preco_produto'))
        frete_inter = parse_optional_decimal(request.POST.get('frete_inter'))
        frete_inter_pago = request.POST.get('frete_inter_pago') in ('on', 'true', '1', True)
        taxa_aduaneira = parse_optional_decimal(request.POST.get('taxa_aduaneira'))
        taxa_aduaneira_paga = request.POST.get('taxa_aduaneira_paga') in ('on', 'true', '1', True)
        observacoes = request.POST.get('observacoes', '').strip()
        foto_url = request.POST.get('foto_url', '').strip()
        next_url = request.POST.get('next_url', '').strip()

        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

        if not nome:
            if is_ajax:
                return JsonResponse({'success': False, 'message': 'O nome do item é obrigatório.'}, status=400)
            messages.error(request, "O nome / descrição do item é obrigatório.")
            return redirect(next_url or '/creations/?category=mercari')

        participant_id = request.POST.get('participant_id', '').strip()
        comprador = None

        if participant_id:
            try:
                comprador = Participant.objects.filter(id=int(participant_id)).first()
            except (ValueError, TypeError):
                comprador = None

        if not comprador:
            if not whatsapp:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'O WhatsApp do comprador é obrigatório.'}, status=400)
                messages.error(request, "Informe o WhatsApp do comprador para vinculação.")
                return redirect(next_url or '/creations/?tab=mercari')

            cleaned_phone = clean_phone_number(whatsapp)
            if not cleaned_phone:
                if is_ajax:
                    return JsonResponse({'success': False, 'message': 'Número de WhatsApp inválido.'}, status=400)
                messages.error(request, "Número de WhatsApp inválido.")
                return redirect(next_url or '/creations/?tab=mercari')

            # Cria ou localiza comprador
            comprador, created = Participant.objects.get_or_create(
                whatsapp=cleaned_phone,
                defaults={
                    'name': comprador_nome or f"Comprador {cleaned_phone[-4:]}",
                    'username': comprador_username,
                    'social_handle': comprador_social if comprador_social.startswith('@') or not comprador_social else f"@{comprador_social}",
                }
            )
            if not created:
                updated = False
                if comprador_nome and comprador.name != comprador_nome:
                    comprador.name = comprador_nome
                    updated = True
                if comprador_username and comprador.username != comprador_username:
                    comprador.username = comprador_username
                    updated = True
                if comprador_social:
                    social_fmt = comprador_social if comprador_social.startswith('@') else f"@{comprador_social}"
                    if comprador.social_handle != social_fmt:
                        comprador.social_handle = social_fmt
                        updated = True
                if updated:
                    comprador.save()
        else:
            # Participante já existente selecionado via dropdown ou lookup
            updated = False
            if comprador_nome and comprador.name != comprador_nome:
                comprador.name = comprador_nome
                updated = True
            if comprador_username and comprador.username != comprador_username:
                comprador.username = comprador_username
                updated = True
            if comprador_social:
                social_fmt = comprador_social if comprador_social.startswith('@') else f"@{comprador_social}"
                if comprador.social_handle != social_fmt:
                    comprador.social_handle = social_fmt
                    updated = True
            if updated:
                comprador.save()

        # Localiza Caixa
        caixa = None
        if caixa_id:
            try:
                caixa = Caixa.objects.filter(id=int(caixa_id)).first()
            except (ValueError, TypeError):
                caixa = None

        try:
            quantidade = max(1, int(quantidade_str))
        except (ValueError, TypeError):
            quantidade = 1

        # Processamento de imagem
        foto_arquivo = request.FILES.get('foto_arquivo')
        foto_base64 = request.POST.get('foto_base64', '').strip()

        if not foto_arquivo and foto_base64:
            try:
                if ',' in foto_base64:
                    header, data_str = foto_base64.split(',', 1)
                else:
                    header = ''
                    data_str = foto_base64
                decoded = base64.b64decode(data_str)
                ext = 'png'
                if 'jpeg' in header or 'jpg' in header:
                    ext = 'jpg'
                elif 'webp' in header:
                    ext = 'webp'
                elif 'gif' in header:
                    ext = 'gif'
                filename = f"mercari_{uuid.uuid4().hex[:10]}.{ext}"
                foto_arquivo = ContentFile(decoded, name=filename)
            except Exception as e:
                logger.warning(f"Erro ao decodificar foto_base64: {e}")
                foto_arquivo = None

        tipo_item_id = request.POST.get('tipo_item_id')
        tipo_item = None
        if tipo_item_id:
            try:
                tipo_item = TipoItem.objects.filter(id=int(tipo_item_id)).first()
            except (ValueError, TypeError):
                tipo_item = None

        try:
            item = ItemIndividual.objects.create(
                caixa=caixa,
                comprador=comprador,
                tipo_item=tipo_item,
                nome=nome,
                link_pedido=link_pedido,
                quantidade=quantidade,
                foto_arquivo=foto_arquivo,
                foto_url=foto_url,
                status=status,
                preco_produto=preco_produto,
                frete_inter=frete_inter,
                frete_inter_pago=frete_inter_pago,
                taxa_aduaneira=taxa_aduaneira,
                taxa_aduaneira_paga=taxa_aduaneira_paga,
                observacoes=observacoes,
            )

            msg = f"🇯🇵 Item '{item.nome}' cadastrado com sucesso para {comprador.display_name}!"
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': msg,
                    'item_id': item.id,
                    'item_nome': item.nome,
                    'tipo_item_id': item.tipo_item_id,
                    'tipo_item_nome': item.tipo_item.nome if item.tipo_item else 'Item',
                    'status': item.status,
                    'image_url': item.image_display_url,
                })

            messages.success(request, msg)
            if next_url:
                return redirect(next_url)
            if caixa:
                return redirect('caixa_detail', slug=caixa.slug)
            return redirect('/creations/?tab=mercari')

        except Exception as e:
            logger.exception("Erro ao criar item individual")
            if is_ajax:
                return JsonResponse({'success': False, 'message': f"Erro ao criar item: {str(e)}"}, status=500)
            messages.error(request, f"Erro ao cadastrar item individual: {str(e)}")
            return redirect(next_url or '/creations/?tab=mercari')


class UpdateItemIndividualView(StaffRequiredMixin, View):
    """Atualiza dados, status e valores de um Item Individual existente."""

    def post(self, request, item_id):
        item = get_object_or_404(ItemIndividual, id=item_id)
        next_url = request.POST.get('next_url', '').strip()
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

        nome = request.POST.get('nome', '').strip()
        if nome:
            item.nome = nome

        link_pedido = request.POST.get('link_pedido', '').strip()
        if 'link_pedido' in request.POST:
            item.link_pedido = link_pedido

        quantidade_str = request.POST.get('quantidade', '').strip()
        if quantidade_str:
            try:
                item.quantidade = max(1, int(quantidade_str))
            except ValueError:
                pass

        if 'status' in request.POST:
            novo_status = request.POST.get('status', '').strip()
            if novo_status in ItemIndividual.Status.values:
                item.status = novo_status

        if 'caixa_id' in request.POST:
            caixa_id = request.POST.get('caixa_id', '').strip()
            if caixa_id:
                try:
                    item.caixa = Caixa.objects.filter(id=int(caixa_id)).first()
                except ValueError:
                    pass
            else:
                item.caixa = None

        if 'tipo_item_id' in request.POST:
            tipo_item_id = request.POST.get('tipo_item_id', '').strip()
            if tipo_item_id:
                try:
                    item.tipo_item = TipoItem.objects.filter(id=int(tipo_item_id)).first()
                except ValueError:
                    pass
            else:
                item.tipo_item = None

        if 'preco_produto' in request.POST:
            item.preco_produto = parse_optional_decimal(request.POST.get('preco_produto'))
        if 'frete_inter' in request.POST:
            item.frete_inter = parse_optional_decimal(request.POST.get('frete_inter'))
        if 'taxa_aduaneira' in request.POST:
            item.taxa_aduaneira = parse_optional_decimal(request.POST.get('taxa_aduaneira'))

        if 'produto_pago' in request.POST:
            item.produto_pago = request.POST.get('produto_pago') in ('on', 'true', '1', True)
        if 'frete_inter_pago' in request.POST:
            item.frete_inter_pago = request.POST.get('frete_inter_pago') in ('on', 'true', '1', True)
        if 'taxa_aduaneira_paga' in request.POST:
            item.taxa_aduaneira_paga = request.POST.get('taxa_aduaneira_paga') in ('on', 'true', '1', True)

        if 'prazo_frete_inter' in request.POST:
            prazo_str = request.POST.get('prazo_frete_inter', '').strip()
            item.prazo_frete_inter = parse_datetime(prazo_str) if prazo_str else None

        if 'prazo_taxa_aduaneira' in request.POST:
            prazo_str = request.POST.get('prazo_taxa_aduaneira', '').strip()
            item.prazo_taxa_aduaneira = parse_datetime(prazo_str) if prazo_str else None

        if 'observacoes' in request.POST:
            item.observacoes = request.POST.get('observacoes', '').strip()

        if 'foto_url' in request.POST:
            item.foto_url = request.POST.get('foto_url', '').strip()

        foto_arquivo = request.FILES.get('foto_arquivo')
        if foto_arquivo:
            item.foto_arquivo = foto_arquivo
        else:
            foto_base64 = request.POST.get('foto_base64', '').strip()
            if foto_base64:
                try:
                    if ',' in foto_base64:
                        header, data_str = foto_base64.split(',', 1)
                    else:
                        header = ''
                        data_str = foto_base64
                    decoded = base64.b64decode(data_str)
                    ext = 'png'
                    if 'jpeg' in header or 'jpg' in header:
                        ext = 'jpg'
                    elif 'webp' in header:
                        ext = 'webp'
                    filename = f"mercari_{uuid.uuid4().hex[:10]}.{ext}"
                    item.foto_arquivo = ContentFile(decoded, name=filename)
                except Exception as e:
                    logger.warning(f"Erro ao decodificar foto_base64 no update: {e}")

        item.save()

        msg = f"Item '{item.nome}' atualizado com sucesso!"
        if is_ajax:
            return JsonResponse({'success': True, 'message': msg})

        messages.success(request, msg)
        if next_url:
            return redirect(next_url)
        if item.caixa:
            return redirect('caixa_detail', slug=item.caixa.slug)
        return redirect('/creations/?tab=mercari')


@method_decorator(csrf_exempt, name='dispatch')
class ToggleItemPaymentView(StaffRequiredMixin, View):
    """Alterna rapidamente o status de pagamento de item (produto), frete internacional ou taxa aduaneira."""

    def post(self, request, item_id):
        item = get_object_or_404(ItemIndividual, id=item_id)
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

        if request.content_type == 'application/json':
            try:
                body = json.loads(request.body.decode('utf-8') or '{}')
            except Exception:
                body = {}
            raw_tipo = (body.get('tipo') or body.get('field') or '').strip().lower()
        else:
            raw_tipo = (request.POST.get('tipo') or request.POST.get('field') or 'frete').strip().lower()

        if 'item' in raw_tipo or 'produto' in raw_tipo:
            tipo = 'item'
        elif 'taxa' in raw_tipo:
            tipo = 'taxa'
        elif 'frete' in raw_tipo or 'inter' in raw_tipo:
            tipo = 'frete'
        else:
            if is_ajax:
                return JsonResponse({'success': False, 'message': f'Tipo de pagamento desconhecido: "{raw_tipo}"'}, status=400)
            return redirect(request.META.get('HTTP_REFERER', '/'))

        if tipo == 'item':
            item.produto_pago = not item.produto_pago
            status_text = "Pago ✔" if item.produto_pago else "Pendente"
            msg = f"Item '{item.nome}' marcado como: {status_text}."
            new_val = item.produto_pago
            item.save(update_fields=['produto_pago'])
        elif tipo == 'taxa':
            item.taxa_aduaneira_paga = not item.taxa_aduaneira_paga
            status_text = "Pago ✔" if item.taxa_aduaneira_paga else "Pendente"
            msg = f"Taxa aduaneira de '{item.nome}' marcada como: {status_text}."
            new_val = item.taxa_aduaneira_paga
            item.save(update_fields=['taxa_aduaneira_paga'])
        else:
            item.frete_inter_pago = not item.frete_inter_pago
            status_text = "Pago ✔" if item.frete_inter_pago else "Pendente"
            msg = f"Frete internacional de '{item.nome}' marcado como: {status_text}."
            new_val = item.frete_inter_pago
            item.save(update_fields=['frete_inter_pago'])

        # Registra auditoria da alteração de pagamento
        try:
            from apps.cegs.audit_service import AuditService
            AuditService.log_payment_change(
                item_individual=item,
                field_name=tipo,
                old_value=not new_val,
                new_value=new_val,
                actor=request.user,
            )
        except Exception:
            pass

        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': msg,
                'item_id': item.id,
                'tipo': tipo,
                'field': tipo,
                'new_value': new_val,
                'is_paid': new_val,
                'is_item_paid': item.produto_pago,
                'is_frete_inter_paid': item.frete_inter_pago,
                'is_taxa_aduaneira_paid': item.taxa_aduaneira_paga,
                'pode_empacotar': item.pode_empacotar,
                'motivo_bloqueio': item.motivo_bloqueio,
            })

        messages.success(request, msg)
        return redirect(request.META.get('HTTP_REFERER', '/'))


class DeleteItemIndividualView(StaffRequiredMixin, View):
    """Remove um Item Individual."""

    def post(self, request, item_id):
        item = get_object_or_404(ItemIndividual, id=item_id)
        nome = item.nome
        caixa = item.caixa
        item.delete()

        msg = f"Item individual '{nome}' removido com sucesso."
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'
        if is_ajax:
            return JsonResponse({'success': True, 'message': msg})

        messages.success(request, msg)
        next_url = request.POST.get('next_url', '')
        if next_url:
            return redirect(next_url)
        if caixa:
            return redirect('caixa_detail', slug=caixa.slug)
        return redirect('/creations/?tab=mercari')
