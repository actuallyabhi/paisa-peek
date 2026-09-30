from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def inr(value) -> str:
    """Indian digit grouping: 1234567.8 -> ₹12,34,567.80"""
    d = Decimal(value or 0).quantize(Decimal("0.01"))
    sign, d = ("\u2212\u2060" if d < 0 else ""), abs(d)  # real minus + word joiner: "−₹2,000" never wraps
    whole, frac = f"{d:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return f"{sign}₹{','.join(([head] if head else []) + groups + [tail])}.{frac}"


@register.filter
def neg(value):
    return -(value or 0)


@register.filter
def sub(value, other):
    return (value or 0) - (other or 0)


# A small face for each row: category first, then the kind of money movement.
CATEGORY_EMOJI = {
    "food & outings": "🍜", "fuel & transport": "🛵", "groceries": "🥦", "bills & recharge": "💡", "health": "💊",
    "shopping": "🛍️", "rent": "🏠", "subscriptions": "📺", "gifts & family": "🎁", "vehicle": "🔧", "other": "🪙",
}
KIND_EMOJI = {"income": "💰", "lend": "🤝", "borrow": "🤝", "repay_in": "↩️", "repay_out": "↪️", "transfer": "🔁"}


@register.filter
def emoji(t) -> str:
    if t.kind in KIND_EMOJI:
        return KIND_EMOJI[t.kind]
    return CATEGORY_EMOJI.get(t.category.name.lower(), "🧾") if t.category_id else "🧾"
