import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("identity_api", "0003_remove_roles_add_session_revocation"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationSyncRun",
            fields=[
                ("run_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("running", "running"), ("succeeded", "succeeded"), ("failed", "failed")], db_index=True, max_length=16)),
                ("started_by", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("started_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("finished_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("summary", models.JSONField(blank=True, default=dict)),
                ("error", models.TextField(blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "organization_sync_runs",
                "ordering": ["-started_at"],
            },
        ),
    ]
