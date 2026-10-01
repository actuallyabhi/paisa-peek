from django import forms
from django.core.validators import RegexValidator
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _

from .models import Account, Category, NotifySettings, Party, Recurring, Tag, Transaction

# Field labels live here (not on the models) so translating them never needs a migration.
LABELS = {
    "date": _("Date"), "time": _("Time"), "amount": _("Amount"), "kind": _("Type"), "description": _("Description"),
    "category": _("Category"), "account": _("Account"), "to_account": _("To account"), "notes": _("Notes"),
    "status": _("Status"), "name": _("Name"), "every": _("Every"), "unit": _("Unit"), "next_due": _("Next date"),
    "remind_days_before": _("Remind days before"), "essential": _("Essential expense (part of the minimum)"),
    "active": _("Active"), "credit_limit": _("Credit limit"), "statement_day": _("Statement day"),
    "due_day": _("Due day"), "is_default": _("Default account for new transactions"),
}

ISO_DATE = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})  # <input type=date> rejects "30/09/2026"
TIME = forms.TimeInput(format="%H:%M", attrs={"type": "time"})


def now_hm():
    """Current local time (app timezone, not the server clock's), to the minute."""
    return timezone.localtime().time().replace(second=0, microsecond=0)


def party_named(name: str, kind: str = "person") -> Party:
    """Existing party by case-insensitive name, else a new one."""
    return Party.objects.filter(name__iexact=name).first() or Party.objects.create(name=name, kind=kind)


def review(t: Transaction, status: str, category=None, kind=None, party_name: str = "") -> None:
    """Inbox confirm/ignore, shared by the web Inbox and the app API. Raises ValueError with a user-facing message."""
    if status not in dict(Transaction.STATUSES):
        raise ValueError("invalid status")
    if status == "confirmed" and t.amount <= 0:
        raise ValueError(gettext("Set an amount before confirming."))
    if category:
        t.category = Category.objects.filter(pk=category).first() or t.category
    # Money coming in: the inbox asks what it was (income / repaid to me / borrowed) instead of a category.
    if kind in Transaction.MONEY_IN:
        name = " ".join((party_name or "").split())
        if kind in Transaction.LOAN_KINDS and not name:
            raise ValueError(gettext("Who? Lent/borrowed/repaid needs a person or company."))
        t.kind = kind
        t.party = party_named(name) if name else t.party
    t.status = status
    t.save(update_fields=["status", "category", "kind", "party"])


class TxnForm(forms.ModelForm):
    party_name = forms.CharField(
        label=_("Person / company"), required=False, max_length=100,
        widget=forms.TextInput(attrs={"list": "party-names", "placeholder": _("e.g. Rohan"), "autocomplete": "off"}),
    )
    tag_names = forms.CharField(label=_("Tags"), required=False, widget=forms.TextInput(attrs={"placeholder": _("Goa trip, Office")}))

    class Meta:
        model = Transaction
        fields = ["date", "time", "amount", "kind", "description", "party_name", "category", "account", "to_account",
                  "tag_names", "notes", "status"]
        widgets = {"date": ISO_DATE, "time": TIME}
        labels = LABELS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "category" in self.fields:  # shipped category names show in your language
            self.fields["category"].label_from_instance = lambda c: gettext(c.name)
        if self.instance.pk:
            self.initial["tag_names"] = ", ".join(self.instance.tags.values_list("name", flat=True))
            self.initial["party_name"] = self.instance.party.name if self.instance.party else ""
        else:  # new entry: today, right now, default account
            self.initial.setdefault("date", timezone.localdate())
            if "time" in self.fields:
                self.initial.setdefault("time", now_hm())
            if "account" in self.fields:
                self.initial.setdefault("account", Account.default())

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError(_("Amount must be positive."))
        return amount

    def clean_party_name(self):
        return " ".join(self.cleaned_data["party_name"].split())

    def clean_tag_names(self):
        names = {}
        for n in self.cleaned_data["tag_names"].split(","):
            if n := " ".join(n.split())[:50]:
                names.setdefault(n.lower(), n)  # dedupe case-insensitively, keep first spelling
        return list(names.values())

    def clean(self):
        data = super().clean()
        if data.get("kind") in Transaction.LOAN_KINDS and not data.get("party_name"):
            self.add_error("party_name", _("Who? Lent/borrowed/repaid needs a person or company."))
        if data.get("to_account"):
            if data.get("kind") != "transfer":
                self.add_error("to_account", _("Only for transfers."))
            elif data.get("to_account") == data.get("account"):
                self.add_error("to_account", _("Pick a different account."))
        return data

    def save(self, commit=True):
        name = self.cleaned_data.get("party_name")
        self.instance.party = party_named(name) if name else None
        obj = super().save(commit)
        if commit and "tag_names" in self.fields:
            obj.tags.set([Tag.objects.filter(name__iexact=n).first() or Tag.objects.create(name=n)
                          for n in self.cleaned_data["tag_names"]])
        return obj


class RambleForm(TxnForm):
    """One draft row on the review screen, shared by Ramble and CSV import."""

    include = forms.BooleanField(required=False, initial=True)
    quote = forms.CharField(required=False, widget=forms.HiddenInput)
    source = "ramble"

    class Meta(TxnForm.Meta):
        fields = ["date", "amount", "kind", "description", "party_name", "category", "account", "tag_names", "notes"]

    def save(self, commit=True):
        self.instance.source = self.source
        self.instance.status = "confirmed"
        self.instance.raw_text = self.cleaned_data["quote"]
        if self.cleaned_data["date"] == timezone.localdate():
            self.instance.time = now_hm()  # logged today: stamp it now (past days' times are unknown)
        return super().save(commit)


class PartyTxnForm(TxnForm):
    """Quick entry on a person's page: the party is fixed, kinds are the loan ones."""

    class Meta(TxnForm.Meta):
        fields = ["date", "time", "amount", "kind", "description", "account", "notes"]

    def __init__(self, *args, party, **kwargs):
        super().__init__(*args, **kwargs)
        self.party = party
        del self.fields["party_name"]  # declared fields ignore Meta.fields; the party is fixed here
        self.fields["kind"].choices = [c for c in Transaction.KINDS if c[0] in Transaction.LOAN_KINDS] + [
            c for c in Transaction.KINDS if c[0] in ("expense", "income")]

    def clean(self):
        self.cleaned_data["party_name"] = self.party.name
        return super().clean()


class PartyForm(forms.ModelForm):
    class Meta:
        model = Party
        fields = ["name", "kind", "notes"]
        labels = LABELS


class AccountForm(forms.ModelForm):
    current_balance = forms.DecimalField(
        required=False, max_digits=14, decimal_places=2,
        label=_("Current balance"),
        help_text=_("What your bank/app shows right now. For cards, credit lines and loans: the amount you owe."),
    )
    last4 = forms.CharField(label=_("Last 4 digits"), required=False, max_length=4,
                            validators=[RegexValidator(r"^\d{0,4}$", _("Up to 4 digits."))],
                            help_text=_("Matches bank SMS to this account."))

    class Meta:
        model = Account
        fields = ["name", "kind", "last4", "current_balance", "credit_limit", "statement_day", "due_day", "is_default"]
        labels = LABELS
        help_texts = {"statement_day": _("Day of month the statement generates (cards)"),
                      "due_day": _("Day of month payment is due")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            b = self.instance.balance
            self.initial["current_balance"] = -b if self.instance.is_credit else b

    def save(self, commit=True):
        obj = super().save(commit=False)
        entered = self.cleaned_data.get("current_balance")
        if entered is not None:
            target = -abs(entered) if obj.kind in Account.CREDIT_KINDS else entered
            # Back-solve so opening + everything already recorded = what the bank shows now.
            obj.opening_balance = target - (obj.net() if obj.pk else 0)
        if commit:
            obj.save()
        return obj


class RecurringForm(forms.ModelForm):
    class Meta:
        model = Recurring
        fields = ["name", "amount", "kind", "category", "account", "every", "unit", "next_due", "remind_days_before",
                  "essential", "active"]
        widgets = {"next_due": ISO_DATE}
        labels = LABELS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [("expense", _("Expense / bill")), ("income", _("Income (salary, stipend, rent received…)")),
                                       ("transfer", _("Transfer / sending money (not spending)"))]
        if not self.instance.pk:
            self.initial.setdefault("account", Account.default())
            self.initial.setdefault("next_due", timezone.localdate())

    def clean_amount(self):
        if self.cleaned_data["amount"] <= 0:
            raise forms.ValidationError(_("Amount must be positive."))
        return self.cleaned_data["amount"]


class NotifyForm(forms.ModelForm):
    class Meta:
        model = NotifySettings
        fields = ["daily_enabled", "daily_time", "reminders_enabled", "reminder_time"]
        widgets = {"daily_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
                   "reminder_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"})}
        labels = {"daily_enabled": _("Daily “log today's spending” reminder"), "daily_time": _("at"),
                  "reminders_enabled": _("Bill, subscription and card statement reminders"), "reminder_time": _("at")}
