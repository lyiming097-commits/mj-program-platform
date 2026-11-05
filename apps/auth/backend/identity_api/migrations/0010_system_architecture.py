import uuid

import django.db.models.deletion
from django.db import migrations, models


def seed_system_architecture_state(apps, schema_editor):
    SystemArchitectureState = apps.get_model("identity_api", "SystemArchitectureState")
    SystemArchitectureState.objects.using(schema_editor.connection.alias).update_or_create(
        state_id=1,
        defaults={"revision": 1},
    )


class Migration(migrations.Migration):
    dependencies = [("identity_api", "0009_remove_audit_tables")]

    operations = [
        migrations.CreateModel(
            name="SystemArchitectureState",
            fields=[
                (
                    "state_id",
                    models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False),
                ),
                ("revision", models.PositiveBigIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "system_architecture_state"},
        ),
        migrations.CreateModel(
            name="SystemDepartment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=80)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="children",
                        to="identity_api.systemdepartment",
                    ),
                ),
            ],
            options={
                "db_table": "system_departments",
                "ordering": ["parent_id", "sort_order", "name", "id"],
            },
        ),
        migrations.CreateModel(
            name="SystemDepartmentScope",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "scope_type",
                    models.CharField(
                        choices=[
                            ("department", "部门"),
                            ("departmentSub", "部门及下级"),
                            ("employee", "人员"),
                            ("excludedEmployee", "排除人员"),
                        ],
                        max_length=24,
                    ),
                ),
                ("target_id", models.CharField(max_length=64)),
                ("target_name", models.CharField(max_length=255)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                (
                    "system_department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rules",
                        to="identity_api.systemdepartment",
                    ),
                ),
            ],
            options={
                "db_table": "system_department_scopes",
                "ordering": ["system_department_id", "sort_order", "scope_type", "target_id"],
                "indexes": [
                    models.Index(fields=["scope_type", "target_id"], name="idx_sys_dept_scope_target"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="systemdepartment",
            constraint=models.CheckConstraint(
                condition=models.Q(("parent__isnull", True), ~models.Q(("parent", models.F("id"))), _connector="OR"),
                name="system_department_parent_not_self",
            ),
        ),
        migrations.AddConstraint(
            model_name="systemdepartment",
            constraint=models.UniqueConstraint(
                fields=("parent", "name"),
                name="uniq_system_department_sibling_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="systemdepartmentscope",
            constraint=models.UniqueConstraint(
                fields=("system_department", "scope_type", "target_id"),
                name="uniq_system_department_scope",
            ),
        ),
        migrations.RunPython(seed_system_architecture_state, migrations.RunPython.noop),
    ]
