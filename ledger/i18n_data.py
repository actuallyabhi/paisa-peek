"""Strings that live in the database but ship with the app (seeded defaults), marked so makemessages finds them.
Templates show them with {% translate obj.name %}; names you create yourself just show as typed."""

from django.utils.translation import gettext_noop

DEFAULT_CATEGORIES = [
    gettext_noop("Bills & Recharge"), gettext_noop("Rent"), gettext_noop("Fuel & Transport"), gettext_noop("Health"),
    gettext_noop("Groceries"), gettext_noop("Subscriptions"), gettext_noop("Food & Outings"), gettext_noop("Shopping"),
    gettext_noop("Gifts & Family"), gettext_noop("Vehicle"), gettext_noop("Other"),
]

# Django's own date names and common form errors, listed here so OUR catalogs carry them. Two reasons:
# - Hindi: our catalog wins over Django's, which misspells सितमबर/नवमबर/दिसमबर/दिस्/गुरूवार.
# - Hinglish ("hi-latn"): gettext falls back from hi_Latn to hi, so without these, Devanagari names and
#   errors from Django's Hindi catalog would leak into the Latin-script UI.
DATE_NAMES = [
    gettext_noop("January"), gettext_noop("February"), gettext_noop("March"), gettext_noop("April"), gettext_noop("May"),
    gettext_noop("June"), gettext_noop("July"), gettext_noop("August"), gettext_noop("September"), gettext_noop("October"),
    gettext_noop("November"), gettext_noop("December"),
    gettext_noop("jan"), gettext_noop("feb"), gettext_noop("mar"), gettext_noop("apr"), gettext_noop("may"), gettext_noop("jun"),
    gettext_noop("jul"), gettext_noop("aug"), gettext_noop("sep"), gettext_noop("oct"), gettext_noop("nov"), gettext_noop("dec"),
    gettext_noop("Monday"), gettext_noop("Tuesday"), gettext_noop("Wednesday"), gettext_noop("Thursday"), gettext_noop("Friday"),
    gettext_noop("Saturday"), gettext_noop("Sunday"),
    gettext_noop("Mon"), gettext_noop("Tue"), gettext_noop("Wed"), gettext_noop("Thu"), gettext_noop("Fri"), gettext_noop("Sat"),
    gettext_noop("Sun"), gettext_noop("AM"), gettext_noop("PM"), gettext_noop("a.m."), gettext_noop("p.m."),
]
FORM_MESSAGES = [
    gettext_noop("This field is required."), gettext_noop("Enter a valid date."), gettext_noop("Enter a valid time."),
    gettext_noop("Enter a number."), gettext_noop("Select a valid choice. That choice is not one of the available choices."),
]
