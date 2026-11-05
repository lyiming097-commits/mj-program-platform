from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity_api", "0019_business_registry_company_history")]

    operations = [
        migrations.AddField(
            model_name="businessregistryquery", name="source_app_id",
            field=models.CharField(max_length=64, blank=True, default="", db_default=""),
        ),
        migrations.AddField(
            model_name="businessregistryquery", name="source_service",
            field=models.CharField(max_length=128, blank=True, default="", db_default=""),
        ),
    ]
