import base64
import binascii
import json
import tomllib
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from itertools import groupby

from django.conf import settings
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
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, gettext_lazy, ngettext
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import backup, charts, csv_import, llm, ocr, push, ramble as ramble_parser
from .ingest import Skipped, ingest
from .paging import paginate
from .forms import now_hm, party_named, review, AccountForm, NotifyForm, PartyForm, PartyTxnForm, RambleForm, RecurringForm, TxnForm
from .models import Account, ApiToken, Category, NotifySettings, Party, PushSubscription, Recurring, Rule, Transaction, clamp_day


def asset_version() -> str:
    """Fingerprint of the CSS/JS files, appended as ?v= so a rebuilt stylesheet gets a new URL.
    The service worker caches /static/ cache-first; without this, phones keep a stale app.css forever."""
    import hashlib
    import os

    from django.contrib.staticfiles import finders

    stamp = "|".join(f"{os.stat(p).st_mtime_ns}-{os.stat(p).st_size}"
                     for p in filter(None, (finders.find(n) for n in ("ledger/app.css", "ledger/htmx.min.js"))))
    return hashlib.sha1(stamp.encode()).hexdigest()[:10]


def pending_count(request):
    if not request.user.is_authenticated:
        return {"asset_v": asset_version()}
    return {
        "pending_count": Transaction.objects.filter(status="pending").count(),
        "party_names": Party.objects.values_list("name", flat=True),  # <datalist> for the person/company field
        "tabs": TABS,
        "asset_v": asset_version(),
        # Rows added on the previous request flash once so your eye finds them (see _celebrate).
        "flash_t": request.session.pop("flash_t", []), "flash_r": request.session.pop("flash_r", []),
    }


def _celebrate(request, message, txns=(), recurring=()):
    """Success toast with a coin burst; new rows flash on the next page; a streak shout-out on the day's first log."""
    request.session["flash_t"] = [t.pk for t in txns]
    request.session["flash_r"] = [r.pk for r in recurring]
    today = timezone.localdate()
    if any(t.date == today for t in txns):
        earlier = Transaction.objects.filter(date=today).exclude(pk__in=[t.pk for t in txns]).exclude(status="ignored")
        n, _logged = _streak(today)
        if not earlier.exists() and n >= 2:
            message = f"{message} " + _("🔥 %(n)d-day streak!") % {"n": n}
    messages.success(request, message, extra_tags="celebrate")


# (url name, label, url names that highlight it, SVG icon). Accounts, Import and Search live under "More"/the header.
VERSION = tomllib.loads((settings.BASE_DIR / "pyproject.toml").read_text())["project"]["version"]

TABS = [
    ("home", gettext_lazy("Home"), {"home", "txn_edit"}, '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>'),
    ("people", gettext_lazy("People"), {"people", "party"},
     '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.3a5 5 0 0 1 5.5 4.7"/>'),
    ("recurring", gettext_lazy("Recurring"), {"recurring", "recurring_edit"},
     '<rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4M9 15l2 2 4-4"/>'),
    ("inbox", gettext_lazy("Inbox"), {"inbox"}, '<path d="M3 13l2.5-8h13L21 13v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M3 13h5l1.5 2.5h5L16 13h5"/>'),
    ("settings", gettext_lazy("More"), {"settings", "import_csv", "accounts", "account_edit", "account_new"},
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
            "label": (f"{date_format(start, 'j M')} – {date_format(end, 'j M Y')}" if start.year == end.year
                      else f"{date_format(start, 'j M Y')} – {date_format(end, 'j M Y')}"),
            "prev": f"?view=week&start={start - timedelta(days=7)}", "next": f"?view=week&start={end + timedelta(days=1)}",
            "week_link": f"?view=week&start={start}", "month_link": f"?view=month&month={anchor:%Y-%m}",  # anchor, not Monday: Monday may be last month
        }
    try:
        y, m = map(int, request.GET.get("month", "").split("-"))
        start = date(y, m, 1)
    except ValueError:
        start = today.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return {
        "view": view, "start": start, "end": end, "current": start <= today <= end, "label": date_format(start, "F Y"),
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
    gettext_lazy("Chai counts. So does the samosa."),
    gettext_lazy("Future you says thanks for writing this down."),
    gettext_lazy("Every rupee has a story. What's today's?"),
    gettext_lazy("Paisa ped pe nahi ugta — but it does grow when you watch it."),
    gettext_lazy("UPI made spending effortless. We're making remembering effortless."),
    gettext_lazy("No judgement here. Just numbers."),
    gettext_lazy("Small change, big picture."),
    gettext_lazy("A 10-second log a day keeps the month-end panic away."),
    gettext_lazy("Who spent all the money? Let's find out (it was Swiggy)."),
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
    name = (user.first_name or user.get_username()).split()[0].title()
    if 5 <= h < 12:
        return _("Good morning, %(name)s") % {"name": name}
    if 12 <= h < 17:
        return _("Good afternoon, %(name)s") % {"name": name}
    if 17 <= h < 22:
        return _("Good evening, %(name)s") % {"name": name}
    return _("Up late, %(name)s") % {"name": name}


@login_required
def home(request):
    period = _period(request)
    form = TxnForm(request.POST or None, initial={"kind": "expense", "status": "confirmed"})
    if request.method == "POST" and form.is_valid():
        t = form.save()
        _celebrate(request, [_("Noted ✍️"), _("Logged. Every paisa accounted for."), _("Got it — future you approves.")][t.pk % 3], [t])
        return redirect(_home_for(request, t.date))

    qs = (Transaction.objects.filter(date__range=(period["start"], period["end"])).exclude(status="ignored")
          .select_related("category", "account", "party").prefetch_related("tags"))
    confirmed = qs.filter(status="confirmed")
    by_cat = confirmed.filter(kind="expense").values("category__name").annotate(total=Sum("amount")).order_by("-total")
    today = timezone.localdate()
    elapsed = ((min(today, period["end"]) - period["start"]).days + 1) if period["start"] <= today else 0
    # Paginated, then grouped by day; day totals come from the whole day even if it spans two pages.
    page = paginate(request, qs, per_page=30)
    day_totals = dict(confirmed.filter(kind="expense").order_by().values("date").annotate(s=Sum("amount"))
                      .values_list("date", "s"))
    days = [(day, list(items), day_totals.get(day, 0)) for day, items in groupby(page, key=lambda t: t.date)]
    return render(request, "ledger/home.html", {
        "p": period, "form": form, "days": days, "page": page, "by_cat": by_cat, "llm_on": llm.enabled(),
        "spent": (spent := confirmed.filter(kind="expense").aggregate(s=Sum("amount"))["s"] or 0),
        "income": confirmed.filter(kind="income").aggregate(s=Sum("amount"))["s"] or 0,
        "per_day": spent / elapsed if elapsed else 0,
        "focus_log": request.GET.get("log") == "1",
        "daily": charts.daily_spend(qs, period["start"], period["end"], today, period["view"]),
        "months": charts.months_in_out(period["start"].replace(day=1)) if period["view"] == "month" else None,
        "cat_rows": charts.category_shares(by_cat, spent, dict(
            Category.objects.filter(budget__gt=0).values_list("name", "budget")) if period["view"] == "month" else {}),
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
        t = form.save()
        if request.POST.get("remember") and t.category and (key := (t.merchant or t.description).strip()[:100]):
            Rule.objects.update_or_create(pattern__iexact=key, defaults={"pattern": key, "category": t.category})
        return redirect(nxt)
    return render(request, "ledger/txn_edit.html", {"t": t, "form": form, "next": nxt,
                                                     "rule_key": t.merchant or t.description})


@csrf_exempt  # the PWA share sheet and the Android app post here without a token; SameSite=Lax keeps it same-site
@login_required
@require_POST
def share(request):
    """A shared or uploaded payment screenshot → OCR → a pending transaction in the Inbox."""
    if f := request.FILES.get("image"):
        data = f.read(10 * 1024 * 1024 + 1)
    else:  # the Android app sends base64 (WebView.postUrl can only post a form body)
        try:
            data = base64.b64decode(request.POST.get("image_b64", ""), validate=True)
        except binascii.Error:
            data = b""
    if not data or len(data) > 10 * 1024 * 1024:
        messages.error(request, _("Share an image under 10 MB."))
        return redirect("inbox")
    try:
        t, dup = ingest(ocr.image_text(data), source="screenshot")
    except ocr.OcrError as e:
        messages.error(request, _("Couldn't read the screenshot: %(error)s") % {"error": e})
    except Skipped:
        messages.error(request, _("No payment found in that screenshot."))
    else:
        if dup:
            messages.info(request, _("Already have this one ✓"))
        else:
            messages.success(request, _("Read it 📸 Check the amount, then confirm."))
    return redirect("inbox")


@login_required
def categories(request):
    """Monthly budgets per category, and "always categorize X as Y" rules."""
    cats = list(Category.objects.all())
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "budgets":
            for c in cats:
                raw = request.POST.get(f"budget-{c.pk}", "").replace(",", "").strip()
                try:
                    c.budget = Decimal(raw).quantize(Decimal("0.01")) if raw else None
                except InvalidOperation:
                    continue
                if c.budget is not None and c.budget <= 0:
                    c.budget = None
            Category.objects.bulk_update(cats, ["budget"])
            messages.success(request, _("Budgets saved."))
        elif action == "rule":
            pattern = " ".join(request.POST.get("pattern", "").split())[:100]
            cat = Category.objects.filter(pk=request.POST.get("category") or 0).first()
            if pattern and cat:
                Rule.objects.update_or_create(pattern__iexact=pattern, defaults={"pattern": pattern, "category": cat})
                # Sort out what's already waiting in the Inbox too.
                n = Transaction.objects.filter(status="pending", kind="expense", category__isnull=True).filter(
                    Q(merchant__icontains=pattern) | Q(description__icontains=pattern) | Q(raw_text__icontains=pattern)
                ).update(category=cat)
                messages.success(request, ngettext("Rule saved. Applied to %(n)d waiting transaction.",
                                                   "Rule saved. Applied to %(n)d waiting transactions.", n) % {"n": n}
                                 if n else _("Rule saved."))
        elif action == "delete_rule":
            Rule.objects.filter(pk=request.POST.get("rule") or 0).delete()
        return redirect("categories")
    return render(request, "ledger/categories.html", {"cats": cats, "rules": Rule.objects.select_related("category")})


@login_required
@require_POST
def txn_delete(request, pk):
    get_object_or_404(Transaction, pk=pk).delete()
    return redirect("home")


@login_required
def inbox(request):
    return render(request, "ledger/inbox.html", {
        "txns": (page := paginate(request, Transaction.objects.filter(status="pending").select_related("account", "category"))),
        "page": page,
        "categories": Category.objects.all(),
        "money_in": [(k, v) for k, v in Transaction.KINDS if k in Transaction.MONEY_IN],
        "money_out": [(k, v) for k, v in Transaction.KINDS if k in Transaction.OUT_KINDS],
        "accounts": Account.objects.all(),
    })


@login_required
@require_POST
def txn_status(request, pk):
    """Inbox one-click confirm/ignore. HTMX swaps the card out with the empty response."""
    t = get_object_or_404(Transaction, pk=pk)
    try:
        review(t, request.POST.get("status"), request.POST.get("category"), request.POST.get("kind"), request.POST.get("party_name", ""),
               request.POST.get("to_account"))
    except ValueError as e:
        return HttpResponseBadRequest(str(e))
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
            messages.success(request, _("Notification settings saved."))
            return redirect("settings")
    return render(request, "ledger/settings.html", {
        "token": ApiToken.current(), "base": request.build_absolute_uri("/")[:-1], "notify": notify,
        "vapid_key": push.public_key(), "devices": PushSubscription.objects.count(),
        "version": VERSION,
        "links": [
            (reverse("accounts"), _("Accounts"), _("Balances, cards, credit lines and the default account")),
            (reverse("categories"), _("Budgets & rules"), _("Monthly budgets per category; always categorize a merchant")),
            (reverse("import_csv"), _("Import CSV"), _("Bring in history from a spreadsheet")),
            (reverse("admin:index"), _("Admin"), _("Categories, tags, SMS templates, everything")),
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
    n = push.send(_("Paisapeek says hi 👋"), _("Notifications work. We'll nudge you, not nag you."), "/")
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
    resp["Content-Disposition"] = f'attachment; filename="paisapeek-backup-{timezone.localdate()}.json"'
    return resp


@login_required
def backup_export_csv(request):
    resp = HttpResponse(backup.export_csv(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="paisapeek-transactions-{timezone.localdate()}.csv"'
    return resp


@login_required
@require_POST
def backup_restore(request):
    back = request.POST.get("next") if request.POST.get("next") == "/" else reverse("settings") + "#backup"
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, _("Choose a backup file."))
    elif request.POST.get("confirm") != "on" and any(m.objects.exists() for m in (Transaction, Account, Party, Recurring)):
        messages.error(request, _("Tick “replace my current data” to restore over existing data."))
    else:
        try:
            counts = backup.restore(upload.read())
        except backup.RestoreError as e:
            messages.error(request, str(e))
        else:
            messages.success(request, _("Restored: %(items)s.") % {"items": ", ".join(f"{n} {m}" for m, n in counts.items())})
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
            messages.error(request, _("This account has transactions, so it can't be deleted."))
            return redirect("account_edit", pk=a.pk)
        a.delete()
        return redirect("accounts")
    form = AccountForm(request.POST or None, instance=a)
    if request.method == "POST" and form.is_valid():
        form.save()
        _celebrate(request, _("Account saved."))
        return redirect("accounts")
    recent = paginate(request, Transaction.objects.filter(Q(account=a) | Q(to_account=a)).exclude(status="ignored")
                      .select_related("category", "party"), per_page=20) if a else []
    return render(request, "ledger/account_edit.html", {"a": a, "form": form, "recent": recent, "page": recent,
                                                        "credit_kinds": json.dumps(sorted(Account.CREDIT_KINDS))})


# ---------- recurring bills & subscriptions ----------

@login_required
def recurring(request):
    form = RecurringForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        r = form.save()
        _celebrate(request, _("%(name)s added 🗓️ — we'll remind you on time.") % {"name": r.name}, recurring=[r])
        return redirect("recurring")
    items = list(Recurring.objects.select_related("category", "account"))
    active = [r for r in items if r.active]
    money_in = sum(r.monthly_cost for r in active if r.is_income)
    money_out = sum(r.monthly_cost for r in active if not r.is_income and not r.is_transfer)
    transfers = sum(r.monthly_cost for r in active if r.is_transfer)
    # "month": what's due by month end (overdue included) vs later; "all": the full paged list. Sticks like home's toggle.
    view = request.GET.get("view") or request.session.get("recurring_view", "month")
    view = request.session["recurring_view"] = view if view in ("month", "all") else "month"
    today = timezone.localdate()
    month_end = clamp_day(today.year, today.month, 31)
    this_month = [r for r in active if r.next_due <= month_end]
    return render(request, "ledger/recurring.html", {
        "items": (page := paginate(request, items)), "page": page, "has_items": bool(items), "form": form,
        "view": view, "this_month": this_month, "later": [r for r in items if r not in this_month],
        "today": today,
        "money_in": money_in, "money_out": money_out, "transfers": transfers, "net": money_in - money_out - transfers,
        "minimum": sum(r.monthly_cost for r in active if not r.is_income and not r.is_transfer and r.essential),
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
        t = Transaction.objects.create(
            date=timezone.localdate(), time=now_hm(), amount=r.amount, kind=r.kind, description=r.name, category=r.category,
            account=r.account or Account.default(), source="recurring", status="confirmed")
        msg = (_("Logged %(name)s as received; next on %(date)s.") if r.is_income
               else _("Logged %(name)s as sent; next on %(date)s.") if r.is_transfer
               else _("Logged %(name)s as paid; next on %(date)s."))
        _celebrate(request, msg % {"name": r.name, "date": date_format(r.following_due(), "j M")}, [t], [r])
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
        return render(request, "ledger/_ramble_review.html", {**_ctx_hints(ctx), "error": _("Tick at least one row to add.")})
    if all([f.is_valid() for f in chosen]):  # list, not generator: validate every row so all errors show
        with db_tx.atomic():
            saved = [f.save() for f in chosen]
        _celebrate(request, ngettext("Added %(n)d transaction — nicely done 🪙", "Added %(n)d transactions — nicely done 🪙",
                                     len(saved)) % {"n": len(saved)}, saved)
        resp = HttpResponse()
        if any(t.kind in Transaction.LOAN_KINDS for t in saved):
            resp["HX-Redirect"] = reverse("people")
        else:
            resp["HX-Redirect"] = _home_for(request, max(t.date for t in saved))
        return resp
    return render(request, "ledger/_ramble_review.html", {**_ctx_hints(ctx), "error": _("Fix the highlighted rows.")})


def _ctx_hints(ctx):
    _with_dup_hints(ctx["forms"])
    return ctx


@login_required
@require_POST
def ramble_add_one(request, i):
    f = RambleForm(request.POST, prefix=f"r{i}")
    f.source = "import" if request.POST.get("source") == "import" else "ramble"
    if f.is_valid():
        resp = render(request, "ledger/_ramble_added.html", {"t": f.save()})
        resp["HX-Trigger"] = "celebrate"  # coin burst on the page, no reload
        return resp
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
            ctx["error"] = _("Choose a CSV file.")
        elif upload.size > 2 * 1024 * 1024:
            ctx["error"] = _("File is over 2 MB; split it up.")
        else:
            try:
                forms_ = csv_import.to_forms(csv_import.read_rows(upload), ctx["default_date"])
            except csv_import.CSVError as e:
                ctx["error"] = str(e)
            else:
                ctx.update(forms=forms_, source="import", parser=upload.name,
                           n_dup=sum(1 for f in forms_ if f.dup), n_bad=sum(1 for f in forms_ if f.errors))
    return render(request, "ledger/import.html", ctx)


# ---------- global search ----------

@login_required
def search(request):
    """One box for everything: transactions, people & companies, recurring items, accounts."""
    q = " ".join(request.GET.get("q", "").split())[:100]
    ctx = {"q": q}
    if q:
        match = (Q(description__icontains=q) | Q(merchant__icontains=q) | Q(notes__icontains=q) | Q(party__name__icontains=q)
                 | Q(tags__name__icontains=q) | Q(category__name__icontains=q) | Q(account__name__icontains=q))
        try:  # "450", "₹1,200", "1200.50" also match the exact amount
            amount = Decimal(q.replace("₹", "").replace(",", "").strip())
            match |= Q(amount=amount)
        except (InvalidOperation, ValueError):
            pass
        txns = (Transaction.objects.exclude(status="ignored").filter(match).distinct()
                .select_related("category", "account", "party").prefetch_related("tags"))
        ctx.update(
            txns=(page := paginate(request, txns, per_page=20)), page=page,
            parties=list(_parties().filter(name__icontains=q)[:10]),
            recurring=list(Recurring.objects.filter(name__icontains=q)[:10]),
            accounts=list(Account.objects.filter(Q(name__icontains=q) | Q(last4=q))[:10]),
        )
        ctx["total"] = page.paginator.count + len(ctx["parties"]) + len(ctx["recurring"]) + len(ctx["accounts"])
    return render(request, "ledger/search.html", ctx)


# ---------- people & companies: who owes whom ----------

def _parties():
    """Parties annotated with balance (+ they owe me, − I owe them), last activity, entry and loan-entry counts."""
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
        loans=Count("transactions", filter=~Q(transactions__status="ignored") & Q(transactions__kind__in=Transaction.LOAN_KINDS)),
    )


@login_required
def people(request):
    form = PartyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        return redirect("party", pk=form.save().pk)
    parties = sorted(_parties(), key=lambda p: (-abs(p.balance), p.name.lower()))
    show_all = request.GET.get("all") == "1"
    # Hide only settled loans; a shop or company you just pay has nothing to settle, so it always shows.
    shown = parties if show_all else [p for p in parties if p.balance or not p.loans]
    sums = dict(Transaction.objects.filter(status="confirmed", kind__in=("lend", "repay_in")).order_by()
                .values("kind").annotate(s=Sum("amount")).values_list("kind", "s"))
    lent, repaid = sums.get("lend", Decimal(0)), sums.get("repay_in", Decimal(0))
    still_out = max(lent - repaid, Decimal(0))
    return render(request, "ledger/people.html", {
        "owed_chart": charts.owed_diverging(parties),
        "lending": {"lent": lent, "repaid": min(repaid, lent), "out": still_out,
                    "repaid_w": charts.pct(min(repaid, lent), lent), "out_w": charts.pct(still_out, lent)},
        "form": form, "show_all": show_all, "parties": (page := paginate(request, shown)), "page": page,
        "settled": sum(1 for p in parties if not p.balance and p.loans),
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
        t = entry.save()
        _celebrate(request, _("Noted in %(name)s's ledger ✍️") % {"name": p.name}, [t])
        return redirect("party", pk=pk)
    if action == "edit" and edit.is_valid():
        edit.save()
        return redirect("party", pk=pk)
    if action == "settle" and (owed := p.balance):
        # Forgiven or squared up off the books: a repayment with no account, so no account balance moves.
        t = Transaction.objects.create(
            date=timezone.localdate(), time=now_hm(), amount=abs(owed), kind="repay_in" if owed > 0 else "repay_out",
            party=p, description=_("Settled, no money changed hands"), source="settle", status="confirmed")
        _celebrate(request, _("%(name)s is all settled 🤝") % {"name": p.name}, [t])
        return redirect("party", pk=pk)
    if action == "delete":
        if p.entries or p.transactions.exists():
            messages.error(request, _("Has transactions; reassign or delete those first."))
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
    page = paginate(request, rows[::-1], per_page=25)  # newest first; running balance already computed over all
    return render(request, "ledger/party.html", {"p": p, "rows": rows, "page": page, "totals": totals,
                                                 "steps": charts.balance_steps(rows),
                                                 "entry": entry, "edit": edit})
