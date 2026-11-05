from django.db import migrations, models


def seed_system_architecture_permissions(apps, schema_editor):
    PermissionState = apps.get_model("identity_api", "SystemArchitecturePermissionState")
    PermissionState.objects.using(schema_editor.connection.alias).update_or_create(
        state_id=1,
        defaults={"revision": 1, "manager_user_ids": []},
    )


class Migration(migrations.Migration):
    dependencies = [("identity_api", "0012_wechat_mini_identity")]

    operations = [
        migrations.CreateModel(
            name="SystemArchitecturePermissionState",
            fields=[
                (
                    "state_id",
                    models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False),
                ),
                ("manager_user_ids", models.JSONField(blank=True, default=list)),
                ("revision", models.PositiveBigIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "system_architecture_permissions"},
        ),
        migrations.RunPython(seed_system_architecture_permissions, migrations.RunPython.noop),
    ]
