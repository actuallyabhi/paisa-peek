from django.contrib import admin

from .models import Account, Category, Party, Rule, SmsTemplate, Tag, Transaction

admin.site.register(Category, list_display=["name", "essential", "budget"])
admin.site.register(Rule, list_display=["pattern", "category"])
admin.site.register(Tag)
admin.site.register(Party, list_display=["name", "kind"], list_filter=["kind"], search_fields=["name"])
admin.site.register(Account, list_display=["name", "kind", "last4"])
admin.site.register(SmsTemplate, list_display=["__str__", "bank", "sender_regex", "kind", "enabled"], list_editable=["enabled"])
admin.site.register(
    Transaction,
    list_display=["date", "amount", "kind", "description", "party", "category", "account", "status", "source"],
    list_filter=["status", "kind", "source", "category", "account", "party"],
    search_fields=["description", "merchant", "raw_text", "ref"],
    date_hierarchy="date",
)
