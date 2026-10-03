# Adding SMS templates

Bank SMS become transactions by matching a **template**: a regex for the SMS body, plus a few fields. The defaults ship in [`ledger/sms_templates.json`](../ledger/sms_templates.json). If no template matches, a generic fallback still grabs the amount, direction, last 4 digits and ref, but it misses the date and often the merchant. A template gets all of them.

Just need your own bank working? Add the template in **Admin → SMS templates**; no code needed. To ship it as a default for everyone, follow the steps below.

## 1. Write the template

Add an entry to the end of `ledger/sms_templates.json`:

```json
{"bank": "slice", "sender": "(?i)SLICE|SLCE", "kind": "expense",
 "body": "(?is)Rs\\.?\\s*(?P<amount>[\\d,]+(?:\\.\\d+)?)\\s+spent\\s+on\\s+your\\s+credit\\s+card\\s+[xX*]*(?P<last4>\\d{4})\\s+at\\s+(?P<merchant>.+?)\\s+on\\s+(?P<date>\\d{2}-\\w{3}-\\d{2,4})(?:\\s*\\(UPI\\s+Ref:?\\s*(?P<ref>\\d+))?"}
```

| Field | What it is |
|---|---|
| `bank` | Shown on the transaction, and used to name the account the first time a new last-4 shows up (`slice xx8928`). |
| `sender` | Regex for the SMS sender ID (`JM-SLCEIT-S`). Keep it loose: match the bank's part and ignore the `XX-` prefix and `-S` suffix, which vary by operator. Only checked when the sender is known. |
| `kind` | `expense` or `income`. Leave it `""` to guess from words like *debited* / *credited*. |
| `body` | Python regex for the message, with the named groups below. |

**Named groups** (only `amount` is required):

| Group | Example | Notes |
|---|---|---|
| `amount` | `14,700` / `150.00` | Commas are fine. Use `[\d,]+(?:\.\d+)?`. |
| `merchant` | `Mohdnaseemsohameed` | Who you paid, or who paid you. A leading `VPA ` and a trailing `.` are stripped. |
| `last4` | `8928` | Links the SMS to an account. Use `[xX*]*(?P<last4>\d{3,4})` to skip the `xx` mask. |
| `date` | `01-Oct-26` | Must be one of the formats below. Unreadable or future dates fall back to the day the SMS arrived. |
| `ref` | `627438040171` | UPI/bank reference, used to merge duplicates (e.g. SMS + screenshot of the same payment). |

**Date formats** understood (`DATE_FORMATS` in [`ledger/ingest.py`](../ledger/ingest.py)): `29/09/26`, `29/09/2026`, `2026-09-29`, `29-09-26`, `29-09-2026`, `29-Sep-26`, `29-Sep-2026`, `29Sep26`, and `03-10` with no year (taken as the latest such day that isn't in the future). A bank using something else needs a new entry there.

**Regex tips:**
- Start with `(?is)`: case-insensitive, and `.` also matches newlines (some banks split the SMS over lines).
- Use `\s+` between words, never a literal space; banks are inconsistent about spaces and line breaks.
- Make the merchant lazy (`.+?`) and end it at the next fixed word (`\s+on\s+`), or it will swallow the rest of the SMS.
- Wrap bits that some messages leave out in `(?:...)?`, e.g. the UPI ref.
- Escape `.`, `(`, `[` and `/` where you mean the literal character: `Rs\.?`, `\(Ref`, `\[CODE:\w+\]`.
- In JSON every backslash is doubled: `\s` is written `\\s`, `\.` is `\\.`.

Templates are tried **in order** and the first match wins, so put a specific template before a broader one for the same bank.

## 2. Add the sample SMS to the tests

Add a row to `SMS_CASES` in [`ledger/tests.py`](../ledger/tests.py) with the real message (change the account digits and refs if you like) and what it should parse to:

```python
# (sender, text, amount, kind, merchant, last4, ref, bank, date)
("JM-SLCEIT-S", "Rs. 70 spent on your credit card xx8928 at Mohdnaseemsohameed on 01-Oct-26 (UPI Ref: 627438040171). Not you? Call 080-4832-9999 - slice",
 "70.00", "expense", "Mohdnaseemsohameed", "8928", "627438040171", "slice", "2026-10-01"),
```

Add one row per SMS shape the template should handle (e.g. with and without the ref).

## 3. Ship it to existing installs

The JSON is loaded when a database is created. Installs that already exist only pick up new templates through a migration. Copy the latest one that adds templates (`ledger/migrations/0008_more_sms_templates.py`) to the next number, e.g. `0009_sms_templates_axis_cc.py`, and point its `dependencies` at the migration before it:

```python
dependencies = [("ledger", "0008_more_sms_templates")]
```

It inserts every template in the JSON whose `body` isn't in the database yet. That means new installs don't get duplicates, and templates people edited in Admin are left alone. (An edited template counts as "missing", so the shipped version is added after it; the user's edit still runs first.)

Changing an existing template's `body` in the JSON works the same way: the new version gets added and the old one stays. If the old one matched wrongly, also delete it in that migration (`SmsTemplate.objects.filter(body_regex=OLD).delete()`).

## 4. Check it

```bash
uv run manage.py test ledger
```

`test_bank_sms` runs every sample, and also fails if any template's regex doesn't compile. To try a message against your local database without writing a test, run `uv run manage.py migrate` first (so the new template is in it), then:

```bash
uv run manage.py shell -c "from datetime import date; from ledger.ingest import parse, compile_templates; from ledger.models import SmsTemplate; print(parse(compile_templates(SmsTemplate.objects.order_by('id')), 'JM-SLCEIT-S', '''PASTE SMS HERE''', date.today()))"
```

The result lists `bank=''` when no template matched and the generic fallback was used.
