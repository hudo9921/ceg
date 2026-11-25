"""
Regras do GOM (C1, docs/GOM_CUSTOMIZATION_PLAN.md).

Só o estreante precisa aceitar: quem nunca teve um claim numa CEG daquele GOM e ainda não aceitou.
Quem já participou (inclusive joiners antigos) nunca é barrado, nem quando as regras mudam.
A checagem roda antes do claim, fora do select_for_update (duas consultas por índice).
"""
import hashlib

from django.http import JsonResponse

from .models import AceiteRegras


def has_rules(gom) -> bool:
    return bool(gom and (gom.regras or '').strip())


def has_participated(participant, gom) -> bool:
    from apps.participants.models import Claim

    return Claim.objects.for_gom(gom).filter(participant=participant).exists()


def needs_rules(participant, gom) -> bool:
    """True se este joiner precisa aceitar as regras do GOM antes de participar."""
    if participant is None or not has_rules(gom):
        return False
    if AceiteRegras.objects.filter(participant=participant, gom=gom).exists():
        return False
    return not has_participated(participant, gom)


def accept_rules(participant, gom, request=None):
    """Registra o aceite (idempotente) com o hash do texto aceito e um registro na auditoria do GOM."""
    from apps.cegs.models import AuditLog

    digest = hashlib.sha256((gom.regras or '').encode('utf-8')).hexdigest()
    aceite, created = AceiteRegras.objects.get_or_create(participant=participant, gom=gom,
                                                         defaults={'texto_hash': digest})
    if created:
        AuditLog.objects.create(
            gom=gom, event_type=AuditLog.EventType.OTHER, participant=participant,
            participant_name=participant.display_name, participant_phone=participant.whatsapp or '',
            action_label=f'Aceitou as regras do {gom.name}',
            metadata={'acao': 'regras_aceitas', 'texto_hash': digest},
        )
    return aceite


def rules_gate(participant, gom, accept=False):
    """
    Barreira do claim. Devolve None (pode seguir) ou a resposta 409 que abre a folha de regras.
    `accept=True` (o joiner marcou "Li e aceito" na folha) registra o aceite e libera.
    """
    if not needs_rules(participant, gom):
        return None
    if accept:
        accept_rules(participant, gom)
        return None
    return JsonResponse({
        'success': False, 'needs_rules': True, 'gom': gom.name,
        'message': f'Primeira vez com o {gom.name}? Leia e aceite as regras para continuar.',
    }, status=409)


def rules_context(request, gom):
    """Contexto do bloco de regras na página da CEG e na página pública."""
    if not has_rules(gom):
        return {'rules': None}
    from apps.participants.models import Participant

    pid = request.session.get('participant_id')
    participant = Participant.objects.filter(pk=pid).first() if pid else None
    must_accept = needs_rules(participant, gom)
    return {'rules': {
        'gom': gom, 'text': gom.regras, 'updated_at': gom.regras_atualizadas_em,
        'logged': participant is not None, 'must_accept': must_accept,
    }}
