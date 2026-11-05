from django.db import migrations, models
import django.db.models.deletion


def enable_existing_departments(apps, schema_editor):
    Department = apps.get_model("identity_api", "Department")
    EnabledDepartment = apps.get_model("identity_api", "PlatformEnabledDepartment")
    State = apps.get_model("identity_api", "PlatformDepartmentState")
    EnabledDepartment.objects.bulk_create(
        [EnabledDepartment(department_id=dept_id) for dept_id in Department.objects.values_list("dept_id", flat=True)],
        ignore_conflicts=True,
    )
    State.objects.update_or_create(state_id=1, defaults={"configured": True, "revision": 1})


class Migration(migrations.Migration):
    dependencies = [("identity_api", "0015_employee_former_organization")]

    operations = [
        migrations.CreateModel(
            name="PlatformDepartmentState",
            fields=[
                ("state_id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("configured", models.BooleanField(default=False)),
                ("revision", models.PositiveBigIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "platform_department_state"},
        ),
        migrations.CreateModel(
            name="PlatformEnabledDepartment",
            fields=[
                ("enabled_by", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "department",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="platform_enabled_setting",
                        serialize=False,
                        to="identity_api.department",
                    ),
                ),
            ],
            options={"db_table": "platform_enabled_departments", "ordering": ["department_id"]},
        ),
        migrations.RunPython(enable_existing_departments, migrations.RunPython.noop),
        migrations.RenameModel(
            old_name="SystemArchitecturePermissionState",
            new_name="OrganizationPermissionState",
        ),
        migrations.AlterModelTable(
            name="organizationpermissionstate",
            table="organization_permissions",
        ),
        migrations.RemoveField(
            model_name="employee",
            name="former_system_departments",
        ),
        migrations.DeleteModel(name="SystemDepartmentScope"),
        migrations.DeleteModel(name="SystemDepartment"),
        migrations.DeleteModel(name="SystemArchitectureState"),
    ]
