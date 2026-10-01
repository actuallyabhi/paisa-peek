import json
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from .ingest import Skipped, compile_templates, ingest, parse, parse_amount
from .models import Account, ApiToken, Category, SmsTemplate, Transaction
from .templatetags.money import inr

RECEIVED = date(2026, 9, 29)

# (sender, text, amount, kind, merchant, last4, ref, bank, date)
SMS_CASES = [
    ("VM-HDFCBK", "Sent Rs.270.00\nFrom HDFC Bank A/C *1234\nTo AIRTEL\nOn 29/09/26\nRef 526712345678\nNot You?\nCall 18002586161/SMS BLOCK UPI to 7308080808",
     "270.00", "expense", "AIRTEL", "1234", "526712345678", "HDFC", "2026-09-29"),
    ("VM-HDFCBK", "Spent Rs.1,100.00 On HDFC Bank Card 5678 At SWIGGY On 2026-09-28:20:11:05.Not You? To Block+Reissue Call 18002323232/SMS BLOCK CC 5678 to 7308080808",
     "1100.00", "expense", "SWIGGY", "5678", "", "HDFC", "2026-09-28"),
    ("VM-HDFCBK", "Money Received - INR 500.00 in HDFC Bank A/c xx1234 on 27-09-26 from VPA meera@okicici (UPI 526712345679)",
     "500.00", "income", "meera@okicici", "1234", "526712345679", "HDFC", "2026-09-27"),
    ("AD-ICICIB", "ICICI Bank Acct XX123 debited for Rs 1700.00 on 29-Sep-26; BSNL credited. UPI:526712345680. Call 18002662 for dispute. SMS BLOCK 123 to 9215676766.",
     "1700.00", "expense", "BSNL", "123", "526712345680", "ICICI", "2026-09-29"),
    ("AD-ICICIB", "INR 12,101.00 spent using ICICI Bank Card XX4321 on 25-Sep-26 on AMAZON PAY. Avl Limit: INR 50,000.00. If not you, call 1800 2662/SMS BLOCK 4321 to 9215676766",
     "12101.00", "expense", "AMAZON PAY", "4321", "", "ICICI", "2026-09-25"),
    ("JD-AXISBK-S", "INR 1150.00 debited\nA/c no. XX9876\n29-09-26, 10:15:22\nUPI/P2M/526712345681/INDIAN OIL\nNot you? SMS BLOCKUPI Cust ID to 919951860002\nAxis Bank",
     "1150.00", "expense", "INDIAN OIL", "9876", "526712345681", "Axis", "2026-09-29"),
    ("JD-AXISBK-S", "Spent INR 11500 Axis Bank Card no. XX2468 26-09-26 10:15:22 IST Flipkart Avl Limit: INR 1000 Not you? SMS BLOCK 2468 to 919951860002",
     "11500.00", "expense", "Flipkart", "2468", "", "Axis", "2026-09-26"),
    ("BZ-SBIUPI", "Dear UPI user A/C X1234 debited by 270.0 on date 29Sep26 trf to AIRTEL Refno 526712345682. If not u? call 1800111109. -SBI",
     "270.00", "expense", "AIRTEL", "1234", "526712345682", "SBI", "2026-09-29"),
    ("BZ-SBIUPI", "Dear SBI UPI User, ur A/cX5555 credited by Rs500 on 29Sep26 by Rohan (Ref no 526712345683)",
     "500.00", "income", "Rohan", "5555", "526712345683", "SBI", "2026-09-29"),
    ("VK-KOTAKB", "Sent Rs.270.00 from Kotak Bank AC X1234 to airtel@upi on 29-09-26.UPI Ref 526712345684. Not you, https://kotak.com/KBANKT/Fraud",
     "270.00", "expense", "airtel@upi", "1234", "526712345684", "Kotak", "2026-09-29"),
    # No template for this bank: generic heuristic, date falls back to the receive date.
    ("XY-RBLBNK", "Your a/c no. XX7777 is debited for Rs.99.00 on 29-09-2026 towards YOUTUBE. Ref 526712345685",
     "99.00", "expense", "YOUTUBE", "7777", "526712345685", "", "2026-09-29"),
]


class ParseTests(TestCase):
    def test_bank_sms(self):
        templates = compile_templates(SmsTemplate.objects.order_by("id"))
        self.assertEqual(len(templates), SmsTemplate.objects.count(), "a seeded template failed to compile")
        for sender, text, *want in SMS_CASES:
            with self.subTest(text=text[:40]):
                p = parse(templates, sender, text, RECEIVED)
                self.assertIsNotNone(p)
                got = [str(p.amount), p.kind, p.merchant, p.last4, p.ref, p.bank, p.date.isoformat()]
                self.assertEqual(got, want)

    def test_amounts_and_format(self):
        self.assertEqual(parse_amount("12,101.5"), Decimal("12101.50"))
        for bad in ["", "-5", "abc", "0"]:
            self.assertIsNone(parse_amount(bad))
        self.assertEqual(inr(Decimal("1234567.8")), "₹12,34,567.80")
        self.assertEqual(inr(999), "₹999.00")


class IngestTests(TestCase):
    def sms(self, text, source="sms"):
        return ingest(text, sender="VM-HDFCBK", source=source, received=RECEIVED)

    def test_dedupe(self):
        upi = "Sent Rs.270.00\nFrom HDFC Bank A/C *1234\nTo AIRTEL\nOn 29/09/26\nRef 526712345678"
        first, dup = self.sms(upi)
        self.assertFalse(dup)
        self.assertEqual(self.sms(upi), (first, True))
        # Screenshot OCR of the same UPI payment: matched by ref.
        self.assertEqual(self.sms("Paid ₹270 to AIRTEL UPI Ref No 526712345678", source="screenshot"), (first, True))
        # Two genuine card spends, same amount and day, no ref: both kept.
        self.assertFalse(self.sms("Spent Rs.100.00 On HDFC Bank Card 5678 At CHAI POINT On 2026-09-28:09:00:00.")[1])
        self.assertFalse(self.sms("Spent Rs.100.00 On HDFC Bank Card 5678 At CHAI POINT On 2026-09-28:17:30:00.")[1])
        with self.assertRaises(Skipped):
            self.sms("483920 is your OTP for txn of Rs 500 at AMAZON")
        self.assertEqual(Transaction.objects.count(), 3)
        self.assertEqual(Account.objects.count(), 2)


class ApiTests(TestCase):
    url = "/api/ingest/sms"

    def test_auth_and_ingest(self):
        body = {"sender": "AD-ICICIB", "text": SMS_CASES[4][1], "ts": "1790000000000"}
        self.assertEqual(self.client.post(self.url, body, content_type="application/json").status_code, 401)
        self.assertEqual(self.client.post(self.url + "?token=wrong", body, content_type="application/json").status_code, 401)
        r = self.client.post(f"{self.url}?token={ApiToken.current()}", body, content_type="application/json")
        self.assertEqual(r.json()["status"], "created")
        r = self.client.post(self.url, body, content_type="application/json", headers={"Authorization": f"Bearer {ApiToken.current()}"})
        self.assertEqual(r.json()["status"], "duplicate")

    def test_app_inbox_review(self):
        auth = {"Authorization": f"Bearer {ApiToken.current()}"}
        r = self.client.post(self.url, {"sender": "VM-HDFCBK", "text": SMS_CASES[0][1]}, content_type="application/json", headers=auth)
        self.assertEqual(r.json()["txn"]["amount"], "−₹270.00")  # summary for the app's notification
        income = self.client.post(self.url, {"sender": "VM-HDFCBK", "text": SMS_CASES[2][1]}, content_type="application/json", headers=auth).json()["id"]
        self.assertEqual(self.client.get("/api/inbox").status_code, 401)
        inbox = self.client.get("/api/inbox", headers=auth).json()
        self.assertEqual(len(inbox["txns"]), 2)
        self.assertTrue(next(t for t in inbox["txns"] if t["id"] == income)["money_in"])
        post = lambda pk, body: self.client.post(f"/api/txns/{pk}/status", body, content_type="application/json", headers=auth)
        # Lent/borrowed/repaid needs a person; the shared rule from the web Inbox applies.
        self.assertEqual(post(income, {"status": "confirmed", "kind": "repay_in"}).status_code, 400)
        self.assertEqual(post(income, {"status": "confirmed", "kind": "repay_in", "party_name": "Meera"}).json(), {"pending": 1})
        t = Transaction.objects.get(pk=income)
        self.assertEqual((t.status, t.kind, t.party.name), ("confirmed", "repay_in", "Meera"))
        cat = inbox["categories"][0]["id"]
        self.assertEqual(post(r.json()["id"], {"status": "confirmed", "category": cat}).json(), {"pending": 0})
        self.assertEqual(Transaction.objects.get(pk=r.json()["id"]).category_id, cat)


class PageTests(TestCase):
    def test_inbox_confirm(self):
        t, _ = ingest(SMS_CASES[0][1], received=RECEIVED)
        self.assertEqual(self.client.get("/inbox/").status_code, 302)  # login required
        self.client.force_login(User.objects.create_user("u", password="x"))
        self.assertContains(self.client.get("/inbox/"), "AIRTEL")
        r = self.client.post(f"/txns/{t.pk}/status/", {"status": "confirmed", "category": 1}, headers={"HX-Request": "true"})
        self.assertContains(r, 'id="pending-badge" hx-swap-oob="true"')
        self.assertNotContains(r, "<article")
        t.refresh_from_db()
        self.assertEqual((t.status, t.category_id), ("confirmed", 1))
        self.assertContains(self.client.get("/?view=month&month=2026-09"), "₹270.00")


class RambleTests(TestCase):
    TODAY = date(2026, 9, 30)  # a Wednesday

    def setUp(self):
        from .models import Tag
        self.hdfc = Account.objects.create(name="HDFC xx1234", kind="credit_card", last4="1234")
        Tag.objects.create(name="GOA")

    def rows(self, text, **kw):
        from . import ramble
        rows, parser = ramble.parse(text, today=self.TODAY, **kw)
        return [(str(r["date"]), str(r["amount"]), r["kind"], r["description"],
                 Category.objects.get(pk=r["category"]).name if r["category"] else None,
                 r["account"], r["tag_names"], r["party_name"]) for r in rows], parser

    def test_heuristic(self):
        rows, parser = self.rows("yesterday 450 petrol, 200 chai with Rohan for GOA, and 1.2k swiggy on hdfc card\n"
                                 "received 5000 from Kabir last friday")
        self.assertEqual(parser, "heuristic")
        self.assertEqual(rows, [
            ("2026-09-29", "450.00", "expense", "Petrol", "Fuel & Transport", None, "", ""),
            ("2026-09-29", "200.00", "expense", "Chai with Rohan GOA", "Food & Outings", None, "GOA", ""),
            ("2026-09-29", "1200.00", "expense", "Swiggy", "Food & Outings", self.hdfc.pk, "", ""),
            ("2026-09-25", "5000.00", "income", "From Kabir", None, None, "", ""),
        ])

    def test_category_memory_beats_keywords(self):
        Transaction.objects.create(date=self.TODAY, amount=99, description="Petrol pump tip",
                                   category=Category.objects.get(name="Other"))
        rows, _ = self.rows("petrol 300")
        self.assertEqual(rows[0][4], "Other")

    def test_loans(self):
        from .models import Party
        Party.objects.create(name="Priya")
        Party.objects.create(name="Chacha ji", kind="person")
        rows, _ = self.rows("lent 500 to Rohan, Priya paid back 2000, borrowed 1000 from Chacha ji, "
                            "returned 300 to Shahid, got back 200 from Kabir")
        self.assertEqual([(r[1], r[2], r[7]) for r in rows], [
            ("500.00", "lend", "Rohan"), ("2000.00", "repay_in", "Priya"), ("1000.00", "borrow", "Chacha ji"),
            ("300.00", "repay_out", "Shahid"), ("200.00", "repay_in", "Kabir"),
        ])
        self.assertTrue(all(r[4] is None for r in rows))  # loans aren't spending categories

    def test_dictated_sentences(self):
        rows, _ = self.rows("Paid Rs. 450 for petrol. Got 1.5k salary today.")
        self.assertEqual([(r[1], r[2], r[3]) for r in rows], [("450.00", "expense", "Petrol"), ("1500.00", "income", "Salary")])

    def test_llm_output_is_validated(self):
        from unittest.mock import patch
        fake = {"transactions": [
            {"date": "2026-10-05", "amount": 450, "kind": "expense", "description": "Petrol",
             "category": "fuel & transport", "account": None, "tags": ["Manali"], "party": "Rohan", "quote": "450 petrol"},
            {"date": "2026-09-29", "amount": 200, "kind": "weird", "description": "Chai", "category": "Nope",
             "account": "hdfc xx1234", "tags": ["goa", "Office"], "party": "office", "quote": "200 chai"},
            {"date": "2026-09-29", "amount": 0, "kind": "expense", "description": "x", "category": None,
             "account": None, "tags": [], "party": None, "quote": "x"},
        ]}
        with self.settings(LLM_MODEL="test"), patch("ledger.llm.chat_json", return_value=fake):
            rows, parser = self.rows("450 petrol, 200 chai for goa with office folks")
        self.assertEqual(parser, "llm")
        self.assertEqual(rows, [
            # future date clamped; tag and party the note never mentions are dropped
            ("2026-09-30", "450.00", "expense", "Petrol", "Fuel & Transport", None, "", ""),
            # unknown category guessed; party kept because it was said
            ("2026-09-29", "200.00", "expense", "Chai", "Food & Outings", self.hdfc.pk, "GOA, Office", "office"),
        ])

    def test_llm_failure_falls_back(self):
        from unittest.mock import patch
        from .llm import LLMError
        with self.settings(LLM_MODEL="test"), patch("ledger.llm.chat_json", side_effect=LLMError("connection refused")):
            rows, parser = self.rows("450 petrol")
        self.assertTrue(parser.startswith("heuristic (LLM failed"))
        self.assertEqual(rows[0][1], "450.00")

    def test_review_and_save(self):
        self.client.force_login(User.objects.create_user("u", password="x"))
        yesterday = date.today() - date.resolution
        Transaction.objects.create(date=yesterday, amount=450, description="Petrol (from SMS)")

        r = self.client.post("/ramble/parse/", {"text": "yesterday 450 petrol, 200 chai for goa"})
        self.assertContains(r, 'name="r1-tag_names" value="GOA"')
        self.assertContains(r, "possible duplicate")
        self.assertContains(r, 'id="id_r0-include">')  # duplicate starts unticked
        self.assertContains(r, 'id="id_r1-include" checked')

        row = lambda i, **kw: {f"r{i}-{k}": v for k, v in {
            "date": yesterday.isoformat(), "amount": "200", "kind": "expense", "description": "Chai",
            "category": "", "account": "", "tag_names": "", "quote": "200 chai", **kw}.items()}
        post = {"row": ["0", "1"], **row(0, amount="450"), **row(1, include="on", tag_names="GOA, goa, Goa trip")}
        r = self.client.post("/ramble/save/", post)
        self.assertIn("/?view=month&month=", r["HX-Redirect"])
        t = Transaction.objects.get(source="ramble")
        self.assertEqual((t.description, t.raw_text, t.status), ("Chai", "200 chai", "confirmed"))
        self.assertEqual(sorted(t.tags.values_list("name", flat=True)), ["GOA", "Goa trip"])

        # An invalid ticked row blocks the whole save.
        post = {"row": ["0", "1"], **row(0, include="on"), **row(1, include="on", amount="")}
        self.assertContains(self.client.post("/ramble/save/", post), "Fix the highlighted rows")
        self.assertEqual(Transaction.objects.filter(source="ramble").count(), 1)

        self.assertContains(self.client.post("/ramble/add/3/", row(3, description="Samosa")), "✓ Added")
        self.assertTrue(Transaction.objects.filter(description="Samosa", source="ramble").exists())


class PartyTests(TestCase):
    def setUp(self):
        from .models import Party
        self.client.force_login(User.objects.create_user("u", password="x"))
        self.om = Party.objects.create(name="Priya")

    def add(self, kind, amount, status="confirmed", day=date(2026, 9, 1)):
        return Transaction.objects.create(date=day, amount=amount, kind=kind, party=self.om, status=status)

    def test_balance_and_ledger(self):
        self.add("lend", 8000)
        self.add("repay_in", 2500, day=date(2026, 9, 5))
        self.add("borrow", 1000, day=date(2026, 9, 6))
        self.add("repay_out", 400, day=date(2026, 9, 7))
        self.add("lend", 9999, status="pending")  # not counted until confirmed
        self.add("expense", 300)  # listed, doesn't change who owes whom
        r = self.client.get(f"/people/{self.om.pk}/")
        self.assertContains(r, "Priya owes you ₹4,900.00")  # 8000 - 2500 - 1000 + 400
        self.assertEqual([run for t, run in r.context["rows"] if t.status == "confirmed"][-1], Decimal("4900"))
        people = self.client.get("/people/")
        self.assertEqual(people.context["owed_to_me"], Decimal("4900"))
        self.assertContains(people, "owes you ₹4,900.00")

    def test_loan_needs_party_and_creates_it(self):
        base = {"date": "2026-09-01", "amount": "500", "kind": "lend", "description": "", "status": "confirmed",
                "category": "", "account": "", "tag_names": "", "notes": ""}
        r = self.client.post("/", {**base, "party_name": ""})
        self.assertContains(r, "needs a person or company")
        self.client.post("/", {**base, "party_name": "  new   Co  "})
        t = Transaction.objects.get(kind="lend")
        self.assertEqual(t.party.name, "new Co")
        self.client.post("/", {**base, "party_name": "NEW CO"})  # same party, any case
        self.assertEqual(t.party.transactions.count(), 2)

    def test_inbox_credit_asks_what_it_was(self):
        t = Transaction.objects.create(date=date(2026, 9, 1), amount=500, kind="income", merchant="Rohan",
                                       source="sms", status="pending")
        r = self.client.get("/inbox/")
        self.assertContains(r, 'value="repay_in"')
        self.assertContains(r, 'name="party_name"')
        url = f"/txns/{t.pk}/status/"
        self.assertEqual(self.client.post(url, {"status": "confirmed", "kind": "repay_in"}).status_code, 400)
        self.client.post(url, {"status": "confirmed", "kind": "repay_in", "party_name": "priya"})
        t.refresh_from_db()
        self.assertEqual((t.kind, t.party, t.status), ("repay_in", self.om, "confirmed"))

    def test_quick_entry_and_delete_guard(self):
        self.assertNotContains(self.client.get(f"/people/{self.om.pk}/"), 'name="party_name"')
        self.client.post(f"/people/{self.om.pk}/", {"action": "entry", "date": "2026-09-02", "amount": "700",
                                                     "kind": "repay_out", "description": "UPI", "account": "", "notes": ""})
        self.assertEqual(self.om.transactions.get().kind, "repay_out")
        self.client.post(f"/people/{self.om.pk}/", {"action": "delete"})
        self.assertTrue(type(self.om).objects.filter(pk=self.om.pk).exists())


class CSVImportTests(TestCase):
    CSV = """date,type,amount,description,party,category,account,tags,notes
,lent,3000,Lent,Asha,,,,
,lent,1800 + 200,Lent,Asha,,,,
2026-09-10,repaid_to_me,1500,UPI,asha,,,,
,lent,700,Lent,Ravi,,,,
2026-09-12,borrowed,400,Cash,Ravi,,,,
2025-10-01,expense,720 + 775 + 380,Movie outing + food,,Food & Outings,,JAN trip; GOA,
2025-10-01,expense,"1,234.50",Router,,,,,
"""

    def forms(self, text=None):
        from io import BytesIO
        from .csv_import import read_rows, to_forms
        return to_forms(read_rows(BytesIO((text or self.CSV).encode())), date(2026, 9, 30))

    def test_shipped_sample_is_valid(self):
        from .csv_import import read_rows, to_forms
        with open("ledger/static/ledger/import-sample.csv", "rb") as f:
            forms_ = to_forms(read_rows(f), date(2026, 9, 30))
        self.assertTrue(forms_)
        self.assertEqual([f.errors for f in forms_ if f.errors], [])

    def test_import_balances_breakdowns_and_reimport(self):
        from .views import _parties
        forms_ = self.forms()
        self.assertEqual([f.errors for f in forms_ if f.errors], [])
        for f in forms_:
            f.save()
        balances = {p.name: p.balance for p in _parties()}
        self.assertEqual(balances, {"Asha": Decimal("3500"), "Ravi": Decimal("300")})  # 3000+2000-1500 ; 700-400
        t = Transaction.objects.get(description="Movie outing + food")
        self.assertEqual((t.amount, t.notes, t.source), (Decimal("1875"), "Breakdown: 720 + 775 + 380", "import"))
        self.assertEqual(sorted(t.tags.values_list("name", flat=True)), ["GOA", "JAN trip"])
        self.assertEqual(Transaction.objects.get(description="Router").amount, Decimal("1234.50"))
        self.assertEqual(Transaction.objects.filter(date="2026-09-30").count(), 3)  # blank dates -> default date
        # Re-importing the same file: every row is flagged and unticked.
        self.assertTrue(all(f.dup and not f["include"].value() for f in self.forms()))

    def test_upload_review_save(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(User.objects.create_user("u", password="x"))
        csv_text = ("Date,Type,Amount,Description,Party,Category,Account,Tags,Notes\n"
                    "01/09/2026,lent,1000,Cash,Rohan,,,trip;GOA,\n"
                    ",borrowed,,Loan,Priya,,,,\n"  # missing amount -> flagged
                    "2026-09-02,expense,450,Petrol,,Nope,,,\n")
        up = SimpleUploadedFile("x.csv", csv_text.encode("utf-8-sig"), content_type="text/csv")
        r = self.client.post("/import/", {"file": up, "default_date": "2026-09-15"})
        self.assertContains(r, "1 need fixing")
        self.assertContains(r, "unknown category")
        self.assertContains(r, 'name="source" value="import"')
        post = {"source": "import", "row": ["0", "1"]}
        for i, (d, k, a, desc, party, tags) in enumerate([("2026-09-01", "lend", "1000", "Cash", "Rohan", "trip, GOA"),
                                                          ("2026-09-15", "borrow", "", "Loan", "Priya", "")]):
            post.update({f"r{i}-date": d, f"r{i}-kind": k, f"r{i}-amount": a, f"r{i}-description": desc,
                         f"r{i}-party_name": party, f"r{i}-tag_names": tags, f"r{i}-quote": "CSV", f"r{i}-include": "on"})
        self.assertContains(self.client.post("/ramble/save/", post), "Fix the highlighted rows")
        post["r1-include"] = ""
        r = self.client.post("/ramble/save/", post)
        self.assertEqual(r["HX-Redirect"], "/people/")
        t = Transaction.objects.get()
        self.assertEqual((t.source, t.party.name, t.kind), ("import", "Rohan", "lend"))

    def test_bad_files(self):
        from io import BytesIO
        from .csv_import import CSVError, read_rows
        with self.assertRaises(CSVError):
            read_rows(BytesIO(b"name,value\nx,1\n"))
        with self.assertRaises(CSVError):
            read_rows(BytesIO("amount\n1\n".encode("utf-16")))


class HomeViewTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("u", password="x"))

    def test_week_month_toggle(self):
        Transaction.objects.create(date=date(2026, 9, 29), amount=100, description="Tue chai")
        Transaction.objects.create(date=date(2026, 9, 21), amount=900, description="Last week")
        r = self.client.get("/?view=week&start=2026-10-01")  # any day snaps to its Monday
        self.assertContains(r, "28 Sep – 4 Oct 2026")
        self.assertContains(r, "Tue chai")
        self.assertNotContains(r, "Last week")
        self.assertEqual(r.context["spent"], Decimal("100"))
        self.assertIn("start=2026-09-21", r.context["p"]["prev"])
        # The choice sticks: plain "/" stays in week view.
        self.assertEqual(self.client.get("/").context["p"]["view"], "week")
        r = self.client.get("/?view=month&month=2026-09")
        self.assertContains(r, "Last week")
        self.assertEqual(r.context["spent"], Decimal("1000"))

    def test_ramble_is_on_home(self):
        self.assertContains(self.client.get("/"), 'hx-post="/ramble/parse/"')
        self.assertContains(self.client.get("/?log=1"), "autofocus")


class AccountTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("u", password="x"))

    def save(self, pk=None, **data):
        base = {"name": "x", "kind": "savings", "last4": "", "current_balance": "", "credit_limit": "",
                "statement_day": "", "due_day": "", "is_default": ""}
        url = f"/accounts/{pk}/" if pk else "/accounts/new/"
        r = self.client.post(url, {**base, **data})
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        return Account.objects.get(name=data["name"])

    def test_balances_cards_and_transfers(self):
        sav = self.save(name="HDFC Savings", current_balance="10000", is_default="on")
        card = self.save(name="ICICI Card", kind="credit_card", current_balance="2000", credit_limit="50000",
                         statement_day="15", due_day="5")
        self.assertEqual((sav.balance, card.balance), (Decimal("10000"), Decimal("-2000")))  # card: owed = negative
        Transaction.objects.create(date=date.today(), amount=500, account=sav)
        Transaction.objects.create(date=date.today(), amount=300, account=card)
        Transaction.objects.create(date=date.today(), amount=1000, kind="transfer", account=sav, to_account=card)
        Transaction.objects.create(date=date.today(), amount=99, account=sav, status="pending")  # not yet counted
        self.assertEqual((sav.balance, card.balance), (Decimal("8500"), Decimal("-1300")))
        r = self.client.get("/accounts/")
        self.assertEqual((r.context["assets"], r.context["dues"], r.context["net"]), (Decimal("8500"), Decimal("1300"), Decimal("7200")))
        # "Set current balance" back-solves: whatever the bank says now becomes the balance.
        sav = self.save(pk=sav.pk, name="HDFC Savings", current_balance="8000", is_default="on")
        self.assertEqual(sav.balance, Decimal("8000"))

    def test_single_default_prefills_forms(self):
        a = self.save(name="Cash", kind="cash", is_default="on")
        b = self.save(name="Wallet", kind="wallet", is_default="on")
        a.refresh_from_db()
        self.assertEqual((a.is_default, b.is_default), (False, True))
        self.assertEqual(self.client.get("/").context["form"].initial["account"], b)
        from . import ramble
        self.assertEqual(ramble.parse("50 chai")[0][0]["account"], b.pk)

    def test_transfer_validation(self):
        a = self.save(name="A")
        r = self.client.post("/", {"date": "2026-09-01", "amount": "5", "kind": "expense", "account": a.pk,
                                   "to_account": a.pk, "status": "confirmed"})
        self.assertContains(r, "Only for transfers")


class RecurringTests(TestCase):
    def test_due_dates_and_cost(self):
        from .models import Recurring
        r = Recurring.objects.create(name="Rent", amount=12000, next_due=date(2026, 1, 31))
        dues = []
        for _ in range(3):
            r.next_due = r.following_due()
            r.save()
            dues.append(r.next_due)
        self.assertEqual(dues, [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)])  # no drift to the 28th
        wifi = Recurring(name="Wifi", amount=11300, every=12, unit="month", next_due=date(2026, 1, 1))
        self.assertEqual(wifi.monthly_cost, Decimal("941.67"))  # the spreadsheet's Wifi row
        self.assertEqual(Recurring(name="w", amount=100, unit="week", next_due=date(2026, 1, 1)).following_due(), date(2026, 1, 8))

    def test_paid_logs_and_advances(self):
        from .models import Recurring
        self.client.force_login(User.objects.create_user("u", password="x"))
        cash = Account.objects.create(name="Cash", kind="cash", is_default=True)
        r = Recurring.objects.create(name="Gym", amount=1700, next_due=date(2026, 10, 5))
        self.client.post(f"/recurring/{r.pk}/done/", {"action": "paid"})
        t = Transaction.objects.get(source="recurring")
        self.assertEqual((t.amount, t.description, t.account), (Decimal("1700"), "Gym", cash))
        self.client.post(f"/recurring/{r.pk}/done/", {"action": "skip"})
        r.refresh_from_db()
        self.assertEqual(r.next_due, date(2026, 12, 5))
        self.assertEqual(Transaction.objects.count(), 1)


class ReminderTests(TestCase):
    def test_fresh_install_first_run(self):
        from .reminders import run_once
        self.assertEqual(run_once(self.at(2026, 9, 1, 10), send=lambda *a: None), [])  # no settings row yet: no crash

    def at(self, y, m, d, hh, mm=0):
        from datetime import datetime
        return datetime(y, m, d, hh, mm)

    def keys(self, now):
        from .reminders import due
        return sorted(k for k, *_ in due(now))

    def test_schedule(self):
        from .models import NotifySettings, Recurring
        cfg = NotifySettings.get()
        cfg.daily_enabled = True
        cfg.save()
        card = Account.objects.create(name="HDFC Card", kind="credit_card", statement_day=31, due_day=5)
        Account.objects.create(name="Savings", kind="savings", statement_day=15)  # not a card: never reminded
        rent = Recurring.objects.create(name="Rent", amount=9000, next_due=date(2026, 9, 3), remind_days_before=2)

        self.assertEqual(self.keys(self.at(2026, 9, 1, 8)), [])  # before 09:00 reminder time
        self.assertEqual(self.keys(self.at(2026, 9, 1, 9)), [f"recurring:{rent.pk}:2026-09-03"])  # 2 days early
        self.assertEqual(self.keys(self.at(2026, 9, 5, 21)),
                         ["daily:2026-09-05", f"due:{card.pk}:2026-09-05"])  # rent passed its due date: no nag
        self.assertEqual(self.keys(self.at(2026, 9, 30, 10)), [f"statement:{card.pk}:2026-09-30"])  # 31st -> last day

    def test_run_once_sends_each_key_once(self):
        from .models import NotifySettings
        from .reminders import run_once
        cfg = NotifySettings.get()
        cfg.daily_enabled = True
        cfg.save()
        sent = []
        fake = lambda title, body, url: sent.append((title, url))
        now = self.at(2026, 9, 5, 21, 30)
        self.assertEqual(run_once(now, send=fake), ["daily:2026-09-05"])
        self.assertEqual(run_once(now, send=fake), [])
        self.assertEqual(sent, [("Log today's spending", "/?log=1")])


class PWATests(TestCase):
    def test_service_worker_and_manifest(self):
        r = self.client.get("/sw.js")
        self.assertEqual(r["Content-Type"], "application/javascript")
        self.assertIn(b"showNotification", r.content)
        from django.contrib.staticfiles import finders
        import json
        manifest = json.load(open(finders.find("ledger/manifest.webmanifest")))
        self.assertEqual((manifest["display"], manifest["start_url"]), ("standalone", "/"))
        for icon in manifest["icons"]:
            self.assertTrue(finders.find(icon["src"].removeprefix("/static/")))

    def test_push_subscribe(self):
        from .models import PushSubscription
        self.client.force_login(User.objects.create_user("u", password="x"))
        sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "k", "auth": "a"}}
        import json
        for _ in range(2):  # re-subscribing the same device doesn't duplicate
            r = self.client.post("/push/subscribe/", json.dumps(sub), content_type="application/json")
        self.assertEqual(r.json(), {"devices": 1})
        bad = self.client.post("/push/subscribe/", json.dumps({**sub, "endpoint": "http://evil"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)
        self.assertContains(self.client.get("/settings/"), "Enable on this device")
        self.client.post("/settings/", {"action": "notify", "daily_enabled": "on", "daily_time": "22:15",
                                        "reminders_enabled": "on", "reminder_time": "08:30"})
        from .models import NotifySettings
        cfg = NotifySettings.get()
        self.assertEqual((cfg.daily_enabled, str(cfg.daily_time), str(cfg.reminder_time)), (True, "22:15:00", "08:30:00"))


class PushSendTests(TestCase):
    """Real VAPID signing + payload encryption against a local fake push service."""

    def test_send_encrypts_signs_and_prunes(self):
        import base64
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from . import push
        from .models import PushSubscription

        seen = []

        class FakePushService(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
                self.send_response(410 if self.path == "/gone" else 201)
                self.end_headers()

            def log_message(self, *a):
                pass

        server = HTTPServer(("127.0.0.1", 0), FakePushService)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
        device_key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        for path in ("/ok", "/gone"):
            PushSubscription.objects.create(endpoint=base + path, p256dh=b64(device_key), auth=b64(b"0123456789abcdef"))
        PushSubscription.objects.create(endpoint="http://127.0.0.1:9/down", p256dh=b64(device_key), auth=b64(b"0123456789abcdef"))

        with self.settings(DATA_DIR=__import__("pathlib").Path(__import__("tempfile").mkdtemp())):
            self.assertEqual(push.send("Rent due today", "₹9,000", "/recurring/"), 1)
            self.assertEqual(len(push.public_key()), 87)  # 65-byte uncompressed P-256 point, base64url
        server.shutdown()
        path, headers, body = next(x for x in seen if x[0] == "/ok")
        self.assertEqual(headers["content-encoding"], "aes128gcm")
        self.assertIn("vapid t=", headers["authorization"])
        self.assertNotIn(b"Rent", body)  # payload is encrypted
        self.assertEqual(sorted(PushSubscription.objects.values_list("endpoint", flat=True)),
                         [base + "/ok", "http://127.0.0.1:9/down"])  # 410 pruned, unreachable kept


class DateTimeDefaultsTests(TestCase):
    """New entries default to today and now, in the app's timezone (not the server clock's)."""

    def setUp(self):
        self.client.force_login(User.objects.create_user("u", password="x"))

    def test_manual_form_defaults_to_local_today_and_now(self):
        from django.utils import timezone
        # Kiritimati is UTC+14: its "today" differs from a UTC/IST server clock for much of the day.
        with self.settings(TIME_ZONE="Pacific/Kiritimati"):
            form = self.client.get("/").context["form"]
            now = timezone.localtime()
            self.assertEqual(form.initial["date"], timezone.localdate())
            self.assertLessEqual(abs(now.hour * 60 + now.minute - form.initial["time"].hour * 60 - form.initial["time"].minute), 1)
        self.assertContains(self.client.get("/"), 'type="time" name="time" value="')

    def test_manual_add_keeps_time(self):
        self.client.post("/", {"date": "2026-09-01", "time": "21:05", "amount": "50", "kind": "expense",
                               "status": "confirmed", "description": "Chai"})
        t = Transaction.objects.get()
        self.assertEqual(str(t.time), "21:05:00")
        self.assertContains(self.client.get("/?view=month&month=2026-09"), "9:05 PM")

    def test_ramble_stamps_today_only(self):
        from django.utils import timezone
        today = timezone.localdate()
        row = lambda i, d: {f"r{i}-date": d, f"r{i}-amount": "10", f"r{i}-kind": "expense", f"r{i}-description": f"x{i}",
                            f"r{i}-quote": "q", f"r{i}-include": "on"}
        self.client.post("/ramble/save/", {"row": ["0", "1"], **row(0, today.isoformat()), **row(1, "2026-01-05")})
        self.assertIsNotNone(Transaction.objects.get(description="x0").time)  # logged today -> now
        self.assertIsNone(Transaction.objects.get(description="x1").time)  # a past day: time unknown

    def test_sms_keeps_arrival_time(self):
        import json
        from datetime import datetime
        from django.utils import timezone
        ts = int(timezone.make_aware(datetime(2026, 9, 29, 20, 11)).timestamp() * 1000)
        body = {"sender": "VM-HDFCBK", "text": SMS_CASES[0][1], "ts": ts}  # SMS dated 29/09/26 -> same day
        self.client.post(f"/api/ingest/sms?token={ApiToken.current()}", json.dumps(body), content_type="application/json")
        self.assertEqual(str(Transaction.objects.get().time), "20:11:00")


class BackupTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("u", password="x"))

    def seed(self):
        from .models import NotifySettings, Party, Recurring, Tag
        sav = Account.objects.create(name="HDFC Savings", kind="savings", opening_balance=50000, is_default=True)
        card = Account.objects.create(name="ICICI Card", kind="credit_card", opening_balance=-2000, statement_day=15, due_day=5)
        om = Party.objects.create(name="Priya", kind="person")
        food = Category.objects.get(name="Food & Outings")
        t = Transaction.objects.create(date=date(2026, 9, 29), time="21:05", amount=450, description="Dinner",
                                       category=food, account=card, party=om, notes="split")
        t.tags.add(Tag.objects.create(name="GOA"))
        Transaction.objects.create(date=date(2026, 9, 30), amount=8000, kind="lend", party=om, account=sav)
        Transaction.objects.create(date=date(2026, 9, 30), amount=1000, kind="transfer", account=sav, to_account=card)
        Recurring.objects.create(name="Rent", amount=12000, next_due=date(2026, 1, 31), essential=True)
        cfg = NotifySettings.get()
        cfg.daily_enabled = True
        cfg.save()
        return sav, card

    def snapshot(self):
        from .models import NotifySettings, Recurring
        from .views import _parties
        return {
            "balances": {a.name: a.balance for a in Account.objects.all()},
            "owed": {p.name: p.balance for p in _parties()},
            "txns": sorted((str(t.date), str(t.time), t.amount, t.kind, t.description, str(t.party), str(t.to_account),
                            tuple(t.tags.values_list("name", flat=True))) for t in Transaction.objects.all()),
            "recurring": [(r.name, r.next_due, r.anchor_day, r.essential) for r in Recurring.objects.all()],
            "default": Account.default().name, "daily": NotifySettings.get().daily_enabled,
            "token": ApiToken.current(), "categories": Category.objects.count(),
        }

    def test_export_restore_round_trip(self):
        self.seed()
        before = self.snapshot()
        r = self.client.get("/backup/export/")
        self.assertIn("attachment", r["Content-Disposition"])
        doc = r.json()
        self.assertEqual((doc["format"], doc["version"], doc["counts"]["ledger.transaction"]), ("paisapeek-backup", 1, 3))

        # Wreck the data, then restore the file.
        Transaction.objects.all().delete()
        Account.objects.all().delete()
        Category.objects.create(name="Junk")
        from django.core.files.uploadedfile import SimpleUploadedFile
        up = SimpleUploadedFile("b.json", r.content, content_type="application/json")
        r = self.client.post("/backup/restore/", {"file": up, "confirm": "on"}, follow=True)
        self.assertContains(r, "Restored:")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(before["owed"], {"Priya": Decimal("8000")})
        from django.conf import settings
        self.assertTrue(list((settings.DATA_DIR / "backups").glob("before-restore-*.json")))  # safety copy

    def test_restore_needs_confirmation_and_rejects_foreign_or_broken_files(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from . import backup
        self.seed()
        good = json.dumps(backup.export()).encode()
        up = lambda b: SimpleUploadedFile("b.json", b, content_type="application/json")
        self.assertContains(self.client.post("/backup/restore/", {"file": up(good)}, follow=True), "replace my current data")
        with self.assertRaisesMessage(backup.RestoreError, "auth.user"):
            backup.restore(json.dumps([{"model": "auth.user", "pk": 9, "fields": {"username": "evil", "is_superuser": True}}]).encode())
        with self.assertRaisesMessage(backup.RestoreError, "not valid JSON"):
            backup.restore(b"hello")
        broken = json.loads(good)
        broken["data"].append({"model": "ledger.transaction", "pk": 999, "fields": {"date": "not-a-date", "amount": "1"}})
        with self.assertRaisesMessage(backup.RestoreError, "nothing was changed"):
            backup.restore(json.dumps(broken).encode())
        self.assertEqual(Transaction.objects.count(), 3)  # untouched after the failed restore
        self.assertFalse(User.objects.filter(username="evil").exists())

    def test_backups_from_earlier_app_names_restore(self):
        from . import backup
        self.seed()
        for legacy in ("budget-backup", "damdi-backup"):
            doc = {**backup.export(), "format": legacy}
            self.assertEqual(backup.restore(json.dumps(doc).encode())["transaction"], 3)

    def test_plain_dumpdata_is_accepted(self):
        from io import StringIO
        from django.core.management import call_command
        from . import backup
        self.seed()
        out = StringIO()
        call_command("dumpdata", "ledger.category", "ledger.tag", "ledger.party", "ledger.account",
                     "ledger.transaction", stdout=out)
        Transaction.objects.all().delete()
        counts = backup.restore(out.getvalue().encode())
        self.assertEqual(counts["transaction"], 3)
        self.assertEqual(Transaction.objects.get(description="Dinner").tags.get().name, "GOA")

    def test_csv_export_reimports(self):
        from io import BytesIO
        from .csv_import import read_rows, to_forms
        self.seed()
        r = self.client.get("/backup/export.csv")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        text = r.content.decode()
        self.assertIn("2026-09-30,,lent,8000.00,,Priya,,HDFC Savings,", text)
        forms_ = to_forms(read_rows(BytesIO(r.content)), date(2026, 10, 1))
        self.assertEqual([f.errors for f in forms_ if f.errors], [])
        self.assertTrue(all(f.dup for f in forms_))  # same data already here -> all flagged, nothing doubled

    def test_onboarding_offers_restore(self):
        r = self.client.get("/")
        self.assertContains(r, "Namaste")
        self.assertContains(r, 'action="/backup/restore/"')
        self.assertNotContains(r, 'name="confirm"')  # nothing to overwrite yet
        self.seed()
        self.assertNotContains(self.client.get("/"), "Namaste")


class RecurringIncomeTests(TestCase):
    def test_income_items(self):
        from datetime import datetime
        from .models import Recurring
        from .reminders import due
        self.client.force_login(User.objects.create_user("u", password="x"))
        form = self.client.get("/recurring/").context["form"]
        self.assertEqual([k for k, _ in form.fields["kind"].choices], ["expense", "income", "transfer"])
        self.client.post("/recurring/", {"name": "Stipend", "amount": "25000", "kind": "income", "every": "1",
                                         "unit": "month", "next_due": "2026-10-05", "remind_days_before": "0", "active": "on"})
        stipend = Recurring.objects.get(name="Stipend")
        Recurring.objects.create(name="Rent", amount=9000, next_due=date(2026, 10, 1), essential=True)
        Recurring.objects.create(name="Netflix", amount=1800, every=3, next_due=date(2026, 10, 9))
        r = self.client.get("/recurring/")
        self.assertEqual((r.context["money_in"], r.context["money_out"], r.context["net"], r.context["minimum"]),
                         (Decimal("25000"), Decimal("9600"), Decimal("15400"), Decimal("9000")))
        self.assertContains(r, "Received")
        self.client.post(f"/recurring/{stipend.pk}/done/", {"action": "paid"})
        t = Transaction.objects.get(description="Stipend")
        self.assertEqual((t.kind, t.amount, t.sign), ("income", Decimal("25000"), "+"))
        stipend.refresh_from_db()
        self.assertEqual(stipend.next_due, date(2026, 11, 5))
        reminders = {k: (title, body) for k, title, body, _ in due(datetime(2026, 11, 5, 10))}
        self.assertEqual(reminders[f"recurring:{stipend.pk}:2026-11-05"],
                         ("Stipend expected today", "₹25,000.00 · tap to mark it received."))


class LanguageTests(TestCase):
    """Standard Django i18n: switcher posts to set_language, which stores a cookie LocaleMiddleware reads."""

    def setUp(self):
        self.client.force_login(User.objects.create_user("abhishek", password="x"))
        Transaction.objects.create(date=date(2026, 9, 29), amount=450, description="Petrol",
                                   category=Category.objects.get(name="Fuel & Transport"))

    def test_switch_to_hindi_and_back(self):
        r = self.client.get("/?view=month&month=2026-09")
        self.assertContains(r, '<html lang="en">')
        self.assertNotContains(r, 'action="/i18n/setlang/"')  # not in the nav any more...
        self.assertContains(self.client.get("/settings/"), 'action="/i18n/setlang/"')  # ...it lives in More
        self.assertContains(r, "Where it went")

        r = self.client.post("/i18n/setlang/", {"language": "hi", "next": "/?view=month&month=2026-09"})
        self.assertEqual(r.status_code, 302)
        r = self.client.get("/?view=month&month=2026-09")
        self.assertContains(r, '<html lang="hi">')
        self.assertContains(r, "पैसा कहाँ गया")            # template string
        self.assertContains(r, "पेट्रोल और आना-जाना")       # shipped category name, stored in English
        self.assertContains(r, "सितंबर 2026")               # month name: Django's Hindi dates, spelling fixed by our catalog
        self.assertContains(self.client.get("/people/"), "लोग और कंपनियाँ")
        # Direction matters: "owes you" = you RECEIVE (मिलना), not pay (देना).
        from .models import Party
        Transaction.objects.create(date=date(2026, 9, 1), amount=500, kind="lend", party=Party.objects.create(name="Priya"))
        self.assertContains(self.client.get("/people/"), "आपको ₹500.00 मिलने हैं")
        form = self.client.get("/").context["form"]
        self.assertEqual(str(form.fields["kind"].label), "प्रकार")

        self.client.post("/i18n/setlang/", {"language": "en", "next": "/"})
        self.assertContains(self.client.get("/people/"), "People & companies")

    def test_browser_language_is_the_default(self):
        self.assertContains(self.client.get("/", HTTP_ACCEPT_LANGUAGE="hi-IN,hi;q=0.9"), '<html lang="hi">')

    def test_catalog_is_complete(self):
        """Every string in the .po is translated AND compiled into the .mo (catches forgetting compilemessages)."""
        import gettext
        import re
        from pathlib import Path
        for folder in sorted((Path(__file__).parent / "locale").glob("*/LC_MESSAGES")):
            with self.subTest(language=folder.parent.name):
                self._check_catalog(folder)

    def _check_catalog(self, folder):
        import gettext
        import re
        po = (folder / "django.po").read_text()
        self.assertNotIn("#, fuzzy", po)
        msgids = set()
        for block in po.split("\n\n")[1:]:  # skip the header
            lines = [l for l in block.splitlines() if not l.startswith("#")]
            body = "\n".join(lines)
            m = re.search(r'^msgid ((?:".*"\n?)+)', body, re.M)
            if m:
                msgids.add("".join(re.findall(r'"(.*)"', m.group(1))).encode().decode("unicode_escape").encode("latin-1").decode())
        with open(folder / "django.mo", "rb") as f:
            compiled = {k[0] if isinstance(k, tuple) else k for k, v in gettext.GNUTranslations(f)._catalog.items() if v}
        self.assertEqual(sorted(msgids - compiled), [])


class HinglishAndSettingsTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("u", password="x"))

    def test_hinglish(self):
        self.client.post("/i18n/setlang/", {"language": "hi-latn", "next": "/"})
        r = self.client.get("/")
        self.assertContains(r, '<html lang="hi-latn">')
        self.assertContains(r, "Aaj kya kharcha hua?")
        self.assertContains(self.client.get("/people/"), "Log aur companies")

    def test_hinglish_never_leaks_devanagari_dates_or_errors(self):
        # gettext falls back hi_Latn -> hi; our catalog must cover Django's date names and form errors.
        Transaction.objects.create(date=date(2026, 9, 9), amount=10, description="Chai")
        self.client.post("/i18n/setlang/", {"language": "hi-latn", "next": "/"})
        r = self.client.get("/?view=month&month=2026-09")
        self.assertContains(r, "Wednesday, 09 Sep")
        self.assertNotContains(r, "सित")
        r = self.client.post("/", {"date": "", "amount": "", "kind": "expense", "status": "confirmed"})
        self.assertContains(r, "Yeh bharna zaroori hai.")

    def test_language_section_in_settings(self):
        r = self.client.get("/settings/")
        self.assertContains(r, 'id="language"')
        for code in ("en", "hi", "hi-latn"):
            self.assertContains(r, f'name="language" value="{code}"')


class PaginationTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("u", password="x"))

    def test_home_pages_keep_period_and_day_totals(self):
        for i in range(35):  # 30 per page
            Transaction.objects.create(date=date(2026, 9, 10), amount=10, description=f"t{i}")
        r = self.client.get("/?view=month&month=2026-09")
        self.assertEqual(sum(len(items) for _d, items, _s in r.context["days"]), 30)
        self.assertContains(r, "?view=month&amp;month=2026-09&amp;page=2")  # querystring keeps the period
        r2 = self.client.get("/?view=month&month=2026-09&page=2")
        day, items, total = r2.context["days"][0]
        self.assertEqual((len(items), total), (5, Decimal("350")))  # total is the whole day, not just this page
        self.assertEqual(self.client.get("/?view=month&month=2026-09&page=99").context["page"].number, 2)  # clamps
        self.assertEqual(self.client.get("/?view=month&month=2026-09&page=abc").context["page"].number, 1)

    def test_every_list_uses_the_pager(self):
        from .models import Party, Recurring
        om = Party.objects.create(name="Priya")
        acct = Account.objects.create(name="Cash", kind="cash")
        for i in range(30):
            Transaction.objects.create(date=date(2026, 9, 1), amount=1, kind="lend", party=om, account=acct, status="pending")
            Party.objects.create(name=f"p{i}")
            Recurring.objects.create(name=f"r{i}", amount=1, next_due=date(2026, 10, 1))
        for url in ("/inbox/", f"/people/{om.pk}/", "/people/?all=1", "/recurring/", f"/accounts/{acct.pk}/"):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), 'rel="next"')


class CelebrationTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("u", password="x"))

    def test_new_row_flashes_once_and_toast_celebrates(self):
        from django.utils import timezone
        today = timezone.localdate()
        r = self.client.post("/", {"date": today.isoformat(), "amount": "50", "kind": "expense", "status": "confirmed",
                                   "description": "Chai"}, follow=True)
        t = Transaction.objects.get()
        self.assertContains(r, "data-celebrate")
        self.assertContains(r, "animate-flash")
        self.assertIn(t.pk, r.context["flash_t"])
        self.assertNotContains(self.client.get("/"), "animate-flash")  # only once

    def test_first_log_of_the_day_mentions_the_streak(self):
        from datetime import timedelta
        from django.utils import timezone
        today = timezone.localdate()
        for d in (1, 2):
            Transaction.objects.create(date=today - timedelta(days=d), amount=5)
        r = self.client.post("/", {"date": today.isoformat(), "amount": "50", "kind": "expense", "status": "confirmed"}, follow=True)
        self.assertContains(r, "3-day streak!")
        r = self.client.post("/", {"date": today.isoformat(), "amount": "20", "kind": "expense", "status": "confirmed"}, follow=True)
        self.assertNotContains(r, "day streak!")  # only the day's first log gets the shout-out

    def test_add_just_this_triggers_coin_burst(self):
        row = {"r0-date": "2026-09-01", "r0-amount": "10", "r0-kind": "expense", "r0-description": "x", "r0-quote": "q"}
        self.assertEqual(self.client.post("/ramble/add/0/", row)["HX-Trigger"], "celebrate")


class TransferAndChartTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("u", password="x"))

    def test_monthly_transfer_to_father_is_not_spending(self):
        from .models import Recurring
        sav = Account.objects.create(name="HDFC", kind="savings", opening_balance=50000, is_default=True)
        self.client.post("/recurring/", {"name": "Papa", "amount": "10000", "kind": "transfer", "every": "1", "unit": "month",
                                         "next_due": "2026-10-01", "remind_days_before": "0", "active": "on"})
        papa = Recurring.objects.get(name="Papa")
        Recurring.objects.create(name="Rent", amount=9000, next_due=date(2026, 10, 5))
        r = self.client.get("/recurring/")
        self.assertEqual((r.context["money_out"], r.context["transfers"]), (Decimal("9000"), Decimal("10000")))
        self.assertContains(r, ">Sent<")
        self.client.post(f"/recurring/{papa.pk}/done/", {"action": "paid"})
        t = Transaction.objects.get(description="Papa")
        self.assertEqual((t.kind, t.account), ("transfer", sav))
        self.assertEqual(sav.balance, Decimal("40000"))  # money left the account...
        month = f"{t.date:%Y-%m}"
        self.assertEqual(self.client.get(f"/?view=month&month={month}").context["spent"], 0)  # ...but isn't spending

    def test_charts_render_and_can_be_hidden(self):
        from .models import Party
        om = Party.objects.create(name="Priya")
        Transaction.objects.create(date=date(2026, 9, 3), amount=1000, kind="lend", party=om)
        Transaction.objects.create(date=date(2026, 9, 9), amount=400, kind="repay_in", party=om)
        Transaction.objects.create(date=date(2026, 9, 5), amount=250, description="Chai")
        Transaction.objects.create(date=date(2026, 9, 6), amount=3000, kind="income", description="Stipend")
        home = self.client.get("/?view=month&month=2026-09")
        self.assertContains(home, "Spent vs came in")
        self.assertContains(home, "This month you kept ₹2,750.00")
        people = self.client.get("/people/")
        self.assertContains(people, "Money you've lent")
        self.assertEqual((people.context["lending"]["repaid"], people.context["lending"]["out"]), (Decimal("400"), Decimal("600")))
        self.assertContains(people, "Who owes the most")
        self.assertContains(self.client.get(f"/people/{om.pk}/"), "Balance over time")
        for r in (home, people):
            self.assertContains(r, "data-chart")
        self.assertContains(self.client.get("/settings/"), 'id="charts-toggle"')

    def test_stat_tiles_cannot_overflow(self):
        for url in ("/people/", "/accounts/", "/recurring/"):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), 'class="stats"')


class SearchTests(TestCase):
    def setUp(self):
        from .models import Party, Recurring, Tag
        self.client.force_login(User.objects.create_user("u", password="x"))
        self.hdfc = Account.objects.create(name="HDFC Savings", kind="savings", last4="1234")
        self.rohan = Party.objects.create(name="Rohan")
        t = Transaction.objects.create(date=date(2026, 9, 29), amount=450, description="Petrol pump", account=self.hdfc,
                                       category=Category.objects.get(name="Fuel & Transport"))
        t.tags.add(Tag.objects.create(name="GOA"))
        Transaction.objects.create(date=date(2026, 9, 28), amount=200, description="Chai", party=self.rohan, kind="lend")
        Transaction.objects.create(date=date(2026, 9, 27), amount=99, description="Hidden", status="ignored")
        Recurring.objects.create(name="Rohan gym share", amount=500, next_due=date(2026, 10, 5))

    def results(self, q):
        r = self.client.get("/search/", {"q": q})
        self.assertEqual(r.status_code, 200)
        return r, [t.description for t in (r.context.get("txns") or [])]

    def test_finds_every_kind_of_thing(self):
        r, txns = self.results("rohan")
        self.assertEqual(txns, ["Chai"])  # via the person
        self.assertEqual([p.name for p in r.context["parties"]], ["Rohan"])
        self.assertEqual([x.name for x in r.context["recurring"]], ["Rohan gym share"])
        self.assertEqual(r.context["total"], 3)
        self.assertEqual(self.results("goa")[1], ["Petrol pump"])       # tag
        self.assertEqual(self.results("fuel")[1], ["Petrol pump"])       # category
        self.assertEqual(self.results("₹450")[1], ["Petrol pump"])       # exact amount
        self.assertEqual([a.name for a in self.results("1234")[0].context["accounts"]], ["HDFC Savings"])  # last 4
        self.assertEqual(self.results("hidden")[1], [])                  # ignored stays hidden

    def test_highlight_escapes_user_text(self):
        from .templatetags.ui import highlight
        self.assertEqual(highlight("<b>Chai</b> & samosa", "chai"),
                         '&lt;b&gt;<mark class="rounded bg-gold-soft px-0.5 text-ink">Chai</mark>&lt;/b&gt; &amp; samosa')
        self.assertContains(self.client.get("/search/", {"q": "petrol"}), "<mark")

    def test_empty_and_no_match_states_and_live_typing(self):
        self.assertContains(self.client.get("/search/"), "Find anything")
        self.assertContains(self.client.get("/search/", {"q": "zzz"}), "Nothing matches")
        r = self.client.get("/search/", {"q": "chai"}, headers={"HX-Request": "true"})
        self.assertContains(r, 'id="results"')
        self.assertContains(self.client.get("/"), 'id="search-link"')


class AssetVersionTests(TestCase):
    """Stale-CSS guard: CSS/JS URLs carry a fingerprint so the service worker's cache can't serve an old build."""

    def test_css_and_js_are_fingerprinted_on_every_page(self):
        import re
        login = self.client.get("/login/").content.decode()
        v = re.search(r'app\.css\?v=([0-9a-f]{10})"', login).group(1)
        self.assertIn(f"htmx.min.js?v={v}", login)
        self.client.force_login(User.objects.create_user("u", password="x"))
        self.assertContains(self.client.get("/"), f"app.css?v={v}")


class NavTests(TestCase):
    def test_recurring_is_a_tab_and_more_has_about(self):
        self.client.force_login(User.objects.create_user("u", password="x"))
        header = self.client.get("/").content.decode().split("<main", 1)[0]
        self.assertIn('href="/recurring/"', header)
        self.assertNotIn('href="/accounts/"', header)
        more = self.client.get("/settings/")
        links = [url for url, label, hint in more.context["links"]]
        self.assertNotIn("/recurring/", links)
        self.assertIn("/accounts/", links)
        self.assertContains(more, 'href="https://github.com/4-bit-soft/paisa-peek"')
        self.assertContains(more, "Abhishek Maurya")
        active = [label for name, label, act, icon in self.client.get("/recurring/").context["tabs"] if "recurring" in act]
        self.assertEqual([str(a) for a in active], ["Recurring"])
        active = [label for name, label, act, icon in self.client.get("/accounts/").context["tabs"] if "accounts" in act]
        self.assertEqual([str(a) for a in active], ["More"])  # More stays highlighted on Recurring pages
