from django.db import migrations


STATUS_VALUE_MAP = {
    "鍦ㄨ亴": "在职",
    "绂昏亴": "离职",
}

ACCOUNT_STATUS_VALUE_MAP = {
    "鍚敤": "启用",
    "绂佺敤": "禁用",
}


def normalize_employee_status_values(apps, schema_editor):
    Employee = apps.get_model("identity_api", "Employee")
    for old_value, new_value in STATUS_VALUE_MAP.items():
        Employee.objects.filter(status=old_value).update(status=new_value)
    for old_value, new_value in ACCOUNT_STATUS_VALUE_MAP.items():
        Employee.objects.filter(account_status=old_value).update(account_status=new_value)


class Migration(migrations.Migration):
    dependencies = [
        ("identity_api", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(normalize_employee_status_values, migrations.RunPython.noop),
    ]
