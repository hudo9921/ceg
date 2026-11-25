"""
Pix estático (BR Code / "copia e cola") com valor e referência, gerado no servidor, sem serviço externo.

Formato EMV do Banco Central (Manual de Padrões para Iniciação do Pix): campos ID + tamanho (2 dígitos) + valor,
terminando com o CRC16-CCITT (polinômio 0x1021, valor inicial 0xFFFF) calculado sobre o payload inteiro + "6304".
"""
import re
import unicodedata
from decimal import Decimal

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$')
EVP_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


def _digits(value):
    return re.sub(r'\D', '', value or '')


def _cpf_ok(cpf):
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(cpf[i]) * (size + 1 - i) for i in range(size))
        if (total * 10 % 11) % 10 != int(cpf[size]):
            return False
    return True


def _cnpj_ok(cnpj):
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    for size, weights in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]), (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        rest = sum(int(cnpj[i]) * weights[i] for i in range(size)) % 11
        if (0 if rest < 2 else 11 - rest) != int(cnpj[size]):
            return False
    return True


def normalize_key(raw):
    """
    (chave normalizada, tipo) ou (None, None) se não for uma chave Pix.
    Tipos: email, cpf, cnpj, telefone, aleatoria. Telefone sai como +55DDDNUMERO.
    """
    value = (raw or '').strip()
    if not value:
        return None, None
    if EVP_RE.match(value):
        return value.lower(), 'aleatoria'
    if EMAIL_RE.match(value):
        return value.lower(), 'email'
    digits = _digits(value)
    if value.startswith('+') or (len(digits) in (12, 13) and digits.startswith('55')):
        phone = digits[2:] if digits.startswith('55') else digits
        if len(phone) in (10, 11):
            return '+55' + phone, 'telefone'
    if len(digits) == 11 and _cpf_ok(digits):
        return digits, 'cpf'
    if len(digits) == 14 and _cnpj_ok(digits):
        return digits, 'cnpj'
    if len(digits) == 11 and digits[2] == '9':  # celular sem +55 (DDD + 9 dígitos)
        return '+55' + digits, 'telefone'
    return None, None


KEY_LABELS = {'email': 'e-mail', 'cpf': 'CPF', 'cnpj': 'CNPJ', 'telefone': 'celular', 'aleatoria': 'chave aleatória'}


def _ascii(text, size):
    """Nome e cidade do recebedor: sem acento, maiúsculas, no tamanho máximo do campo."""
    plain = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode('ascii')
    plain = re.sub(r'[^A-Za-z0-9 ]', ' ', plain).upper()
    return re.sub(r'\s+', ' ', plain).strip()[:size]


def _field(field_id, value):
    return f'{field_id}{len(value):02d}{value}'


def crc16(payload):
    crc = 0xFFFF
    for byte in payload.encode('utf-8'):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f'{crc:04X}'


def brcode(*, key, name, city, amount, reference):
    """Payload "copia e cola" do Pix estático com valor. `reference`: até 25 letras/números (vai no txid)."""
    key, _kind = normalize_key(key)
    if key is None:
        raise ValueError('Chave Pix inválida.')
    amount = Decimal(amount).quantize(Decimal('0.01'))
    if amount <= 0:
        raise ValueError('Valor do Pix precisa ser maior que zero.')
    txid = re.sub(r'[^A-Za-z0-9]', '', reference or '')[:25] or '***'
    account = _field('00', 'br.gov.bcb.pix') + _field('01', key)
    payload = (
        _field('00', '01')
        + _field('26', account)
        + _field('52', '0000')
        + _field('53', '986')
        + _field('54', f'{amount:.2f}')
        + _field('58', 'BR')
        + _field('59', _ascii(name, 25) or 'RECEBEDOR')
        + _field('60', _ascii(city, 15) or 'BRASIL')
        + _field('62', _field('05', txid))
        + '6304'
    )
    return payload + crc16(payload)


def qr_svg(payload):
    """QR code como data URI (SVG em base64) para usar em <img src>: sem arquivo, sem |safe, sem serviço externo."""
    import base64
    import io

    import qrcode
    import qrcode.image.svg

    img = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return 'data:image/svg+xml;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
