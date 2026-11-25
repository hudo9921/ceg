"""Regras das conversas: abrir (uma por assunto), enviar, marcar como lida e o JSON para a tela atualizar sozinha."""
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Conversa, Mensagem

MAX_TEXTO = 2000


class ConversaError(ValueError):
    pass


def _assunto(tipo, alvo, gom):
    if tipo == Conversa.Tipo.PACOTE:
        return f'Pacote {alvo.identificador}'
    if tipo == Conversa.Tipo.CEG:
        return alvo.title
    if tipo == Conversa.Tipo.VITRINE:
        return f'Vitrine · {alvo.titulo}'
    return f'Conversa com {gom.name}'


def abrir(participant, gom, tipo=Conversa.Tipo.GERAL, alvo=None):
    """A conversa do assunto (cria se não existir). `alvo` precisa ser do mesmo GOM."""
    if tipo != Conversa.Tipo.GERAL and (alvo is None or alvo.gom_id != gom.id):
        raise ConversaError('Assunto inválido para este GOM.')
    field = {Conversa.Tipo.PACOTE: 'pacote', Conversa.Tipo.CEG: 'ceg', Conversa.Tipo.VITRINE: 'item_vitrine'}.get(tipo)
    lookup = {'gom': gom, 'participant': participant, 'tipo': tipo}
    if field:
        lookup[field] = alvo
    conversa = Conversa.objects.filter(**lookup).first()
    if conversa is None:
        conversa = Conversa.objects.create(assunto=_assunto(tipo, alvo, gom), **lookup)
    return conversa


@transaction.atomic
def enviar(conversa, autor, texto, user=None):
    texto = (texto or '').strip()
    if not texto:
        raise ConversaError('Escreva a mensagem.')
    if len(texto) > MAX_TEXTO:
        raise ConversaError(f'Mensagem longa demais (máx. {MAX_TEXTO} caracteres).')
    msg = Mensagem.objects.create(conversa=conversa, autor=autor, texto=texto, autor_user=user)
    # Aviso do sistema (ex.: reserva na Vitrine) conta como novidade para os dois lados.
    if autor == Mensagem.Autor.SISTEMA:
        Conversa.objects.filter(pk=conversa.pk).update(atualizada_em=timezone.now(), nao_lidas_gom=F('nao_lidas_gom') + 1,
                                                        nao_lidas_joiner=F('nao_lidas_joiner') + 1)
        conversa.refresh_from_db()
        _avisar(conversa, Mensagem.Autor.JOINER, texto)
        return msg
    other = 'nao_lidas_gom' if autor == Mensagem.Autor.JOINER else 'nao_lidas_joiner'
    era_zero = getattr(conversa, other) == 0
    Conversa.objects.filter(pk=conversa.pk).update(atualizada_em=timezone.now(), **{other: F(other) + 1})
    conversa.refresh_from_db()
    if era_zero:  # um aviso por rodada de mensagens, não um por mensagem
        _avisar(conversa, autor, texto)
    return msg


def marcar_lida(conversa, lado):
    field = 'nao_lidas_joiner' if lado == 'joiner' else 'nao_lidas_gom'
    if getattr(conversa, field):
        Conversa.objects.filter(pk=conversa.pk).update(**{field: 0})
        setattr(conversa, field, 0)


def mensagens_json(conversa, depois=0, lado='joiner'):
    """Mensagens novas (id > depois) para a tela de conversa, já com quem é "eu"."""
    eu = Mensagem.Autor.JOINER if lado == 'joiner' else Mensagem.Autor.GOM
    return [{'id': m.id, 'texto': m.texto, 'autor': m.autor, 'meu': m.autor == eu,
             'quando': timezone.localtime(m.criada_em).strftime('%d/%m %H:%M'),
             'quem': (m.autor_user.get_username() if m.autor_user and lado == 'gom' else '')}
            for m in conversa.mensagens.filter(id__gt=depois).select_related('autor_user')]


def _avisar(conversa, autor, texto):
    preview = texto if len(texto) <= 140 else texto[:137] + '…'
    if autor == Mensagem.Autor.JOINER:
        from apps.cegs.models import GOMNotification
        GOMNotification.objects.create(
            gom=conversa.gom, participant=conversa.participant,
            notification_type=GOMNotification.NotificationType.SYSTEM,
            title=f'Mensagem de {conversa.participant.display_name}', message=f'{conversa.assunto}: {preview}')
    elif autor == Mensagem.Autor.GOM:
        from apps.participants.models import ParticipantNotification
        ParticipantNotification.objects.create(
            participant=conversa.participant, notification_type=ParticipantNotification.NotificationType.GENERAL,
            title=f'{conversa.gom.name} respondeu', message=f'{conversa.assunto}: {preview}')
