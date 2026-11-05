import uuid

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class CompetitorStatus(models.TextChoices):
    NORMAL = "正常", "正常"
    NEEDS_INFO = "待补充", "待补充"
    EXPIRED = "已过期", "已过期"
    NO_DATA = "无资料", "无资料"


class SubmissionStatus(models.TextChoices):
    PENDING = "待审核", "待审核"
    NEEDS_INFO = "待补充", "待补充"
    ADOPTED = "已采纳", "已采纳"
    EXPIRED = "已过期", "已过期"


class PermissionCode(models.TextChoices):
    ADMIN = "admin", "系统管理员"
    REVIEWER = "reviewer", "审核人员"
    COLLECTOR = "collector", "采集人员"


class PermissionScope(models.TextChoices):
    DEPARTMENT = "department", "部门"
    DEPARTMENT_WITH_SUB = "departmentSub", "部门及下级"
    EMPLOYEE = "employee", "人员"
    EXCLUDED_EMPLOYEE = "excludedEmployee", "排除人员"


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Competitor(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product_id = models.CharField(max_length=32, db_index=True)
    brand = models.CharField(max_length=160)
    name = models.CharField(max_length=200)
    model = models.CharField(max_length=160)
    regions = models.JSONField(default=list, blank=True)
    sources = models.PositiveIntegerField(default=0)
    updated_on = models.DateField(db_index=True)
    expires_on = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=CompetitorStatus.choices,
        default=CompetitorStatus.NORMAL,
        db_index=True,
    )
    price = models.CharField(max_length=120, default="待采集")
    dealer = models.TextField(blank=True, default="")
    advantage = models.TextField(blank=True, default="")
    weakness = models.TextField(blank=True, default="")
    tactic = models.TextField(blank=True, default="")
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "competitors"
        ordering = ["-updated_on", "name"]


class Submission(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    competitor = models.ForeignKey(
        Competitor,
        null=True,
        blank=True,
        related_name="submissions",
        on_delete=models.SET_NULL,
    )
    competitor_release = models.ForeignKey(
        "CompetitorRelease",
        null=True,
        blank=True,
        related_name="submissions",
        on_delete=models.SET_NULL,
    )
    product_id = models.CharField(max_length=32, db_index=True)
    owner = models.CharField(max_length=80)
    owner_user_id = models.CharField(max_length=80, null=True, blank=True, db_index=True)
    brand = models.CharField(max_length=160)
    name = models.CharField(max_length=200)
    model = models.CharField(max_length=160)
    price = models.CharField(max_length=120, default="待采集")
    dealer = models.TextField(blank=True, default="")
    customer = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    advantage = models.TextField(blank=True, default="")
    weakness = models.TextField(blank=True, default="")
    tactic = models.TextField(blank=True, default="")
    competitor_parameters = models.JSONField(default=str, blank=True)
    review_comment = models.TextField(blank=True, default="")
    region = models.CharField(max_length=80)
    city = models.CharField(max_length=80, blank=True, default="")
    location = models.TextField(blank=True, default="")
    located = models.BooleanField(default=False)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location_accuracy = models.FloatField(null=True, blank=True)
    located_at = models.DateTimeField(null=True, blank=True)
    location_source = models.CharField(max_length=20, default="manual")
    validity = models.CharField(max_length=40)
    expires_on = models.DateField()
    reminder_owner = models.CharField(max_length=120)
    status = models.CharField(
        max_length=16,
        choices=SubmissionStatus.choices,
        default=SubmissionStatus.PENDING,
        db_index=True,
    )
    submitted_on = models.DateField(db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "submissions"
        ordering = ["-submitted_on", "-created_at"]
        indexes = [
            models.Index(fields=["owner", "submitted_on"], name="idx_sub_owner_date"),
            models.Index(
                fields=["owner_user_id", "submitted_on"],
                name="idx_sub_user_date",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(status=SubmissionStatus.ADOPTED) | Q(competitor__isnull=False),
                name="ck_submission_adopted_comp",
            ),
            models.CheckConstraint(
                condition=Q(latitude__isnull=True)
                | (Q(latitude__gte=-90) & Q(latitude__lte=90)),
                name="ck_submission_latitude",
            ),
            models.CheckConstraint(
                condition=Q(longitude__isnull=True)
                | (Q(longitude__gte=-180) & Q(longitude__lte=180)),
                name="ck_submission_longitude",
            ),
            models.CheckConstraint(
                condition=Q(location_accuracy__isnull=True) | Q(location_accuracy__gte=0),
                name="ck_submission_accuracy",
            ),
            models.CheckConstraint(
                condition=Q(location_source__in=["manual", "device"]),
                name="ck_submission_location_src",
            ),
        ]


class CompetitorParameter(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    competitor = models.ForeignKey(
        Competitor,
        related_name="parameters",
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=160)
    competitor_value = models.TextField()
    own_value = models.TextField(default="待产品经理确认")
    comparison_status = models.CharField(max_length=40, default="待判断")
    deviation = models.TextField(default="待确认具体差异")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "competitor_parameters"
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["competitor", "name"],
                name="uq_competitor_parameter_name",
            ),
        ]
        indexes = [
            models.Index(
                fields=["competitor", "position"],
                name="idx_comp_param_position",
            ),
        ]


class CompetitorVersion(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    competitor = models.ForeignKey(
        Competitor,
        related_name="versions",
        on_delete=models.CASCADE,
    )
    version = models.CharField(max_length=40)
    changed_on = models.DateField()
    note = models.TextField()
    action = models.CharField(max_length=40, default="历史导入")
    changed_by = models.CharField(max_length=80, default="系统")
    source_submission = models.ForeignKey(
        Submission,
        null=True,
        blank=True,
        related_name="version_entries",
        on_delete=models.SET_NULL,
    )
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "competitor_versions"
        ordering = ["-changed_on", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["competitor", "version"],
                name="uq_competitor_version",
            ),
        ]
        indexes = [
            models.Index(
                fields=["competitor", "changed_on"],
                name="idx_comp_version_date",
            ),
        ]


class CompetitorRelease(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    competitor = models.ForeignKey(
        Competitor,
        related_name="releases",
        on_delete=models.CASCADE,
    )
    number = models.PositiveIntegerField()
    brand = models.CharField(max_length=160)
    name = models.CharField(max_length=200)
    model = models.CharField(max_length=160)
    regions = models.JSONField(default=list, blank=True)
    price = models.CharField(max_length=120, default="待采集")
    dealer = models.TextField(blank=True, default="")
    advantage = models.TextField(blank=True, default="")
    weakness = models.TextField(blank=True, default="")
    tactic = models.TextField(blank=True, default="")
    parameters = models.JSONField(default=list, blank=True)
    changed_on = models.DateField(db_index=True)
    expires_on = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=CompetitorStatus.choices,
        default=CompetitorStatus.NORMAL,
        db_index=True,
    )
    note = models.TextField(blank=True, default="")
    created_by = models.CharField(max_length=80, default="系统")
    is_current = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "competitor_releases"
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(
                fields=["competitor", "number"],
                name="uq_competitor_release_number",
            ),
            models.UniqueConstraint(
                fields=["competitor"],
                condition=Q(is_current=True),
                name="uq_competitor_current_release",
            ),
        ]
        indexes = [
            models.Index(
                fields=["competitor", "is_current"],
                name="idx_comp_release_current",
            ),
        ]


class SubmissionAttachment(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        Submission,
        related_name="attachments",
        on_delete=models.CASCADE,
    )
    filename = models.CharField(max_length=255)
    byte_size = models.BigIntegerField(validators=[MinValueValidator(0)])
    media_type = models.CharField(max_length=160)
    category = models.CharField(max_length=80, db_index=True)
    storage_key = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "submission_attachments"
        ordering = ["created_at"]


class PendingFileDeletion(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    storage_key = models.TextField()
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "pending_file_deletions"
        ordering = ["created_at"]


class CollectionDraft(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=80)
    owner_user_id = models.CharField(max_length=80, null=True, blank=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "collection_drafts"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["owner", "updated_at"], name="idx_draft_owner_date"),
            models.Index(
                fields=["owner_user_id", "updated_at"],
                name="idx_draft_user_date",
            ),
        ]


class CollectionDraftAttachment(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    draft = models.ForeignKey(
        CollectionDraft,
        related_name="attachments",
        on_delete=models.CASCADE,
    )
    filename = models.CharField(max_length=255)
    byte_size = models.BigIntegerField(validators=[MinValueValidator(0)])
    media_type = models.CharField(max_length=160)
    category = models.CharField(max_length=80)
    storage_key = models.TextField()

    class Meta:
        db_table = "collection_draft_attachments"
        ordering = ["created_at"]


class SettingItem(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.CharField(max_length=40)
    code = models.CharField(max_length=80)
    label = models.CharField(max_length=120)
    enabled = models.BooleanField(default=True)
    required = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "setting_items"
        ordering = ["group", "position", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["group", "code"],
                name="uq_setting_group_code",
            ),
            models.UniqueConstraint(
                fields=["group", "label"],
                name="uq_setting_group_label",
            ),
        ]
        indexes = [
            models.Index(fields=["group", "position"], name="idx_setting_position"),
        ]


class PermissionRule(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    permission = models.CharField(max_length=16, choices=PermissionCode.choices)
    scope_type = models.CharField(max_length=16, choices=PermissionScope.choices)
    target_id = models.CharField(max_length=80)
    target_name = models.CharField(max_length=160, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)
    created_by = models.CharField(max_length=80, blank=True, default="")

    class Meta:
        db_table = "permission_rules"
        ordering = ["permission", "scope_type", "sort_order", "target_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["permission", "scope_type", "target_id"],
                name="uq_permission_rule_target",
            ),
        ]
        indexes = [
            models.Index(
                fields=["permission", "scope_type"],
                name="idx_permission_scope",
            ),
        ]


class PermissionState(TimestampedModel):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    revision = models.PositiveBigIntegerField(default=0)
    updated_by = models.CharField(max_length=80, blank=True, default="")

    class Meta:
        db_table = "permission_states"


class OrganizationDepartment(TimestampedModel):
    dept_id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    manager_user_id = models.CharField(max_length=80, blank=True, default="")
    parent_dept_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "organization_departments"
        ordering = ["dept_id"]


class OrganizationEmployee(TimestampedModel):
    user_id = models.CharField(max_length=80, primary_key=True)
    name = models.CharField(max_length=255)
    avatar_url = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, default="在职")
    account_status = models.CharField(max_length=16, default="启用")

    class Meta:
        db_table = "organization_employees"
        ordering = ["user_id"]


class OrganizationDepartmentEmployee(TimestampedModel):
    department = models.ForeignKey(
        OrganizationDepartment,
        on_delete=models.CASCADE,
        db_column="department_id",
        related_name="employee_relations",
    )
    employee = models.ForeignKey(
        OrganizationEmployee,
        on_delete=models.CASCADE,
        db_column="employee_id",
        related_name="department_relations",
    )

    class Meta:
        db_table = "organization_department_employees"
        ordering = ["department_id", "employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "employee"],
                name="uq_org_department_employee",
            ),
        ]


class OrganizationSyncState(TimestampedModel):
    state_key = models.CharField(
        max_length=64,
        unique=True,
        default="auth-organization",
    )
    org_revision = models.PositiveBigIntegerField(default=0)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "organization_sync_states"
        ordering = ["state_key"]
