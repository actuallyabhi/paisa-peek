"""What to remind about right now. Pure function of the clock + data; run_once() sends and records each key once."""

from datetime import datetime, timedelta

from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from .models import Account, NotifySettings, Recurring, SentReminder, clamp_day
from .templatetags.money import inr


def due(now: datetime) -> list[tuple[str, str, str, str]]:
    """(key, title, body, url) for everything due at `now` (local time). Keys make repeats harmless."""
    cfg, today, out = NotifySettings.get(), now.date(), []
    if cfg.daily_enabled and now.time() >= cfg.daily_time:
        out.append((f"daily:{today}", "Log today's spending", "Say what you spent today — takes 10 seconds.", "/?log=1"))
    if not cfg.reminders_enabled or now.time() < cfg.reminder_time:
        return out

    for a in Account.objects.filter(kind__in=Account.CREDIT_KINDS):
        if a.statement_day and today == clamp_day(today.year, today.month, a.statement_day):
            out.append((f"statement:{a.pk}:{today}", f"{a.name}: statement today",
                        f"Your statement generates today. Outstanding so far {inr(-a.balance)} — plan the payment.",
                        reverse("account_edit", args=[a.pk])))
        if a.due_day and today == clamp_day(today.year, today.month, a.due_day):
            out.append((f"due:{a.pk}:{today}", f"{a.name}: payment due today",
                        f"Pay your {a.get_kind_display().lower()} bill today to avoid interest. Outstanding {inr(-a.balance)}.",
                        reverse("account_edit", args=[a.pk])))

    for r in Recurring.objects.filter(active=True, next_due__lte=today + timedelta(days=30)):
        if r.next_due - timedelta(days=r.remind_days_before) <= today <= r.next_due:
            when = "today" if r.next_due == today else f"on {r.next_due:%d %b}"
            title, done = (f"{r.name} expected {when}", "received") if r.is_income else (f"{r.name} due {when}", "paid")
            out.append((f"recurring:{r.pk}:{r.next_due}", title, f"{inr(r.amount)} · tap to mark it {done}.",
                        reverse("recurring")))
    return out


def run_once(now: datetime | None = None, send=None) -> list[str]:
    """Send every due reminder not sent before. Returns the keys sent."""
    from . import push

    send = send or push.send
    sent = []
    for key, title, body, url in due(now or timezone.localtime()):
        try:
            SentReminder.objects.create(key=key)  # claim first: a second scheduler can't double-send
        except IntegrityError:
            continue
        send(title, body, url)
        sent.append(key)
    return sent
