"""
Regras de joiner entre GOMs (docs/MULTI_GOM_DESIGN.md §2.4).

O joiner é um só na plataforma (um WhatsApp). Por isso:
- o GOM "conhece" o joiner quando o cadastra ou registra uma compra dele (`remember`);
- nome, @ e usuário são do joiner: depois do primeiro login por WhatsApp, só ele altera
  (`may_update_profile`). Antes disso o cadastro ainda é mantido pelos GOMs.
"""


def may_update_profile(participant) -> bool:
    """Dados cadastrais podem ser alterados pela equipe enquanto o joiner nunca fez login."""
    return participant is not None and participant.last_login_at is None


def remember(participant, gom) -> None:
    """Registra que o GOM conhece este joiner (passa a vê-lo nas buscas e listas do GOM)."""
    if participant is not None and gom is not None:
        participant.known_by_goms.add(gom)


def apply_profile_updates(participant, *, name='', username='', social_handle='') -> list[str]:
    """Preenche/atualiza nome, usuário e @ respeitando `may_update_profile`. Devolve os campos salvos."""
    if not may_update_profile(participant):
        return []
    changed = []
    for field, value in (('name', name), ('username', username), ('social_handle', social_handle)):
        if value and getattr(participant, field) != value:
            setattr(participant, field, value)
            changed.append(field)
    if changed:
        participant.save(update_fields=changed)
    return changed
