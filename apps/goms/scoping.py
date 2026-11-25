"""
Escopo dos dados por GOM (docs/MULTI_GOM_DESIGN.md §2.2 e §3).

Toda consulta de backoffice passa por `Modelo.objects.for_gom(gom)`:
- modelos donos (CEG, Caixa, ItemIndividual, ItemVitrine, PacoteNacional, GOMNotification,
  AuditLog, ConfiguracaoEnvio) filtram pelo próprio campo `gom`;
- modelos derivados (sets, itens, slots, claims, votos...) filtram pelo dono via o pai;
- `Participant` é compartilhado: o GOM só enxerga quem tem vínculo com ele.
"""
from django.db import models
from django.db.models import Q

VALCEGS_SLUG = 'valcegs'
_default_gom_id_cache = {}


def default_gom_id():
    """
    GOM de dados legados (ValCegs). Usado como default do campo `gom` para código antigo,
    comandos e testes. Views de backoffice SEMPRE informam o GOM ativo explicitamente.
    """
    if 'id' not in _default_gom_id_cache:
        from .models import Gom
        gom = Gom.objects.filter(slug=VALCEGS_SLUG).only('id').first()
        if gom is None:  # banco novo (ex.: testes) sem a migração de dados aplicada
            gom = Gom.objects.create(slug=VALCEGS_SLUG, name='ValCegs')
        _default_gom_id_cache['id'] = gom.id
    return _default_gom_id_cache['id']


def reset_default_gom_cache(**kwargs):
    _default_gom_id_cache.clear()


class GomScopedQuerySet(models.QuerySet):
    """Queryset com `for_gom`. `gom_lookup` é o caminho até o GOM dono."""
    gom_lookup = 'gom'

    def for_gom(self, gom):
        if gom is None:
            return self.none()
        return self.filter(**{self.gom_lookup: gom})


def scoped_manager(lookup='gom'):
    """Manager com `for_gom` para um caminho específico (ex.: 'set__ceg__gom')."""
    queryset_class = type(f'GomScopedQuerySet_{lookup.replace("__", "_")}',
                          (GomScopedQuerySet,), {'gom_lookup': lookup})
    return queryset_class.as_manager()


def participant_gom_filter(gom):
    """Participantes com vínculo com o GOM: conhecidos por ele ou com claim/item/voto/pacote dele."""
    return (
        Q(known_by_goms=gom)
        | Q(reserved_slots__set__ceg__gom=gom)
        | Q(claims__slot__set__ceg__gom=gom)
        | Q(itens_individuais__gom=gom)
        | Q(pacotes_nacionais__gom=gom)
        | Q(ceg_interest_votes__ceg__gom=gom)
        | Q(waiting_entries__item_definition__ceg__gom=gom)
    )


class ParticipantQuerySet(models.QuerySet):
    def for_gom(self, gom):
        if gom is None:
            return self.none()
        ids = self.model.objects.filter(participant_gom_filter(gom)).values('id')
        return self.filter(id__in=ids)
