import logging
from django.core.exceptions import RequestDataTooBig
from django.contrib import messages
from django.shortcuts import redirect
from django.http import HttpResponseRedirect, JsonResponse
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)


class UploadSizeExceptionMiddleware:
    """
    Middleware para capturar exceções RequestDataTooBig quando um usuário envia
    arquivos ou strings Base64 que excedem o limite de memória do Django.
    Evita erro HTTP 500 feio e apresenta mensagem amigável ou resposta JSON adequada.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        from .image_utils import ImageSizeError
        if isinstance(exception, (RequestDataTooBig, ImageSizeError)):
            logger.warning(f"Upload recusado: {exception} (Path: {request.path})")
            if isinstance(exception, ImageSizeError):
                error_msg = str(exception)
            else:
                error_msg = "O arquivo ou imagem enviada ultrapassa o limite máximo permitido (máximo 5 MB). Por favor, escolha uma imagem menor ou use um compressor de fotos."

            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or (
                request.content_type and 'application/json' in request.content_type
            ):
                return JsonResponse({
                    'success': False,
                    'error': error_msg,
                    'message': error_msg
                }, status=400)

            messages.error(request, f"⚠️ {error_msg}")
            referer = request.META.get('HTTP_REFERER')
            if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
                return HttpResponseRedirect(referer)
            return redirect('home')

        return None
