from django.db import migrations, models
from django.db.models import F


def backfill_salesperson_price(apps, schema_editor):
    CableProduct = apps.get_model("cable_mall", "CableProduct")
    CableProduct.objects.update(salesperson_price=F("unit_price"))


class Migration(migrations.Migration):
    dependencies = [
        ("cable_mall", "0003_clear_legacy_product_identity"),
    ]

    operations = [
        migrations.AddField(
            model_name="cableproduct",
            name="salesperson_price",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.RunPython(backfill_salesperson_price, migrations.RunPython.noop),
    ]
