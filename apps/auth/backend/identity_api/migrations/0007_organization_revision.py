from django.db import migrations, models


def seed_organization_revision(apps, schema_editor):
    Department = apps.get_model("identity_api", "Department")
    OrganizationState = apps.get_model("identity_api", "OrganizationState")
    database_alias = schema_editor.connection.alias
    revision = 1 if Department.objects.using(database_alias).exists() else 0
    OrganizationState.objects.using(database_alias).update_or_create(
        state_id=1,
        defaults={"revision": revision},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("identity_api", "0006_durable_sessions_and_department_managers"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationState",
            fields=[
                ("state_id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("revision", models.PositiveBigIntegerField(default=0)),
                ("synced_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "organization_state"},
        ),
        migrations.RunPython(seed_organization_revision, migrations.RunPython.noop),
    ]
