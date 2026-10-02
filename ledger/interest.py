"""Savings interest: on each account's credit date, put an estimate in the Inbox to check against the bank's figure."""

from datetime import date, timedelta
from decimal import Decimal

from .models import Account, NotifySettings, Transaction, clamp_day


def add_months(d: date, months: int) -> date:
    """Keeps month-ends at month-ends: 30 Jun + 3 → 30 Sep, 30 Sep + 3 → 31 Dec."""
    y, m = divmod(d.month - 1 + months, 12)
    last = d == clamp_day(d.year, d.month, 31)
    return clamp_day(d.year + y, m + 1, 31 if last else d.day)


def period_end(today: date, every: int) -> date:
    """Default first credit date: the end of the current period (quarterly → 30 Jun / 30 Sep / 31 Dec / 31 Mar)."""
    return clamp_day(today.year, -(-today.month // every) * every, 31)


def estimate(account: Account, start: date, end: date) -> Decimal:
    """Interest for the days start..end-1 on each day's closing balance, the way Indian banks compute it."""
    changes = account.daily_net(before=end)
    bal = account.opening_balance + sum((v for d, v in changes.items() if d < start), Decimal(0))
    total, d = Decimal(0), start
    while d < end:
        bal += changes.get(d, 0)
        total += max(bal, Decimal(0))
        d += timedelta(days=1)
    return (total * account.interest_rate / 100 / 365).quantize(Decimal("0.01"))


def credit_due(today: date) -> list[Transaction]:
    """Adds an interest entry for every credit date up to today (pending, or confirmed if set to auto-confirm).
    Safe to run every minute."""
    made, auto = [], NotifySettings.get().interest_auto_confirm
    for a in Account.objects.filter(interest_rate__gt=0, interest_next__lte=today):
        while a.interest_next <= today:  # several, if the scheduler was down over a credit date
            when, start = a.interest_next, add_months(a.interest_next, -a.interest_every)
            a.interest_next = add_months(when, a.interest_every)
            # Claim this credit date first, so a second scheduler can't add it twice.
            if not Account.objects.filter(pk=a.pk, interest_next=when).update(interest_next=a.interest_next):
                break
            amount = estimate(a, start + timedelta(days=1), when + timedelta(days=1))
            if amount <= 0:
                continue
            made.append(Transaction.objects.create(
                date=when, amount=amount, kind="income", account=a, source="interest",
                status="confirmed" if auto else "pending",
                description="Savings interest (estimated)", merchant="Interest",
                raw_text=f"Estimated at {a.interest_rate}% a year on daily balances, {start + timedelta(days=1):%d %b} – "
                         f"{when:%d %b %Y}. Edit the amount to match your bank's credit, then confirm.",
            ))
    return made
