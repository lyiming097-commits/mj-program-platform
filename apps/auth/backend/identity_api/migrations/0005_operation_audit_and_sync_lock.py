from django.db import migrations, models


def create_sync_lock(apps, schema_editor):
    sync_lock = apps.get_model("identity_api", "OrganizationSyncLock")
    sync_lock.objects.get_or_create(lock_id=1)


class Migration(migrations.Migration):
    dependencies = [
        ("identity_api", "0004_organization_sync_run"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationSyncLock",
            fields=[
                (
                    "lock_id",
                    models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "organization_sync_lock"},
        ),
        migrations.CreateModel(
            name="AuthOperationAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_id", models.CharField(db_index=True, max_length=64)),
                ("actor_user_id", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("effective_user_id", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("action", models.CharField(db_index=True, max_length=64)),
                ("target_type", models.CharField(blank=True, db_index=True, default="", max_length=32)),
                ("target_id", models.CharField(blank=True, db_index=True, default="", max_length=128)),
                ("success", models.BooleanField(db_index=True, default=True)),
                ("client_ip", models.CharField(blank=True, default="", max_length=45)),
                ("user_agent", models.CharField(blank=True, default="", max_length=255)),
                ("detail", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={"db_table": "auth_operation_audit_logs", "ordering": ["-created_at"]},
        ),
        migrations.RunPython(create_sync_lock, reverse_code=migrations.RunPython.noop),
    ]
