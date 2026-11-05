from django.db import migrations, models


def collapse_closed_tickets(apps, _schema_editor):
    ticket_model = apps.get_model("after_sales_api", "ServiceTicket")
    for ticket in ticket_model.objects.filter(status="closed").iterator():
        ticket.status = "completed"
        if ticket.completed_at is None:
            ticket.completed_at = ticket.closed_at or ticket.updated_at
        ticket.save(update_fields=["status", "completed_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("after_sales_api", "0013_settlement_related_project"),
    ]

    operations = [
        migrations.RunPython(collapse_closed_tickets, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="serviceticket",
            name="status",
            field=models.CharField(
                choices=[
                    ("open", "待分配"),
                    ("assigned", "已指派"),
                    ("in_progress", "正在执行"),
                    ("pending_review", "待审核"),
                    ("completed", "已完成"),
                    ("rejected", "已驳回"),
                ],
                default="open",
                max_length=20,
            ),
        ),
    ]
