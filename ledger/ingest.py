"""Turn raw SMS / OCR text into pending transactions: parse → match account → dedupe → save."""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction as db_tx
from django.db.models import Q
from django.utils import timezone

from .models import Account, SmsTemplate, Transaction

log = logging.getLogger(__name__)

DENY = re.compile(
    r"\botp\b|one[- ]time password|verification code|\boffer\b|cashback on|pre-?approved"
    r"|has requested money|\bis due\b|\bdue (?:on|by)\b",
    re.I,
)
AMOUNT = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d{1,2})?)", re.I)
DIRECTION = re.compile(r"\b(debited|sent|spent|paid|withdrawn|purchase|credited|received|deposited|refund(?:ed)?)\b", re.I)
DEBIT_WORDS = {"debited", "sent", "spent", "paid", "withdrawn", "purchase"}
LAST4 = re.compile(r"\b(?:a/?c|acct|account|card)(?:\s*no\.?)?(?:\s*ending(?:\s*with)?)?\s*[xX*]*\s*(\d{3,4})\b", re.I)
REF = re.compile(r"\b(?:ref(?:\s*no)?|utr|upi(?:\s*ref)?)[\s:.#-]*(\d{9,})", re.I)
_END = r"(?:\.\s|\.$|[;,(]|\s+on\b|\s+ref\b|\s+avl|\s*$)"
TO = re.compile(r"\b(?:towards|trf to|to|at)\s+([A-Za-z0-9@&' _.-]+?)" + _END, re.I)
FROM = re.compile(r"\bfrom\s+([A-Za-z0-9@&' _.-]+?)" + _END, re.I)
DATE_FORMATS = ["%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%d-%m-%Y", "%d-%b-%y", "%d-%b-%Y", "%d%b%y"]


class Skipped(Exception):
    """Text is not a transaction (OTP, promo, no amount)."""


@dataclass
class Parsed:
    amount: Decimal
    kind: str
    date: date
    merchant: str = ""
    last4: str = ""
    ref: str = ""
    bank: str = ""


def parse_amount(s: str) -> Decimal | None:
    try:
        d = Decimal(s.replace(",", "").strip())
    except InvalidOperation:
        return None
    return d.quantize(Decimal("0.01")) if d > 0 else None


def parse_date(s: str, fallback: date) -> date:
    """SMS date if readable and not in the future, else the receive date."""
    for fmt in DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        if d <= fallback + timedelta(days=1):
            return d
    return fallback


def clean_merchant(s: str) -> str:
    s = " ".join(s.split())
    if s[:4].lower() == "vpa ":
        s = s[4:]
    return s.rstrip(".")


def kind_of(text: str) -> str:
    m = DIRECTION.search(text)
    return "income" if m and m.group(1).lower() not in DEBIT_WORDS else "expense"


def compile_templates(rows) -> list[tuple]:
    out = []
    for t in rows:
        try:
            out.append((t, re.compile(t.sender_regex) if t.sender_regex else None, re.compile(t.body_regex)))
        except re.error as e:
            log.warning("SMS template %s has a bad regex: %s", t, e)
    return out


def parse(templates, sender: str, text: str, received: date) -> Parsed | None:
    for t, sender_re, body_re in templates:
        if sender and sender_re and not sender_re.search(sender):
            continue
        m = body_re.search(text)
        if not m:
            continue
        g = {k: (v or "").strip() for k, v in m.groupdict().items()}
        amount = parse_amount(g.get("amount", ""))
        if not amount:
            continue
        return Parsed(
            amount=amount,
            kind=t.kind or kind_of(text),
            date=parse_date(g.get("date", ""), received),
            merchant=clean_merchant(g.get("merchant", "")),
            last4=g.get("last4", ""),
            ref=g.get("ref", ""),
            bank=t.bank,
        )
    return generic_parse(text, received)


def generic_parse(text: str, received: date) -> Parsed | None:
    """Fallback for banks without a template: needs an amount and a debit/credit word."""
    am = AMOUNT.search(text)
    if not am or not DIRECTION.search(text) or not (amount := parse_amount(am.group(1))):
        return None
    p = Parsed(amount=amount, kind=kind_of(text), date=received)
    if m := LAST4.search(text):
        p.last4 = m.group(1)
    if m := REF.search(text):
        p.ref = m.group(1)
    if m := (FROM if p.kind == "income" else TO).search(text):
        p.merchant = clean_merchant(m.group(1))
    return p


def account_for(p: Parsed, text: str) -> Account | None:
    """Find by last 4 digits; first sighting creates a placeholder account."""
    if not p.last4:
        return None
    acct = Account.objects.filter(last4=p.last4).first()
    if not acct:
        kind = "credit_card" if re.search(r"\bcard\b", text, re.I) else "savings"
        acct = Account.objects.create(name=f"{p.bank} xx{p.last4}".strip(), kind=kind, last4=p.last4)
    return acct


def ingest(text: str, sender: str = "", source: str = "sms", received: date | None = None,
           received_time: time | None = None) -> tuple[Transaction, bool]:
    """Store text as a pending transaction. Returns (txn, was_duplicate). Raises Skipped."""
    text = text.strip()
    if received is None:
        now = timezone.localtime()
        received, received_time = now.date(), received_time or now.time().replace(second=0, microsecond=0)
    if not text or DENY.search(text):
        raise Skipped
    templates = compile_templates(SmsTemplate.objects.filter(enabled=True).order_by("id"))
    p = parse(templates, sender, text, received)

    with db_tx.atomic():  # IMMEDIATE mode: check+insert can't race another worker
        if not p:
            if not AMOUNT.search(text):
                raise Skipped
            # Has an amount but no known shape: keep it for manual review rather than lose it.
            if dup := Transaction.objects.filter(raw_text__contains=text).first():
                return dup, True
            return Transaction.objects.create(
                date=received, time=received_time, amount=0, source=source, raw_text=text, status="pending",
                description=sender
            ), False

        account = account_for(p, text)
        dup = Transaction.objects.filter(ref=p.ref).first() if p.ref else None
        if not dup:
            # No ref match: same amount+account within a day is a duplicate only if it is the identical
            # message or arrived via another channel (SMS vs screenshot). Two real ₹20 teas both stay.
            near = Transaction.objects.filter(
                amount=p.amount, account=account, date__range=(p.date - timedelta(days=1), p.date + timedelta(days=1))
            )
            if p.ref:
                near = near.filter(ref="")
            dup = near.filter(Q(raw_text__contains=text) | ~Q(source=source)).first()
        if dup:
            if text not in dup.raw_text:
                dup.raw_text += "\n---\n" + text
                dup.ref = dup.ref or p.ref
                dup.save(update_fields=["raw_text", "ref"])
            return dup, True

        return Transaction.objects.create(
            date=p.date, time=received_time if p.date == received else None,
            amount=p.amount, kind=p.kind, merchant=p.merchant, description=p.merchant,
            account=account, source=source, raw_text=text, ref=p.ref, status="pending",
        ), False
