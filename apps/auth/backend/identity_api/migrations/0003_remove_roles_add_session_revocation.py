from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("identity_api", "0002_normalize_employee_status_values"),
    ]

    operations = [
        migrations.DeleteModel(
            name="RoleEmployee",
        ),
        migrations.DeleteModel(
            name="Role",
        ),
        migrations.CreateModel(
            name="AuthSessionRevocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("user_id", models.CharField(db_index=True, max_length=64)),
                ("actor_user_id", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("session_started_at", models.PositiveBigIntegerField(db_index=True)),
                ("reason", models.CharField(blank=True, default="", max_length=64)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "auth_session_revocations",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="authsessionrevocation",
            constraint=models.UniqueConstraint(
                fields=("user_id", "actor_user_id", "session_started_at"),
                name="uniq_auth_session_revocation",
            ),
        ),
    ]
