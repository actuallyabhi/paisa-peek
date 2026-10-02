from django.db import migrations


def seed(apps, schema_editor):
    Account = apps.get_model("ledger", "Account")
    if not Account.objects.filter(kind="cash").exists():  # someone may have made their own already
        Account.objects.create(name="Cash", kind="cash")


class Migration(migrations.Migration):
    dependencies = [("ledger", "0011_account_interest")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
