from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity_api", "0010_system_architecture")]

    operations = [
        migrations.AddField(
            model_name="systemdepartment",
            name="manager_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="systemdepartment",
            name="manager_user_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
