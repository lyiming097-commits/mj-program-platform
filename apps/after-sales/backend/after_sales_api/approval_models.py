from django.db import models

from .models import AuditedModel


class PresalesApprovalStep(AuditedModel):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待审批"),
        (STATUS_APPROVED, "已通过"),
        (STATUS_REJECTED, "已驳回"),
    ]

    node = models.ForeignKey(
        "after_sales_api.ProjectNode",
        related_name="presales_approval_steps",
        on_delete=models.CASCADE,
    )
    sequence = models.PositiveIntegerField()
    title = models.CharField(max_length=128)
    approver_user_id = models.CharField(max_length=64, blank=True, default="")
    approver_name = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    opinion = models.TextField(blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "presales_approval_steps"
        ordering = ["node_id", "sequence", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["node", "sequence"],
                name="uniq_ps_approval_node_seq",
            ),
        ]
        indexes = [
            models.Index(fields=["node", "status"], name="idx_ps_approval_status"),
        ]


class PresalesApprovalRevision(models.Model):
    step = models.ForeignKey(
        PresalesApprovalStep,
        related_name="revisions",
        on_delete=models.CASCADE,
    )
    revision = models.PositiveIntegerField()
    title = models.CharField(max_length=128)
    approver_user_id = models.CharField(max_length=64, blank=True, default="")
    approver_name = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=PresalesApprovalStep.STATUS_CHOICES)
    opinion = models.TextField(blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    recorded_by_user_id = models.CharField(max_length=64, blank=True, default="")
    recorded_by_name = models.CharField(max_length=128, blank=True, default="")
    recorded_actor_id = models.CharField(max_length=64, blank=True, default="")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "presales_approval_revisions"
        ordering = ["-revision", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["step", "revision"],
                name="uniq_ps_approval_step_rev",
            ),
        ]
        indexes = [
            models.Index(fields=["step", "recorded_at"], name="idx_ps_approval_history"),
        ]
