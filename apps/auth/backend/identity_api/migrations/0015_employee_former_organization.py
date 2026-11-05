from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("identity_api", "0014_system_architecture_permission_rules"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="former_dingtalk_departments",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="employee",
            name="former_system_departments",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="employee",
            name="former_organization_recorded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
