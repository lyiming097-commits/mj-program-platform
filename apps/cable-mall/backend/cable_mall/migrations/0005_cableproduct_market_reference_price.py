from django.db import migrations, models
from django.db.models import F


def preserve_legacy_market_reference_price(apps, schema_editor):
    CableProduct = apps.get_model("cable_mall", "CableProduct")
    # Before the product archive gained a separate budget tier, budget_price
    # carried the market-reference value in this local catalog snapshot.
    CableProduct.objects.update(market_reference_price=F("budget_price"))


class Migration(migrations.Migration):
    dependencies = [
        ("cable_mall", "0004_cableproduct_salesperson_price"),
    ]

    operations = [
        migrations.AddField(
            model_name="cableproduct",
            name="market_reference_price",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.RunPython(
            preserve_legacy_market_reference_price,
            migrations.RunPython.noop,
        ),
    ]
