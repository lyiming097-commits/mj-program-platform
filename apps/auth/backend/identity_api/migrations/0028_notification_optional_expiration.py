from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity_api", "0027_platform_notifications")]

    operations = [
        migrations.AlterField(
            model_name="platformnotification",
            name="expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
