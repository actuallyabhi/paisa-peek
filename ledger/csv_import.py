"""CSV import → the same review cards Ramble uses, so nothing is saved until you tick and add.

Columns (header row required, any order, only `amount` is mandatory):
  date, type, amount, description, party, category, account, tags, notes
- date: YYYY-MM-DD or DD/MM/YYYY; blank = the default date chosen on upload.
- type: expense (default), income, transfer, lent, borrowed, repaid_to_me, repaid_by_me.
- amount: 450 or 1,23,456.50 or an Excel-style breakdown "720 + 775 + 380" (summed, kept in notes).
- party: person or company; created on save if new. Required for lent/borrowed/repaid.
- category / account: must match an existing name (account can also be its last 4 digits).
- tags: separated by ; or |
"""

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .forms import RambleForm
from .models import Account, Category
from .ramble import guess_category, possible_duplicate

MAX_ROWS = 1000
KIND_ALIASES = {
    "": "expense", "expense": "expense", "spent": "expense", "income": "income", "transfer": "transfer",
    "lent": "lend", "lend": "lend", "borrowed": "borrow", "borrow": "borrow",
    "repaid_to_me": "repay_in", "repay_in": "repay_in", "received_back": "repay_in", "got_back": "repay_in",
    "repaid_by_me": "repay_out", "repay_out": "repay_out", "paid_back": "repay_out",
}
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%d-%b-%Y", "%d %b %Y"]


class CSVError(Exception):
    pass


def read_rows(upload) -> list[dict]:
    try:
        text = upload.read().decode("utf-8-sig")  # -sig: Excel's "CSV UTF-8" adds a BOM
    except UnicodeDecodeError:
        raise CSVError("File isn't UTF-8 text. In Excel use Save As → “CSV UTF-8”.")
    reader = csv.DictReader(io.StringIO(text))
    headers = [(h or "").strip().lower() for h in reader.fieldnames or []]
    if "amount" not in headers:
        raise CSVError("Missing header row with an 'amount' column. See the sample CSV.")
    rows = []
    for raw in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        if any(row.values()):
            rows.append(row)
    if len(rows) > MAX_ROWS:
        raise CSVError(f"{len(rows)} rows; import at most {MAX_ROWS} at a time.")
    return rows


def _amount(s: str) -> tuple[str, str]:
    """(amount for the form, breakdown text if it was "a + b + c"). Bad input passes through so the form flags it."""
    parts = s.replace(",", "").split("+")
    try:
        total = sum(Decimal(p.strip()) for p in parts)
    except InvalidOperation:
        return s, ""
    return str(total), (" + ".join(p.strip() for p in parts) if len(parts) > 1 else "")


def _date(s: str, default: date) -> str:
    if not s:
        return default.isoformat()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return s


def _account(name: str, accounts) -> Account | None:
    low = name.lower()
    return next((a for a in accounts if a.name.lower() == low or (a.last4 and a.last4 == name)), None)


def to_forms(rows: list[dict], default_date: date) -> list[RambleForm]:
    """Bound review forms (errors show immediately). Rows that look already-imported start unticked."""
    cats = {c.name.lower(): c for c in Category.objects.all()}
    accounts = list(Account.objects.all())
    out = []
    for i, r in enumerate(rows):
        warnings = []
        amount, breakdown = _amount(r.get("amount", ""))
        day = _date(r.get("date", ""), default_date)
        kind = KIND_ALIASES.get(re.sub(r"[\s-]+", "_", r.get("type", "").lower()), r.get("type", ""))
        category = cats.get(r.get("category", "").lower())
        if r.get("category") and not category:
            warnings.append(f"unknown category “{r['category']}”")
        elif not category and kind in ("expense", "income"):
            category = guess_category(r.get("description", ""), cats)
        account = _account(r.get("account", ""), accounts) if r.get("account") else Account.default()
        if r.get("account") and not account:
            warnings.append(f"unknown account “{r['account']}”")
        dup = possible_duplicate(amount, day, r.get("party", ""))
        p = f"r{i}"
        data = {
            f"{p}-date": day, f"{p}-amount": amount, f"{p}-kind": kind,
            f"{p}-description": r.get("description", ""), f"{p}-party_name": r.get("party", ""),
            f"{p}-category": category.pk if category else "", f"{p}-account": account.pk if account else "",
            f"{p}-tag_names": ", ".join(t.strip() for t in re.split(r"[;|]", r.get("tags", "")) if t.strip()),
            f"{p}-notes": r.get("notes") or (f"Breakdown: {breakdown}" if breakdown else ""),
            f"{p}-quote": f"CSV row {i + 2}: " + " | ".join(v for v in r.values() if v)
                          + (f" ⚠ {'; '.join(warnings)}" if warnings else ""),
        }
        if not dup:
            data[f"{p}-include"] = "on"
        f = RambleForm(data, prefix=p)
        f.source, f.dup = "import", dup
        f.is_valid()  # populate errors so bad rows are highlighted right away
        out.append(f)
    return out
