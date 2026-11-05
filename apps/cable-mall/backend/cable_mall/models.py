from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CableProduct(TimeStampedModel):
    product_archive_id = models.BigIntegerField(unique=True)
    label = models.CharField(max_length=255)
    product_brand = models.CharField(max_length=255, blank=True)
    product_model = models.CharField(max_length=255, blank=True)
    abbr = models.CharField(max_length=255, blank=True)
    category_a = models.CharField(max_length=128, db_index=True)
    category_b = models.CharField(max_length=128, db_index=True)
    kingdee_code = models.CharField(max_length=128, blank=True)
    product_images = models.JSONField(default=list, blank=True)
    plan_para = models.TextField(blank=True)
    spec_text = models.CharField(max_length=512, blank=True)
    length_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    quantity_unit = models.CharField(max_length=32, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    salesperson_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    distributor_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    budget_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    market_reference_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    comments = models.TextField(blank=True)
    phase = models.IntegerField(db_index=True)
    archive_updated_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["category_a", "category_b", "product_archive_id"]

    def __str__(self):
        return f"{self.abbr or self.label} ({self.product_model})"


class Project(TimeStampedModel):
    external_account = models.ForeignKey(
        "CableMallExternalAccount",
        null=True,
        blank=True,
        related_name="projects",
        on_delete=models.SET_NULL,
    )
    name = models.CharField(max_length=160, db_index=True)
    created_by = models.CharField(max_length=120, blank=True)
    customer_name = models.CharField(max_length=120, blank=True)
    opportunity_info = models.TextField(blank=True)
    shipping_address = models.TextField(blank=True)
    shipping_contact = models.CharField(max_length=80, blank=True)
    shipping_phone = models.CharField(max_length=80, blank=True)
    note = models.TextField(blank=True)
    is_archived = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(is_archived=False),
                name="unique_active_project_name",
            )
        ]

    def __str__(self):
        return self.name


class CablePackage(TimeStampedModel):
    CLASSROOM_SCOPE_CHOICES = [
        ("", "未分区"),
        ("教室内", "教室内"),
        ("教室外", "教室外"),
    ]

    project = models.ForeignKey(Project, null=True, blank=True, related_name="packages", on_delete=models.SET_NULL)
    external_account = models.ForeignKey(
        "CableMallExternalAccount",
        null=True,
        blank=True,
        related_name="packages",
        on_delete=models.SET_NULL,
    )
    name = models.CharField(max_length=120)
    created_by = models.CharField(max_length=120, blank=True)
    owner_name = models.CharField(max_length=80, blank=True)
    classroom_name = models.CharField(max_length=120, blank=True)
    classroom_scope = models.CharField(max_length=20, choices=CLASSROOM_SCOPE_CHOICES, blank=True)
    note = models.TextField(blank=True)
    quantity = models.PositiveIntegerField(default=1)
    is_default = models.BooleanField(default=False, db_index=True)
    is_archived = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name


class CablePackageItem(TimeStampedModel):
    package = models.ForeignKey(CablePackage, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(CableProduct, null=True, blank=True, on_delete=models.SET_NULL)
    product_archive_id = models.BigIntegerField()
    product_label = models.CharField(max_length=255)
    product_brand = models.CharField(max_length=255, blank=True)
    product_model = models.CharField(max_length=255, blank=True)
    product_abbr = models.CharField(max_length=255, blank=True)
    category_a = models.CharField(max_length=128, blank=True)
    category_b = models.CharField(max_length=128, blank=True)
    spec_text = models.CharField(max_length=512, blank=True)
    length_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    source_unit = models.CharField(max_length=32, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity = models.PositiveIntegerField(default=1)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.package.name} - {self.product_abbr or self.product_label}"


class CartItem(TimeStampedModel):
    package = models.OneToOneField(CablePackage, related_name="cart_item", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.package.name} x {self.quantity}"


class ProductCartItem(TimeStampedModel):
    product = models.ForeignKey(CableProduct, related_name="product_cart_items", on_delete=models.CASCADE)
    owner_user_id = models.CharField(max_length=64, blank=True, db_index=True)
    owner_name = models.CharField(max_length=120, blank=True)
    external_account = models.ForeignKey(
        "CableMallExternalAccount",
        null=True,
        blank=True,
        related_name="product_cart_items",
        on_delete=models.CASCADE,
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner_user_id", "product"],
                condition=models.Q(external_account__isnull=True),
                name="unique_internal_product_cart_item",
            ),
            models.UniqueConstraint(
                fields=["external_account", "product"],
                condition=models.Q(external_account__isnull=False),
                name="unique_external_product_cart_item",
            ),
        ]
        indexes = [
            models.Index(fields=["owner_user_id", "updated_at"], name="idx_product_cart_owner_time"),
            models.Index(fields=["external_account", "updated_at"], name="idx_product_cart_ext_time"),
        ]

    def __str__(self):
        owner = self.external_account or self.owner_name or self.owner_user_id
        return f"{owner} - {self.product} x {self.quantity}"


class Order(TimeStampedModel):
    SOURCE_INTERNAL = "internal"
    SOURCE_EXTERNAL = "external"
    SOURCE_CHOICES = [
        (SOURCE_INTERNAL, "内部下单"),
        (SOURCE_EXTERNAL, "外部商城"),
    ]
    STATUS_UNLOCKED = "未锁定"
    STATUS_PENDING_CONTRACT = "待签合同"
    STATUS_PENDING_SHIPMENT = "待发货"
    STATUS_PENDING_RECEIPT = "待签收"
    STATUS_COMPLETED = "已完结"
    STATUS_DELETED = "已删除"
    STATUS_CHOICES = [
        (STATUS_UNLOCKED, STATUS_UNLOCKED),
        (STATUS_PENDING_CONTRACT, STATUS_PENDING_CONTRACT),
        (STATUS_PENDING_SHIPMENT, STATUS_PENDING_SHIPMENT),
        (STATUS_PENDING_RECEIPT, STATUS_PENDING_RECEIPT),
        (STATUS_COMPLETED, STATUS_COMPLETED),
        (STATUS_DELETED, STATUS_DELETED),
    ]

    order_no = models.CharField(max_length=32, unique=True)
    customer_name = models.CharField(max_length=80, blank=True)
    customer_phone = models.CharField(max_length=40, blank=True)
    project_name = models.CharField(max_length=120, blank=True)
    source_shipping_address_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_signing_info_id = models.PositiveBigIntegerField(null=True, blank=True)
    signing_info = models.ForeignKey(
        "SigningInfo",
        null=True,
        blank=True,
        related_name="orders",
        on_delete=models.SET_NULL,
    )
    signing_company_name = models.CharField(max_length=160, blank=True)
    signing_opening_bank = models.CharField(max_length=160, blank=True)
    signing_tax_number = models.CharField(max_length=80, blank=True)
    signing_bank_account = models.CharField(max_length=80, blank=True)
    shipping_method = models.CharField(max_length=80, blank=True)
    arrival_date = models.DateField(null=True, blank=True)
    remark = models.TextField(blank=True)
    total_packages = models.PositiveIntegerField(default=0)
    total_cables = models.PositiveIntegerField(default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_UNLOCKED, db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    contract_file = models.FileField(upload_to="cable_mall/contracts/", max_length=255, blank=True)
    contract_uploaded_at = models.DateTimeField(null=True, blank=True)
    contract_note = models.TextField(blank=True)
    shipment_file = models.FileField(upload_to="cable_mall/shipments/", max_length=255, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    shipment_note = models.TextField(blank=True)
    invoice_file = models.FileField(upload_to="cable_mall/invoices/", max_length=255, blank=True)
    invoice_uploaded_at = models.DateTimeField(null=True, blank=True)
    invoice_note = models.TextField(blank=True)
    payment_file = models.FileField(upload_to="cable_mall/payments/", max_length=255, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_note = models.TextField(blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_INTERNAL, db_index=True)
    owner_user_id = models.CharField(max_length=64, blank=True, db_index=True)
    owner_name = models.CharField(max_length=120, blank=True)
    salesperson_user_id = models.CharField(max_length=64, blank=True, db_index=True)
    salesperson_name = models.CharField(max_length=120, blank=True)
    submitter_user_id = models.CharField(max_length=64, blank=True, db_index=True)
    submitter_name = models.CharField(max_length=120, blank=True)
    external_account = models.ForeignKey(
        "CableMallExternalAccount",
        null=True,
        blank=True,
        related_name="orders",
        on_delete=models.SET_NULL,
    )
    external_account_username = models.CharField(max_length=64, blank=True)
    external_account_name = models.CharField(max_length=120, blank=True)
    external_account_credit_code = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_no


class CableMallExternalAccount(TimeStampedModel):
    STATUS_ACTIVE = "active"
    STATUS_DISABLED = "disabled"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "启用"),
        (STATUS_DISABLED, "停用"),
    ]

    username = models.CharField(max_length=64, unique=True)
    display_name = models.CharField(max_length=120, blank=True)
    credit_code = models.CharField(max_length=64, blank=True, db_index=True)
    phone = models.CharField(max_length=40, blank=True)
    password_hash = models.CharField(max_length=160)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    owner_user_id = models.CharField(max_length=64, db_index=True)
    owner_name = models.CharField(max_length=120, blank=True)
    created_by = models.CharField(max_length=64, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["owner_user_id", "status"], name="idx_cable_ext_owner_status"),
        ]

    def __str__(self):
        return self.display_name or self.username


class ShippingAddress(TimeStampedModel):
    detail_address = models.TextField()
    receiver_name = models.CharField(max_length=80)
    receiver_phone = models.CharField(max_length=40)
    created_by = models.CharField(max_length=120, blank=True)
    owner_user_id = models.CharField(max_length=64, blank=True, db_index=True)
    is_default = models.BooleanField(default=False, db_index=True)
    external_account = models.ForeignKey(
        CableMallExternalAccount,
        null=True,
        blank=True,
        related_name="shipping_addresses",
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.receiver_name} - {self.receiver_phone}"


class SigningInfo(TimeStampedModel):
    company_name = models.CharField(max_length=160)
    opening_bank = models.CharField(max_length=160)
    tax_number = models.CharField(max_length=80)
    bank_account = models.CharField(max_length=80)
    created_by = models.CharField(max_length=120, blank=True)
    owner_user_id = models.CharField(max_length=64, blank=True, db_index=True)
    external_account = models.ForeignKey(
        CableMallExternalAccount,
        null=True,
        blank=True,
        related_name="signing_infos",
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.company_name


class OrderPackage(models.Model):
    order = models.ForeignKey(Order, related_name="packages", on_delete=models.CASCADE)
    source_package_id = models.BigIntegerField(null=True, blank=True)
    source_project_id = models.BigIntegerField(null=True, blank=True)
    project_name = models.CharField(max_length=120, blank=True)
    classroom_name = models.CharField(max_length=120, blank=True)
    classroom_scope = models.CharField(max_length=20, blank=True)
    package_name = models.CharField(max_length=120)
    package_note = models.TextField(blank=True)
    package_quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.order.order_no} - {self.package_name}"


class OrderItem(models.Model):
    order_package = models.ForeignKey(OrderPackage, related_name="items", on_delete=models.CASCADE)
    product_archive_id = models.BigIntegerField()
    product_label = models.CharField(max_length=255)
    product_brand = models.CharField(max_length=255, blank=True)
    product_model = models.CharField(max_length=255, blank=True)
    product_abbr = models.CharField(max_length=255, blank=True)
    category_a = models.CharField(max_length=128, blank=True)
    category_b = models.CharField(max_length=128, blank=True)
    spec_text = models.CharField(max_length=512, blank=True)
    length_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    source_unit = models.CharField(max_length=32, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity_per_package = models.PositiveIntegerField(default=1)
    total_quantity = models.PositiveIntegerField(default=1)
    billing_quantity = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.product_abbr or self.product_label


class CustomCableRequest(TimeStampedModel):
    STATUS_CHOICES = [
        ("待处理", "待处理"),
        ("处理中", "处理中"),
        ("已绑定", "已绑定"),
        ("已完成", "已完成"),
        ("已忽略", "已忽略"),
        ("已取消", "已取消"),
        ("已关闭", "已关闭"),
    ]

    contact_name = models.CharField(max_length=80, blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    bound_product = models.ForeignKey(CableProduct, null=True, blank=True, related_name="custom_requests", on_delete=models.SET_NULL)
    head_a_type = models.CharField(max_length=80)
    head_a_gender = models.CharField(max_length=40, blank=True)
    head_b_type = models.CharField(max_length=80)
    head_b_gender = models.CharField(max_length=40, blank=True)
    length_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    category_a = models.CharField(max_length=128, blank=True)
    category_b = models.CharField(max_length=128, blank=True)
    scenario = models.CharField(max_length=160, blank=True)
    note = models.TextField(blank=True)
    handle_result = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="待处理", db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.head_a_type} - {self.head_b_type}"


class CableMallPermissionRule(models.Model):
    PERMISSION_ADMIN = "admin"
    PERMISSION_USER = "user"
    SCOPE_DEPARTMENT = "department"
    SCOPE_DEPARTMENT_WITH_SUB = "departmentSub"
    SCOPE_EMPLOYEE = "employee"
    SCOPE_EXCLUDED_EMPLOYEE = "excludedEmployee"

    PERMISSION_CHOICES = [
        (PERMISSION_ADMIN, "线材商城管理员"),
        (PERMISSION_USER, "线材商城普通用户"),
    ]
    SCOPE_CHOICES = [
        (SCOPE_DEPARTMENT, "部门"),
        (SCOPE_DEPARTMENT_WITH_SUB, "部门（含下级）"),
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
        db_table = "cable_mall_permission_rules"
        ordering = ["permission", "scope_type", "sort_order", "target_name", "target_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["permission", "scope_type", "target_id"],
                name="uniq_cable_mall_permission_rule",
            ),
        ]
        indexes = [
            models.Index(fields=["permission", "scope_type"], name="idx_cable_mall_perm_scope"),
        ]

    def __str__(self):
        return f"{self.get_permission_display()} - {self.target_name or self.target_id}"


class CableMallConfigurationRevision(models.Model):
    key = models.CharField(max_length=64, unique=True)
    revision = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cable_mall_configuration_revisions"
        ordering = ["key"]


class CableMallOrganizationSyncState(models.Model):
    state_key = models.CharField(max_length=64, unique=True, default="auth-organization")
    org_revision = models.PositiveBigIntegerField(default=0)
    synced_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cable_mall_organization_sync_states"
        ordering = ["state_key"]
