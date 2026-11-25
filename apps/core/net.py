"""
Download seguro de URLs informadas por usuários (proteção contra SSRF).

Use `fetch_public_url()` sempre que o servidor precisar baixar uma URL que veio de um
formulário (ex.: imagem externa para recorte ou extração de cor). Ela só aceita
http/https, bloqueia destinos internos (localhost, rede privada, metadados de nuvem,
containers do Docker) inclusive após redirects, e limita o tamanho da resposta.
"""
import ipaddress
import socket
import urllib.request
from urllib.parse import urlsplit

DEFAULT_MAX_BYTES = 15 * 1024 * 1024
USER_AGENT = 'Mozilla/5.0 (compatible; ValCegsImageFetcher/1.0)'


class UnsafeURLError(ValueError):
    """URL recusada: esquema inválido, destino interno ou resposta grande demais."""


def _is_public_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def assert_public_url(url: str) -> None:
    """Lança UnsafeURLError se a URL não for http(s) ou resolver para algum IP não público."""
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise UnsafeURLError("Apenas URLs http(s) são permitidas.")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80))
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Não foi possível resolver o host: {parts.hostname}") from exc
    for info in infos:
        if not _is_public_ip(info[4][0]):
            raise UnsafeURLError(f"Destino interno bloqueado: {parts.hostname}")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirectHandler)


def fetch_public_url(url: str, timeout: float = 10, max_bytes: int = DEFAULT_MAX_BYTES,
                     headers: dict | None = None) -> bytes:
    """Baixa `url` validando o destino (e cada redirect) e o tamanho máximo da resposta."""
    url = (url or '').strip()
    assert_public_url(url)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})
    with _opener.open(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UnsafeURLError("Arquivo remoto maior que o limite permitido.")
    return data
