from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity_api", "0007_organization_revision")]

    operations = [
        migrations.CreateModel(
            name="InternalServiceCredential",
            fields=[
                ("service_name", models.CharField(max_length=128, primary_key=True, serialize=False)),
                ("app_id", models.SlugField(db_index=True, max_length=64)),
                ("secret_salt", models.CharField(max_length=32)),
                ("secret_digest", models.CharField(max_length=64)),
                ("enabled", models.BooleanField(db_index=True, default=True)),
                ("registry_revision", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "internal_service_credentials",
                "ordering": ["service_name"],
            },
        )
    ]
