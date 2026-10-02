import calendar
import secrets
from datetime import date, time, timedelta
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Case, F, Sum, Value, When
from django.utils.translation import gettext_lazy as _


class Account(models.Model):
    KINDS = [
        ("savings", _("Savings account")), ("current", _("Current account")), ("credit_card", _("Credit card")),
        ("credit_line", _("Credit line")), ("loan", _("Loan")), ("cash", _("Cash")), ("wallet", _("Wallet")),
    ]
    CREDIT_KINDS = {"credit_card", "credit_line", "loan"}  # balance is what you owe (shown as outstanding)

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=12, choices=KINDS, default="savings")
    last4 = models.CharField(max_length=4, blank=True, db_index=True)
    # Balance = opening_balance + net of all confirmed transactions. "Set current balance" back-solves this.
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    statement_day = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(31)])
    due_day = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(31)])
    is_default = models.BooleanField(default=False, help_text="Pre-selected for new transactions")

    class Meta:
        ordering = ["-is_default", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Picking a new default un-sets the old one (keeps exactly one without a form-blocking DB constraint).
        if self.is_default:
            Account.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
        super().save(*args, **kwargs)

    @classmethod
    def default(cls):
        return cls.objects.filter(is_default=True).first()

    @property
    def is_credit(self):
        return self.kind in self.CREDIT_KINDS

    def net(self) -> Decimal:
        """Sum of confirmed money in (+) and out (−) of this account."""
        ok = Transaction.objects.filter(status="confirmed")
        own = ok.filter(account=self).aggregate(s=Sum(Case(
            When(kind__in=Transaction.MONEY_IN, then=F("amount")),
            When(kind__in=Transaction.MONEY_OUT + ("transfer",), then=-F("amount")),
            default=Value(0), output_field=models.DecimalField(max_digits=14, decimal_places=2),
        )))["s"] or 0
        incoming = ok.filter(kind="transfer", to_account=self).aggregate(s=Sum("amount"))["s"] or 0
        return Decimal(own) + Decimal(incoming)

    @property
    def balance(self) -> Decimal:
        return self.opening_balance + self.net()


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    essential = models.BooleanField(default=False)
    budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Monthly limit")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Rule(models.Model):
    """"Always categorize X as Y": text containing `pattern` (merchant, description or SMS) gets `category`."""

    pattern = models.CharField(max_length=100, unique=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)

    class Meta:
        ordering = ["pattern"]

    def __str__(self):
        return f"{self.pattern} → {self.category}"

    @classmethod
    def match(cls, text: str) -> Category | None:
        """Longest matching pattern wins, so "amazon prime" beats "amazon"."""
        low = text.lower()
        hits = [r for r in cls.objects.select_related("category") if r.pattern.lower() in low]
        return max(hits, key=lambda r: len(r.pattern)).category if hits else None


class Tag(models.Model):
    """Free labels: trips, places, people, e.g. Goa trip, Diwali."""

    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Party(models.Model):
    """A person or company you lend to / borrow from / transact with."""

    KINDS = [("person", _("Person")), ("company", _("Company"))]
    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=10, choices=KINDS, default="person")
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "people & companies"

    def __str__(self):
        return self.name


class Transaction(models.Model):
    KINDS = [
        ("expense", _("Expense")), ("income", _("Income")), ("transfer", _("Transfer")),
        ("lend", _("Lent (they owe me)")), ("borrow", _("Borrowed (I owe them)")),
        ("repay_in", _("Repaid to me")), ("repay_out", _("Repaid by me")),
    ]
    STATUSES = [("pending", _("pending")), ("confirmed", _("confirmed")), ("ignored", _("ignored"))]
    OUTFLOW = {"expense", "lend", "repay_out"}
    # Effect on what a party owes me: lending or repaying my debt raises it; borrowing or being repaid lowers it.
    OWED_UP, OWED_DOWN = ("lend", "repay_out"), ("borrow", "repay_in")
    LOAN_KINDS = OWED_UP + OWED_DOWN
    # Effect on the account's balance (transfers: out of `account`, into `to_account`).
    MONEY_IN, MONEY_OUT = ("income", "repay_in", "borrow"), ("expense", "lend", "repay_out")
    # What a debit SMS can turn out to be, in inbox order (transfer: to your own account, or sent to family/friends).
    OUT_KINDS = ("expense", "transfer", "lend", "repay_out")

    date = models.DateField(db_index=True)
    time = models.TimeField(null=True, blank=True)  # when it happened, if known (blank for old/imported entries)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    kind = models.CharField(max_length=10, choices=KINDS, default="expense")
    description = models.CharField(max_length=200, blank=True)
    merchant = models.CharField(max_length=200, blank=True)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL)
    to_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name="transfers_in",
                                   help_text="Transfers only, e.g. paying a card from savings")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    # PROTECT: deleting someone with history would silently erase who owes what.
    party = models.ForeignKey(Party, null=True, blank=True, on_delete=models.PROTECT, related_name="transactions")
    source = models.CharField(max_length=20, default="manual")  # manual / sms / screenshot / import
    raw_text = models.TextField(blank=True)
    ref = models.CharField(max_length=50, blank=True, db_index=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="confirmed")
    notes = models.CharField(max_length=500, blank=True)
    tags = models.ManyToManyField(Tag, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-time", "-id"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gte=0), name="amount_non_negative")]

    def __str__(self):
        return f"{self.date} {self.amount} {self.description or self.merchant}"

    @property
    def owed_delta(self):
        """Change to what the party owes me (0 for non-loan kinds)."""
        return self.amount if self.kind in self.OWED_UP else -self.amount if self.kind in self.OWED_DOWN else 0

    @property
    def sign(self):
        return "−" if self.kind in self.OUTFLOW else "" if self.kind == "transfer" else "+"


class SmsTemplate(models.Model):
    """Regex with named groups: amount, merchant, last4, date, ref. Tried in id order."""

    bank = models.CharField(max_length=50)
    sender_regex = models.CharField(max_length=200, blank=True)
    body_regex = models.TextField()
    kind = models.CharField(max_length=10, blank=True, help_text="Leave blank to infer from debit/credit words")
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.bank} #{self.pk}"


def new_token():
    return secrets.token_urlsafe(24)


class ApiToken(models.Model):
    """Token SMS forwarders use to post to the ingest API."""

    token = models.CharField(max_length=64, default=new_token, unique=True)

    @classmethod
    def current(cls):
        return (cls.objects.first() or cls.objects.create()).token


def clamp_day(year: int, month: int, day: int) -> date:
    """date(year, month, day), with 31 → the month's last day."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


class Recurring(models.Model):
    """A bill or subscription that repeats: rent, recharge, Wi-Fi every 12 months…"""

    UNITS = [("day", _("day(s)")), ("week", _("week(s)")), ("month", _("month(s)")), ("year", _("year(s)"))]
    PER_MONTH = {"day": Decimal("30.4375"), "week": Decimal("4.348125"), "month": Decimal(1), "year": Decimal(1) / 12}

    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    kind = models.CharField(max_length=10, choices=Transaction.KINDS, default="expense")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL)
    every = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    unit = models.CharField(max_length=5, choices=UNITS, default="month")
    next_due = models.DateField()
    anchor_day = models.PositiveSmallIntegerField(null=True, editable=False)  # keeps the 31st from drifting to the 28th
    remind_days_before = models.PositiveSmallIntegerField(default=0)
    essential = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["next_due", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.anchor_day is None or self._state.adding:
            self.anchor_day = self.next_due.day
        super().save(*args, **kwargs)

    @property
    def is_income(self) -> bool:
        return self.kind in ("income", "repay_in", "borrow")

    @property
    def is_transfer(self) -> bool:
        """Money that leaves your account but isn't spending, e.g. sending your father money every month."""
        return self.kind == "transfer"

    @property
    def cadence(self) -> str:
        """"every month", "every 12 months"."""
        one, many = {
            "day": (_("every day"), _("every %(n)d days")), "week": (_("every week"), _("every %(n)d weeks")),
            "month": (_("every month"), _("every %(n)d months")), "year": (_("every year"), _("every %(n)d years")),
        }[self.unit]
        return str(one) if self.every == 1 else str(many) % {"n": self.every}

    @property
    def monthly_cost(self) -> Decimal:
        return (self.amount * self.PER_MONTH[self.unit] / self.every).quantize(Decimal("0.01"))

    def following_due(self) -> date:
        d = self.next_due
        if self.unit in ("day", "week"):
            return d + timedelta(days=self.every * (7 if self.unit == "week" else 1))
        months = self.every * (12 if self.unit == "year" else 1)
        y, m = divmod(d.month - 1 + months, 12)
        return clamp_day(d.year + y, m + 1, self.anchor_day or d.day)


class NotifySettings(models.Model):
    """Singleton: when to send push reminders."""

    daily_enabled = models.BooleanField("Daily “log today's spending” reminder", default=False)
    daily_time = models.TimeField(default=time(21, 0))
    reminders_enabled = models.BooleanField("Bill, subscription and card statement reminders", default=True)
    reminder_time = models.TimeField(default=time(9, 0))

    @classmethod
    def get(cls):
        return cls.objects.first() or cls.objects.create()


class PushSubscription(models.Model):
    """A browser/phone that allowed notifications."""

    endpoint = models.CharField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SentReminder(models.Model):
    """One row per reminder sent, keyed e.g. "daily:2026-10-01", so nothing is sent twice."""

    key = models.CharField(max_length=100, unique=True)
    sent_at = models.DateTimeField(auto_now_add=True)
