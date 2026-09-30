"""Chart data: plain dicts with values, percentages and tick marks. Templates draw them as HTML/SVG.

Conventions: heights/widths are percentages of the plot (0-100) so charts stay crisp at any width; money uses
Indian compact units on axes (₹12k, ₹1.2L); every chart also renders a table view from the same dicts.
"""

import math
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from .models import Transaction


def nice_ticks(top_value, count=3) -> tuple[float, list[float]]:
    """(axis max, gridline values) with round steps: 1, 2, 2.5, 5 × 10^k."""
    top_value = float(top_value or 0)
    if top_value <= 0:
        return 1.0, []
    raw = top_value / count
    exp = 10 ** math.floor(math.log10(raw))
    step = next(m * exp for m in (1, 2, 2.5, 5, 10) if raw <= m * exp)
    top = step * math.ceil(top_value / step)
    return top, [step * i for i in range(1, int(round(top / step)) + 1)]


def pct(value, top) -> float:
    return round(float(value) / float(top) * 100, 2) if top else 0.0


def daily_spend(qs, start: date, end: date, today: date, view: str) -> dict:
    """Column per day of the week/month: confirmed spending, with the daily average for days so far."""
    # order_by(): the caller's ordering would otherwise join the GROUP BY and split the per-day sums
    sums = dict(qs.filter(status="confirmed", kind="expense").order_by().values("date").annotate(s=Sum("amount"))
                .values_list("date", "s"))
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    elapsed = [d for d in days if d <= today]
    avg = sum((sums.get(d, 0) for d in elapsed), Decimal(0)) / len(elapsed) if elapsed else Decimal(0)
    top, ticks = nice_ticks(max([sums.get(d, 0) for d in days] + [avg]))
    cols = []
    for d in days:
        v = sums.get(d, Decimal(0))
        label = date_format(d, "D") if view == "week" else (str(d.day) if d.day in (1, 8, 15, 22, 29) or d == today else "")
        cols.append({"date": d, "value": v, "h": pct(v, top), "label": label, "today": d == today, "future": d > today,
                     "tip": date_format(d, "D, j M")})
    return {"cols": cols, "avg": avg, "avg_h": pct(avg, top), "ticks": [{"v": t, "h": pct(t, top)} for t in ticks],
            "has_data": any(sums.values())}


def months_in_out(month_start: date, n=6) -> dict:
    """Spent vs came in for the n months ending at month_start (grouped columns, one ₹ axis)."""
    first = month_start
    for _i in range(n - 1):
        first = (first - timedelta(days=1)).replace(day=1)
    end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    rows = (Transaction.objects.filter(status="confirmed", date__gte=first, date__lt=end, kind__in=("expense", "income"))
            .order_by().annotate(m=TruncMonth("date")).values("m", "kind").annotate(s=Sum("amount")))
    got = {(r["m"], r["kind"]): r["s"] for r in rows}
    months, m = [], first
    while m < end:
        months.append(m)
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    top, ticks = nice_ticks(max([v for v in got.values()] + [0]))
    out = []
    for m in months:
        spent, came = got.get((m, "expense"), Decimal(0)), got.get((m, "income"), Decimal(0))
        out.append({"month": m, "label": date_format(m, "M"), "full": date_format(m, "F Y"), "spent": spent,
                    "income": came, "spent_h": pct(spent, top), "income_h": pct(came, top), "current": m == month_start})
    return {"months": out, "ticks": [{"v": t, "h": pct(t, top)} for t in ticks], "has_data": bool(got)}


def category_shares(by_cat, spent) -> list[dict]:
    """One series (nominal categories) → one colour; bar length = amount, label = share."""
    rows = list(by_cat)
    top = max([r["total"] for r in rows] + [0])
    return [{"name": r["category__name"], "total": r["total"], "w": pct(r["total"], top),
             "share": round(float(r["total"]) / float(spent) * 100) if spent else 0} for r in rows]


def owed_diverging(parties, limit=8) -> dict:
    """People balances around zero: right = they owe me, left = I owe. Tail folds into 'Others'."""
    live = sorted([p for p in parties if p.balance], key=lambda p: -abs(p.balance))
    head, tail = live[:limit], live[limit:]
    rows = [{"name": p.name, "pk": p.pk, "balance": p.balance} for p in head]
    if tail:
        for sign, bucket in ((1, [p for p in tail if p.balance > 0]), (-1, [p for p in tail if p.balance < 0])):
            if bucket:
                rows.append({"name": _("%(n)d others") % {"n": len(bucket)}, "pk": None,
                             "balance": sum(p.balance for p in bucket)})
    top = max([abs(r["balance"]) for r in rows] + [0])
    for r in rows:
        r["w"] = pct(abs(r["balance"]), top)
    return {"rows": rows}


def balance_steps(rows) -> dict | None:
    """Running 'they owe' balance as a step line (SVG coords 0-100). Needs 2+ confirmed changes."""
    pts = [(t.date, float(run)) for t, run in rows if t.status == "confirmed" and t.owed_delta]
    if len(pts) < 2:
        return None
    lo, hi = min(0.0, *(v for _d, v in pts)), max(0.0, *(v for _d, v in pts))
    span = (hi - lo) or 1.0
    y = lambda v: round(100 - (v - lo) / span * 100, 2)
    xs = [round(i / (len(pts) - 1) * 100, 2) for i in range(len(pts))]
    line = f"M0 {y(0)} H{xs[0]} V{y(pts[0][1])}"  # starts from zero, steps with every entry
    for i in range(1, len(pts)):
        line += f" H{xs[i]} V{y(pts[i][1])}"
    area = line + f" H100 V{y(0)} Z"
    line += " H100"
    hits = [{"x": xs[i], "w": (xs[i + 1] - xs[i]) if i + 1 < len(xs) else 100 - xs[i] or 2, "date": d, "value": v}
            for i, (d, v) in enumerate(pts)]
    return {"line": line, "area": area, "zero": y(0), "end": {"x": 100, "y": y(pts[-1][1]), "value": pts[-1][1]},
            "hits": hits, "first": pts[0][0], "last": pts[-1][0]}
