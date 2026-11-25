"""
Filtro seguro para embutir JSON em templates.

`{{ dados|json_embed }}` aceita um objeto Python ou uma string JSON pronta e escapa
`<`, `>` e `&` como sequências \\u003C / \\u003E / \\u0026 (continua sendo JSON válido),
impedindo que um valor como "</script><script>..." feche a tag. Use dentro de
<script type="application/json"> ou de <script> inline.

`{{ dados|json_attr }}` faz o mesmo e ainda escapa aspas para uso dentro de atributos
HTML (ex.: @click="abrir({{ log.metadata|json_attr }})").

Registrado como builtin em settings.TEMPLATES: não precisa de {% load %}.
"""
import json

from django import template
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_ESCAPES = {
    ord('<'): '\\u003C',
    ord('>'): '\\u003E',
    ord('&'): '\\u0026',
    0x2028: '\\u2028',
    0x2029: '\\u2029',
}


def _to_json_text(value, default):
    if value is None or value == '':
        return default
    if isinstance(value, str):
        return value
    return json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False)


@register.filter
def json_embed(value, default='null'):
    """JSON para blocos <script type="application/json"> e <script> inline."""
    return mark_safe(_to_json_text(value, default).translate(_ESCAPES))


@register.filter
def json_attr(value, default='null'):
    """JSON para dentro de atributos HTML."""
    return mark_safe(escape(_to_json_text(value, default).translate(_ESCAPES)))
