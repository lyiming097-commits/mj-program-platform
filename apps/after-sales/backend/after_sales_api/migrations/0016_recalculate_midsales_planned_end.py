import math
import re
from datetime import timedelta

from django.db import migrations


def recalculate_midsales_planned_end(apps, _schema_editor):
    project_model = apps.get_model("after_sales_api", "ServiceProject")
    assignment_model = apps.get_model("after_sales_api", "ProjectAssignment")
    node_model = apps.get_model("after_sales_api", "ProjectNode")

    for project in project_model.objects.filter(service_type="midsales", deleted_at__isnull=True):
        nodes = node_model.objects.filter(project_id=project.id, actual_start_at__isnull=False)
        for node in nodes:
            assignment = assignment_model.objects.filter(
                project_id=project.id,
                node_id=node.id,
            ).exclude(status="cancelled").order_by("-id").first()
            match = re.search(r"\d+(?:\.\d+)?", str(getattr(assignment, "standard_duration", "") or ""))
            if not match:
                continue
            try:
                duration = max(1, math.ceil(float(match.group(0))))
            except (TypeError, ValueError):
                continue
            planned_end = node.actual_start_at + timedelta(days=duration)
            if node.planned_end_at == planned_end:
                continue
            node.planned_end_at = planned_end
            node.save(update_fields=["planned_end_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("after_sales_api", "0015_gate_midsales_node_start"),
    ]

    operations = [
        migrations.RunPython(recalculate_midsales_planned_end, migrations.RunPython.noop),
    ]
