"""Strings that live in the database but ship with the app (seeded defaults), marked so makemessages finds them.
Templates show them with {% translate obj.name %}; names you create yourself just show as typed."""

from django.utils.translation import gettext_noop

DEFAULT_CATEGORIES = [
    gettext_noop("Bills & Recharge"), gettext_noop("Rent"), gettext_noop("Fuel & Transport"), gettext_noop("Health"),
    gettext_noop("Groceries"), gettext_noop("Subscriptions"), gettext_noop("Food & Outings"), gettext_noop("Shopping"),
    gettext_noop("Gifts & Family"), gettext_noop("Vehicle"), gettext_noop("Other"),
]

# Our catalog is checked before Django's own, so these fix misspellings in Django's Hindi dates
# (सितमबर → सितंबर, नवमबर → नवंबर, दिसमबर → दिसंबर, दिस् → दिस, गुरूवार → गुरुवार).
DATE_NAME_FIXES = [
    gettext_noop("September"), gettext_noop("November"), gettext_noop("December"), gettext_noop("dec"),
    gettext_noop("Monday"), gettext_noop("Thursday"),
]
