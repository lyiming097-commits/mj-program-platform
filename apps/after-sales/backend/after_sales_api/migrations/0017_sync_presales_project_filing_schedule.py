import math
import re
from datetime import timedelta

from django.db import migrations


def sync_project_filing_schedule(apps, _schema_editor):
    assignment_model = apps.get_model("after_sales_api", "ProjectAssignment")
    project_model = apps.get_model("after_sales_api", "ServiceProject")

    for project in project_model.objects.filter(service_type="presales", deleted_at__isnull=True):
        budget = assignment_model.objects.filter(
            project_id=project.id,
            node__node_key="budget-match",
        ).exclude(status="cancelled").order_by("-id").first()
        if budget is None or budget.planned_start_date is None:
            continue
        match = re.search(r"\d+(?:\.\d+)?", str(budget.standard_duration or ""))
        if not match:
            continue
        duration = max(1, math.ceil(float(match.group(0))))
        assignment_model.objects.filter(
            project_id=project.id,
            node__node_key="project-filing",
        ).exclude(status="cancelled").update(
            planned_start_date=budget.planned_start_date + timedelta(days=duration),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("after_sales_api", "0016_recalculate_midsales_planned_end"),
    ]

    operations = [
        migrations.RunPython(sync_project_filing_schedule, migrations.RunPython.noop),
    ]
