from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('form_designer_api', '0002_categorysupervisorstate')]

    operations = [
        migrations.AddField(model_name='categorysupervisorstate', name='names', field=models.JSONField(default=dict)),
        migrations.AddField(model_name='categorysupervisorstate', name='administrators', field=models.JSONField(default=dict)),
    ]
