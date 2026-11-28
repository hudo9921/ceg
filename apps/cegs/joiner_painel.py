"""
Painel lateral do joiner (equipe do GOM): clicar no nome de um joiner em qualquer tela do painel abre um resumo —
quanto deve, o que pagou, itens, pacotes e se tem endereço — sem sair da página. Só o GOM ativo (for_gom).
Não mostra endereço nem telefone completo (LGPD): para isso, a Consulta 360°.
"""
from decimal import Decimal

from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from apps.core.permissions import staff_required
from apps.participants.models import Claim, Participant

from .models import ItemIndividual, PacoteNacional

LIMITE_ITENS = 8


@staff_required('pedidos.ver')
def painel(request, participant_id):
    from apps.pagamentos.models import Cobranca
    from apps.pagamentos.services import open_groups

    gom = request.active_gom
    p = get_object_or_404(Participant.objects.for_gom(gom), pk=participant_id)
    claims = list(Claim.objects.for_gom(gom).filter(participant=p).exclude(status=Claim.Status.CANCELLED)
                  .select_related('slot__item_definition', 'slot__set__ceg', 'slot__pacote_nacional')
                  .order_by('-claimed_at'))
    avulsos = list(ItemIndividual.objects.for_gom(gom).filter(comprador=p).order_by('-created_at')[:LIMITE_ITENS])
    grupos = open_groups(p, gom)
    pix_abertos = list(Cobranca.objects.filter(gom=gom, participant=p, status__in=Cobranca.OPEN).order_by('-criada_em'))
    pago = sum((c.total_price for c in claims if c.status == Claim.Status.PAID), Decimal('0'))
    pacotes = PacoteNacional.objects.for_gom(gom).filter(participant=p)
    contexto = {
        'p': p,
        'telefone': f'•••• {p.whatsapp[-4:]}' if p.whatsapp else '',
        'devendo': sum((g['total'] for g in grupos), Decimal('0')) + sum((c.valor_total for c in pix_abertos), Decimal('0')),
        'pago': pago,
        'grupos': grupos[:6],
        'mais_grupos': max(0, len(grupos) - 6),
        'pix_abertos': pix_abertos[:3],
        'itens': claims[:LIMITE_ITENS],
        'total_itens': len(claims),
        'pendentes': sum(1 for c in claims if c.status == Claim.Status.PENDING),
        'avulsos': avulsos,
        'pacotes_abertos': pacotes.filter(~Q(status__in=[PacoteNacional.Status.ENVIADO, PacoteNacional.Status.ENTREGUE])).count(),
        'pacotes_total': pacotes.count(),
        'tem_endereco': p.enderecos.exists(),
    }
    return render(request, 'cegs/partials/_joiner_painel_conteudo.html', contexto)
