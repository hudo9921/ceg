from .models import Participant


def current_participant(request):
    """
    Context processor para injetar o participante logado via sessão nas páginas de template,
    e a contagem de notificações não lidas da GOM para administradores staff.
    """
    context = {
        'logged_participant': None,
        'gom_unread_notifications_count': 0,
        'gom_unread_mensagens': 0,       # conversas com mensagem nova do joiner (S5)
        'joiner_unread_mensagens': 0,    # conversas com resposta nova do GOM (S5)
    }
    participant_id = request.session.get('participant_id')
    if participant_id:
        try:
            participant = Participant.objects.get(id=participant_id)
            context['logged_participant'] = participant
            from apps.conversas.models import Conversa
            context['joiner_unread_mensagens'] = Conversa.objects.filter(participant=participant, nao_lidas_joiner__gt=0).count()
        except Participant.DoesNotExist:
            request.session.pop('participant_id', None)

    # Contagem de notificações pendentes para a GOM
    if getattr(request, 'is_gom_staff', False):
        try:
            from apps.cegs.models import GOMNotification
            context['gom_unread_notifications_count'] = (
                GOMNotification.objects.for_gom(request.active_gom).filter(is_read=False).count())
        except Exception:
            context['gom_unread_notifications_count'] = 0
        from apps.conversas.models import Conversa
        context['gom_unread_mensagens'] = Conversa.objects.for_gom(request.active_gom).filter(nao_lidas_gom__gt=0).count()

    return context
