from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("identity_api", "0008_internal_service_credentials")]

    operations = [
        migrations.DeleteModel(name="AuthOperationAuditLog"),
        migrations.DeleteModel(name="InternalApiAuditLog"),
    ]
