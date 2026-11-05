from django.db import migrations


def clear_legacy_product_codes(apps, schema_editor):
    CableProduct = apps.get_model("cable_mall", "CableProduct")
    CableProduct.objects.filter(
        kingdee_code__iregex=r"^(SRC|PROD)-"
    ).update(kingdee_code="")


class Migration(migrations.Migration):
    dependencies = [
        ("cable_mall", "0002_product_archive_identity_columns"),
    ]

    operations = [
        migrations.RunPython(clear_legacy_product_codes, migrations.RunPython.noop),
    ]
