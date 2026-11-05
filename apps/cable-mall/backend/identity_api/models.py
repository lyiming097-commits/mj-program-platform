from django.db import models


class Department(models.Model):
    dept_id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    manager_user_id = models.CharField(max_length=64, blank=True, default="")
    parent_dept_id = models.BigIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_departments"
        ordering = ["dept_id"]


class Employee(models.Model):
    STATUS_ACTIVE = "在职"
    STATUS_INACTIVE = "离职"
    ACCOUNT_ENABLED = "启用"
    ACCOUNT_DISABLED = "禁用"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, STATUS_ACTIVE),
        (STATUS_INACTIVE, STATUS_INACTIVE),
    ]
    ACCOUNT_STATUS_CHOICES = [
        (ACCOUNT_ENABLED, ACCOUNT_ENABLED),
        (ACCOUNT_DISABLED, ACCOUNT_DISABLED),
    ]

    user_id = models.CharField(max_length=64, primary_key=True)
    name = models.CharField(max_length=255)
    avatar_url = models.TextField(blank=True, default="")
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    account_status = models.CharField(
        max_length=8,
        choices=ACCOUNT_STATUS_CHOICES,
        default=ACCOUNT_ENABLED,
    )
    handover_user_id = models.CharField(max_length=64, blank=True, default="")
    auth_version = models.PositiveIntegerField(default=1)
    create_time = models.DateTimeField(null=True, blank=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_employees"
        ordering = ["user_id"]


class DepartmentEmployee(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        db_column="department_id",
        related_name="department_employees",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        db_column="employee_id",
        related_name="department_employees",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_department_employees"
        constraints = [
            models.UniqueConstraint(
                fields=["department", "employee"],
                name="uniq_department_employee",
            ),
        ]
        ordering = ["department_id", "employee_id"]
