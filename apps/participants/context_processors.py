from .models import Participant


def current_participant(request):
    """
    Context processor para injetar o participante logado via sessão nas páginas de template,
    e a contagem de notificações não lidas da GOM para administradores staff.
    """
    context = {
        'logged_participant': None,
        'gom_unread_notifications_count': 0,
    }
    participant_id = request.session.get('participant_id')
    if participant_id:
        try:
            participant = Participant.objects.get(id=participant_id)
            context['logged_participant'] = participant
        except Participant.DoesNotExist:
            request.session.pop('participant_id', None)

    # Contagem de notificações pendentes para a GOM
    if hasattr(request, 'user') and request.user.is_authenticated and request.user.is_staff:
        try:
            from apps.cegs.models import GOMNotification
            context['gom_unread_notifications_count'] = GOMNotification.objects.filter(is_read=False).count()
        except Exception:
            context['gom_unread_notifications_count'] = 0

    return context
