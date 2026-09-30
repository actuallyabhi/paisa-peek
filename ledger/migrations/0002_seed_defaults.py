import json
from pathlib import Path

from django.db import migrations

CATEGORIES = [
    ("Bills & Recharge", True), ("Rent", True), ("Fuel & Transport", True), ("Health", True), ("Groceries", True),
    ("Subscriptions", False), ("Food & Outings", False), ("Shopping", False), ("Gifts & Family", False),
    ("Vehicle", False), ("Other", False),
]


def seed(apps, schema_editor):
    Category = apps.get_model("ledger", "Category")
    SmsTemplate = apps.get_model("ledger", "SmsTemplate")
    Category.objects.bulk_create([Category(name=n, essential=e) for n, e in CATEGORIES])
    rows = json.loads((Path(__file__).parent.parent / "sms_templates.json").read_text())
    SmsTemplate.objects.bulk_create(
        [SmsTemplate(bank=r["bank"], sender_regex=r["sender"], body_regex=r["body"], kind=r["kind"]) for r in rows]
    )


class Migration(migrations.Migration):
    dependencies = [("ledger", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
