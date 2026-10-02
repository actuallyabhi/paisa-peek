from django.db import migrations

CATEGORIES = [
    ("Personal Care", False), ("Transfers", False), ("Education", True), ("Insurance", True), ("EMI & Loans", True),
    ("Household", True), ("Entertainment", False), ("Travel", False), ("Investments", False), ("Kids", False),
    ("Donations", False), ("Fees & Charges", False),
]


def seed(apps, schema_editor):
    Category = apps.get_model("ledger", "Category")
    for name, essential in CATEGORIES:  # get_or_create: someone may already have made "Travel" themselves
        Category.objects.get_or_create(name=name, defaults={"essential": essential})


class Migration(migrations.Migration):
    dependencies = [("ledger", "0009_rules_budgets")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
