from decimal import Decimal, InvalidOperation

import json

from django import template
from django.core.serializers.json import DjangoJSONEncoder

register = template.Library()


@register.filter(name="intcomma")
def intcomma(value):
    if value is None or value == "" or isinstance(value, bool):
        return value
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    if not number.is_finite():
        return value
    if number == number.to_integral_value():
        return f"{int(number):,}"
    return f"{number:,.2f}"


@register.filter(name="json_value")
def json_value(value, indent=2):
    if value is None or value == "":
        return "{}"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "{}"
        try:
            value = json.loads(text)
        except (TypeError, ValueError):
            value = text
    try:
        return json.dumps(value, indent=int(indent), cls=DjangoJSONEncoder, sort_keys=True)
    except (TypeError, ValueError):
        return json.dumps(str(value), cls=DjangoJSONEncoder)
