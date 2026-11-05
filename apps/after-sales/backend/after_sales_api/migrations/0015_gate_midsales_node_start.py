from django.db import migrations


def gate_midsales_node_start(apps, _schema_editor):
    project_model = apps.get_model("after_sales_api", "ServiceProject")
    node_model = apps.get_model("after_sales_api", "ProjectNode")

    for project in project_model.objects.filter(service_type="midsales", deleted_at__isnull=True):
        nodes = list(node_model.objects.filter(project_id=project.id).order_by("sequence", "id"))
        for node in nodes:
            if not node.enabled:
                node.status = "skipped"
            elif node.node_key != project.current_node_key and node.status == "active":
                node.status = "pending"
            elif (
                node.node_key == project.current_node_key
                and node.kind != "approval"
                and node.actual_start_at is None
            ):
                node.status = "pending"
            else:
                continue
            node.save(update_fields=["status"])


class Migration(migrations.Migration):
    dependencies = [
        ("after_sales_api", "0014_collapse_closed_ticket_status"),
    ]

    operations = [
        migrations.RunPython(gate_midsales_node_start, migrations.RunPython.noop),
    ]
