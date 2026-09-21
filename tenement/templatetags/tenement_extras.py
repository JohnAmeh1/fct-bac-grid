from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter(name='money')
def money(value, decimals=2):
    """
    Format a number with thousands-separator commas.

    Usage:
        {{ total_amount_due|money }}      -> 1,234,567.89
        {{ total_amount_due|money:0 }}    -> 1,234,568
        {{ total_records_count|money:0 }} -> 12,345

    Unlike Django's built-in `floatformat`, this adds comma grouping on the
    integer part. Safe against None/blank/non-numeric input (falls back to
    rendering the original value unchanged).
    """
    if value is None or value == '':
        value = 0

    try:
        decimals = int(decimals)
    except (TypeError, ValueError):
        decimals = 2

    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        # Not something we can format as a number — leave it as-is rather
        # than raising or silently hiding data.
        return value

    quantizer = Decimal(1).scaleb(-decimals) if decimals > 0 else Decimal(1)
    try:
        number = number.quantize(quantizer)
    except InvalidOperation:
        # e.g. quantize precision overflow on a huge number — fall back to
        # plain rounding instead of erroring out.
        number = round(number, decimals)

    return f"{number:,.{decimals}f}"