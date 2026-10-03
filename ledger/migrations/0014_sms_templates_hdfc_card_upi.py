import json
from pathlib import Path

from django.db import migrations


def add_new(apps, schema_editor):
    """Insert templates from sms_templates.json the database doesn't have yet (here: HDFC credit card UPI "Txn")."""
    SmsTemplate = apps.get_model("ledger", "SmsTemplate")
    have = set(SmsTemplate.objects.values_list("body_regex", flat=True))
    rows = json.loads((Path(__file__).parent.parent / "sms_templates.json").read_text())
    SmsTemplate.objects.bulk_create([SmsTemplate(bank=r["bank"], sender_regex=r["sender"], body_regex=r["body"], kind=r["kind"])
                                     for r in rows if r["body"] not in have])


class Migration(migrations.Migration):
    dependencies = [("ledger", "0013_interest_daily")]
    operations = [migrations.RunPython(add_new, migrations.RunPython.noop)]
