from django.db import migrations, models


def remove_excluded_employee_rules(apps, schema_editor):
    """Drop the retired scope before narrowing the model field choices."""
    AppPermissionRule = apps.get_model("approval_center_api", "AppPermissionRule")
    ApprovalCategoryPermission = apps.get_model(
        "approval_center_api",
        "ApprovalCategoryPermission",
    )
    AppPermissionRule.objects.filter(scope_type="excludedEmployee").delete()
    ApprovalCategoryPermission.objects.filter(scope_type="excludedEmployee").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("approval_center_api", "0002_approval_categories"),
    ]

    operations = [
        migrations.RunPython(
            remove_excluded_employee_rules,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="apppermissionrule",
            name="scope_type",
            field=models.CharField(
                choices=[
                    ("department", "部门"),
                    ("departmentSub", "部门及下级"),
                    ("employee", "成员"),
                ],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="approvalcategorypermission",
            name="scope_type",
            field=models.CharField(
                choices=[
                    ("department", "部门"),
                    ("departmentSub", "部门及下级"),
                    ("employee", "成员"),
                ],
                max_length=16,
            ),
        ),
    ]
