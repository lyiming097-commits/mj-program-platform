import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity_api", "0011_system_department_manager")]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="identity_source",
            field=models.CharField(
                choices=[("dingtalk", "钉钉"), ("wechat-mini", "微信小程序")],
                db_index=True,
                default="dingtalk",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="WeChatMiniIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("app_id", models.CharField(max_length=64)),
                ("openid", models.CharField(max_length=128)),
                ("unionid", models.CharField(blank=True, db_index=True, default="", max_length=128)),
                ("privacy_version", models.CharField(blank=True, default="", max_length=32)),
                ("privacy_agreed_at", models.DateTimeField(blank=True, null=True)),
                ("last_login_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "employee",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="wechat_mini_identity",
                        to="identity_api.employee",
                    ),
                ),
            ],
            options={
                "db_table": "wechat_mini_identities",
                "ordering": ["app_id", "openid"],
            },
        ),
        migrations.CreateModel(
            name="WeChatMiniRegistrationChallenge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_digest", models.CharField(max_length=64, unique=True)),
                ("app_id", models.CharField(max_length=64)),
                ("openid", models.CharField(max_length=128)),
                ("unionid", models.CharField(blank=True, default="", max_length=128)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("used_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "wechat_mini_registration_challenges",
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["app_id", "openid"], name="idx_wx_challenge_identity")],
            },
        ),
        migrations.AddConstraint(
            model_name="wechatminiidentity",
            constraint=models.UniqueConstraint(
                fields=("app_id", "openid"),
                name="uniq_wechat_mini_app_openid",
            ),
        ),
    ]
