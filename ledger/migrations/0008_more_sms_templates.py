import json
from pathlib import Path

from django.db import migrations


def add_new(apps, schema_editor):
    """Templates added to sms_templates.json after 0002 seeded it: insert any the database doesn't have yet."""
    SmsTemplate = apps.get_model("ledger", "SmsTemplate")
    have = set(SmsTemplate.objects.values_list("body_regex", flat=True))
    rows = json.loads((Path(__file__).parent.parent / "sms_templates.json").read_text())
    SmsTemplate.objects.bulk_create([SmsTemplate(bank=r["bank"], sender_regex=r["sender"], body_regex=r["body"], kind=r["kind"])
                                     for r in rows if r["body"] not in have])


class Migration(migrations.Migration):
    dependencies = [("ledger", "0007_notify_time_defaults")]
    operations = [migrations.RunPython(add_new, migrations.RunPython.noop)]
