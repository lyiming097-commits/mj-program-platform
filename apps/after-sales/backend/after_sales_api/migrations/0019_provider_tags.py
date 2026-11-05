from django.db import migrations, models


DEFAULT_PROVIDER_TAGS = [
    "讲台安装",
    "中控联调",
    "智慧板书",
    "录播联动",
    "平台接入",
]


def seed_provider_tags(apps, _schema_editor):
    provider_tag_model = apps.get_model("after_sales_api", "ProviderTag")
    provider_tag_model.objects.bulk_create([
        provider_tag_model(name=name, sort_order=index)
        for index, name in enumerate(DEFAULT_PROVIDER_TAGS, start=1)
    ])


class Migration(migrations.Migration):
    dependencies = [
        ("after_sales_api", "0018_separate_service_ratings"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProviderTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_by", models.CharField(blank=True, default="", max_length=64)),
                ("created_actor_id", models.CharField(blank=True, default="", max_length=64)),
                ("updated_by", models.CharField(blank=True, default="", max_length=64)),
                ("updated_actor_id", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=128, unique=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "db_table": "provider_tags",
                "ordering": ["sort_order", "name", "id"],
            },
        ),
        migrations.RunPython(seed_provider_tags, migrations.RunPython.noop),
    ]
