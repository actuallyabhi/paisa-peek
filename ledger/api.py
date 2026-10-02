import secrets
from datetime import datetime
from typing import Literal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.formats import date_format, time_format
from django.utils.translation import gettext
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.security import APIKeyQuery, HttpBearer

from .forms import review
from .ingest import Skipped, ingest
from .models import Account, ApiToken, Category, Party, Transaction
from .templatetags.money import inr


def _valid(token: str | None) -> bool:
    return bool(token) and secrets.compare_digest(token, ApiToken.current())


class BearerAuth(HttpBearer):
    def authenticate(self, request, token):
        return _valid(token)


class QueryAuth(APIKeyQuery):
    """?token=… for forwarder apps that can't set headers."""

    param_name = "token"

    def authenticate(self, request, key):
        return _valid(key)


api = NinjaAPI(title="Paisapeek API", auth=[BearerAuth(), QueryAuth()])


class SmsIn(Schema):
    text: str
    sender: str = ""
    # Unix seconds or milliseconds; forwarders often send it as a string.
    ts: int | str | None = None


class TxnOut(Schema):
    """A pending transaction as the Android app shows it; display strings are formatted server-side."""
    id: int
    amount: str  # "−₹450.00" / "+₹500.00", or "" when the SMS had no readable amount
    money_in: bool
    merchant: str
    when: str
    account: str
    source: str
    raw_text: str
    kind: str
    category: int | None
    category_name: str
    party_name: str


def _txn(t: Transaction) -> dict:
    return {
        "id": t.id, "amount": f"{t.sign}{inr(t.amount)}" if t.amount else "",
        "money_in": t.kind in Transaction.MONEY_IN, "merchant": t.merchant,
        "when": date_format(t.date, "j M Y") + (f", {time_format(t.time, 'g:i A')}" if t.time else ""),
        "account": str(t.account or ""), "source": t.source, "raw_text": t.raw_text, "kind": t.kind,
        "category": t.category_id, "category_name": gettext(t.category.name) if t.category else "",
        # Only a real person: prefilling the UPI ID made every confirm create a junk "rohan@oksbi" party.
        "party_name": t.party.name if t.party else "",
    }


class IngestOut(Schema):
    status: Literal["created", "duplicate", "skipped"]
    id: int | None = None
    txn: TxnOut | None = None  # set when created, for the app's notification


def _received(ts) -> datetime:
    try:
        n = int(ts)
    except (TypeError, ValueError):
        return timezone.localtime()
    return timezone.localtime(datetime.fromtimestamp(n / 1000 if n > 1e12 else n, tz=timezone.get_current_timezone()))


@api.post("/ingest/sms", response=IngestOut)
def ingest_sms(request, payload: SmsIn):
    try:
        at = _received(payload.ts)
        txn, dup = ingest(payload.text, sender=payload.sender, source="sms", received=at.date(),
                          received_time=at.time().replace(second=0, microsecond=0))
    except Skipped:
        return {"status": "skipped"}
    return {"status": "duplicate" if dup else "created", "id": txn.id, "txn": None if dup else _txn(txn)}


class Choice(Schema):
    id: int | str
    name: str


class InboxOut(Schema):
    txns: list[TxnOut]
    categories: list[Choice]
    money_in_kinds: list[Choice]
    money_out_kinds: list[Choice]
    accounts: list[Choice]  # transfer targets
    parties: list[str]


@api.get("/inbox", response=InboxOut)
def inbox(request):
    # ponytail: first 200 pending only; the web Inbox paginates if a big backlog ever needs it.
    txns = Transaction.objects.filter(status="pending").select_related("account", "category", "party")[:200]
    return {
        "txns": [_txn(t) for t in txns],
        "categories": [{"id": c.id, "name": gettext(c.name)} for c in Category.objects.all()],
        "money_in_kinds": [{"id": k, "name": str(v)} for k, v in Transaction.KINDS if k in Transaction.MONEY_IN],
        "money_out_kinds": [{"id": k, "name": str(v)} for k, v in Transaction.KINDS if k in Transaction.OUT_KINDS],
        "accounts": [{"id": a.id, "name": a.name} for a in Account.objects.all()],
        "parties": list(Party.objects.values_list("name", flat=True)),
    }


class StatusIn(Schema):
    status: Literal["confirmed", "ignored", "pending"]  # pending = undo
    category: int | None = None
    kind: str | None = None
    party_name: str = ""
    to_account: int | None = None


@api.post("/txns/{pk}/status")
def txn_status(request, pk: int, payload: StatusIn):
    try:
        review(get_object_or_404(Transaction, pk=pk), payload.status, payload.category, payload.kind, payload.party_name, payload.to_account)
    except ValueError as e:
        raise HttpError(400, str(e))
    return {"pending": Transaction.objects.filter(status="pending").count()}
