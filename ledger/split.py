"""Split a bill you paid, Splitwise-style: equally, by percentage, or by exact amounts.

The expense keeps only your share, so spending charts count what was really yours. Everyone else's share
becomes a "lend" to them from the same account: the account still drops by the full bill, and each person's
balance shows what they owe you until they repay (or you settle).
"""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction as db_tx
from django.utils.translation import gettext as _

from .forms import party_named
from .models import Transaction

MODES = ("equal", "percent", "amount")
PAISA = Decimal("0.01")


def can_split(t: Transaction) -> bool:
    return t.kind == "expense" and not t.split_of_id and t.amount > 0


def _num(s) -> Decimal | None:
    try:
        d = Decimal(str(s or "").replace(",", "").strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def compute(total: Decimal, mode: str, mine, others: list[tuple[str, object]]) -> tuple[Decimal, list[tuple[str, Decimal]]]:
    """(your share, [(name, share)]) for a bill of `total`. `mine` and the values are the raw form inputs
    (ignored when splitting equally). Shares add up to the total to the paisa. Raises ValueError with a
    user-facing message."""
    if mode not in MODES:
        raise ValueError(_("Pick how to split it."))
    rows, seen = [], set()
    for name, value in others:
        name = " ".join((name or "").split())[:100]
        if not name:
            if _num(value):
                raise ValueError(_("Every share needs a name."))
            continue  # an empty row the form left over
        if name.casefold() in seen:
            raise ValueError(_("%(name)s is in the list twice.") % {"name": name})
        seen.add(name.casefold())
        rows.append((name, value))
    if not rows:
        raise ValueError(_("Add at least one person to split with."))

    if mode == "equal":
        n = len(rows) + 1
        each = (total / n).quantize(PAISA, rounding=ROUND_DOWN)
        my_share = total - each * len(rows)  # the leftover paisa stay with you
        return my_share, [(name, each) for name, _v in rows]

    values = [_num(v) for _n, v in rows]
    mine = _num(mine) if str(mine or "").strip() else Decimal(0)
    if mine is None or any(v is None or v < 0 for v in values) or mine < 0:
        raise ValueError(_("Use plain numbers, like 250 or 33.5."))
    if mode == "percent":
        if sum(values) + mine != 100:
            raise ValueError(_("The percentages add up to %(pct)s%%, not 100%%.") % {"pct": sum(values) + mine})
        shares = [(total * v / 100).quantize(PAISA, rounding=ROUND_HALF_UP) for v in values]  # as the page's preview rounds
    else:
        shares = [v.quantize(PAISA, rounding=ROUND_HALF_UP) for v in values]
        if sum(shares) + mine.quantize(PAISA, rounding=ROUND_HALF_UP) != total:
            raise ValueError(_("The amounts add up to ₹%(sum)s, not ₹%(total)s.")
                             % {"sum": sum(shares) + mine.quantize(PAISA, rounding=ROUND_HALF_UP), "total": total})
    if any(s <= 0 for s in shares):
        raise ValueError(_("Everyone you split with needs a share above zero."))
    my_share = total - sum(shares)  # absorbs rounding, so the pieces always add back to the bill
    if my_share <= 0:
        raise ValueError(_("Your share comes to nothing. If you paid for them entirely, record it as Lent instead."))
    return my_share, list(zip((n for n, _v in rows), shares))


def apply(t: Transaction, my_share: Decimal, shares: list[tuple[str, Decimal]]) -> list[Transaction]:
    """Turn t into your share plus one lend per person, replacing any earlier split. Splitting confirms it."""
    with db_tx.atomic():
        t.split_shares.all().delete()
        t.amount, t.status = my_share, "confirmed"
        t.save(update_fields=["amount", "status"])
        tags = list(t.tags.all())
        made = []
        for name, amount in shares:
            s = Transaction.objects.create(
                date=t.date, time=t.time, amount=amount, kind="lend", description=t.description or t.merchant,
                account=t.account, party=party_named(name), source="split", status="confirmed", split_of=t)
            s.tags.set(tags)
            made.append(s)
        return made


def undo(t: Transaction) -> None:
    """Back to one expense for the whole bill."""
    with db_tx.atomic():
        t.amount = t.split_total
        t.save(update_fields=["amount"])
        t.split_shares.all().delete()
