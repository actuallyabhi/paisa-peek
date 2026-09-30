"""Full backup / restore, plus a spreadsheet-friendly CSV of transactions.

Backup file = {"format": "budget-backup", "version": 1, "exported_at": …, "schema": …, "counts": {…}, "data": [...]}
where "data" is Django's standard serialization ({"model", "pk", "fields"}), so it is also accepted by
`manage.py loaddata`, and a bare `manage.py dumpdata ledger` list can be restored here.
Device-specific rows (push subscriptions, sent-reminder log) and login users are not included.
"""

import csv
import io
import json
from collections import Counter
from datetime import datetime

from django.conf import settings
from django.core import serializers
from django.core.serializers.base import DeserializationError
from django.db import DatabaseError, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from .models import Account, ApiToken, Category, NotifySettings, Party, Recurring, SmsTemplate, Tag, Transaction

FORMAT, VERSION = "damdi-backup", 1
LEGACY_FORMATS = {"budget-backup"}  # files exported before the rename
# Dependency order: everything a row points to comes before it.
MODELS = [Category, Tag, Party, Account, SmsTemplate, Transaction, Recurring, NotifySettings, ApiToken]
LABELS = {m._meta.label_lower: i for i, m in enumerate(MODELS)}  # "ledger.transaction" -> 5
MAX_BYTES = 50 * 1024 * 1024


class RestoreError(Exception):
    pass


def export() -> dict:
    rows = json.loads(serializers.serialize("json", [o for m in MODELS for o in m.objects.order_by("pk")]))
    schema = MigrationRecorder.Migration.objects.filter(app="ledger").order_by("-id").values_list("name", flat=True).first()
    return {
        "format": FORMAT, "version": VERSION, "exported_at": timezone.localtime().isoformat(timespec="seconds"),
        "schema": schema, "counts": dict(Counter(r["model"] for r in rows)), "data": rows,
    }


def restore(raw: bytes) -> dict:
    """Replace all ledger data with the backup's, atomically. Returns counts per model."""
    if len(raw) > MAX_BYTES:
        raise RestoreError("Backup is over 50 MB.")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise RestoreError("That isn't a Damdi backup (not valid JSON).")
    if isinstance(doc, dict) and (doc.get("format") == FORMAT or doc.get("format") in LEGACY_FORMATS):
        if doc.get("version", 1) > VERSION:
            raise RestoreError("This backup is from a newer version of Damdi; update the app first.")
        rows = doc.get("data")
    else:
        rows = doc  # plain `manage.py dumpdata ledger` output
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise RestoreError("That isn't a Damdi backup.")
    unexpected = sorted({str(r.get("model")) for r in rows} - LABELS.keys())
    if unexpected:  # never load users, sessions or anything outside the ledger from an uploaded file
        raise RestoreError(f"Backup contains records this app doesn't restore: {', '.join(unexpected)}")
    rows.sort(key=lambda r: LABELS[r["model"]])

    save_safety_copy()
    try:
        with transaction.atomic():
            for m in reversed(MODELS):  # transactions before the people/accounts they PROTECT
                m.objects.all().delete()
            for obj in serializers.deserialize("json", json.dumps(rows), ignorenonexistent=True):
                obj.save()  # raw save: bypasses model save() hooks, restores rows exactly as exported
    except (DeserializationError, DatabaseError, ValueError, KeyError) as e:
        raise RestoreError(f"Backup couldn't be restored, nothing was changed: {e}")
    return dict(Counter(r["model"].split(".")[1] for r in rows))


def save_safety_copy():
    """Current data → DATA_DIR/backups/ before a restore overwrites it."""
    folder = settings.DATA_DIR / "backups"
    folder.mkdir(exist_ok=True)
    path = folder / f"before-restore-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(export(), ensure_ascii=False))
    return path


# ---------- CSV (same columns the CSV importer reads) ----------

CSV_TYPES = {"lend": "lent", "borrow": "borrowed", "repay_in": "repaid_to_me", "repay_out": "repaid_by_me"}
CSV_COLUMNS = ["date", "time", "type", "amount", "description", "party", "category", "account", "to_account",
               "tags", "notes", "status"]


def export_csv() -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CSV_COLUMNS)
    for t in (Transaction.objects.order_by("date", "time", "id")
              .select_related("party", "category", "account", "to_account").prefetch_related("tags")):
        w.writerow([
            t.date.isoformat(), t.time.strftime("%H:%M") if t.time else "", CSV_TYPES.get(t.kind, t.kind), t.amount,
            t.description or t.merchant, t.party or "", t.category or "", t.account or "", t.to_account or "",
            "; ".join(tag.name for tag in t.tags.all()), t.notes, t.status,
        ])
    return out.getvalue()
