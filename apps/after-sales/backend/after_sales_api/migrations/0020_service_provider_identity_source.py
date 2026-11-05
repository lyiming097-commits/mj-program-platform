from django.db import migrations, models


def classify_existing_providers(apps, _schema_editor):
    provider_model = apps.get_model("after_sales_api", "ServiceProvider")
    provider_model.objects.exclude(auth_user_id__startswith="wxmini:").update(
        identity_source="dingtalk",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("after_sales_api", "0019_provider_tags"),
    ]

    operations = [
        migrations.AddField(
            model_name="serviceprovider",
            name="identity_source",
            field=models.CharField(
                choices=[
                    ("wechat-mini", "微信小程序"),
                    ("dingtalk", "钉钉历史档案"),
                ],
                default="wechat-mini",
                max_length=16,
            ),
        ),
        migrations.RunPython(classify_existing_providers, migrations.RunPython.noop),
    ]
