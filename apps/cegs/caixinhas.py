"""
Caixinhas abertas: caixas (remessas internacionais) que ainda aceitam pedidos de joiners.

Uma caixa aparece em /caixinhas/ e na página do GOM enquanto:
- está em consolidação (ainda não foi embalada);
- a GOM deixa "Aberta para pedidos" marcado (Caixa.aceita_pedidos);
- o prazo de pedidos (Caixa.pedidos_ate), se houver, não passou;
- o GOM está ativo.
Nada aqui muda a caixa: o prazo só tira a caixa da lista (a GOM decide o resto).
"""
from django.db.models import Count, F, Q
from django.utils import timezone

from .models import Caixa

# Rótulo curto da origem para os cards (sem bandeiras em emoji).
ORIGEM_CURTA = {
    Caixa.Origem.KR: ('KR', 'Coreia'),
    Caixa.Origem.JP: ('JP', 'Japão · Mercari'),
    Caixa.Origem.CN: ('CN', 'China'),
    Caixa.Origem.US: ('US', 'Estados Unidos'),
    Caixa.Origem.OTHER: ('+', 'Outra origem'),
}


def abertas(gom=None, now=None):
    """Caixas abertas para pedidos, com contagem de CEGs e itens avulsos, prazo mais próximo primeiro."""
    now = now or timezone.now()
    qs = Caixa.objects.for_gom(gom) if gom is not None else Caixa.objects.all()
    return (qs.filter(status=Caixa.Status.EM_CONSOLIDACAO, aceita_pedidos=True, gom__is_active=True)
            .filter(Q(pedidos_ate__isnull=True) | Q(pedidos_ate__gt=now))
            .select_related('gom')
            .annotate(n_cegs=Count('cegs', distinct=True), n_itens=Count('itens_individuais', distinct=True))
            .order_by(F('pedidos_ate').asc(nulls_last=True), '-created_at'))


def esta_aberta(caixa, now=None):
    now = now or timezone.now()
    return (caixa.status == Caixa.Status.EM_CONSOLIDACAO and caixa.aceita_pedidos
            and (caixa.pedidos_ate is None or caixa.pedidos_ate > now))


def com_rotulos(caixas):
    """Põe origem_sigla/origem_nome em cada caixa (usado pelos cards)."""
    caixas = list(caixas)
    for c in caixas:
        c.origem_sigla, c.origem_nome = ORIGEM_CURTA.get(c.origem, ('+', c.get_origem_display()))
    return caixas
