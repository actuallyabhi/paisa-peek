"""Turn a spoken/typed ramble ("yesterday 450 petrol, 200 chai with Rohan") into draft transactions.

Uses the LLM when configured, else (or on LLM failure) a small heuristic parser. Either way the output is
only a draft: every row goes through the review screen before anything is saved.
"""

import logging
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from pydantic import BaseModel, ValidationError

from . import llm
from .models import Account, Category, Party, Rule, Tag, Transaction

log = logging.getLogger(__name__)

KINDS = [k for k, _ in Transaction.KINDS]


# ---------- shared helpers ----------

def _by_name(objs) -> dict:
    return {o.name.lower(): o for o in objs}


def guess_category(text: str, categories: dict) -> Category | None:
    """Your rule for it, else the category you last used for a similar description, else a keyword hint."""
    if rule := Rule.match(text):
        return rule
    words = [w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in STOPWORDS]
    for w in words:
        t = (Transaction.objects.filter(status="confirmed", category__isnull=False, description__icontains=w)
             .select_related("category").first())
        if t:
            return t.category
    for name, keys in KEYWORDS.items():
        if name.lower() in categories and any(w in keys for w in words):
            return categories[name.lower()]
    return None


def guess_account(text: str, accounts) -> Account | None:
    low = text.lower()
    for a in accounts:
        first = a.name.split()[0].lower()
        if (a.last4 and a.last4 in low) or (len(first) >= 3 and re.search(rf"\b{re.escape(first)}\b", low)):
            return a
    return None


def tags_in(text: str, tags) -> list[str]:
    low = text.lower()
    return [t.name for t in tags if re.search(rf"\b{re.escape(t.name.lower())}\b", low)]


def possible_duplicate(amount, day, party_name="") -> Transaction | None:
    """An existing transaction (incl. SMS-captured or ignored ones) with the same amount within a day.
    With a party, only that party's transactions count (₹3000 lent to two people is not a duplicate)."""
    try:
        amount, day = Decimal(str(amount)), date.fromisoformat(str(day))
    except (InvalidOperation, ValueError):
        return None
    qs = Transaction.objects.filter(amount=amount, date__range=(day - timedelta(days=1), day + timedelta(days=1)))
    if party_name:
        qs = qs.filter(party__name__iexact=party_name)
    return qs.first()


def parties_in(text: str, parties) -> list[str]:
    low = text.lower()
    return [p.name for p in parties if re.search(rf"\b{re.escape(p.name.lower())}\b", low)]


# ---------- LLM path ----------

class _Item(BaseModel):
    date: date
    amount: Decimal
    kind: str
    description: str
    category: str | None
    account: str | None
    tags: list[str]
    party: str | None
    quote: str


class _Result(BaseModel):
    transactions: list[_Item]


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["transactions"],
    "properties": {"transactions": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["date", "amount", "kind", "description", "category", "account", "tags", "party", "quote"],
        "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "amount": {"type": "number"},
            "kind": {"type": "string", "enum": KINDS},
            "description": {"type": "string"},
            "category": {"type": ["string", "null"]},
            "account": {"type": ["string", "null"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "party": {"type": ["string", "null"]},
            "quote": {"type": "string"},
        },
    }}},
}

PROMPT = """You extract personal finance transactions from casual, possibly voice-dictated notes (Indian English, INR).
Today is {today:%A %Y-%m-%d}.
Rules:
- One item per distinct payment or receipt. Amount is a plain number ("1.5k" = 1500, "2 hundred" = 200).
- Resolve relative dates ("yesterday", "last Friday") against today. A date said once applies to following items until another is said. No date = today. Never a future date.
- kind: expense by default; income if money came in; lend = I gave someone a loan; borrow = I took a loan; repay_in = someone paid me back; repay_out = I paid someone back.
- description: short and clean, e.g. "Petrol", "Chai with Rohan", "Swiggy dinner".
- category: exactly one of {categories}, or null if none fits.
- account: exactly one of {accounts}, or null if not mentioned.
- party: the person or company money was lent to, borrowed from, or repaid by/to (and optionally who was paid).
  Prefer existing names {parties}; otherwise the name as said; null if none.
- tags: trip/event/place labels. Prefer existing tags {tags}; add a new one only if the note clearly names it.
- quote: the exact words this item came from."""


def _llm_parse(text: str, today: date) -> list[dict]:
    categories, accounts, tags, parties = Category.objects.all(), Account.objects.all(), Tag.objects.all(), Party.objects.all()
    system = PROMPT.format(
        today=today,
        categories=[c.name for c in categories] or "[]",
        accounts=[a.name for a in accounts] or "[]",
        tags=[t.name for t in tags] or "[]",
        parties=[p.name for p in parties] or "[]",
    )
    try:
        result = _Result.model_validate(llm.chat_json(system, text, SCHEMA))
    except ValidationError as e:
        raise llm.LLMError(f"unexpected shape: {e}") from e
    cats, accts, known_tags, known_parties = _by_name(categories), _by_name(accounts), _by_name(tags), _by_name(parties)
    rows = []
    for it in result.transactions:
        if it.amount <= 0:
            continue
        category = cats.get((it.category or "").lower()) or guess_category(f"{it.description} {it.quote}", cats)
        # Keep a tag only if it already exists or the user literally said it: no invented labels.
        tag_names = [known_tags[t.lower()].name if t.lower() in known_tags else t.strip()
                     for t in it.tags if t.lower() in known_tags or t.lower() in text.lower()]
        # Same guard for people: existing, or actually named in the note.
        p = (it.party or "").strip()
        party = known_parties[p.lower()].name if p.lower() in known_parties else p if p and p.lower() in text.lower() else ""
        rows.append(_row(
            day=min(it.date, today), amount=it.amount, kind=it.kind if it.kind in KINDS else "expense",
            description=it.description, category=category, account=accts.get((it.account or "").lower()),
            tags=tag_names, party=party, quote=it.quote,
        ))
    return rows


# ---------- heuristic path ----------

STOPWORDS = {"the", "and", "for", "with", "paid", "spent", "rupees", "rupee", "bucks", "rs", "inr", "on", "at", "to",
             "today", "yesterday", "ago", "days", "last", "from", "got", "received", "via", "using", "card", "account"}
KEYWORDS = {
    "Fuel & Transport": {"petrol", "fuel", "diesel", "cng", "uber", "ola", "rapido", "cab", "auto", "metro", "bus",
                         "train", "parking", "toll"},
    "Food & Outings": {"chai", "tea", "coffee", "lunch", "dinner", "breakfast", "swiggy", "zomato", "pizza", "movie",
                       "restaurant", "snacks", "samosa", "food", "outing", "party", "treat"},
    "Groceries": {"grocery", "groceries", "vegetables", "sabzi", "milk", "blinkit", "zepto", "bigbasket", "dmart"},
    "Bills & Recharge": {"recharge", "bill", "electricity", "wifi", "broadband", "airtel", "jio", "bsnl"},
    "Health": {"medicine", "medicines", "meds", "doctor", "pharmacy", "hospital", "chemist"},
    "Shopping": {"amazon", "flipkart", "meesho", "myntra", "clothes", "shoes"},
    "Subscriptions": {"netflix", "spotify", "youtube", "prime", "subscription"},
    "Rent": {"rent"},
    "Vehicle": {"repair", "puncture", "servicing"},
    "Gifts & Family": {"gift"},
}
# Filler removed from heuristic descriptions ("paid 450 for petrol on hdfc card" -> "Petrol").
DROP = {"i", "paid", "spent", "spend", "rupees", "rupee", "bucks", "rs", "inr", "via", "using", "card", "account",
        "on", "for", "got", "received"}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
# Sentence ends split too, but not "1.2k" (no space) or "Rs. 450" (digit follows).
SPLIT = re.compile(r"\n|[,;]|\.\s+(?=[^\d\s])|\band then\b|\bthen\b|\band\b|\balso\b", re.I)
NUMBER = re.compile(r"(?P<cur>₹|rs\.?|inr)?\s*(?P<n>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k\b)?", re.I)
INCOME = re.compile(r"\b(received|got|salary|refund|credited)\b", re.I)
REPAY = re.compile(r"\b(returned|paid back|repaid|gave back|got back)\b", re.I)
LEND = re.compile(r"\b(lent|loaned|gave)\b", re.I)
BORROW = re.compile(r"\b(borrowed|took)\b", re.I)
NAME_AFTER = re.compile(r"\b(?:to|from)\s+([A-Za-z][\w.]*)")


def _kind_and_party(chunk: str, parties) -> tuple[str, str]:
    """Loan direction from verbs; party from known names, else the word after to/from on a loan verb."""
    found = parties_in(chunk, parties)
    loan = REPAY.search(chunk) or LEND.search(chunk) or BORROW.search(chunk)
    party = found[0] if found else ""
    if not party and loan and (m := NAME_AFTER.search(chunk)):
        party = m.group(1)[:1].upper() + m.group(1)[1:]
    if m := REPAY.search(chunk):
        # "got back 500 from Priya" / "Priya returned 500" -> repaid to me; "returned 500 to Priya" / "repaid Priya" -> by me.
        named_first = bool(party) and chunk.lower().find(party.lower()) < m.start()
        into_me = m.group(1).lower() == "got back" or re.search(r"\bfrom\b", chunk, re.I) or named_first
        return ("repay_in" if into_me else "repay_out"), party
    if LEND.search(chunk):
        return "lend", party
    if BORROW.search(chunk):
        return "borrow", party
    return ("income" if INCOME.search(chunk) else "expense"), party
DATE_WORDS = re.compile(r"\b(?:day before yesterday|yesterday|today|\d+\s+days?\s+ago|(?:last|on)?\s*(?:%s))\b" % "|".join(WEEKDAYS), re.I)


def _date_in(chunk: str, today: date) -> date | None:
    low = chunk.lower()
    if "day before yesterday" in low:
        return today - timedelta(days=2)
    if "yesterday" in low:
        return today - timedelta(days=1)
    if "today" in low:
        return today
    if m := re.search(r"(\d+)\s+days?\s+ago", low):
        return today - timedelta(days=int(m.group(1)))
    for i, name in enumerate(WEEKDAYS):
        if m := re.search(rf"\b(last\s+)?{name}\b", low):
            back = (today.weekday() - i) % 7 or (7 if m.group(1) else 0)
            return today - timedelta(days=back)
    return None


def _amount_in(chunk: str) -> tuple[Decimal, str] | None:
    """Currency-marked number first, else the largest number ("200 chai for 2 people" -> 200)."""
    found = []
    for m in NUMBER.finditer(chunk):
        try:
            n = Decimal(m.group("n").replace(",", ""))
        except InvalidOperation:
            continue
        if m.group("k"):
            n *= 1000
        found.append((bool(m.group("cur")), n, m.group(0)))
    if not found:
        return None
    _, n, token = max(found, key=lambda f: (f[0], f[1]))
    return (n, token) if n > 0 else None


def _heuristic_parse(text: str, today: date) -> list[dict]:
    chunks = [c.strip() for c in SPLIT.split(text) if c and c.strip()]
    # Glue amount-less fragments ("chai and samosa 50") onto the next chunk that has an amount.
    merged, carry = [], ""
    for c in chunks:
        c = f"{carry} {c}".strip() if carry else c
        if _amount_in(c) or _date_in(c, today) and not DATE_WORDS.sub("", c).strip():
            merged.append(c)
            carry = ""
        else:
            carry = c
    if carry and merged:
        merged[-1] += " " + carry

    cats, accounts, tags = _by_name(Category.objects.all()), list(Account.objects.all()), list(Tag.objects.all())
    parties = list(Party.objects.all())
    rows, current = [], today
    for c in merged:
        current = _date_in(c, today) or current  # a date carries forward to later items
        amt = _amount_in(c)
        if not amt:
            continue
        amount, token = amt
        desc = DATE_WORDS.sub(" ", c.replace(token, " "))
        desc = " ".join(w for w in desc.split() if w.lower().strip(".") not in DROP)
        account = guess_account(c, accounts)
        if account:  # "on hdfc card" is an account, not part of the description
            desc = re.sub(rf"\b{re.escape(account.name.split()[0])}\b", "", desc, flags=re.I).strip()
        desc = desc.strip(" .-") or "Unknown"
        kind, party = _kind_and_party(c, parties)
        rows.append(_row(
            day=min(current, today), amount=amount, kind=kind, description=desc[:1].upper() + desc[1:],
            category=None if kind in Transaction.LOAN_KINDS else guess_category(c, cats), account=account,
            tags=tags_in(c, tags), party=party, quote=c,
        ))
    return rows


# ---------- entry point ----------

def _row(*, day, amount, kind, description, category, account, tags, quote, party="") -> dict:
    """A draft row, shaped as initial data for RambleForm. No account mentioned = the default account."""
    account = account or Account.default()
    return {
        "date": day, "amount": Decimal(amount).quantize(Decimal("0.01")), "kind": kind,
        "description": description[:200], "category": category.pk if category else None,
        "account": account.pk if account else None, "party_name": party, "tag_names": ", ".join(dict.fromkeys(tags)), "quote": quote[:500],
        "include": True,
    }


def parse(text: str, today: date | None = None) -> tuple[list[dict], str]:
    """Returns (draft rows, parser used: 'llm' | 'heuristic' | 'heuristic (LLM failed: …)')."""
    today = today or timezone.localdate()
    if llm.enabled():
        try:
            return _llm_parse(text, today), "llm"
        except llm.LLMError as e:
            log.warning("ramble LLM failed, using heuristic: %s", e)
            return _heuristic_parse(text, today), f"heuristic (LLM failed: {str(e)[:120]})"
    return _heuristic_parse(text, today), "heuristic"
