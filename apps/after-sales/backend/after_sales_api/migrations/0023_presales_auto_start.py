from django.db import migrations


# Freeze the flow used by this data migration; future workflow changes must not
# alter which historical nodes were eligible to start.
DEPENDENCIES = {
    "early-approval": (),
    "early-plan": ("early-approval",),
    "budget-match": ("early-approval",),
    "project-filing": ("budget-match",),
    "early-plan-result": ("early-plan", "project-filing"),
    "late-approval": ("early-plan-result",),
    "late-plan": ("late-approval",),
    "device-plan": ("late-approval",),
    "budget": ("late-plan",),
    "device-budget": ("device-plan",),
    "cost-control": ("budget",),
    "device-cost-control": ("device-budget",),
    "rendering": ("cost-control",),
    "tender-plan": ("device-cost-control",),
    "layout": ("rendering",),
    "bid-prep": ("tender-plan",),
    "construction-result": ("layout", "bid-prep"),
    "construction": ("construction-result",),
    "project-end": ("construction",),
}
SUCCESS_OUTCOMES = {
    "early-approval": "approved", "late-approval": "approved",
    "early-plan-result": "passed", "construction-result": "won",
}


def backfill_presales_starts(apps, schema_editor):
    Project = apps.get_model("after_sales_api", "ServiceProject")
    Node = apps.get_model("after_sales_api", "ProjectNode")
    database = schema_editor.connection.alias
    projects = Project.objects.using(database).filter(
        service_type="presales", status="in_progress", deleted_at__isnull=True,
        nodes__status="active", nodes__enabled=True, nodes__actual_start_at__isnull=True,
    ).distinct().prefetch_related("nodes")
    changed = []
    for project in projects.iterator(chunk_size=100):
        nodes = list(project.nodes.all())
        by_key = {node.node_key: node for node in nodes}
        for node in nodes:
            if not node.enabled or node.status != "active" or node.actual_start_at is not None:
                continue
            keys = DEPENDENCIES.get(node.node_key)
            if keys is None or any(key not in by_key for key in keys):
                continue
            prerequisites = [by_key[key] for key in keys if by_key[key].enabled]
            successful = all(
                (parent.business_data or {}).get("outcome") == SUCCESS_OUTCOMES[parent.node_key]
                if parent.node_key in SUCCESS_OUTCOMES else parent.status == "completed"
                for parent in prerequisites
            )
            if not successful:
                continue
            times = [parent.completed_at or parent.actual_end_at for parent in prerequisites]
            if any(stamp is None for stamp in times):
                continue
            started = max(times) if times else node.created_at
            if node.actual_end_at and started > node.actual_end_at:
                continue
            node.actual_start_at = started
            changed.append(node)
    if changed:
        Node.objects.using(database).bulk_update(changed, ["actual_start_at"], batch_size=200)


class Migration(migrations.Migration):
    dependencies = [("after_sales_api", "0022_crm_presales_source")]
    operations = [migrations.RunPython(backfill_presales_starts, migrations.RunPython.noop)]
