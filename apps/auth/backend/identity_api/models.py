import uuid
import hashlib
import hmac
import secrets

from django.db import models


class AdministrativeRegionDirectory(models.Model):
    revision = models.CharField(max_length=64, primary_key=True)
    source = models.CharField(max_length=128)
    source_fingerprint = models.CharField(max_length=64)
    region_count = models.PositiveIntegerField()
    is_current = models.BooleanField(default=False)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform_administrative_region_directories"
        constraints = [
            models.UniqueConstraint(
                fields=["is_current"], condition=models.Q(is_current=True),
                name="one_current_region_directory",
            ),
        ]


class AdministrativeRegion(models.Model):
    directory = models.ForeignKey(AdministrativeRegionDirectory, on_delete=models.CASCADE, related_name="regions")
    code = models.CharField(max_length=6)
    name = models.CharField(max_length=128)
    level = models.CharField(max_length=8, choices=[("province", "省级"), ("city", "市级"), ("district", "区县")])
    parent_code = models.CharField(max_length=6, blank=True, default="")
    pinyin = models.CharField(max_length=256)
    pinyin_initials = models.CharField(max_length=128)
    sort_order = models.PositiveIntegerField()

    class Meta:
        db_table = "platform_administrative_regions"
        ordering = ["sort_order", "code"]
        constraints = [
            models.UniqueConstraint(fields=["directory", "code"], name="unique_region_code_per_directory"),
        ]
        indexes = [models.Index(fields=["directory", "level", "parent_code"], name="region_directory_parent_idx")]


class PlatformCompanyEntity(models.Model):
    """Platform-owned company master data, maintained in backend management."""

    company_name = models.CharField(max_length=255)
    category = models.CharField(max_length=64, blank=True, default="")  # Legacy contract alias.
    tax_number = models.CharField(max_length=64, unique=True)
    bank_name = models.CharField(max_length=255)
    bank_account = models.CharField(max_length=64)
    address = models.CharField(max_length=512)
    phone = models.CharField(max_length=64)
    revision = models.PositiveBigIntegerField(default=1)
    created_by = models.CharField(max_length=64, blank=True, default="")
    updated_by = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "platform_company_entities"
        ordering = ["id"]


class PlatformCompanyEntityHistory(models.Model):
    entity_id = models.BigIntegerField(db_index=True)
    action = models.CharField(max_length=16)
    actor_user_id = models.CharField(max_length=64)
    effective_user_id = models.CharField(max_length=64)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform_company_entity_history"


class BusinessRegistryCompany(models.Model):
    identity_key = models.CharField(max_length=80, unique=True)
    company_name = models.CharField(max_length=512, db_index=True)
    credit_no = models.CharField(max_length=128, blank=True, db_index=True)
    company_code = models.CharField(max_length=128, blank=True, db_index=True)
    legal_person = models.CharField(max_length=255, blank=True)
    company_status = models.CharField(max_length=128, blank=True)
    establish_date = models.CharField(max_length=32, blank=True)
    first_queried_at = models.DateTimeField(auto_now_add=True)
    last_queried_at = models.DateTimeField()
    last_query = models.ForeignKey("BusinessRegistryQuery", on_delete=models.PROTECT)

    class Meta:
        db_table = "business_registry_companies"
        ordering = ["-last_queried_at", "-id"]


class BusinessRegistryQuery(models.Model):
    request_id = models.UUIDField(unique=True)
    source_app_id = models.CharField(max_length=64, blank=True, default="", db_default="")
    source_service = models.CharField(max_length=128, blank=True, default="", db_default="")
    keyword = models.CharField(max_length=200)
    page_num = models.PositiveSmallIntegerField()
    page_size = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=16, default="running")
    message = models.CharField(max_length=512, blank=True)
    actor_user_id = models.CharField(max_length=64)
    actor_name = models.CharField(max_length=255)
    effective_user_id = models.CharField(max_length=64)
    effective_name = models.CharField(max_length=255)
    http_status = models.PositiveSmallIntegerField(null=True)
    business_code = models.CharField(max_length=32, blank=True)
    order_no = models.CharField(max_length=128, blank=True)
    gateway_request_id = models.CharField(max_length=128, blank=True)
    total_records = models.PositiveBigIntegerField(null=True)
    result_count = models.PositiveSmallIntegerField(default=0)
    companies = models.JSONField(default=list)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "business_registry_queries"
        ordering = ["-created_at", "-id"]


class BusinessRegistryQueryCompany(models.Model):
    company = models.ForeignKey(BusinessRegistryCompany, on_delete=models.CASCADE, related_name="query_links")
    query = models.ForeignKey(BusinessRegistryQuery, on_delete=models.CASCADE, related_name="company_links")

    class Meta:
        db_table = "business_registry_query_companies"
        constraints = [models.UniqueConstraint(fields=["company", "query"], name="registry_company_query_unique")]


class Department(models.Model):
    dept_id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    manager_user_id = models.CharField(max_length=64, blank=True, default="")
    manager_user_ids = models.JSONField(default=list, blank=True)
    parent_dept_id = models.BigIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_departments"
        ordering = ["dept_id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(parent_dept_id__isnull=True) | ~models.Q(parent_dept_id=models.F("dept_id")),
                name="department_parent_not_self",
            ),
        ]


class Employee(models.Model):
    IDENTITY_DINGTALK = "dingtalk"
    IDENTITY_WECHAT_MINI = "wechat-mini"
    STATUS_ACTIVE = "在职"
    STATUS_INACTIVE = "离职"
    ACCOUNT_ENABLED = "启用"
    ACCOUNT_DISABLED = "禁用"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, STATUS_ACTIVE),
        (STATUS_INACTIVE, STATUS_INACTIVE),
    ]
    ACCOUNT_STATUS_CHOICES = [
        (ACCOUNT_ENABLED, ACCOUNT_ENABLED),
        (ACCOUNT_DISABLED, ACCOUNT_DISABLED),
    ]
    IDENTITY_SOURCE_CHOICES = [
        (IDENTITY_DINGTALK, "钉钉"),
        (IDENTITY_WECHAT_MINI, "微信小程序"),
    ]

    user_id = models.CharField(max_length=64, primary_key=True)
    identity_source = models.CharField(
        max_length=20,
        choices=IDENTITY_SOURCE_CHOICES,
        default=IDENTITY_DINGTALK,
        db_index=True,
    )
    name = models.CharField(max_length=255)
    avatar_url = models.TextField(blank=True, default="")
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    account_status = models.CharField(
        max_length=8,
        choices=ACCOUNT_STATUS_CHOICES,
        default=ACCOUNT_ENABLED,
    )
    handover_user_id = models.CharField(max_length=64, blank=True, default="")
    former_dingtalk_departments = models.JSONField(default=list, blank=True)
    former_organization_recorded_at = models.DateTimeField(null=True, blank=True)
    auth_version = models.PositiveIntegerField(default=1)
    create_time = models.DateTimeField(null=True, blank=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_employees"
        ordering = ["user_id"]


class DepartmentEmployee(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        db_column="department_id",
        related_name="department_employees",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        db_column="employee_id",
        related_name="department_employees",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_department_employees"
        constraints = [
            models.UniqueConstraint(
                fields=["department", "employee"],
                name="uniq_department_employee",
            ),
        ]
        ordering = ["department_id", "employee_id"]


class DepartmentManager(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        db_column="department_id",
        related_name="department_managers",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        db_column="employee_id",
        related_name="managed_department_relations",
    )
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_department_managers"
        constraints = [
            models.UniqueConstraint(
                fields=["department", "employee"],
                name="uniq_department_manager",
            ),
        ]
        ordering = ["department_id", "sort_order", "employee_id"]


class AuthSession(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, STATUS_ACTIVE),
        (STATUS_REVOKED, STATUS_REVOKED),
    ]

    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.CharField(max_length=64, db_index=True)
    actor_user_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    session_started_at = models.PositiveBigIntegerField(db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoke_reason = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "auth_sessions"
        ordering = ["-created_at"]


class WeChatMiniIdentity(models.Model):
    app_id = models.CharField(max_length=64)
    openid = models.CharField(max_length=128)
    unionid = models.CharField(max_length=128, blank=True, default="", db_index=True)
    employee = models.OneToOneField(
        Employee,
        on_delete=models.PROTECT,
        related_name="wechat_mini_identity",
    )
    privacy_version = models.CharField(max_length=32, blank=True, default="")
    privacy_agreed_at = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wechat_mini_identities"
        ordering = ["app_id", "openid"]
        constraints = [
            models.UniqueConstraint(
                fields=["app_id", "openid"],
                name="uniq_wechat_mini_app_openid",
            ),
        ]


class WeChatMiniRegistrationChallenge(models.Model):
    token_digest = models.CharField(max_length=64, unique=True)
    app_id = models.CharField(max_length=64)
    openid = models.CharField(max_length=128)
    unionid = models.CharField(max_length=128, blank=True, default="")
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wechat_mini_registration_challenges"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["app_id", "openid"], name="idx_wx_challenge_identity"),
        ]


class OrganizationSyncRun(models.Model):
    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_RUNNING, STATUS_RUNNING),
        (STATUS_SUCCEEDED, STATUS_SUCCEEDED),
        (STATUS_FAILED, STATUS_FAILED),
    ]

    run_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, db_index=True)
    started_by = models.CharField(max_length=64, blank=True, default="", db_index=True)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True, db_index=True)
    summary = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_sync_runs"
        ordering = ["-started_at"]


class OrganizationSyncLock(models.Model):
    lock_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_sync_lock"


class OrganizationState(models.Model):
    state_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    revision = models.PositiveBigIntegerField(default=0)
    synced_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_state"


class PlatformDepartmentState(models.Model):
    state_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    configured = models.BooleanField(default=False)
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "platform_department_state"


class PlatformEnabledDepartment(models.Model):
    department = models.OneToOneField(
        Department,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="platform_enabled_setting",
    )
    enabled_by = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "platform_enabled_departments"
        ordering = ["department_id"]


class RobotMessagePermissionState(models.Model):
    state_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    rules = models.JSONField(default=list, blank=True)
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "robot_message_permissions"


class RobotMessageGroup(models.Model):
    name = models.CharField(max_length=128)
    conversation_id = models.CharField(max_length=256)
    robot_code = models.CharField(max_length=128)
    enabled = models.BooleanField(default=True)
    created_by = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "robot_message_groups"
        constraints = [models.UniqueConstraint(fields=["robot_code", "conversation_id"], name="robot_group_unique")]


class RobotMessageBatch(models.Model):
    message_spec = models.JSONField(default=dict, db_default={}, blank=True)
    source_app_id = models.SlugField(max_length=64, blank=True, default="", db_default="", db_index=True)
    source_service = models.CharField(max_length=128, blank=True, default="", db_default="", db_index=True)
    business_key = models.CharField(max_length=200, blank=True, default="", db_default="")
    content_html = models.TextField(blank=True, default="")
    message_key = models.CharField(max_length=32, default="sampleText")
    message_param = models.JSONField(default=dict, blank=True)
    payload_hash = models.CharField(max_length=64, blank=True, default="")
    request_id = models.UUIDField(unique=True)
    robot_code = models.CharField(max_length=128)
    content = models.TextField()
    effective_user_id = models.CharField(max_length=64)
    effective_name = models.CharField(max_length=255)
    actor_user_id = models.CharField(max_length=64)
    actor_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "robot_message_batches"
        ordering = ["-created_at", "-id"]


class RobotMessageMedia(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_app_id = models.SlugField(max_length=64, db_index=True)
    source_service = models.CharField(max_length=128, db_index=True)
    robot_code = models.CharField(max_length=128)
    kind = models.CharField(max_length=16)
    upstream_media_id = models.CharField(max_length=1024)
    file_name = models.CharField(max_length=255)
    byte_size = models.PositiveIntegerField()
    content_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "robot_message_media"
        ordering = ["-created_at", "-id"]


class RobotMessageImage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(RobotMessageBatch, related_name="images", on_delete=models.CASCADE)
    file = models.FileField(upload_to="robot-messages/%Y/%m/")
    access_token = models.CharField(max_length=64)
    content_type = models.CharField(max_length=32)
    byte_size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "robot_message_images"
        ordering = ["created_at", "id"]


class RobotMessageDelivery(models.Model):
    batch = models.ForeignKey(RobotMessageBatch, related_name="deliveries", on_delete=models.CASCADE)
    kind = models.CharField(max_length=8, choices=[("group", "群聊"), ("person", "人员")])
    target_id = models.CharField(max_length=256)
    target_name = models.CharField(max_length=255)
    group = models.ForeignKey(RobotMessageGroup, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=12, default="pending", db_index=True, choices=[
        ("pending", "待发送"), ("sending", "发送中"), ("accepted", "已发送"),
        ("failed", "发送失败"), ("unknown", "结果待核实"),
    ])
    message = models.CharField(max_length=300, blank=True)
    error_code = models.CharField(max_length=128, blank=True)
    process_query_key = models.CharField(max_length=512, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "robot_message_deliveries"
        constraints = [models.UniqueConstraint(fields=["batch", "kind", "target_id"], name="robot_delivery_unique")]


class NotificationPermissionState(models.Model):
    state_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    roles = models.JSONField(default=dict, blank=True)
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notification_permission_state"


class NotificationCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    created_by = models.CharField(max_length=64, blank=True, default="")
    updated_by = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notification_categories"
        ordering = ["name", "id"]


class PlatformNotification(models.Model):
    LEVEL_ORDINARY = "ordinary"
    LEVEL_CONFIRM = "confirm"
    LEVEL_ACCEPT = "accept"
    LEVEL_CHOICES = [(LEVEL_ORDINARY, "普通通知"), (LEVEL_CONFIRM, "确认"), (LEVEL_ACCEPT, "确认并接受")]
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "草稿"),
        (STATUS_PUBLISHED, "已发布"),
        (STATUS_WITHDRAWN, "已撤回"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    level = models.CharField(max_length=12, choices=LEVEL_CHOICES, default=LEVEL_ORDINARY, db_default=LEVEL_ORDINARY)
    publication_revision = models.PositiveIntegerField(default=1, db_default=1)
    content_html = models.TextField()
    category = models.ForeignKey(NotificationCategory, related_name="notifications", on_delete=models.PROTECT)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    recipient_selection = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=64, db_index=True)
    created_by_name = models.CharField(max_length=255, blank=True, default="")
    actor_user_id = models.CharField(max_length=64, blank=True, default="")
    actor_name = models.CharField(max_length=255, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "platform_notifications"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "expires_at"], name="notice_status_exp_idx")]


class NotificationRecipient(models.Model):
    notification = models.ForeignKey(PlatformNotification, related_name="recipients", on_delete=models.CASCADE)
    user_id = models.CharField(max_length=64)
    name = models.CharField(max_length=255, blank=True, default="")
    department_names = models.JSONField(default=list, blank=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_recipients"
        ordering = ["name", "user_id"]
        constraints = [models.UniqueConstraint(fields=["notification", "user_id"], name="notice_recipient_unique")]
        indexes = [models.Index(fields=["user_id", "read_at"], name="notice_user_read_idx")]


class NotificationAcknowledgement(models.Model):
    notification = models.ForeignKey(PlatformNotification, related_name="acknowledgements", on_delete=models.CASCADE)
    publication_revision = models.PositiveIntegerField()
    user_id = models.CharField(max_length=64)
    name = models.CharField(max_length=255, blank=True, default="")
    actor_user_id = models.CharField(max_length=64)
    actor_name = models.CharField(max_length=255, blank=True, default="")
    level = models.CharField(max_length=12, choices=PlatformNotification.LEVEL_CHOICES)
    statement = models.TextField(blank=True, default="")
    entered_statement = models.TextField(blank=True, default="")
    content_snapshot = models.JSONField(default=dict)
    confirmed_at = models.DateTimeField()

    class Meta:
        db_table = "notification_acknowledgements"
        ordering = ["-confirmed_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["notification", "publication_revision", "user_id"], name="notice_ack_revision_user_unique")]


class NotificationAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(PlatformNotification, related_name="attachments", on_delete=models.CASCADE)
    file = models.FileField(upload_to="notifications/%Y/%m/")
    file_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128, blank=True, default="")
    byte_size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_attachments"
        ordering = ["created_at", "id"]


class OrganizationPermissionState(models.Model):
    state_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    manager_user_ids = models.JSONField(default=list, blank=True)
    rules = models.JSONField(default=list, blank=True)
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_permissions"


class InternalServiceCredential(models.Model):
    service_name = models.CharField(max_length=128, primary_key=True)
    app_id = models.SlugField(max_length=64, db_index=True)
    secret_salt = models.CharField(max_length=32)
    secret_digest = models.CharField(max_length=64)
    enabled = models.BooleanField(default=True, db_index=True)
    registry_revision = models.CharField(max_length=64, blank=True, default="", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "internal_service_credentials"
        ordering = ["service_name"]

    @staticmethod
    def _digest(secret: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}\0{secret}".encode("utf-8")).hexdigest()

    def set_secret(self, secret: str) -> None:
        normalized = str(secret or "").strip()
        if len(normalized) < 32:
            raise ValueError("Internal service secrets must be at least 32 characters")
        self.secret_salt = secrets.token_hex(16)
        self.secret_digest = self._digest(normalized, self.secret_salt)

    def matches_secret(self, secret: str) -> bool:
        normalized = str(secret or "").strip()
        if not normalized or not self.secret_salt or not self.secret_digest:
            return False
        candidate = self._digest(normalized, self.secret_salt)
        return hmac.compare_digest(candidate, self.secret_digest)


class OrganizationAccountOperation(models.Model):
    actor_user_id = models.CharField(max_length=64)
    actor_name = models.CharField(max_length=255)
    effective_user_id = models.CharField(max_length=64)
    effective_name = models.CharField(max_length=255)
    account_status = models.CharField(max_length=16, choices=Employee.ACCOUNT_STATUS_CHOICES)
    scope = models.CharField(max_length=16)
    changes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "organization_account_operations"
        ordering = ["-created_at", "-id"]
