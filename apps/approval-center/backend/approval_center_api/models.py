from django.db import models


class AppPermissionRule(models.Model):
    PERMISSION_ADMIN = "admin"
    SCOPE_DEPARTMENT = "department"
    SCOPE_DEPARTMENT_WITH_SUB = "departmentSub"
    SCOPE_EMPLOYEE = "employee"

    PERMISSION_CHOICES = [
        (PERMISSION_ADMIN, "管理员权限"),
    ]
    SCOPE_CHOICES = [
        (SCOPE_DEPARTMENT, "部门"),
        (SCOPE_DEPARTMENT_WITH_SUB, "部门及下级"),
        (SCOPE_EMPLOYEE, "成员"),
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
        indexes = [
            models.Index(fields=["permission", "scope_type"], name="idx_app_perm_scope"),
        ]


class AppConfigurationRevision(models.Model):
    key = models.CharField(max_length=64, unique=True)
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "app_configuration_revisions"
        ordering = ["key"]


class ApprovalCategory(models.Model):
    """A manageable group of approval templates.

    ``ApprovalTemplate.category`` remains as a denormalized label for backward
    compatibility with existing clients and published versions. ``category_ref``
    is the canonical relationship used by the management APIs.
    """

    name = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    created_by = models.CharField(max_length=64, blank=True, default="")
    created_by_name = models.CharField(max_length=128, blank=True, default="")
    updated_by = models.CharField(max_length=64, blank=True, default="")
    updated_by_name = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approval_categories"
        ordering = ["sort_order", "name", "id"]
        indexes = [
            models.Index(fields=["sort_order", "name"], name="idx_appr_cat_order"),
        ]


class ApprovalCategoryPermission(models.Model):
    """Management permission rules scoped to one approval category."""

    PERMISSION_ADMIN = "admin"
    SCOPE_DEPARTMENT = "department"
    SCOPE_DEPARTMENT_WITH_SUB = "departmentSub"
    SCOPE_EMPLOYEE = "employee"
    PERMISSION_CHOICES = [(PERMISSION_ADMIN, "管理员权限")]
    SCOPE_CHOICES = [
        (SCOPE_DEPARTMENT, "部门"),
        (SCOPE_DEPARTMENT_WITH_SUB, "部门及下级"),
        (SCOPE_EMPLOYEE, "成员"),
    ]

    category = models.ForeignKey(
        ApprovalCategory,
        related_name="permission_rules",
        on_delete=models.CASCADE,
    )
    permission = models.CharField(
        max_length=16,
        choices=PERMISSION_CHOICES,
        default=PERMISSION_ADMIN,
    )
    scope_type = models.CharField(max_length=16, choices=SCOPE_CHOICES)
    target_id = models.CharField(max_length=64)
    target_name = models.CharField(max_length=255, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    created_by = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "approval_category_permissions"
        ordering = ["scope_type", "sort_order", "target_name", "target_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["category", "permission", "scope_type", "target_id"],
                name="uniq_appr_category_perm",
            ),
        ]
        indexes = [
            models.Index(fields=["category", "permission"], name="idx_appr_cat_perm"),
        ]


class ApprovalTemplate(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_DISABLED = "disabled"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "草稿"),
        (STATUS_PUBLISHED, "已发布"),
        (STATUS_DISABLED, "已停用"),
        (STATUS_ARCHIVED, "已归档"),
    ]

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=64, blank=True, default="通用")
    category_ref = models.ForeignKey(
        ApprovalCategory,
        related_name="templates",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    category_order = models.PositiveIntegerField(default=0)
    icon = models.CharField(max_length=64, blank=True, default="FileText")
    color = models.CharField(max_length=32, blank=True, default="#1677ff")
    form_schema = models.JSONField(default=dict, blank=True)
    flow_schema = models.JSONField(default=dict, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    revision = models.PositiveBigIntegerField(default=1)
    published_revision = models.PositiveBigIntegerField(default=0)
    published_version = models.ForeignKey(
        "ApprovalTemplateVersion",
        related_name="published_by_templates",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    created_by = models.CharField(max_length=64)
    created_by_name = models.CharField(max_length=128, blank=True, default="")
    updated_by = models.CharField(max_length=64, blank=True, default="")
    updated_by_name = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approval_templates"
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["status", "-updated_at"], name="idx_appr_tpl_status"),
            models.Index(fields=["category", "status"], name="idx_appr_tpl_category"),
            models.Index(fields=["category_ref", "category_order"], name="idx_appr_tpl_cat_order"),
        ]


class ApprovalTemplateVersion(models.Model):
    template = models.ForeignKey(
        ApprovalTemplate,
        related_name="versions",
        on_delete=models.PROTECT,
    )
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=64, blank=True, default="通用")
    icon = models.CharField(max_length=64, blank=True, default="FileText")
    color = models.CharField(max_length=32, blank=True, default="#1677ff")
    form_schema = models.JSONField(default=dict, blank=True)
    flow_schema = models.JSONField(default=dict, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    source_revision = models.PositiveBigIntegerField(default=1)
    release_note = models.CharField(max_length=500, blank=True, default="")
    published_by = models.CharField(max_length=64)
    published_by_name = models.CharField(max_length=128, blank=True, default="")
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "approval_template_versions"
        ordering = ["template_id", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "version"],
                name="uniq_appr_tpl_version",
            ),
        ]
        indexes = [
            models.Index(fields=["template", "-version"], name="idx_appr_tpl_version"),
        ]


class ApprovalApplication(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_RETURNED = "returned"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_EXCEPTION = "exception"
    STATUS_CHOICES = [
        (STATUS_PENDING, "审批中"),
        (STATUS_APPROVED, "已通过"),
        (STATUS_REJECTED, "已拒绝"),
        (STATUS_RETURNED, "已退回"),
        (STATUS_WITHDRAWN, "已撤回"),
        (STATUS_EXCEPTION, "流程异常"),
    ]
    TERMINAL_STATUSES = {
        STATUS_APPROVED,
        STATUS_REJECTED,
        STATUS_RETURNED,
        STATUS_WITHDRAWN,
        STATUS_EXCEPTION,
    }

    serial_no = models.CharField(max_length=40, unique=True)
    template = models.ForeignKey(
        ApprovalTemplate,
        related_name="applications",
        on_delete=models.PROTECT,
    )
    template_version = models.ForeignKey(
        ApprovalTemplateVersion,
        related_name="applications",
        on_delete=models.PROTECT,
    )
    title = models.CharField(max_length=200)
    values = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    initiator_user_id = models.CharField(max_length=64)
    initiator_name = models.CharField(max_length=128, blank=True, default="")
    initiator_department_id = models.CharField(max_length=64, blank=True, default="")
    initiator_department_name = models.CharField(max_length=128, blank=True, default="")
    current_node_key = models.CharField(max_length=80, blank=True, default="")
    current_node_name = models.CharField(max_length=120, blank=True, default="")
    current_node_order = models.PositiveIntegerField(null=True, blank=True)
    revision = models.PositiveBigIntegerField(default=1)
    exception_message = models.CharField(max_length=500, blank=True, default="")
    submitted_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "approval_applications"
        ordering = ["-submitted_at", "-id"]
        indexes = [
            models.Index(fields=["initiator_user_id", "-submitted_at"], name="idx_appr_app_owner"),
            models.Index(fields=["status", "-submitted_at"], name="idx_appr_app_status"),
            models.Index(fields=["template", "status"], name="idx_appr_app_template"),
        ]


class ApprovalTask(models.Model):
    TYPE_APPROVAL = "approval"
    TYPE_CC = "cc"
    TYPE_CHOICES = [
        (TYPE_APPROVAL, "审批"),
        (TYPE_CC, "抄送"),
    ]
    MODE_ALL = "all"
    MODE_ANY = "any"
    MODE_CHOICES = [
        (MODE_ALL, "会签"),
        (MODE_ANY, "或签"),
    ]
    STATUS_WAITING = "waiting"
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_RETURNED = "returned"
    STATUS_COPIED = "copied"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_WAITING, "未开始"),
        (STATUS_PENDING, "待处理"),
        (STATUS_APPROVED, "已同意"),
        (STATUS_REJECTED, "已拒绝"),
        (STATUS_RETURNED, "已退回"),
        (STATUS_COPIED, "已抄送"),
        (STATUS_CANCELLED, "已取消"),
    ]

    application = models.ForeignKey(
        ApprovalApplication,
        related_name="tasks",
        on_delete=models.CASCADE,
    )
    node_key = models.CharField(max_length=80)
    node_name = models.CharField(max_length=120)
    node_order = models.PositiveIntegerField()
    task_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_APPROVAL)
    approval_mode = models.CharField(max_length=16, choices=MODE_CHOICES, default=MODE_ALL)
    assignee_user_id = models.CharField(max_length=64)
    assignee_name = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_WAITING)
    comment = models.TextField(blank=True, default="")
    acted_by_user_id = models.CharField(max_length=64, blank=True, default="")
    acted_by_name = models.CharField(max_length=128, blank=True, default="")
    activated_at = models.DateTimeField(null=True, blank=True)
    acted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "approval_tasks"
        ordering = ["node_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "node_order", "assignee_user_id"],
                name="uniq_appr_task_assignee",
            ),
        ]
        indexes = [
            models.Index(fields=["assignee_user_id", "status"], name="idx_appr_task_user"),
            models.Index(fields=["application", "node_order", "status"], name="idx_appr_task_node"),
        ]


class ApprovalEvent(models.Model):
    ACTION_SUBMITTED = "submitted"
    ACTION_NODE_STARTED = "node_started"
    ACTION_APPROVED = "approved"
    ACTION_REJECTED = "rejected"
    ACTION_RETURNED = "returned"
    ACTION_COPIED = "copied"
    ACTION_COMPLETED = "completed"
    ACTION_WITHDRAWN = "withdrawn"
    ACTION_EXCEPTION = "exception"
    ACTION_CHOICES = [
        (ACTION_SUBMITTED, "提交申请"),
        (ACTION_NODE_STARTED, "进入审批节点"),
        (ACTION_APPROVED, "同意"),
        (ACTION_REJECTED, "拒绝"),
        (ACTION_RETURNED, "退回"),
        (ACTION_COPIED, "抄送"),
        (ACTION_COMPLETED, "审批完成"),
        (ACTION_WITHDRAWN, "撤回"),
        (ACTION_EXCEPTION, "流程异常"),
    ]

    application = models.ForeignKey(
        ApprovalApplication,
        related_name="events",
        on_delete=models.CASCADE,
    )
    task = models.ForeignKey(
        ApprovalTask,
        related_name="events",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    action = models.CharField(max_length=24, choices=ACTION_CHOICES)
    actor_user_id = models.CharField(max_length=64, blank=True, default="")
    actor_name = models.CharField(max_length=128, blank=True, default="")
    node_key = models.CharField(max_length=80, blank=True, default="")
    node_name = models.CharField(max_length=120, blank=True, default="")
    from_status = models.CharField(max_length=16, blank=True, default="")
    to_status = models.CharField(max_length=16, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "approval_events"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["application", "created_at"], name="idx_appr_event_time"),
            models.Index(fields=["actor_user_id", "-created_at"], name="idx_appr_event_actor"),
        ]


class ApprovalDraft(models.Model):
    template = models.ForeignKey(
        ApprovalTemplate,
        related_name="application_drafts",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    owner_user_id = models.CharField(max_length=64)
    owner_name = models.CharField(max_length=128, blank=True, default="")
    title = models.CharField(max_length=200, blank=True, default="")
    values = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "approval_drafts"
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["owner_user_id", "-updated_at"], name="idx_appr_draft_owner"),
        ]
