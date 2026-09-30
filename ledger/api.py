import secrets
from datetime import datetime
from typing import Literal

from django.utils import timezone
from ninja import NinjaAPI, Schema
from ninja.security import APIKeyQuery, HttpBearer

from .ingest import Skipped, ingest
from .models import ApiToken


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


api = NinjaAPI(title="Damdi API", auth=[BearerAuth(), QueryAuth()])


class SmsIn(Schema):
    text: str
    sender: str = ""
    # Unix seconds or milliseconds; forwarders often send it as a string.
    ts: int | str | None = None


class IngestOut(Schema):
    status: Literal["created", "duplicate", "skipped"]
    id: int | None = None


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
    return {"status": "duplicate" if dup else "created", "id": txn.id}
