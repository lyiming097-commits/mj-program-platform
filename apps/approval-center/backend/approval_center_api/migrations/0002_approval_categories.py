from django.db import migrations, models
import django.db.models.deletion


def populate_approval_categories(apps, schema_editor):
    Category = apps.get_model("approval_center_api", "ApprovalCategory")
    Template = apps.get_model("approval_center_api", "ApprovalTemplate")

    category_by_name = {}
    next_order = 0
    raw_names = (
        Template.objects.values_list("category", flat=True)
        .distinct()
        .order_by("category")
    )
    for raw_name in raw_names:
        name = str(raw_name or "").strip()[:64] or "通用"
        if name in category_by_name:
            continue
        category, _created = Category.objects.get_or_create(
            name=name,
            defaults={"sort_order": next_order},
        )
        category_by_name[name] = category
        next_order += 1

    # A fresh installation has no templates yet; still expose the default
    # category so the management UI has a stable destination for new forms.
    if not category_by_name:
        category = Category.objects.create(name="通用", sort_order=0)
        category_by_name["通用"] = category

    counters = {}
    for template in Template.objects.all().order_by("category", "id").iterator():
        name = str(template.category or "").strip()[:64] or "通用"
        category = category_by_name.get(name) or category_by_name["通用"]
        template.category_ref_id = category.pk
        template.category_order = counters.get(category.pk, 0)
        counters[category.pk] = template.category_order + 1
        template.save(update_fields=["category_ref", "category_order"])


def unpopulate_approval_categories(apps, schema_editor):
    Category = apps.get_model("approval_center_api", "ApprovalCategory")
    Template = apps.get_model("approval_center_api", "ApprovalTemplate")
    Template.objects.update(category_ref=None, category_order=0)
    Category.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("approval_center_api", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApprovalCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=64, unique=True)),
                ("description", models.TextField(blank=True, default="")),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_by", models.CharField(blank=True, default="", max_length=64)),
                ("created_by_name", models.CharField(blank=True, default="", max_length=128)),
                ("updated_by", models.CharField(blank=True, default="", max_length=64)),
                ("updated_by_name", models.CharField(blank=True, default="", max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "approval_categories",
                "ordering": ["sort_order", "name", "id"],
                "indexes": [
                    models.Index(
                        fields=["sort_order", "name"],
                        name="idx_appr_cat_order",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ApprovalCategoryPermission",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "permission",
                    models.CharField(
                        choices=[("admin", "管理员权限")],
                        default="admin",
                        max_length=16,
                    ),
                ),
                (
                    "scope_type",
                    models.CharField(
                        choices=[
                            ("department", "部门"),
                            ("departmentSub", "部门及下级"),
                            ("employee", "成员"),
                            ("excludedEmployee", "排除成员"),
                        ],
                        max_length=16,
                    ),
                ),
                ("target_id", models.CharField(max_length=64)),
                ("target_name", models.CharField(blank=True, default="", max_length=255)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_by", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="permission_rules",
                        to="approval_center_api.approvalcategory",
                    ),
                ),
            ],
            options={
                "db_table": "approval_category_permissions",
                "ordering": ["scope_type", "sort_order", "target_name", "target_id"],
                "indexes": [
                    models.Index(
                        fields=["category", "permission"],
                        name="idx_appr_cat_perm",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("category", "permission", "scope_type", "target_id"),
                        name="uniq_appr_category_perm",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="approvaltemplate",
            name="category_order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="approvaltemplate",
            name="category_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="templates",
                to="approval_center_api.approvalcategory",
            ),
        ),
        migrations.RunPython(
            populate_approval_categories,
            unpopulate_approval_categories,
        ),
        migrations.AddIndex(
            model_name="approvaltemplate",
            index=models.Index(
                fields=["category_ref", "category_order"],
                name="idx_appr_tpl_cat_order",
            ),
        ),
    ]
