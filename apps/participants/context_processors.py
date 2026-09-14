from .models import Participant


def current_participant(request):
    """
    Context processor para injetar o participante logado via sessão nas páginas de template.
    """
    participant_id = request.session.get('participant_id')
    if participant_id:
        try:
            participant = Participant.objects.get(id=participant_id)
            return {'logged_participant': participant}
        except Participant.DoesNotExist:
            request.session.pop('participant_id', None)
    return {'logged_participant': None}
