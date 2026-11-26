"""
Seguir grupos e integrantes (model Seguindo): personaliza o que o joiner vê e avisa quando abre CEG.

- Seguir um grupo vale para as subunidades dele (NCT → NCT 127). Seguir um integrante (ex.: Karina) destaca as CEGs
  do grupo que têm item dela.
- Relevância de uma CEG: 2 = tem item de integrante seguido; 1 = é de grupo seguido (ou do grupo de um integrante
  seguido); 0 = nada. O aviso de CEG nova é mais estrito: integrante seguido só avisa se a CEG tem item dele.
- Aviso: quando uma CEG fica visível (agendada, aberta ou em enquete), cada seguidor recebe uma notificação,
  uma vez só por CEG (AvisoSeguidores). Nada é automático além do aviso.
"""
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.groups.models import normalize_name

VISIVEIS = ('SCHEDULED', 'OPEN', 'POLLING')


@dataclass
class Preferencias:
    grupos: set = field(default_factory=set)       # ids de grupos seguidos (inteiros)
    membros: dict = field(default_factory=dict)    # group_id → {nome normalizado: nome}

    def __bool__(self):
        return bool(self.grupos or self.membros)

    @property
    def todos_grupos(self):
        return self.grupos | set(self.membros)


def preferencias(participant):
    """O que o joiner segue (vazio para visitante)."""
    from apps.groups.models import KpopGroup

    from .models import Seguindo

    prefs = Preferencias()
    if participant is None:
        return prefs
    for s in Seguindo.objects.filter(participant=participant).select_related('member'):
        if s.member_id:
            for nome in (s.member.name, s.member.name_native):
                if nome:
                    prefs.membros.setdefault(s.group_id, {})[normalize_name(nome)] = s.member.name
        else:
            prefs.grupos.add(s.group_id)
    if prefs.grupos:  # subunidades dos grupos seguidos
        prefs.grupos |= set(KpopGroup.objects.filter(parent_id__in=prefs.grupos).values_list('id', flat=True))
    return prefs


def membros_da_ceg(ceg):
    """Nomes dos integrantes dos itens da CEG (usa o que já veio de enrich_cegs_with_availability, se tiver)."""
    itens = getattr(ceg, 'grouped_available_items', None)
    if itens is not None:
        nomes = [i.get('member_name') or '' for i in itens]
    else:
        nomes = list(ceg.item_definitions.values_list('member_name', flat=True))
    return {normalize_name(n) for n in nomes if n}


def relevancia(ceg, prefs):
    """(nota, integrantes seguidos que têm item nesta CEG)."""
    if not prefs:
        return 0, []
    gid = ceg.era.group_id
    seguidos = prefs.membros.get(gid) or {}
    achados = [seguidos[n] for n in membros_da_ceg(ceg) if n in seguidos] if seguidos else []
    if achados:
        return 2, sorted(set(achados))
    parent = getattr(ceg.era.group, 'parent_id', None)
    return (1 if gid in prefs.todos_grupos or parent in prefs.grupos else 0), []


def marcar(cegs, prefs):
    """Põe .para_voce (nota) e .seguidos_nomes em cada CEG; devolve as relevantes, mais relevantes primeiro."""
    relevantes = []
    for c in cegs:
        c.para_voce, c.seguidos_nomes = relevancia(c, prefs)
        if c.para_voce:
            relevantes.append(c)
    return sorted(relevantes, key=lambda c: -c.para_voce)


def alternar(participant, group, member=None):
    """Segue ou deixa de seguir. Devolve True se passou a seguir."""
    from .models import Seguindo

    filtro = {'participant': participant, 'group': group, 'member': member}
    existente = Seguindo.objects.filter(**filtro)
    if existente.exists():
        existente.delete()
        return False
    try:
        with transaction.atomic():
            Seguindo.objects.create(**filtro)
    except IntegrityError:
        pass  # dois cliques ao mesmo tempo
    return True


def seguidores_da_ceg(ceg):
    """Joiners que seguem o grupo (ou o grupo principal) ou um integrante com item nesta CEG."""
    from .models import Participant, Seguindo

    group = ceg.era.group
    grupos = [group.id] + ([group.parent_id] if group.parent_id else [])
    nomes = membros_da_ceg(ceg)
    ids_membros = [m.id for m in group.members.all()
                   if normalize_name(m.name) in nomes or (m.name_native and normalize_name(m.name_native) in nomes)]
    filtro = Q(group_id__in=grupos, member__isnull=True) | Q(member_id__in=ids_membros)
    ids = Seguindo.objects.filter(filtro).values_list('participant_id', flat=True).distinct()
    return Participant.objects.filter(id__in=ids)


def avisar_seguidores(ceg):
    """Avisa quem segue, uma vez por CEG, quando ela está visível. Devolve quantos foram avisados."""
    from .models import AvisoSeguidores, ParticipantNotification

    if ceg.status not in VISIVEIS or AvisoSeguidores.objects.filter(ceg=ceg).exists():
        return 0
    try:
        with transaction.atomic():
            aviso = AvisoSeguidores.objects.create(ceg=ceg)
    except IntegrityError:
        return 0  # já avisados
    quando = {'SCHEDULED': f'abre {ceg.opens_at:%d/%m às %H:%M}' if ceg.opens_at else 'abre em breve',
              'OPEN': 'já está aberta', 'POLLING': 'está em enquete'}[ceg.status]
    from .models import Seguindo

    group = ceg.era.group
    nomes_ceg = membros_da_ceg(ceg)
    seguidores = list(seguidores_da_ceg(ceg))
    quem_segue = {}  # participant_id → integrantes seguidos que têm item nesta CEG
    for s in Seguindo.objects.filter(participant__in=seguidores, group=group, member__isnull=False).select_related('member'):
        if normalize_name(s.member.name) in nomes_ceg:
            quem_segue.setdefault(s.participant_id, []).append(s.member.name)
    avisos = []
    for p in seguidores:
        quem = sorted(quem_segue.get(p.id, []))
        com = f' com {", ".join(quem)}' if quem else ''
        avisos.append(ParticipantNotification(
            participant=p, notification_type=ParticipantNotification.NotificationType.NOVA_CEG,
            title=f'Nova CEG de {group.name}{com}',
            message=f'{ceg.title} ({ceg.gom.name}) {quando}. /ceg/{ceg.slug}/'))
    ParticipantNotification.objects.bulk_create(avisos)
    aviso.avisados = len(avisos)
    aviso.save(update_fields=['avisados'])
    return len(avisos)


def anotar_seguindo(qs, prefs, campo_grupo, campo_membro=None):
    """
    Anota `_seg` num queryset (2 = item de integrante seguido, 1 = grupo seguido, 0 = nada) para ordenar
    "quem eu sigo primeiro". `campo_grupo`/`campo_membro`: caminhos até o id do grupo e o nome do integrante.
    """
    from django.db.models import Case, IntegerField, Value, When

    if not prefs:
        return qs.annotate(_seg=Value(0, output_field=IntegerField()))
    casos = []
    if campo_membro and prefs.membros:
        q = Q()
        for gid, nomes in prefs.membros.items():
            for nome in set(nomes.values()):
                q |= Q(**{campo_grupo: gid, f'{campo_membro}__iexact': nome})
        casos.append(When(q, then=Value(2)))
    casos.append(When(Q(**{f'{campo_grupo}__in': prefs.todos_grupos}), then=Value(1)))
    return qs.annotate(_seg=Case(*casos, default=Value(0), output_field=IntegerField()))
