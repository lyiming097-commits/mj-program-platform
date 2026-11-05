from django.db import migrations, models


def migrate_legacy_managers(apps, schema_editor):
    PermissionState = apps.get_model("identity_api", "SystemArchitecturePermissionState")
    Employee = apps.get_model("identity_api", "Employee")
    alias = schema_editor.connection.alias
    for state in PermissionState.objects.using(alias).all():
        user_ids = list(dict.fromkeys(
            user_id.strip()
            for user_id in (state.manager_user_ids or [])
            if isinstance(user_id, str) and user_id.strip()
        ))
        names = dict(
            Employee.objects.using(alias).filter(user_id__in=user_ids).values_list("user_id", "name")
        )
        state.rules = [
            {
                "scopeType": "employee",
                "targetId": user_id,
                "targetName": names.get(user_id, user_id),
                "sortOrder": index,
            }
            for index, user_id in enumerate(user_ids)
        ]
        state.save(update_fields=["rules"])


class Migration(migrations.Migration):
    dependencies = [("identity_api", "0013_system_architecture_permissions")]

    operations = [
        migrations.AddField(
            model_name="systemarchitecturepermissionstate",
            name="rules",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(migrate_legacy_managers, migrations.RunPython.noop),
    ]
