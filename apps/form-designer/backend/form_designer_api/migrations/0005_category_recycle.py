from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('form_designer_api', '0004_uploadedfile')]

    operations = [
        migrations.AddField(
            model_name='categorysupervisorstate',
            name='deleted_categories',
            field=models.JSONField(default=dict),
        ),
    ]
