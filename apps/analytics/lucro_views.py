"""
Relatórios → Lucro por CEG: vendido e recebido (itens) contra o custo que o GOM pagou pelos itens.
Frete internacional e taxa ficam de fora: são repassados ao joiner pela caixa.
"""
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.cegs.models import CEG
from apps.core.permissions import staff_required
from apps.participants.models import Claim

ZERO = Decimal('0.00')


class CustoForm(forms.ModelForm):
    class Meta:
        model = CEG
        fields = ['custo_moeda', 'custo_valor', 'custo_cambio', 'custo_taxas_brl', 'custo_obs']

    def clean(self):
        data = super().clean()
        if data.get('custo_valor') is not None and data.get('custo_moeda') != 'BRL' and not data.get('custo_cambio'):
            self.add_error('custo_cambio', 'Informe o câmbio para converter para reais.')
        return data


def _rows(gom):
    claims = (Claim.objects.for_gom(gom).exclude(status=Claim.Status.CANCELLED).order_by()
              .values('slot__set__ceg').annotate(
                  vendido=Sum('total_price'), itens=Count('id'),
                  recebido=Sum('total_price', filter=Q(status=Claim.Status.PAID))))
    by_ceg = {c['slot__set__ceg']: c for c in claims}
    rows, tot = [], {'vendido': ZERO, 'recebido': ZERO, 'custo': ZERO, 'lucro': ZERO}
    for ceg in CEG.objects.for_gom(gom).select_related('era__group').order_by('-created_at'):
        agg = by_ceg.get(ceg.id, {})
        vendido, recebido = agg.get('vendido') or ZERO, agg.get('recebido') or ZERO
        custo = ceg.custo_brl
        lucro = vendido - custo if custo is not None else None
        rows.append({'ceg': ceg, 'itens': agg.get('itens', 0), 'vendido': vendido, 'recebido': recebido,
                     'custo': custo, 'lucro': lucro,
                     'margem': round(lucro / vendido * 100) if lucro is not None and vendido else None})
        tot['vendido'] += vendido
        tot['recebido'] += recebido
        if custo is not None:
            tot['custo'] += custo
            tot['lucro'] += lucro
    tot['sem_custo'] = sum(1 for r in rows if r['custo'] is None and r['vendido'])
    return rows, tot


@staff_required('analytics.ver')
@require_http_methods(['GET', 'POST'])
def lucro_cegs(request):
    gom = request.active_gom
    if request.method == 'POST':
        ceg = get_object_or_404(CEG.objects.for_gom(gom), pk=request.POST.get('ceg_id'))
        form = CustoForm(request.POST, instance=ceg)
        if form.is_valid():
            form.save()
            messages.success(request, f'Custo de "{ceg.title}" salvo.')
        else:
            erros = '; '.join(' '.join(v) for v in form.errors.values())
            messages.error(request, f'Não salvou o custo: {erros}')
        return redirect(f"{request.path}#ceg-{ceg.id}")
    rows, tot = _rows(gom)
    vendido_com_custo = sum((r['vendido'] for r in rows if r['custo'] is not None), ZERO)
    tot['margem'] = round(tot['lucro'] / vendido_com_custo * 100) if vendido_com_custo else None
    return render(request, 'analytics/lucro.html', {'rows': rows, 'tot': tot, 'moedas': CEG.CUSTO_MOEDAS})
