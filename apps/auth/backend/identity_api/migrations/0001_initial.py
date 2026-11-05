from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Department",
            fields=[
                ("dept_id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("manager_user_id", models.CharField(blank=True, default="", max_length=64)),
                ("parent_dept_id", models.BigIntegerField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "organization_departments",
                "ordering": ["dept_id"],
            },
        ),
        migrations.CreateModel(
            name="Employee",
            fields=[
                ("user_id", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("avatar_url", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[("在职", "在职"), ("离职", "离职")],
                        default="在职",
                        max_length=8,
                    ),
                ),
                (
                    "account_status",
                    models.CharField(
                        choices=[("启用", "启用"), ("禁用", "禁用")],
                        default="启用",
                        max_length=8,
                    ),
                ),
                ("handover_user_id", models.CharField(blank=True, default="", max_length=64)),
                ("auth_version", models.PositiveIntegerField(default=1)),
                ("create_time", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "organization_employees",
                "ordering": ["user_id"],
            },
        ),
        migrations.CreateModel(
            name="InternalApiAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_id", models.CharField(db_index=True, max_length=64)),
                ("caller", models.CharField(blank=True, db_index=True, default="unknown", max_length=128)),
                ("endpoint", models.CharField(db_index=True, max_length=255)),
                ("method", models.CharField(blank=True, default="", max_length=16)),
                ("input_size", models.PositiveIntegerField(default=0)),
                ("result_count", models.PositiveIntegerField(default=0)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("status_code", models.PositiveIntegerField(default=200)),
                ("ok", models.BooleanField(default=True)),
                ("error_code", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "db_table": "internal_api_audit_logs",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Role",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64, unique=True)),
                ("description", models.CharField(blank=True, default="", max_length=255)),
                ("creator_user_id", models.CharField(blank=True, default="", max_length=64)),
                ("is_system", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "organization_roles",
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="DepartmentEmployee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "department",
                    models.ForeignKey(
                        db_column="department_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="department_employees",
                        to="identity_api.department",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        db_column="employee_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="department_employees",
                        to="identity_api.employee",
                    ),
                ),
            ],
            options={
                "db_table": "organization_department_employees",
                "ordering": ["department_id", "employee_id"],
            },
        ),
        migrations.CreateModel(
            name="RoleEmployee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "employee",
                    models.ForeignKey(
                        db_column="employee_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="role_employees",
                        to="identity_api.employee",
                    ),
                ),
                (
                    "role",
                    models.ForeignKey(
                        db_column="role_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="role_employees",
                        to="identity_api.role",
                    ),
                ),
            ],
            options={
                "db_table": "organization_role_employees",
                "ordering": ["role_id", "employee_id"],
            },
        ),
        migrations.AddConstraint(
            model_name="departmentemployee",
            constraint=models.UniqueConstraint(
                fields=("department", "employee"),
                name="uniq_department_employee",
            ),
        ),
        migrations.AddConstraint(
            model_name="roleemployee",
            constraint=models.UniqueConstraint(
                fields=("role", "employee"),
                name="uniq_role_employee",
            ),
        ),
    ]
