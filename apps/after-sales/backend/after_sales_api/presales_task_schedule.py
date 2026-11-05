from datetime import date
import re

from django.db.models import OuterRef, Subquery

from .models import PresalesTaskSchedule, ProjectNode, ServiceProject


def round_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def sync_presales_task_schedules(node):
    if node.project.service_type != ServiceProject.TYPE_PRESALES or node.kind != "delivery":
        return
    rounds = (node.business_data or {}).get("schemeRounds", [])
    rounds = rounds if isinstance(rounds, list) else []
    existing = {item.round_number: item for item in node.presales_tasks.all()}
    created, changed, numbers = [], [], []
    fields = ("planned_start_date", "planned_end_date", "actual_end_date")
    for number, item in enumerate(rounds, 1):
        if not isinstance(item, dict):
            continue
        numbers.append(number)
        values = [round_date(item.get(key)) for key in ("plannedStartDate", "plannedEndDate", "designDate")]
        task = existing.get(number)
        if task is None:
            created.append(PresalesTaskSchedule(node=node, round_number=number, **dict(zip(fields, values))))
        elif any(getattr(task, field) != value for field, value in zip(fields, values)):
            for field, value in zip(fields, values):
                setattr(task, field, value)
            changed.append(task)
    node.presales_tasks.exclude(round_number__in=numbers).delete()
    if created:
        PresalesTaskSchedule.objects.bulk_create(created, batch_size=200)
    if changed:
        PresalesTaskSchedule.objects.bulk_update(changed, fields, batch_size=200)


def pending_presales_task_schedules():
    return PresalesTaskSchedule.objects.filter(
        node__project__service_type=ServiceProject.TYPE_PRESALES,
        node__project__status__in=[ServiceProject.STATUS_IN_PROGRESS, ServiceProject.STATUS_BLOCKED],
        node__project__deleted_at__isnull=True,
        node__status=ProjectNode.STATUS_ACTIVE, node__enabled=True,
    )


def annotate_presales_task_deadline(projects):
    deadline = pending_presales_task_schedules().filter(
        node__project_id=OuterRef("pk"), planned_end_date__isnull=False,
    ).order_by("planned_end_date", "id").values("planned_end_date")[:1]
    return projects.annotate(presales_task_deadline=Subquery(deadline))
