import json
from datetime import date, timedelta
from decimal import Decimal
from itertools import groupby

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_tx
from django.db.models import Case, Count, DecimalField, F, Max, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.contrib.staticfiles import finders
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import backup, csv_import, llm, push, ramble as ramble_parser
from .forms import now_hm, AccountForm, NotifyForm, PartyForm, PartyTxnForm, RambleForm, RecurringForm, TxnForm
from .models import Account, ApiToken, Category, NotifySettings, Party, PushSubscription, Recurring, Transaction


def pending_count(request):
    if not request.user.is_authenticated:
        return {}
    return {
        "pending_count": Transaction.objects.filter(status="pending").count(),
        "party_names": Party.objects.values_list("name", flat=True),  # <datalist> for the person/company field
        "tabs": TABS,
    }


# (url name, label, url names that highlight it, SVG icon). Recurring lives under "More" on phones.
TABS = [
    ("home", "Home", {"home", "txn_edit"}, '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>'),
    ("people", "People", {"people", "party"},
     '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.3a5 5 0 0 1 5.5 4.7"/>'),
    ("accounts", "Accounts", {"accounts", "account_edit", "account_new"},
     '<rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="M2.5 9.5h19M6 15h4"/>'),
    ("recurring", "Recurring", {"recurring", "recurring_edit"}, ""),
    ("inbox", "Inbox", {"inbox"}, '<path d="M3 13l2.5-8h13L21 13v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M3 13h5l1.5 2.5h5L16 13h5"/>'),
    ("settings", "More", {"settings", "import_csv", "recurring", "recurring_edit"},
     '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>'),
]


def _period(request):
    """Week or month to show; the choice sticks (session) so the toggle is remembered."""
    view = request.GET.get("view") or request.session.get("view", "month")
    view = view if view in ("week", "month") else "month"
    request.session["view"] = view
    today = timezone.localdate()
    if view == "week":
        try:
            anchor = date.fromisoformat(request.GET.get("start", ""))
        except ValueError:
            anchor = today
        start = anchor - timedelta(days=anchor.weekday())  # Monday
        end = start + timedelta(days=6)
        return {
            "view": view, "start": start, "end": end, "current": start <= today <= end,
            "label": f"{start:%d %b} – {end:%d %b %Y}" if start.year == end.year else f"{start:%d %b %Y} – {end:%d %b %Y}",
            "prev": f"?view=week&start={start - timedelta(days=7)}", "next": f"?view=week&start={end + timedelta(days=1)}",
            "week_link": f"?view=week&start={start}", "month_link": f"?view=month&month={start:%Y-%m}",
        }
    try:
        y, m = map(int, request.GET.get("month", "").split("-"))
        start = date(y, m, 1)
    except ValueError:
        start = today.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return {
        "view": view, "start": start, "end": end, "current": start <= today <= end, "label": f"{start:%B %Y}",
        "prev": f"?view=month&month={start - timedelta(days=1):%Y-%m}", "next": f"?view=month&month={end + timedelta(days=1):%Y-%m}",
        "week_link": f"?view=week&start={today if start <= today <= end else start}", "month_link": f"?view=month&month={start:%Y-%m}",
    }


def _home_for(request, d: date) -> str:
    """Home URL showing the period (in the remembered view) that contains date d."""
    if request.session.get("view") == "week":
        return f"{reverse('home')}?view=week&start={d}"
    return f"{reverse('home')}?view=month&month={d:%Y-%m}"


# A different line each day. Human, a little cheeky, never preachy.
QUIPS = [
    "Chamdi jaaye, par damdi na jaaye.",
    "Chai counts. So does the samosa.",
    "Future you says thanks for writing this down.",
    "Every rupee has a story. What's today's?",
    "Paisa ped pe nahi ugta — but it does grow when you watch it.",
    "UPI made spending effortless. We're making remembering effortless.",
    "No judgement here. Just numbers.",
    "Small change, big picture.",
    "A 10-second log a day keeps the month-end panic away.",
    "Who spent all the money? Let's find out (it was Swiggy).",
]


def _streak(today) -> tuple[int, bool]:
    """(consecutive days with something logged, whether today is one of them)."""
    days = set(Transaction.objects.filter(date__gte=today - timedelta(days=366)).exclude(status="ignored")
               .values_list("date", flat=True).distinct())
    d, n = (today if today in days else today - timedelta(days=1)), 0
    while d in days:
        n, d = n + 1, d - timedelta(days=1)
    return n, today in days


def _hello(user) -> str:
    h = timezone.localtime().hour
    part = ("Up late" if h < 5 else "Good morning" if h < 12 else "Good afternoon" if h < 17
            else "Good evening" if h < 22 else "Up late")
    name = (user.first_name or user.get_username()).split()[0].title()
    return f"{part}, {name}"


@login_required
def home(request):
    period = _period(request)
    form = TxnForm(request.POST or None, initial={"kind": "expense", "status": "confirmed"})
    if request.method == "POST" and form.is_valid():
        t = form.save()
        messages.success(request, ["Noted ✍️", "Logged. Every damdi accounted for.", "Got it — future you approves."][t.pk % 3])
        return redirect(_home_for(request, t.date))

    qs = (Transaction.objects.filter(date__range=(period["start"], period["end"])).exclude(status="ignored")
          .select_related("category", "account", "party").prefetch_related("tags"))
    confirmed = qs.filter(status="confirmed")
    by_cat = confirmed.filter(kind="expense").values("category__name").annotate(total=Sum("amount")).order_by("-total")
    today = timezone.localdate()
    elapsed = ((min(today, period["end"]) - period["start"]).days + 1) if period["start"] <= today else 0
    days = []  # [(date, [txns], spent that day)] newest first, like a bank app
    for day, items in groupby(qs, key=lambda t: t.date):
        items = list(items)
        days.append((day, items, sum(t.amount for t in items if t.kind == "expense" and t.status == "confirmed")))
    return render(request, "ledger/home.html", {
        "p": period, "form": form, "days": days, "by_cat": by_cat, "llm_on": llm.enabled(),
        "spent": (spent := confirmed.filter(kind="expense").aggregate(s=Sum("amount"))["s"] or 0),
        "income": confirmed.filter(kind="income").aggregate(s=Sum("amount"))["s"] or 0,
        "per_day": spent / elapsed if elapsed else 0,
        "focus_log": request.GET.get("log") == "1",
        # Brand-new install: offer restore / first account instead of an empty list.
        "onboarding": not Transaction.objects.exists() and not Account.objects.exists(),
        "hello": _hello(request.user), "quip": QUIPS[timezone.localdate().toordinal() % len(QUIPS)],
        "today": timezone.localdate(), "yesterday": timezone.localdate() - timedelta(days=1),
        "streak": _streak(timezone.localdate()),
    })


@login_required
def txn_edit(request, pk):
    t = get_object_or_404(Transaction, pk=pk)
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = _home_for(request, t.date)
    form = TxnForm(request.POST or None, instance=t)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(nxt)
    return render(request, "ledger/txn_edit.html", {"t": t, "form": form, "next": nxt})


@login_required
@require_POST
def txn_delete(request, pk):
    get_object_or_404(Transaction, pk=pk).delete()
    return redirect("home")


@login_required
def inbox(request):
    return render(request, "ledger/inbox.html", {
        "txns": Transaction.objects.filter(status="pending").select_related("account", "category"),
        "categories": Category.objects.all(),
    })


@login_required
@require_POST
def txn_status(request, pk):
    """Inbox one-click confirm/ignore. HTMX swaps the card out with the empty response."""
    t = get_object_or_404(Transaction, pk=pk)
    status = request.POST.get("status")
    if status not in dict(Transaction.STATUSES):
        return HttpResponseBadRequest("invalid status")
    if status == "confirmed" and t.amount <= 0:
        return HttpResponseBadRequest("Set an amount before confirming.")
    if cat := request.POST.get("category"):
        t.category = get_object_or_404(Category, pk=cat)
    t.status = status
    t.save(update_fields=["status", "category"])
    if request.headers.get("HX-Request"):
        # Empty body removes the card; the out-of-band badge refreshes the nav count.
        return render(request, "ledger/_badge.html", {"oob": True})
    return redirect("inbox")


@login_required
def settings_page(request):
    """The "More" tab: notifications, SMS token, links to everything else."""
    notify = NotifyForm(request.POST if request.POST.get("action") == "notify" else None, instance=NotifySettings.get())
    if request.method == "POST":
        if request.POST.get("action") == "token":
            ApiToken.objects.all().delete()
            return redirect("settings")
        if notify.is_valid():
            notify.save()
            messages.success(request, "Notification settings saved.")
            return redirect("settings")
    return render(request, "ledger/settings.html", {
        "token": ApiToken.current(), "base": request.build_absolute_uri("/")[:-1], "notify": notify,
        "vapid_key": push.public_key(), "devices": PushSubscription.objects.count(),
        "links": [
            (reverse("recurring"), "Recurring income & bills", "Salary, stipends, subscriptions: reminders + one tap"),
            (reverse("import_csv"), "Import CSV", "Bring in history from a spreadsheet"),
            (reverse("admin:index"), "Admin", "Categories, tags, SMS templates, everything"),
        ],
    })


@login_required
@require_POST
def push_subscribe(request):
    try:
        sub = json.loads(request.body)
        endpoint, keys = sub["endpoint"], sub["keys"]
        if not endpoint.startswith("https://"):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return HttpResponseBadRequest("bad subscription")
    PushSubscription.objects.update_or_create(endpoint=endpoint[:500], defaults={
        "p256dh": keys["p256dh"][:200], "auth": keys["auth"][:100],
        "user_agent": request.headers.get("User-Agent", "")[:300]})
    return JsonResponse({"devices": PushSubscription.objects.count()})


@login_required
@require_POST
def push_test(request):
    n = push.send("Damdi says hi 👋", "Notifications work. We'll nudge you, not nag you.", "/")
    return JsonResponse({"sent": n})


def service_worker(request):
    """Served from / (not /static/) so the worker controls the whole app."""
    with open(finders.find("ledger/sw.js"), "rb") as f:
        resp = HttpResponse(f.read(), content_type="application/javascript")
    resp["Cache-Control"] = "no-cache"
    return resp


# ---------- backup & restore ----------

@login_required
def backup_export(request):
    resp = HttpResponse(json.dumps(backup.export(), ensure_ascii=False, indent=1), content_type="application/json")
    resp["Content-Disposition"] = f'attachment; filename="damdi-backup-{timezone.localdate()}.json"'
    return resp


@login_required
def backup_export_csv(request):
    resp = HttpResponse(backup.export_csv(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="damdi-transactions-{timezone.localdate()}.csv"'
    return resp


@login_required
@require_POST
def backup_restore(request):
    back = request.POST.get("next") if request.POST.get("next") == "/" else reverse("settings") + "#backup"
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Choose a backup file.")
    elif request.POST.get("confirm") != "on" and any(m.objects.exists() for m in (Transaction, Account, Party, Recurring)):
        messages.error(request, "Tick “replace my current data” to restore over existing data.")
    else:
        try:
            counts = backup.restore(upload.read())
        except backup.RestoreError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Restored: " + ", ".join(f"{n} {m}" for m, n in counts.items()) + ".")
            return redirect("home")
    return redirect(back)


# ---------- accounts ----------

@login_required
def accounts(request):
    accts = list(Account.objects.all())
    for a in accts:
        a.bal = a.balance
    assets = sum(a.bal for a in accts if not a.is_credit)
    dues = -sum(a.bal for a in accts if a.is_credit)
    return render(request, "ledger/accounts.html", {"accounts": accts, "assets": assets, "dues": dues, "net": assets - dues})


@login_required
def account_edit(request, pk=None):
    a = get_object_or_404(Account, pk=pk) if pk else None
    if request.POST.get("action") == "delete" and a:
        if a.transaction_set.exists() or a.transfers_in.exists():
            messages.error(request, "This account has transactions, so it can't be deleted.")
            return redirect("account_edit", pk=a.pk)
        a.delete()
        return redirect("accounts")
    form = AccountForm(request.POST or None, instance=a)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Account saved.")
        return redirect("accounts")
    recent = (Transaction.objects.filter(Q(account=a) | Q(to_account=a)).exclude(status="ignored")
              .select_related("category", "party")[:30] if a else [])
    return render(request, "ledger/account_edit.html", {"a": a, "form": form, "recent": recent,
                                                        "credit_kinds": json.dumps(sorted(Account.CREDIT_KINDS))})


# ---------- recurring bills & subscriptions ----------

@login_required
def recurring(request):
    form = RecurringForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("recurring")
    items = list(Recurring.objects.select_related("category", "account"))
    active = [r for r in items if r.active]
    money_in = sum(r.monthly_cost for r in active if r.is_income)
    money_out = sum(r.monthly_cost for r in active if not r.is_income)
    return render(request, "ledger/recurring.html", {
        "items": items, "form": form, "today": timezone.localdate(),
        "money_in": money_in, "money_out": money_out, "net": money_in - money_out,
        "minimum": sum(r.monthly_cost for r in active if not r.is_income and r.essential),
    })


@login_required
def recurring_edit(request, pk):
    r = get_object_or_404(Recurring, pk=pk)
    if request.POST.get("action") == "delete":
        r.delete()
        return redirect("recurring")
    form = RecurringForm(request.POST or None, instance=r)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("recurring")
    return render(request, "ledger/recurring_edit.html", {"r": r, "form": form})


@login_required
@require_POST
def recurring_done(request, pk):
    """Paid/received: log the transaction and move to the next due date. Skip: just move on."""
    r = get_object_or_404(Recurring, pk=pk)
    if request.POST.get("action") == "paid":
        Transaction.objects.create(
            date=timezone.localdate(), time=now_hm(), amount=r.amount, kind=r.kind, description=r.name, category=r.category,
            account=r.account or Account.default(), source="recurring", status="confirmed")
        done = "received" if r.is_income else "paid"
        messages.success(request, f"Logged {r.name} as {done}; next on {r.following_due():%d %b}.")
    r.next_due = r.following_due()
    r.save(update_fields=["next_due"])
    return redirect("recurring")


# ---------- ramble: say/type several transactions, review, add ----------

def _dup(f):
    return ramble_parser.possible_duplicate(f["amount"].value(), f["date"].value(), f["party_name"].value() or "")


def _with_dup_hints(forms_):
    for f in forms_:
        f.dup = _dup(f)
    return forms_


def _review_forms(request):
    source = "import" if request.POST.get("source") == "import" else "ramble"
    forms_ = [RambleForm(request.POST, prefix=f"r{i}") for i in request.POST.getlist("row") if i.isdigit()]
    for f in forms_:
        f.source = source
    return forms_, source


@login_required
@require_POST
def ramble_parse(request):
    text = request.POST.get("text", "").strip()[:5000]
    rows, parser = ramble_parser.parse(text) if text else ([], "")
    forms_ = []
    for i, row in enumerate(rows):
        f = RambleForm(prefix=f"r{i}", initial=row)
        f.dup = ramble_parser.possible_duplicate(row["amount"], row["date"], row["party_name"])
        if f.dup:  # already logged (e.g. arrived by SMS): default to not adding it again
            f.initial["include"] = False
        forms_.append(f)
    return render(request, "ledger/_ramble_review.html", {"forms": forms_, "parser": parser, "text": text})


@login_required
@require_POST
def ramble_save(request):
    """Add every ticked row, all or nothing. Shared by Ramble and CSV import."""
    forms_, source = _review_forms(request)
    ctx = {"forms": forms_, "source": source}
    chosen = [f for f in forms_ if f["include"].value()]
    if not chosen:
        return render(request, "ledger/_ramble_review.html", {**_ctx_hints(ctx), "error": "Tick at least one row to add."})
    if all([f.is_valid() for f in chosen]):  # list, not generator: validate every row so all errors show
        with db_tx.atomic():
            saved = [f.save() for f in chosen]
        messages.success(request, f"Added {len(saved)} transaction{'s' if len(saved) != 1 else ''} — nicely done 🪙")
        resp = HttpResponse()
        if any(t.kind in Transaction.LOAN_KINDS for t in saved):
            resp["HX-Redirect"] = reverse("people")
        else:
            resp["HX-Redirect"] = _home_for(request, max(t.date for t in saved))
        return resp
    return render(request, "ledger/_ramble_review.html", {**_ctx_hints(ctx), "error": "Fix the highlighted rows."})


def _ctx_hints(ctx):
    _with_dup_hints(ctx["forms"])
    return ctx


@login_required
@require_POST
def ramble_add_one(request, i):
    f = RambleForm(request.POST, prefix=f"r{i}")
    f.source = "import" if request.POST.get("source") == "import" else "ramble"
    if f.is_valid():
        return render(request, "ledger/_ramble_added.html", {"t": f.save()})
    f.dup = _dup(f)
    return render(request, "ledger/_ramble_row.html", {"f": f, "i": i})


# ---------- CSV import ----------

@login_required
def import_csv(request):
    ctx = {"default_date": timezone.localdate()}
    if request.method == "POST":
        try:
            ctx["default_date"] = date.fromisoformat(request.POST.get("default_date", ""))
        except ValueError:
            pass
        upload = request.FILES.get("file")
        if not upload:
            ctx["error"] = "Choose a CSV file."
        elif upload.size > 2 * 1024 * 1024:
            ctx["error"] = "File is over 2 MB; split it up."
        else:
            try:
                forms_ = csv_import.to_forms(csv_import.read_rows(upload), ctx["default_date"])
            except csv_import.CSVError as e:
                ctx["error"] = str(e)
            else:
                ctx.update(forms=forms_, source="import", parser=upload.name,
                           n_dup=sum(1 for f in forms_ if f.dup), n_bad=sum(1 for f in forms_ if f.errors))
    return render(request, "ledger/import.html", ctx)


# ---------- people & companies: who owes whom ----------

def _parties():
    """Parties annotated with balance (+ they owe me, − I owe them), last activity and entry count."""
    ok = Q(transactions__status="confirmed")
    dec = DecimalField(max_digits=14, decimal_places=2)
    return Party.objects.annotate(
        balance=Coalesce(Sum(Case(
            When(ok & Q(transactions__kind__in=Transaction.OWED_UP), then=F("transactions__amount")),
            When(ok & Q(transactions__kind__in=Transaction.OWED_DOWN), then=-F("transactions__amount")),
            output_field=dec,
        )), Value(Decimal(0)), output_field=dec),
        last_date=Max("transactions__date", filter=~Q(transactions__status="ignored")),
        entries=Count("transactions", filter=~Q(transactions__status="ignored")),
    )


@login_required
def people(request):
    form = PartyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        return redirect("party", pk=form.save().pk)
    parties = sorted(_parties(), key=lambda p: (-abs(p.balance), p.name.lower()))
    show_all = request.GET.get("all") == "1"
    return render(request, "ledger/people.html", {
        "form": form, "show_all": show_all,
        "parties": parties if show_all else [p for p in parties if p.balance or not p.entries],
        "settled": sum(1 for p in parties if not p.balance and p.entries),
        "owed_to_me": sum(p.balance for p in parties if p.balance > 0),
        "i_owe": -sum(p.balance for p in parties if p.balance < 0),
    })


@login_required
def party(request, pk):
    p = get_object_or_404(_parties(), pk=pk)
    action = request.POST.get("action")
    entry = PartyTxnForm(request.POST if action == "entry" else None, party=p,
                         initial={"kind": "lend", "status": "confirmed"})
    edit = PartyForm(request.POST if action == "edit" else None, instance=p)
    if action == "entry" and entry.is_valid():
        entry.save()
        return redirect("party", pk=pk)
    if action == "edit" and edit.is_valid():
        edit.save()
        return redirect("party", pk=pk)
    if action == "delete":
        if p.entries or p.transactions.exists():
            messages.error(request, "Has transactions; reassign or delete those first.")
            return redirect("party", pk=pk)
        p.delete()
        return redirect("people")

    # Ledger oldest-first with a running balance, like the spreadsheet breakdowns.
    rows, running = [], Decimal(0)
    for t in p.transactions.exclude(status="ignored").select_related("account", "category").prefetch_related("tags").order_by("date", "id"):
        if t.status == "confirmed":
            running += t.owed_delta
        rows.append((t, running))
    totals = {k: sum(t.amount for t, _ in rows if t.kind == k and t.status == "confirmed") for k in Transaction.LOAN_KINDS}
    return render(request, "ledger/party.html", {"p": p, "rows": rows, "totals": totals, "entry": entry, "edit": edit})
