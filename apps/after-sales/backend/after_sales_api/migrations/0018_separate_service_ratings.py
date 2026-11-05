from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_ratings(apps, _schema_editor):
    assignment_model = apps.get_model("after_sales_api", "ProjectAssignment")
    feedback_model = apps.get_model("after_sales_api", "FieldFeedback")
    provider_model = apps.get_model("after_sales_api", "ServiceProvider")
    rating_model = apps.get_model("after_sales_api", "ServiceRating")

    legacy = feedback_model.objects.filter(
        feedback_type="service_report",
        status="accepted",
        rating__isnull=False,
    ).order_by("id")
    for feedback in legacy.iterator():
        if not 1 <= feedback.rating <= 5 or feedback.node_id is None:
            continue
        assignment = assignment_model.objects.filter(
            project_id=feedback.project_id,
            node_id=feedback.node_id,
            provider_id=feedback.provider_id,
        ).exclude(status="cancelled").order_by("-id").first()
        if assignment is None:
            continue
        rating_model.objects.update_or_create(
            assignment_id=assignment.id,
            defaults={
                "rating": feedback.rating,
                "created_by": feedback.created_by,
                "created_actor_id": feedback.created_actor_id,
                "updated_by": feedback.updated_by,
                "updated_actor_id": feedback.updated_actor_id,
            },
        )

    for provider in provider_model.objects.all().iterator():
        values = list(rating_model.objects.filter(
            assignment__provider_id=provider.id,
        ).values_list("rating", flat=True))
        if not values:
            continue
        provider.score = (Decimal(sum(values)) / Decimal(len(values))).quantize(Decimal("0.01"))
        provider.save(update_fields=["score"])


class Migration(migrations.Migration):
    dependencies = [
        ("after_sales_api", "0017_sync_presales_project_filing_schedule"),
    ]

    operations = [
        migrations.CreateModel(
            name="ServiceRating",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_by", models.CharField(blank=True, default="", max_length=64)),
                ("created_actor_id", models.CharField(blank=True, default="", max_length=64)),
                ("updated_by", models.CharField(blank=True, default="", max_length=64)),
                ("updated_actor_id", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("rating", models.PositiveSmallIntegerField()),
                ("assignment", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="service_rating", to="after_sales_api.projectassignment")),
            ],
            options={
                "db_table": "service_ratings",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="servicerating",
            constraint=models.CheckConstraint(
                condition=models.Q(("rating__gte", 1), ("rating__lte", 5)),
                name="service_rating_between_1_and_5",
            ),
        ),
        migrations.RunPython(migrate_legacy_ratings, migrations.RunPython.noop),
    ]
