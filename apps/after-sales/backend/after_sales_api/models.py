from pathlib import Path
import uuid

from django.db import models
from django.utils import timezone


def private_attachment_upload_to(_instance, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    today = timezone.localdate()
    return f"private_attachments/{today:%Y/%m/%d}/{uuid.uuid4().hex}{suffix}"


class AppPermissionRule(models.Model):
    PERMISSION_ADMIN = "admin"
    PERMISSION_SALES = "sales"
    PERMISSION_SERVICE = "service"
    SCOPE_DEPARTMENT = "department"
    SCOPE_DEPARTMENT_WITH_SUB = "departmentSub"
    SCOPE_EMPLOYEE = "employee"
    SCOPE_EXCLUDED_EMPLOYEE = "excludedEmployee"

    PERMISSION_CHOICES = [
        (PERMISSION_ADMIN, "系统管理员"),
        (PERMISSION_SERVICE, "服务管理员"),
        (PERMISSION_SALES, "业务员"),
    ]
    SCOPE_CHOICES = [
        (SCOPE_DEPARTMENT, "部门"),
        (SCOPE_DEPARTMENT_WITH_SUB, "部门及下级"),
        (SCOPE_EMPLOYEE, "成员"),
        (SCOPE_EXCLUDED_EMPLOYEE, "排除成员"),
    ]

    permission = models.CharField(max_length=16, choices=PERMISSION_CHOICES)
    scope_type = models.CharField(max_length=16, choices=SCOPE_CHOICES)
    target_id = models.CharField(max_length=64)
    target_name = models.CharField(max_length=255, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    created_by = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_permission_rules"
        ordering = ["permission", "scope_type", "sort_order", "target_name", "target_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["permission", "scope_type", "target_id"],
                name="uniq_app_perm_rule",
            ),
        ]
        indexes = [models.Index(fields=["permission", "scope_type"], name="idx_app_perm_scope")]


class AppConfigurationRevision(models.Model):
    key = models.CharField(max_length=64, unique=True)
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_configuration_revisions"
        ordering = ["key"]


class AuditedModel(models.Model):
    created_by = models.CharField(max_length=64, blank=True, default="")
    created_actor_id = models.CharField(max_length=64, blank=True, default="")
    updated_by = models.CharField(max_length=64, blank=True, default="")
    updated_actor_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ServiceProvider(AuditedModel):
    IDENTITY_WECHAT_MINI = "wechat-mini"
    IDENTITY_DINGTALK = "dingtalk"
    IDENTITY_CHOICES = [
        (IDENTITY_WECHAT_MINI, "微信小程序"),
        (IDENTITY_DINGTALK, "钉钉历史档案"),
    ]
    ROLE_INSTALLER = "installer"
    ROLE_MAINTENANCE = "maintenance"
    ROLE_SUPPORT = "support"
    ROLE_PARTNER = "partner"
    ROLE_CHOICES = [
        (ROLE_INSTALLER, "安装/调试人员"),
        (ROLE_MAINTENANCE, "售后维修人员"),
        (ROLE_SUPPORT, "技术支持人员"),
        (ROLE_PARTNER, "第三方合作资源"),
    ]
    CERT_PENDING = "pending"
    CERT_CERTIFIED = "certified"
    CERT_PAUSED = "paused"
    CERT_CHOICES = [
        (CERT_PENDING, "待审核"),
        (CERT_CERTIFIED, "已认证"),
        (CERT_PAUSED, "暂停"),
    ]

    auth_user_id = models.CharField(max_length=64, unique=True)
    identity_source = models.CharField(
        max_length=16,
        choices=IDENTITY_CHOICES,
        default=IDENTITY_WECHAT_MINI,
    )
    name = models.CharField(max_length=128)
    role = models.CharField(max_length=24, choices=ROLE_CHOICES, default=ROLE_INSTALLER)
    phone = models.CharField(max_length=32, blank=True, default="")
    city = models.CharField(max_length=64, blank=True, default="")
    regions = models.JSONField(default=list, blank=True)
    skills = models.JSONField(default=list, blank=True)
    certification_status = models.CharField(max_length=16, choices=CERT_CHOICES, default=CERT_PENDING)
    score = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    month_orders = models.PositiveIntegerField(default=0)
    total_orders = models.PositiveIntegerField(default=0)
    bio = models.TextField(blank=True, default="")
    last_active_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "service_providers"
        ordering = ["name", "auth_user_id"]
        indexes = [
            models.Index(fields=["certification_status", "role"], name="idx_provider_cert_role"),
            models.Index(fields=["city"], name="idx_provider_city"),
        ]


class ServiceProject(AuditedModel):
    TYPE_PRESALES = "presales"
    TYPE_MIDSALES = "midsales"
    TYPE_AFTERSALES = "aftersales"
    TYPE_CHOICES = [
        (TYPE_PRESALES, "售前服务"),
        (TYPE_MIDSALES, "售中服务"),
        (TYPE_AFTERSALES, "售后服务"),
    ]
    STATUS_DRAFT = "draft"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_BLOCKED = "blocked"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "草稿"),
        (STATUS_IN_PROGRESS, "进行中"),
        (STATUS_BLOCKED, "异常跟进"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_CANCELLED, "已取消"),
    ]

    code = models.CharField(max_length=40, unique=True)
    service_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    name = models.CharField(max_length=255)
    customer = models.CharField(max_length=255)
    owner_user_id = models.CharField(max_length=64, blank=True, default="")
    owner_name = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)
    current_node_key = models.CharField(max_length=64, blank=True, default="")
    address = models.CharField(max_length=500, blank=True, default="")
    province = models.CharField(max_length=64, blank=True, default="")
    planned_start_date = models.DateField(null=True, blank=True)
    planned_end_date = models.DateField(null=True, blank=True)
    actual_start_date = models.DateField(null=True, blank=True)
    actual_end_date = models.DateField(null=True, blank=True)
    summary = models.TextField(blank=True, default="")
    business_data = models.JSONField(default=dict, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.CharField(max_length=64, blank=True, default="")

    source_crm_id = models.CharField(max_length=64, blank=True, default="")
    crm_snapshot = models.JSONField(default=dict, blank=True)
    crm_synced_at = models.DateTimeField(null=True, blank=True)
    presales_project = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="midsales_project",
    )

    class Meta:
        db_table = "service_projects"
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["service_type", "source_crm_id"],
                condition=~models.Q(source_crm_id=""),
                name="unique_project_crm_source_type",
            ),
        ]
        indexes = [
            models.Index(fields=["service_type", "status"], name="idx_project_type_status"),
            models.Index(fields=["owner_user_id"], name="idx_project_owner"),
            models.Index(fields=["deleted_at"], name="idx_project_deleted"),
        ]


class ProjectNode(AuditedModel):
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = [
        (STATUS_PENDING, "未开始"),
        (STATUS_ACTIVE, "进行中"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_SKIPPED, "不包含"),
    ]

    project = models.ForeignKey(ServiceProject, related_name="nodes", on_delete=models.CASCADE)
    node_key = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=32, blank=True, default="delivery")
    description = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    planned_start_at = models.DateTimeField(null=True, blank=True)
    planned_end_at = models.DateTimeField(null=True, blank=True)
    actual_start_at = models.DateTimeField(null=True, blank=True)
    actual_end_at = models.DateTimeField(null=True, blank=True)
    estimated_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    business_data = models.JSONField(default=dict, blank=True)
    completed_by = models.CharField(max_length=64, blank=True, default="")
    completed_actor_id = models.CharField(max_length=64, blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "project_nodes"
        ordering = ["project_id", "sequence", "id"]
        constraints = [
            models.UniqueConstraint(fields=["project", "node_key"], name="uniq_project_node_key"),
            models.UniqueConstraint(fields=["project", "sequence"], name="uniq_project_node_seq"),
        ]
        indexes = [models.Index(fields=["project", "status"], name="idx_node_project_status")]


class PresalesTaskSchedule(models.Model):
    """Queryable schedule for a node's JSON progress round, rebuilt on save."""

    node = models.ForeignKey(ProjectNode, related_name="presales_tasks", on_delete=models.CASCADE)
    round_number = models.PositiveIntegerField()
    planned_start_date = models.DateField(null=True, blank=True)
    planned_end_date = models.DateField(null=True, blank=True)
    actual_end_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "presales_task_schedules"
        ordering = ["round_number"]
        constraints = [models.UniqueConstraint(fields=["node", "round_number"], name="uniq_presales_task_round")]
        indexes = [models.Index(fields=["actual_end_date", "planned_end_date"], name="idx_presales_task_deadline")]


class ProjectAssignment(AuditedModel):
    STATUS_ASSIGNED = "assigned"
    STATUS_ACCEPTED = "accepted"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_ASSIGNED, "已指派"),
        (STATUS_ACCEPTED, "已接受"),
        (STATUS_IN_PROGRESS, "执行中"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_CANCELLED, "已取消"),
    ]

    project = models.ForeignKey(ServiceProject, related_name="assignments", on_delete=models.CASCADE)
    node = models.ForeignKey(ProjectNode, related_name="assignments", on_delete=models.CASCADE)
    provider = models.ForeignKey(ServiceProvider, related_name="assignments", on_delete=models.PROTECT)
    role = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ASSIGNED)
    planned_start_date = models.DateField(null=True, blank=True)
    standard_duration = models.CharField(max_length=64, blank=True, default="")
    assigned_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "project_assignments"
        ordering = ["-assigned_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["project", "node", "provider"], name="uniq_project_node_provider"),
        ]
        indexes = [
            models.Index(fields=["provider", "status"], name="idx_assignment_provider"),
            models.Index(fields=["project", "node"], name="idx_assignment_project_node"),
        ]


class ServiceRating(AuditedModel):
    assignment = models.OneToOneField(
        ProjectAssignment,
        related_name="service_rating",
        on_delete=models.CASCADE,
    )
    rating = models.PositiveSmallIntegerField()

    class Meta:
        db_table = "service_ratings"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="service_rating_between_1_and_5",
            ),
        ]


class MidsalesProof(AuditedModel):
    TYPE_PROCESS = "process"
    TYPE_COMPLETION = "completion"
    TYPE_EVALUATION = "evaluation"
    TYPE_CHOICES = [
        (TYPE_PROCESS, "过程证明照片"),
        (TYPE_COMPLETION, "完工证明照片"),
        (TYPE_EVALUATION, "用户评价文件"),
    ]
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "未处理"),
        (STATUS_APPROVED, "通过"),
        (STATUS_REJECTED, "驳回"),
    ]

    node = models.ForeignKey(ProjectNode, related_name="midsales_proofs", on_delete=models.CASCADE)
    proof_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    review_opinion = models.TextField(blank=True, default="")
    reviewed_by_user_id = models.CharField(max_length=64, blank=True, default="")
    reviewed_by_name = models.CharField(max_length=128, blank=True, default="")
    reviewed_actor_id = models.CharField(max_length=64, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "midsales_proofs"
        ordering = ["node_id", "proof_type", "id"]
        constraints = [
            models.UniqueConstraint(fields=["node", "proof_type"], name="uniq_midsales_node_proof"),
        ]
        indexes = [models.Index(fields=["node", "status"], name="idx_midsales_proof_status")]


class ProjectEvent(models.Model):
    project = models.ForeignKey(ServiceProject, related_name="events", on_delete=models.CASCADE)
    node = models.ForeignKey(ProjectNode, null=True, blank=True, related_name="events", on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    detail = models.TextField(blank=True, default="")
    before_values = models.JSONField(default=dict, blank=True)
    after_values = models.JSONField(default=dict, blank=True)
    auth_user_id = models.CharField(max_length=64, blank=True, default="")
    auth_user_name = models.CharField(max_length=128, blank=True, default="")
    actor_user_id = models.CharField(max_length=64, blank=True, default="")
    actor_name = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "project_events"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["project", "created_at"], name="idx_event_project_time"),
            models.Index(fields=["event_type"], name="idx_event_type"),
        ]


class ProjectMessage(models.Model):
    TYPE_TEXT = "text"
    TYPE_SYSTEM = "system"
    TYPE_CHOICES = [
        (TYPE_TEXT, "文本消息"),
        (TYPE_SYSTEM, "系统消息"),
    ]

    project = models.ForeignKey(ServiceProject, related_name="messages", on_delete=models.CASCADE)
    node = models.ForeignKey(
        ProjectNode,
        null=True,
        blank=True,
        related_name="messages",
        on_delete=models.SET_NULL,
    )
    author_user_id = models.CharField(max_length=64)
    author_name = models.CharField(max_length=128, blank=True, default="")
    actor_user_id = models.CharField(max_length=64, blank=True, default="")
    message_type = models.CharField(max_length=24, choices=TYPE_CHOICES, default=TYPE_TEXT)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "project_messages"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["project", "node", "created_at"], name="idx_project_msg_chat"),
            models.Index(fields=["author_user_id", "created_at"], name="idx_project_msg_author"),
        ]


class ProjectMessageRead(models.Model):
    message = models.ForeignKey(ProjectMessage, related_name="read_receipts", on_delete=models.CASCADE)
    user_id = models.CharField(max_length=64)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "project_message_reads"
        ordering = ["read_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["message", "user_id"], name="uniq_project_msg_read"),
        ]
        indexes = [
            models.Index(fields=["user_id", "read_at"], name="idx_project_msg_reader"),
        ]


class ServiceTicket(AuditedModel):
    PRIORITY_LOW = "low"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_HIGH = "high"
    PRIORITY_CHOICES = [(PRIORITY_LOW, "低"), (PRIORITY_MEDIUM, "中"), (PRIORITY_HIGH, "高")]
    STATUS_OPEN = "open"
    STATUS_ASSIGNED = "assigned"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_PENDING_REVIEW = "pending_review"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_OPEN, "待分配"),
        (STATUS_ASSIGNED, "已指派"),
        (STATUS_IN_PROGRESS, "正在执行"),
        (STATUS_PENDING_REVIEW, "待审核"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_REJECTED, "已驳回"),
    ]

    code = models.CharField(max_length=40, unique=True)
    project = models.ForeignKey(ServiceProject, related_name="tickets", on_delete=models.PROTECT)
    node = models.ForeignKey(ProjectNode, null=True, blank=True, related_name="tickets", on_delete=models.SET_NULL)
    title = models.CharField(max_length=255)
    ticket_type = models.CharField(max_length=64)
    priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    owner_user_id = models.CharField(max_length=64, blank=True, default="")
    owner_name = models.CharField(max_length=128, blank=True, default="")
    reporter_user_id = models.CharField(max_length=64)
    reporter_name = models.CharField(max_length=128, blank=True, default="")
    description = models.TextField()
    resolution = models.TextField(blank=True, default="")
    business_data = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "service_tickets"
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["project", "status"], name="idx_ticket_project_status"),
            models.Index(fields=["owner_user_id", "status"], name="idx_ticket_owner_status"),
            models.Index(fields=["ticket_type", "priority"], name="idx_ticket_type_priority"),
        ]


class TicketMessage(models.Model):
    ticket = models.ForeignKey(ServiceTicket, related_name="messages", on_delete=models.CASCADE)
    author_user_id = models.CharField(max_length=64)
    author_name = models.CharField(max_length=128, blank=True, default="")
    actor_user_id = models.CharField(max_length=64, blank=True, default="")
    message_type = models.CharField(max_length=24, default="text")
    content = models.TextField()
    status_snapshot = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_messages"
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["ticket", "created_at"], name="idx_ticket_message_time")]


class FieldFeedback(AuditedModel):
    TYPE_ISSUE = "issue"
    TYPE_RESOURCE = "resource_suggestion"
    TYPE_REWARD = "reward_application"
    TYPE_REPORT = "service_report"
    TYPE_CHOICES = [
        (TYPE_ISSUE, "现场问题"),
        (TYPE_RESOURCE, "资料建议"),
        (TYPE_REWARD, "奖励申请"),
        (TYPE_REPORT, "服务反馈"),
    ]
    STATUS_SUBMITTED = "submitted"
    STATUS_REVIEWING = "under_review"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_SUBMITTED, "待审核"),
        (STATUS_REVIEWING, "审核中"),
        (STATUS_ACCEPTED, "已采纳"),
        (STATUS_REJECTED, "未采纳"),
    ]

    project = models.ForeignKey(ServiceProject, related_name="feedback_entries", on_delete=models.PROTECT)
    node = models.ForeignKey(ProjectNode, null=True, blank=True, related_name="feedback_entries", on_delete=models.SET_NULL)
    provider = models.ForeignKey(ServiceProvider, related_name="feedback_entries", on_delete=models.PROTECT)
    title = models.CharField(max_length=255, blank=True, default="")
    feedback_type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    content = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SUBMITTED)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    review_note = models.TextField(blank=True, default="")
    reviewed_by = models.CharField(max_length=64, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reward_generated = models.BooleanField(default=False)
    business_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "field_feedback"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["provider", "status"], name="idx_feedback_provider"),
            models.Index(fields=["project", "feedback_type"], name="idx_feedback_project_type"),
        ]


class RewardPrize(AuditedModel):
    name = models.CharField(max_length=255, unique=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "reward_prizes"
        ordering = ["id"]


class Reward(AuditedModel):
    TYPE_PRIZE = "prize"
    TYPE_CASH = "cash"
    TYPE_POINTS = "points"
    TYPE_TIME_OFF = "time_off"
    TYPE_CHOICES = [
        (TYPE_PRIZE, "实物奖励"),
        (TYPE_CASH, "现金奖励"),
        (TYPE_POINTS, "积分奖励"),
        (TYPE_TIME_OFF, "调休奖励"),
    ]
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_ISSUED = "issued"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待审核"),
        (STATUS_APPROVED, "待发放"),
        (STATUS_ISSUED, "已发放"),
        (STATUS_REJECTED, "已驳回"),
    ]

    code = models.CharField(max_length=40, unique=True)
    provider = models.ForeignKey(ServiceProvider, related_name="rewards", on_delete=models.PROTECT)
    project = models.ForeignKey(ServiceProject, null=True, blank=True, related_name="rewards", on_delete=models.SET_NULL)
    feedback = models.OneToOneField(FieldFeedback, null=True, blank=True, related_name="reward", on_delete=models.SET_NULL)
    reward_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_PRIZE)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    points = models.PositiveIntegerField(default=0)
    prize = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    issued_at = models.DateTimeField(null=True, blank=True)
    transition_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "service_rewards"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["provider", "status"], name="idx_reward_provider"),
            models.Index(fields=["status", "reward_type"], name="idx_reward_status_type"),
        ]


class Settlement(AuditedModel):
    BEARER_CUSTOMER = "customer"
    BEARER_COMPANY = "company"
    BEARER_CHOICES = [(BEARER_CUSTOMER, "客户承担"), (BEARER_COMPANY, "公司承担")]
    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_SETTLED = "settled"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "草稿"),
        (STATUS_PENDING, "待结算"),
        (STATUS_SETTLED, "已结算"),
        (STATUS_CANCELLED, "已取消"),
    ]

    code = models.CharField(max_length=40, unique=True)
    project = models.ForeignKey(ServiceProject, related_name="settlements", on_delete=models.PROTECT)
    related_project = models.ForeignKey(
        ServiceProject,
        null=True,
        blank=True,
        related_name="related_settlements",
        on_delete=models.SET_NULL,
    )
    source_node = models.ForeignKey(
        ProjectNode,
        null=True,
        blank=True,
        related_name="settlements",
        on_delete=models.PROTECT,
    )
    source_assignment = models.ForeignKey(
        ProjectAssignment,
        null=True,
        blank=True,
        related_name="settlements",
        on_delete=models.PROTECT,
    )
    service_type = models.CharField(max_length=16, choices=ServiceProject.TYPE_CHOICES)
    customer = models.CharField(max_length=255)
    bearer = models.CharField(max_length=16, choices=BEARER_CHOICES)
    service_content = models.TextField()
    budget_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    final_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    order_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    received_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    invoice_due_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    invoiced_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    invoice_type = models.CharField(max_length=64, blank=True, default="")
    invoice_number = models.CharField(max_length=128, blank=True, default="")
    subject_type = models.CharField(max_length=32, blank=True, default="")
    subject_name = models.CharField(max_length=255, blank=True, default="")
    subject_id = models.CharField(max_length=64, blank=True, default="")
    external_quote = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    revision = models.PositiveBigIntegerField(default=1)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    remark = models.TextField(blank=True, default="")

    class Meta:
        db_table = "service_settlements"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_node"],
                condition=models.Q(source_node__isnull=False) & ~models.Q(status="cancelled"),
                name="uniq_settle_source_node",
            ),
            models.UniqueConstraint(
                fields=["source_assignment"],
                condition=models.Q(source_assignment__isnull=False) & ~models.Q(status="cancelled"),
                name="uniq_settle_source_assign",
            ),
        ]
        indexes = [
            models.Index(fields=["service_type", "status"], name="idx_settle_type_status"),
            models.Index(fields=["project", "status"], name="idx_settle_project_status"),
        ]


class SettlementEvent(AuditedModel):
    """Append-only financial changes; opening rows are historical balances, not new cash."""

    settlement = models.ForeignKey(Settlement, related_name="events", on_delete=models.PROTECT)
    revision = models.PositiveBigIntegerField()
    kind = models.CharField(max_length=24)
    operator_name = models.CharField(max_length=255, blank=True, default="")
    actor_name = models.CharField(max_length=255, blank=True, default="")
    receipt_delta = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    invoice_delta = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reason = models.TextField(blank=True, default="")
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)

    class Meta:
        db_table = "service_settlement_events"
        ordering = ["-revision", "-id"]
        constraints = [models.UniqueConstraint(fields=["settlement", "revision"], name="uniq_settlement_event_revision")]


class ServiceResource(AuditedModel):
    TYPE_VIDEO = "video"
    TYPE_WIRING = "wiring"
    TYPE_MANUAL = "manual"
    TYPE_DEBUG = "debug"
    TYPE_TRAINING = "training"
    TYPE_OTHER = "other"
    TYPE_CHOICES = [
        (TYPE_VIDEO, "安装视频"),
        (TYPE_WIRING, "接线说明"),
        (TYPE_MANUAL, "产品资料"),
        (TYPE_DEBUG, "调试资料"),
        (TYPE_TRAINING, "培训资料"),
        (TYPE_OTHER, "其他资料"),
    ]
    AUDIENCE_PUBLIC = "public"
    AUDIENCE_ASSIGNED = "assigned"
    AUDIENCE_ADMIN = "admin"
    AUDIENCE_CHOICES = [
        (AUDIENCE_PUBLIC, "公开"),
        (AUDIENCE_ASSIGNED, "项目指派人员"),
        (AUDIENCE_ADMIN, "仅管理员"),
    ]

    project = models.ForeignKey(ServiceProject, null=True, blank=True, related_name="resources", on_delete=models.CASCADE)
    node_key = models.CharField(max_length=64, blank=True, default="")
    title = models.CharField(max_length=255)
    resource_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    audience = models.CharField(max_length=16, choices=AUDIENCE_CHOICES, default=AUDIENCE_ASSIGNED)
    summary = models.TextField(blank=True, default="")
    content = models.TextField(blank=True, default="")
    external_url = models.URLField(max_length=500, blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)
    authorization_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "service_resources"
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["project", "node_key"], name="idx_resource_project_node"),
            models.Index(fields=["resource_type", "enabled"], name="idx_resource_type_enabled"),
        ]


class ServiceCapabilityTag(AuditedModel):
    service_type = models.CharField(max_length=16, choices=ServiceProject.TYPE_CHOICES)
    node_key = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "service_capability_tags"
        ordering = ["service_type", "node_key", "sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["service_type", "node_key", "name"],
                name="uniq_capability_node_name",
            ),
        ]
        indexes = [
            models.Index(
                fields=["service_type", "node_key", "sort_order"],
                name="idx_capability_node_sort",
            ),
        ]


class ProviderTag(AuditedModel):
    name = models.CharField(max_length=128, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "provider_tags"
        ordering = ["sort_order", "name", "id"]


class WorkflowCase(AuditedModel):
    TYPE_COMPLAINT = "complaint"
    TYPE_SUPPORT = "support"
    TYPE_REWARD_APPLICATION = "reward_application"
    TYPE_CHOICES = [
        (TYPE_COMPLAINT, "提议事项"),
        (TYPE_SUPPORT, "求助事项"),
        (TYPE_REWARD_APPLICATION, "奖励申请"),
    ]
    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待受理"),
        (STATUS_PROCESSING, "处理中"),
        (STATUS_AWAITING_CONFIRMATION, "待确认"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_REJECTED, "已驳回"),
    ]

    code = models.CharField(max_length=40, unique=True)
    case_type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    title = models.CharField(max_length=255)
    applicant_user_id = models.CharField(max_length=64)
    applicant_name = models.CharField(max_length=128, blank=True, default="")
    target_user_id = models.CharField(max_length=64, blank=True, default="")
    target_name = models.CharField(max_length=128, blank=True, default="")
    category = models.CharField(max_length=128, blank=True, default="")
    urgency = models.CharField(max_length=16, default="normal")
    content = models.TextField()
    handler_user_id = models.CharField(max_length=64, blank=True, default="")
    handler_name = models.CharField(max_length=128, blank=True, default="")
    current_step = models.CharField(max_length=32, default="raise")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    result = models.TextField(blank=True, default="")
    round = models.PositiveIntegerField(default=1)
    business_data = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workflow_cases"
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["case_type", "status"], name="idx_case_type_status"),
            models.Index(fields=["applicant_user_id"], name="idx_case_applicant"),
            models.Index(fields=["handler_user_id", "status"], name="idx_case_handler"),
        ]


class PrivateAttachment(models.Model):
    TARGET_TICKET = "ticket"
    TARGET_FEEDBACK = "feedback"
    TARGET_PROJECT_NODE = "project_node"
    TARGET_PRESALES_PROJECT = "presales_project"
    TARGET_RESOURCE = "resource"
    TARGET_CASE = "case"
    TARGET_PROVIDER_APPLICATION = "provider_application"
    TARGET_MIDSALES_PROOF = "midsales_proof"
    TARGET_CHOICES = [
        (TARGET_TICKET, "服务工单"),
        (TARGET_FEEDBACK, "现场反馈"),
        (TARGET_PROJECT_NODE, "项目节点"),
        (TARGET_PRESALES_PROJECT, "售前项目需求文档"),
        (TARGET_RESOURCE, "服务资料"),
        (TARGET_CASE, "流程事项"),
        (TARGET_PROVIDER_APPLICATION, "服务商申请"),
        (TARGET_MIDSALES_PROOF, "售中证明材料"),
    ]

    CATEGORY_GENERAL = "general"
    CATEGORY_FEE_ESTIMATED = "fee_estimated"
    CATEGORY_FEE_ACTUAL = "fee_actual"
    CATEGORY_SCHEME_SUBMISSION = "scheme_submission"
    CATEGORY_PACKAGE = "package"
    CATEGORY_MODEL_LABEL = "model_label"
    CATEGORY_APPEARANCE = "appearance"
    CATEGORY_INSTALLATION = "installation"
    CATEGORY_DEBUGGING = "debugging"
    CATEGORY_OTHER = "other"
    CATEGORY_QUALIFICATION = "qualification"
    CATEGORY_CHOICES = [
        (CATEGORY_GENERAL, "普通附件"),
        (CATEGORY_FEE_ESTIMATED, "预计费用清单"),
        (CATEGORY_FEE_ACTUAL, "实际费用清单"),
        (CATEGORY_SCHEME_SUBMISSION, "方案提交附件"),
        (CATEGORY_PACKAGE, "包装照片"),
        (CATEGORY_MODEL_LABEL, "型号标签"),
        (CATEGORY_APPEARANCE, "产品外观"),
        (CATEGORY_INSTALLATION, "安装完成"),
        (CATEGORY_DEBUGGING, "调试完成"),
        (CATEGORY_OTHER, "其他附件"),
        (CATEGORY_QUALIFICATION, "资质证明"),
    ]

    target_type = models.CharField(max_length=32, choices=TARGET_CHOICES)
    target_id = models.PositiveBigIntegerField()
    category = models.CharField(max_length=24, choices=CATEGORY_CHOICES, default=CATEGORY_GENERAL)
    file = models.FileField(upload_to=private_attachment_upload_to, max_length=500)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=127)
    size = models.PositiveBigIntegerField()
    uploaded_by = models.CharField(max_length=64)
    uploaded_actor_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "private_attachments"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["target_type", "target_id"], name="idx_attachment_target"),
            models.Index(fields=["uploaded_by"], name="idx_attachment_uploader"),
        ]


# Approval models live separately so their append-only history stays isolated
# from the core project schema.
from .approval_models import PresalesApprovalRevision, PresalesApprovalStep  # noqa: E402,F401
