"""
Juntar eras: um single que é parte de um comeback (ex.: BTS "SWIM" dentro de "ARIRANG") vira apelido da era
principal. Usado pela carga do catálogo (singles sem CEG) e pelo botão "Juntar com outra era" da plataforma.
"""
from django.db import transaction

from .models import Era, normalize_name


def _juntar_nomes(*listas):
    vistos, nomes = set(), []
    for lista in listas:
        for n in (lista or '').split(','):
            n = n.strip()
            if n and normalize_name(n) not in vistos:
                vistos.add(normalize_name(n))
                nomes.append(n)
    return nomes


@transaction.atomic
def juntar_eras(origem, destino):
    """
    Move CEGs e itens da vitrine de `origem` para `destino`, guarda o nome dela como apelido e apaga `origem`.
    As duas precisam ser do mesmo grupo. Devolve quantas CEGs mudaram de era.
    """
    from apps.cegs.models import CEG, ItemVitrine

    if origem.pk == destino.pk or origem.group_id != destino.group_id:
        raise ValueError('As eras precisam ser diferentes e do mesmo grupo.')
    origem = Era.objects.select_for_update().get(pk=origem.pk)
    destino = Era.objects.select_for_update().get(pk=destino.pk)
    n_cegs = CEG.objects.filter(era=origem).update(era=destino)  # antes de apagar: CEG.era é CASCADE
    ItemVitrine.objects.filter(era=origem).update(era=destino)
    nomes = [n for n in _juntar_nomes(destino.aliases, origem.name, origem.aliases)
             if normalize_name(n) != normalize_name(destino.name)]
    destino.aliases = ', '.join(nomes)[:300]
    campos = ['aliases']
    if not destino.banner_url and origem.banner_url:
        destino.banner_url = origem.banner_url
        campos.append('banner_url')
    if destino.parte_de_id == origem.pk:
        destino.parte_de = None
        campos.append('parte_de')
    destino.save(update_fields=campos)
    origem.delete()
    return n_cegs


def era_por_nome(grupo, nome):
    """Era do grupo pelo nome ou por um dos apelidos (ex.: "SWIM" acha "ARIRANG")."""
    alvo = normalize_name(nome)
    if not alvo:
        return None
    eras = list(grupo.eras.all())
    return next((e for e in eras if normalize_name(e.name) == alvo), None) \
        or next((e for e in eras if alvo in {normalize_name(n) for n in (e.aliases or '').split(',')}), None)
