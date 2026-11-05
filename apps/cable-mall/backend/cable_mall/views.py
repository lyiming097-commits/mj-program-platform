from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, IntegerField, Max, Q, Value, When
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.views.decorators.csrf import csrf_exempt

from identity_api.auth.http import extract_bearer_token
from identity_api.auth.org_client import AuthOrgClientError

from .external_auth import (
    ExternalAuthError,
    decode_external_token,
    external_password_version,
    hash_external_password,
    issue_external_token,
    verify_external_password,
)
from .exports import export_order_excel, export_order_pdf
from .image_cache import ensure_product_thumbnail, ensure_product_thumbnails, product_thumb_path
from .models import (
    CableMallExternalAccount,
    CableMallConfigurationRevision,
    CablePackage,
    CablePackageItem,
    CableProduct,
    CartItem,
    CustomCableRequest,
    Order,
    OrderItem,
    OrderPackage,
    ProductCartItem,
    Project,
    ShippingAddress,
    SigningInfo,
)
from .org_sync import refresh_auth_organization_snapshot
from .permissions import (
    CABLE_MALL_PERMISSION_LABELS,
    cable_mall_permission_directory as build_cable_mall_permission_directory,
    list_cable_mall_permission_rules,
    replace_cable_mall_permission_rules,
    request_cable_mall_scope,
)
from .serializers import (
    cable_product_dict,
    cart_item_dict,
    custom_request_dict,
    external_account_dict,
    order_dict,
    package_dict,
    product_cart_item_dict,
    project_dict,
    shipping_address_dict,
    signing_info_dict,
)
from .source_catalog import (
    CableSourceError,
    fetch_online_cables,
    request_product_image,
    source_cable_category_labels,
    source_health,
)


def json_response(data, status=200):
    return JsonResponse(data, status=status, safe=False, json_dumps_params={"ensure_ascii": False})


def parse_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def bad_request(message, status=400):
    return json_response({"ok": False, "message": message, "error": message}, status=status)


CABLE_MALL_CONFIGURATION_PERMISSIONS = "permissions"


def _configuration_revision_value(key: str) -> str:
    state, _created = CableMallConfigurationRevision.objects.get_or_create(
        key=key,
        defaults={"revision": 1},
    )
    return str(max(1, int(state.revision or 1)))


def _lock_configuration_revision(data: dict, key: str, label: str):
    expected = str(data.get("revision") or "").strip()
    state, _created = CableMallConfigurationRevision.objects.select_for_update().get_or_create(
        key=key,
        defaults={"revision": 1},
    )
    current_revision = str(max(1, int(state.revision or 1)))
    if not expected:
        return None, json_response({
            "ok": False,
            "error": f"缺少{label}版本，请刷新后重新编辑",
            "code": "REVISION_REQUIRED",
            "revision": current_revision,
        }, status=400)
    if expected != current_revision:
        return None, json_response({
            "ok": False,
            "error": f"{label}已被其他人修改，请刷新后重新编辑",
            "code": "REVISION_CONFLICT",
            "revision": current_revision,
        }, status=409)
    return state, None


def _advance_configuration_revision(state: CableMallConfigurationRevision) -> str:
    state.revision = max(1, int(state.revision or 1)) + 1
    state.save(update_fields=["revision", "updated_at"])
    return str(state.revision)


def _org_revision_conflict(data: dict, current_revision) -> JsonResponse | None:
    expected = str(data.get("orgRevision") or "").strip()
    current = str(current_revision if current_revision is not None else "").strip()
    if not expected:
        return json_response({
            "ok": False,
            "error": "缺少组织架构版本，请重新打开选择窗口后再保存",
            "code": "ORG_REVISION_REQUIRED",
            "orgRevision": current,
        }, status=400)
    if not current or expected != current:
        return json_response({
            "ok": False,
            "error": "组织架构已发生变化，请重新打开选择窗口后再保存",
            "code": "ORG_REVISION_CONFLICT",
            "orgRevision": current,
        }, status=409)
    return None


def _actor(request):
    return str(getattr(request, "auth_user_id", "") or "").strip()


def _actor_name(request):
    employee = getattr(request, "auth_employee", None)
    return str(
        getattr(employee, "name", "")
        or getattr(request, "auth_user_name", "")
        or _actor(request)
    ).strip()


def ensure_cable_mall_access(request):
    scope = request_cable_mall_scope(request)
    if scope["can_access_cable_mall"]:
        return None
    return json_response({"error": "暂无线材商城访问权限，请联系线材商城管理员"}, status=403)


def ensure_cable_mall_admin(request):
    scope = request_cable_mall_scope(request)
    if scope["can_manage_cable_mall"]:
        return None
    return json_response({"error": "暂无线材商城管理员权限"}, status=403)


def to_decimal(value, default=None):
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return default


def positive_int(value, default=1):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def truthy_payload(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "是", "默认"}


ORDER_WORKFLOW_UPLOAD_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".jfif"}
ORDER_WORKFLOW_UPLOAD_MIME_TYPES = {"application/pdf", "application/octet-stream"}
ORDER_WORKFLOW_FILE_FIELDS = {
    "contract": "contract_file",
    "shipment": "shipment_file",
    "invoice": "invoice_file",
    "payment": "payment_file",
}


def validate_order_workflow_upload(uploaded_file):
    filename = str(getattr(uploaded_file, "name", "") or "")
    suffix = Path(filename).suffix.lower()
    content_type = str(getattr(uploaded_file, "content_type", "") or "").lower()
    if suffix not in ORDER_WORKFLOW_UPLOAD_EXTENSIONS:
        raise ValueError("文件只支持 PDF 或图片格式")
    if content_type and content_type not in ORDER_WORKFLOW_UPLOAD_MIME_TYPES and not content_type.startswith("image/"):
        raise ValueError("文件只支持 PDF 或图片格式")


def parse_signing_info_payload(payload):
    company_name = payload.get("company_name", "").strip()
    opening_bank = payload.get("opening_bank", "").strip()
    tax_number = payload.get("tax_number", "").strip()
    bank_account = payload.get("bank_account", "").strip()
    if not company_name:
        raise ValueError("请填写公司名称")
    if not opening_bank:
        raise ValueError("请填写开户银行")
    if not tax_number:
        raise ValueError("请填写税号")
    if not bank_account:
        raise ValueError("请填写账号")
    return {
        "company_name": company_name,
        "opening_bank": opening_bank,
        "tax_number": tax_number,
        "bank_account": bank_account,
    }


def shipping_address_scope_queryset(item):
    if item.external_account_id:
        return ShippingAddress.objects.filter(external_account_id=item.external_account_id)
    return ShippingAddress.objects.filter(owner_user_id=item.owner_user_id, external_account__isnull=True)


def internal_orders_queryset(request):
    scope = request_cable_mall_scope(request)
    qs = Order.objects.prefetch_related("packages", "packages__items")
    if scope["can_manage_cable_mall"]:
        return qs
    actor = _actor(request)
    return qs.filter(owner_user_id=actor)


def internal_external_accounts_queryset(request):
    scope = request_cable_mall_scope(request)
    qs = CableMallExternalAccount.objects.annotate(order_count=Count("orders"))
    if scope["can_manage_cable_mall"]:
        return qs
    actor = _actor(request)
    return qs.filter(owner_user_id=actor)


def internal_shipping_addresses_queryset(request):
    scope = request_cable_mall_scope(request)
    qs = ShippingAddress.objects.all()
    if scope["can_manage_cable_mall"]:
        return qs
    actor = _actor(request)
    return qs.filter(owner_user_id=actor, external_account__isnull=True)


def internal_signing_infos_queryset(request):
    scope = request_cable_mall_scope(request)
    qs = SigningInfo.objects.all()
    if scope["can_manage_cable_mall"]:
        return qs
    actor = _actor(request)
    return qs.filter(owner_user_id=actor, external_account__isnull=True)


def internal_custom_requests_queryset(request):
    scope = request_cable_mall_scope(request)
    qs = CustomCableRequest.objects.select_related("bound_product")
    if scope["can_manage_cable_mall"]:
        return qs
    actor = _actor(request)
    owned_external_usernames = CableMallExternalAccount.objects.filter(owner_user_id=actor).values_list("username", flat=True)
    return qs.filter(Q(contact_phone__in=owned_external_usernames) | Q(contact_phone=actor))


def active_cable_products():
    return CableProduct.objects.filter(is_active=True)


def parse_custom_category_payload(payload):
    category_a = payload.get("category_a", "").strip()
    category_b = payload.get("category_b", "").strip()
    if not category_a or not category_b:
        raise ValueError("请选择线材分类")
    if not active_cable_products().filter(category_a=category_a, category_b=category_b).exists():
        raise ValueError("请选择系统已有线材分类")
    return category_a, category_b


def require_external_account(request):
    token = extract_bearer_token(request.META.get("HTTP_AUTHORIZATION"))
    if not token:
        return None, json_response({"error": "请先登录外部商城账号"}, status=401)
    try:
        claims = decode_external_token(token)
    except ExternalAuthError as exc:
        return None, json_response({"error": str(exc)}, status=401)
    account = CableMallExternalAccount.objects.filter(pk=claims["sub"]).first()
    if account is None:
        return None, json_response({"error": "外部商城账号不存在"}, status=401)
    password_changed_at = account.password_changed_at or account.updated_at
    password_version = external_password_version(password_changed_at)
    if int(claims.get("pwd") or 0) != password_version:
        return None, json_response({"error": "密码错误，请重新登录"}, status=401)
    if account.status != CableMallExternalAccount.STATUS_ACTIVE:
        return None, json_response({"error": "外部商城账号已停用"}, status=403)
    return account, None


def _legacy_cable_product_match(row):
    candidates = CableProduct.objects.select_for_update().filter(product_archive_id__gte=0)
    kingdee_code = str(row.get("kingdee_code") or "").strip()
    if kingdee_code:
        matches = list(candidates.filter(kingdee_code=kingdee_code)[:2])
        if len(matches) == 1:
            return matches[0]
    matches = list(candidates.filter(
        label=row["label"],
        product_model=row["product_model"],
        abbr=row["abbr"],
    )[:2])
    return matches[0] if len(matches) == 1 else None


def upsert_cable_products(rows, *, category_a_labels=None, exclude_category_a_labels=None):
    seen = []
    created = 0
    updated = 0
    migrated = 0
    deactivated = 0
    category_a_labels = [item for item in (category_a_labels or []) if item]
    exclude_category_a_labels = [item for item in (exclude_category_a_labels or []) if item]
    with transaction.atomic():
        for row in rows:
            source_id = row["product_archive_id"]
            seen.append(source_id)
            defaults = {
                "label": row["label"],
                "product_brand": row["product_brand"],
                "product_model": row["product_model"],
                "abbr": row["abbr"],
                "category_a": row["category_a"],
                "category_b": row["category_b"],
                "kingdee_code": row["kingdee_code"],
                "product_images": row["product_images"],
                "plan_para": row["plan_para"],
                "spec_text": row["spec_text"],
                "length_m": row["length_m"],
                "quantity_unit": row["quantity_unit"],
                "unit_price": row["unit_price"],
                "salesperson_price": row["salesperson_price"],
                "distributor_price": row["distributor_price"],
                "budget_price": row["budget_price"],
                "market_reference_price": row["market_reference_price"],
                "comments": row["comments"],
                "phase": row["phase"],
                "archive_updated_at": row["archive_updated_at"],
                "is_active": bool(row.get("is_active", True)),
            }
            item = CableProduct.objects.select_for_update().filter(product_archive_id=source_id).first()
            if item is None:
                item = _legacy_cable_product_match(row)
                if item is not None:
                    item.product_archive_id = source_id
                    migrated += 1
            if item is None:
                CableProduct.objects.create(product_archive_id=source_id, **defaults)
                created += 1
            else:
                for key, value in defaults.items():
                    setattr(item, key, value)
                item.save(update_fields=[
                    "product_archive_id",
                    *defaults.keys(),
                    "synced_at",
                    "updated_at",
                ])
                updated += 1
        inactive_qs = CableProduct.objects.exclude(product_archive_id__in=seen)
        if category_a_labels:
            inactive_qs = inactive_qs.filter(category_a__in=category_a_labels)
        if exclude_category_a_labels:
            inactive_qs = inactive_qs.exclude(category_a__in=exclude_category_a_labels)
        deactivated = inactive_qs.update(is_active=False)
    return {
        "created": created,
        "updated": updated,
        "migrated": migrated,
        "deactivated": deactivated,
        "active_count": (
            CableProduct.objects.filter(is_active=True, category_a__in=category_a_labels).count()
            if category_a_labels
            else (
                CableProduct.objects.filter(is_active=True)
                .exclude(category_a__in=exclude_category_a_labels)
                .count()
                if exclude_category_a_labels
                else CableProduct.objects.filter(is_active=True).count()
            )
        ),
    }


def sync_product_thumbnails(*, force=False):
    products = CableProduct.objects.filter(is_active=True).only(
        "id",
        "product_archive_id",
        "product_images",
    )
    return ensure_product_thumbnails(products, force=force)


def product_catalog_sync_due():
    interval = max(int(settings.PRODUCT_ARCHIVE_CATALOG.get("SYNC_INTERVAL_SECONDS", 300)), 0)
    if interval == 0:
        return True
    latest = CableProduct.objects.aggregate(value=Max("synced_at"))["value"]
    if latest is None:
        return True
    return (timezone.now() - latest).total_seconds() >= interval


def sync_product_catalog(*, force=False):
    if not force and not product_catalog_sync_due():
        return {"skipped": True, "active_count": active_cable_products().count()}
    rows = fetch_online_cables()
    if not rows and CableProduct.objects.exists():
        raise CableSourceError("产品档案返回的线材目录为空，已保留现有线材数据")
    result = upsert_cable_products(rows, category_a_labels=source_cable_category_labels())
    result["thumbnails"] = sync_product_thumbnails()
    result["source"] = "product-archive"
    return result


def package_totals(package):
    items = list(package.items.all())
    return {
        "item_count": len(items),
        "cable_count": sum(item.quantity for item in items),
    }


def snapshot_item_from_product(package, product, quantity=1, note="", length_m=None):
    return CablePackageItem.objects.create(
        package=package,
        product=product,
        product_archive_id=product.product_archive_id,
        product_label=product.label,
        product_brand=product.product_brand,
        product_model=product.product_model,
        product_abbr=product.abbr,
        category_a=product.category_a,
        category_b=product.category_b,
        spec_text=product.spec_text,
        length_m=length_m if length_m is not None else product.length_m,
        source_unit=product.quantity_unit,
        unit_price=product.salesperson_price,
        quantity=quantity,
        note=note,
    )


def calculate_billing_quantity(item, package_quantity):
    total_quantity = item.quantity_per_package * package_quantity
    if item.source_unit == "米" and item.length_m:
        return Decimal(total_quantity) * item.length_m
    return Decimal(total_quantity)


def selected_packages_from_payload(payload, package_qs, *, require_project_source=False):
    selected = payload.get("packages") or []
    if not selected:
        return []
    if not isinstance(selected, list):
        raise ValueError("选择的线材清单格式错误")
    package_ids = [positive_int(item.get("package_id"), 0) for item in selected if item.get("package_id")]
    package_map = {
        package.id: package
        for package in package_qs.filter(id__in=package_ids, is_archived=False).prefetch_related("items")
    }
    selected_packages = []
    for item in selected:
        package_id = positive_int(item.get("package_id"), 0)
        package = package_map.get(package_id)
        if not package:
            raise ValueError("选择的线材清单不存在或已归档")
        if require_project_source and (item.get("source") != "project" or not package.project_id):
            raise ValueError("该下单入口已移除，请使用购物车或项目下单")
        selected_packages.append((package, positive_int(item.get("quantity"), 1)))
    return selected_packages


def create_snapshot_package_from_products(payload, product_qs, *, name, created_by, owner_name, external_account=None):
    products = payload.get("products") or []
    if not isinstance(products, list) or not products:
        raise ValueError("请选择需要购买的线材")
    product_ids = [positive_int(item.get("product_id"), 0) for item in products if item.get("product_id")]
    product_map = {
        product.id: product
        for product in product_qs.filter(id__in=product_ids, is_active=True)
    }
    if not product_map:
        raise ValueError("选择的线材不存在或已下架")
    package = CablePackage.objects.create(
        external_account=external_account,
        name=name,
        created_by=created_by,
        owner_name=owner_name,
        note="直接下单自动生成",
        quantity=1,
        is_archived=True,
    )
    for row in products:
        product_id = positive_int(row.get("product_id"), 0)
        product = product_map.get(product_id)
        if not product:
            raise ValueError("选择的线材不存在或已下架")
        snapshot_item_from_product(
            package,
            product,
            quantity=positive_int(row.get("quantity"), 1),
            note=row.get("note", "").strip(),
            length_m=to_decimal(row.get("length_m"), product.length_m),
        )
    return package


def order_salesperson_snapshot(customer_account, *, owner_user_id="", owner_name=""):
    if customer_account is not None:
        return (
            getattr(customer_account, "owner_user_id", "") or str(owner_user_id or "").strip(),
            getattr(customer_account, "owner_name", "") or str(owner_name or "").strip(),
        )
    return str(owner_user_id or "").strip(), str(owner_name or "").strip()


def order_submitter_snapshot(*, source=Order.SOURCE_INTERNAL, owner_user_id="", owner_name="", external_account=None):
    if source == Order.SOURCE_EXTERNAL and external_account is not None:
        return (
            getattr(external_account, "username", "") or str(owner_user_id or "").strip(),
            getattr(external_account, "display_name", "") or getattr(external_account, "username", "") or str(owner_name or "").strip(),
        )
    return str(owner_user_id or "").strip(), str(owner_name or "").strip()


def order_customer_account_snapshot(order):
    if getattr(order, "external_account_id", None):
        account = CableMallExternalAccount.objects.filter(pk=order.external_account_id).first()
        if account is not None:
            return account
    username = getattr(order, "external_account_username", "")
    if username:
        return CableMallExternalAccount.objects.filter(username=username).first()
    return None


def create_order_from_packages(
    payload,
    selected_packages,
    *,
    source=Order.SOURCE_INTERNAL,
    owner_user_id="",
    owner_name="",
    external_account=None,
    allow_all_signing_infos=False,
):
    if not selected_packages:
        raise ValueError("请选择需要下单的线材")
    customer_account = external_account
    if customer_account is None:
        account_id = positive_int(payload.get("external_account_id"), 0)
        if not account_id:
            raise ValueError("请选择客户")
        customer_qs = CableMallExternalAccount.objects.filter(status=CableMallExternalAccount.STATUS_ACTIVE)
        if not allow_all_signing_infos:
            customer_qs = customer_qs.filter(owner_user_id=str(owner_user_id))
        customer_account = customer_qs.filter(pk=account_id).first()
        if customer_account is None:
            raise ValueError("选择的客户不存在或已停用")
    shipping_address_id = payload.get("shipping_address_id")
    shipping_address = None
    if shipping_address_id:
        address_qs = ShippingAddress.objects.filter(pk=shipping_address_id)
        if external_account is not None:
            address_qs = address_qs.filter(external_account=external_account)
        elif not allow_all_signing_infos:
            address_qs = address_qs.filter(Q(owner_user_id=str(owner_user_id)), external_account__isnull=True)
        shipping_address = address_qs.first()
        if shipping_address is None:
            raise ValueError("选择的收货地址不存在")
    else:
        raise ValueError("请选择收货地址")
    signing_info_id = payload.get("signing_info_id")
    if not signing_info_id:
        raise ValueError("请选择签单信息")
    info_qs = SigningInfo.objects.filter(pk=signing_info_id)
    if external_account is not None:
        info_qs = info_qs.filter(external_account=external_account)
    elif not allow_all_signing_infos:
        info_qs = info_qs.filter(Q(owner_user_id=str(owner_user_id)), external_account__isnull=True)
    signing_info = info_qs.first()
    if signing_info is None:
        raise ValueError("选择的签单信息不存在")
    salesperson_user_id, salesperson_name = order_salesperson_snapshot(
        customer_account,
        owner_user_id=owner_user_id,
        owner_name=owner_name,
    )
    submitter_user_id, submitter_name = order_submitter_snapshot(
        source=source,
        owner_user_id=owner_user_id,
        owner_name=owner_name,
        external_account=external_account,
    )
    order_no = f"XC{timezone.localtime().strftime('%Y%m%d%H%M%S')}{uuid4().hex[:4].upper()}"
    order = Order.objects.create(
        order_no=order_no,
        customer_name=payload.get("customer_name", "").strip(),
        customer_phone=payload.get("customer_phone", "").strip(),
        project_name=payload.get("project_name", "").strip(),
        source_shipping_address_id=getattr(shipping_address, "id", None),
        source_signing_info_id=getattr(signing_info, "id", None),
        signing_info=signing_info,
        signing_company_name=getattr(signing_info, "company_name", ""),
        signing_opening_bank=getattr(signing_info, "opening_bank", ""),
        signing_tax_number=getattr(signing_info, "tax_number", ""),
        signing_bank_account=getattr(signing_info, "bank_account", ""),
        shipping_method=payload.get("shipping_method", "").strip(),
        arrival_date=parse_order_arrival_date(payload.get("arrival_date")),
        remark=payload.get("remark", "").strip(),
        source=source,
        owner_user_id=str(owner_user_id or "").strip(),
        owner_name=str(owner_name or "").strip(),
        salesperson_user_id=salesperson_user_id,
        salesperson_name=salesperson_name,
        submitter_user_id=submitter_user_id,
        submitter_name=submitter_name,
        external_account=external_account,
        external_account_username=getattr(customer_account, "username", "") if customer_account else "",
        external_account_name=getattr(customer_account, "display_name", "") if customer_account else "",
        external_account_credit_code=getattr(customer_account, "credit_code", "") if customer_account else "",
    )

    total_packages = 0
    total_cables = 0
    total_amount = Decimal("0")
    for package, quantity in selected_packages:
        if not package.items.exists():
            raise ValueError(f"{package.name} 为空，不能下单")
        package_quantity = positive_int(quantity)
        total_packages += package_quantity
        order_package = OrderPackage.objects.create(
            order=order,
            source_package_id=package.id if not package.is_archived else None,
            source_project_id=package.project_id,
            project_name=getattr(package.project, "name", "") if package.project_id else "",
            classroom_name=package.classroom_name,
            classroom_scope=package.classroom_scope,
            package_name=package.name,
            package_note=package.note,
            package_quantity=package_quantity,
        )
        for package_item in package.items.all():
            total_quantity = package_item.quantity * package_quantity
            billing_quantity = (
                Decimal(total_quantity) * package_item.length_m
                if package_item.source_unit == "米" and package_item.length_m
                else Decimal(total_quantity)
            )
            line_total = (billing_quantity * package_item.unit_price).quantize(Decimal("0.01"))
            OrderItem.objects.create(
                order_package=order_package,
                product_archive_id=package_item.product_archive_id,
                product_label=package_item.product_label,
                product_brand=package_item.product_brand,
                product_model=package_item.product_model,
                product_abbr=package_item.product_abbr,
                category_a=package_item.category_a,
                category_b=package_item.category_b,
                spec_text=package_item.spec_text,
                length_m=package_item.length_m,
                source_unit=package_item.source_unit,
                unit_price=package_item.unit_price,
                quantity_per_package=package_item.quantity,
                total_quantity=total_quantity,
                billing_quantity=billing_quantity,
                line_total=line_total,
                note=package_item.note,
            )
            total_cables += total_quantity
            total_amount += line_total

    order.total_packages = total_packages
    order.total_cables = total_cables
    order.total_amount = total_amount.quantize(Decimal("0.01"))
    order.save(update_fields=["total_packages", "total_cables", "total_amount", "updated_at"])
    return order


def replace_order_from_packages(
    order,
    payload,
    selected_packages,
    *,
    owner_user_id="",
    external_account=None,
    allow_all_signing_infos=False,
):
    if order.status == Order.STATUS_DELETED:
        raise ValueError("已删除订单不能修改")
    if not order_is_unlocked(order):
        raise ValueError("锁单后不能修改订单，只能复制下单")
    if not selected_packages:
        raise ValueError("请选择需要下单的线材")
    customer_account = external_account
    if customer_account is None:
        account_id = positive_int(payload.get("external_account_id"), 0)
        if not account_id:
            raise ValueError("请选择客户")
        customer_qs = CableMallExternalAccount.objects.filter(status=CableMallExternalAccount.STATUS_ACTIVE)
        if not allow_all_signing_infos:
            customer_qs = customer_qs.filter(owner_user_id=str(owner_user_id))
        customer_account = customer_qs.filter(pk=account_id).first()
        if customer_account is None:
            raise ValueError("选择的客户不存在或已停用")

    shipping_address_id = payload.get("shipping_address_id")
    if not shipping_address_id:
        raise ValueError("请选择收货地址")
    address_qs = ShippingAddress.objects.filter(pk=shipping_address_id)
    if external_account is not None:
        address_qs = address_qs.filter(external_account=external_account)
    elif not allow_all_signing_infos:
        address_qs = address_qs.filter(Q(owner_user_id=str(owner_user_id)), external_account__isnull=True)
    shipping_address = address_qs.first()
    if shipping_address is None:
        raise ValueError("选择的收货地址不存在")

    signing_info_id = payload.get("signing_info_id")
    if not signing_info_id:
        raise ValueError("请选择签单信息")
    info_qs = SigningInfo.objects.filter(pk=signing_info_id)
    if external_account is not None:
        info_qs = info_qs.filter(external_account=external_account)
    elif not allow_all_signing_infos:
        info_qs = info_qs.filter(Q(owner_user_id=str(owner_user_id)), external_account__isnull=True)
    signing_info = info_qs.first()
    if signing_info is None:
        raise ValueError("选择的签单信息不存在")
    salesperson_user_id, salesperson_name = order_salesperson_snapshot(
        customer_account,
        owner_user_id=owner_user_id,
        owner_name=order.owner_name,
    )
    submitter_user_id = order.submitter_user_id or str(owner_user_id or "").strip()
    submitter_name = order.submitter_name or order.owner_name

    order.customer_name = payload.get("customer_name", "").strip()
    order.customer_phone = payload.get("customer_phone", "").strip()
    order.project_name = payload.get("project_name", "").strip()
    order.source_shipping_address_id = getattr(shipping_address, "id", None)
    order.source_signing_info_id = getattr(signing_info, "id", None)
    order.signing_info = signing_info
    order.signing_company_name = getattr(signing_info, "company_name", "")
    order.signing_opening_bank = getattr(signing_info, "opening_bank", "")
    order.signing_tax_number = getattr(signing_info, "tax_number", "")
    order.signing_bank_account = getattr(signing_info, "bank_account", "")
    order.shipping_method = payload.get("shipping_method", "").strip()
    order.arrival_date = parse_order_arrival_date(payload.get("arrival_date"))
    order.external_account_username = getattr(customer_account, "username", "") if customer_account else ""
    order.external_account_name = getattr(customer_account, "display_name", "") if customer_account else ""
    order.external_account_credit_code = getattr(customer_account, "credit_code", "") if customer_account else ""
    order.salesperson_user_id = salesperson_user_id
    order.salesperson_name = salesperson_name
    order.submitter_user_id = submitter_user_id
    order.submitter_name = submitter_name
    order.remark = payload.get("remark", "").strip()
    order.status = Order.STATUS_UNLOCKED
    order.total_packages = 0
    order.total_cables = 0
    order.total_amount = Decimal("0")
    order.save()

    order.packages.all().delete()
    total_packages = 0
    total_cables = 0
    total_amount = Decimal("0")
    for package, quantity in selected_packages:
        if not package.items.exists():
            raise ValueError(f"{package.name} 为空，不能下单")
        package_quantity = positive_int(quantity)
        total_packages += package_quantity
        order_package = OrderPackage.objects.create(
            order=order,
            source_package_id=package.id if not package.is_archived else None,
            source_project_id=package.project_id,
            project_name=getattr(package.project, "name", "") if package.project_id else "",
            classroom_name=package.classroom_name,
            classroom_scope=package.classroom_scope,
            package_name=package.name,
            package_note=package.note,
            package_quantity=package_quantity,
        )
        for package_item in package.items.all():
            order_item = create_order_item_from_package_item(order_package, package_item)
            total_cables += order_item.total_quantity
            total_amount += order_item.line_total

    order.total_packages = total_packages
    order.total_cables = total_cables
    order.total_amount = total_amount.quantize(Decimal("0.01"))
    order.save(update_fields=["total_packages", "total_cables", "total_amount", "status", "updated_at"])
    sync_unlocked_order_snapshot(order)
    return order


def build_order_from_cart(payload, **order_kwargs):
    cart_items = list(CartItem.objects.select_related("package").prefetch_related("package__items").all())
    if not cart_items:
        raise ValueError("购物车为空，请先加入线材")

    order = create_order_from_packages(
        payload,
        [(cart_item.package, positive_int(cart_item.quantity)) for cart_item in cart_items],
        **order_kwargs,
    )
    CartItem.objects.all().delete()
    return order


def delete_snapshot_package_unless_saved(package, payload):
    package.delete()


def parse_order_arrival_date(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("到货日期格式错误") from exc


def order_snapshot_signing(order):
    return {
        "company_name": order.signing_company_name or "",
        "opening_bank": order.signing_opening_bank or "",
        "tax_number": order.signing_tax_number or "",
        "bank_account": order.signing_bank_account or "",
    }


def order_snapshot_address(order):
    return {
        "receiver_name": order.customer_name or "",
        "receiver_phone": order.customer_phone or "",
        "detail_address": order.project_name or "",
    }


def order_is_unlocked(order):
    return order.status in {Order.STATUS_UNLOCKED, "已下单", ""}


def order_status_allows_pdf(order):
    return not order_is_unlocked(order) and order.status != Order.STATUS_DELETED


def scoped_order_shipping_address(order):
    if not order.source_shipping_address_id:
        return None
    qs = ShippingAddress.objects.filter(pk=order.source_shipping_address_id)
    if order.external_account_id:
        qs = qs.filter(external_account_id=order.external_account_id)
    return qs.first()


def scoped_order_signing_info(order):
    source_id = order.source_signing_info_id or order.signing_info_id
    if not source_id:
        return None
    qs = SigningInfo.objects.filter(pk=source_id)
    if order.external_account_id:
        qs = qs.filter(external_account_id=order.external_account_id)
    return qs.first()


def current_product_for_source(product_archive_id):
    if not product_archive_id:
        return None
    return active_cable_products().filter(product_archive_id=product_archive_id).first()


def product_snapshot_values(product, fallback):
    if product is None:
        return {
            "product_label": fallback.product_label,
            "product_brand": fallback.product_brand,
            "product_model": fallback.product_model,
            "product_abbr": fallback.product_abbr,
            "category_a": fallback.category_a,
            "category_b": fallback.category_b,
            "spec_text": fallback.spec_text,
            "length_m": fallback.length_m,
            "source_unit": fallback.source_unit,
            "unit_price": fallback.unit_price,
        }
    return {
        "product_label": product.label,
        "product_brand": product.product_brand,
        "product_model": product.product_model,
        "product_abbr": product.abbr,
        "category_a": product.category_a,
        "category_b": product.category_b,
        "spec_text": product.spec_text,
        "length_m": product.length_m,
        "source_unit": product.quantity_unit,
        "unit_price": product.salesperson_price,
    }


def order_item_amounts(quantity_per_package, package_quantity, source_unit, length_m, unit_price):
    total_quantity = positive_int(quantity_per_package) * positive_int(package_quantity)
    billing_quantity = (
        Decimal(total_quantity) * length_m
        if source_unit == "米" and length_m
        else Decimal(total_quantity)
    )
    line_total = (billing_quantity * unit_price).quantize(Decimal("0.01"))
    return total_quantity, billing_quantity, line_total


def create_order_item_from_package_item(order_package, package_item):
    product = current_product_for_source(package_item.product_archive_id)
    product_values = product_snapshot_values(product, package_item)
    total_quantity, billing_quantity, line_total = order_item_amounts(
        package_item.quantity,
        order_package.package_quantity,
        product_values["source_unit"],
        product_values["length_m"],
        product_values["unit_price"],
    )
    return OrderItem.objects.create(
        order_package=order_package,
        product_archive_id=package_item.product_archive_id,
        quantity_per_package=package_item.quantity,
        total_quantity=total_quantity,
        billing_quantity=billing_quantity,
        line_total=line_total,
        note=package_item.note,
        **product_values,
    )


def refresh_order_item_from_current_product(order_item, package_quantity):
    product = current_product_for_source(order_item.product_archive_id)
    product_values = product_snapshot_values(product, order_item)
    total_quantity, billing_quantity, line_total = order_item_amounts(
        order_item.quantity_per_package,
        package_quantity,
        product_values["source_unit"],
        product_values["length_m"],
        product_values["unit_price"],
    )
    for field, value in product_values.items():
        setattr(order_item, field, value)
    order_item.total_quantity = total_quantity
    order_item.billing_quantity = billing_quantity
    order_item.line_total = line_total
    order_item.save()
    return total_quantity, line_total


def sync_unlocked_order_snapshot(order):
    if not order_is_unlocked(order):
        return order

    address = scoped_order_shipping_address(order)
    signing_info = scoped_order_signing_info(order)
    order_fields = []
    if order.status != Order.STATUS_UNLOCKED:
        order.status = Order.STATUS_UNLOCKED
        order_fields.append("status")
    if address is not None:
        next_values = {
            "customer_name": address.receiver_name,
            "customer_phone": address.receiver_phone,
            "project_name": address.detail_address,
        }
        for field, value in next_values.items():
            if getattr(order, field) != value:
                setattr(order, field, value)
                order_fields.append(field)
    if signing_info is not None:
        next_values = {
            "source_signing_info_id": signing_info.id,
            "signing_info": signing_info,
            "signing_company_name": signing_info.company_name,
            "signing_opening_bank": signing_info.opening_bank,
            "signing_tax_number": signing_info.tax_number,
            "signing_bank_account": signing_info.bank_account,
        }
        for field, value in next_values.items():
            if getattr(order, field) != value:
                setattr(order, field, value)
                order_fields.append(field)
    customer_account = order_customer_account_snapshot(order)
    if customer_account is not None:
        external_account = customer_account
        if external_account is not None:
            salesperson_user_id, salesperson_name = order_salesperson_snapshot(
                external_account,
                owner_user_id=order.owner_user_id,
                owner_name=order.owner_name,
            )
            next_values = {
                "external_account_username": external_account.username,
                "external_account_name": external_account.display_name,
                "external_account_credit_code": external_account.credit_code,
                "salesperson_user_id": salesperson_user_id,
                "salesperson_name": salesperson_name,
            }
            if order.source == Order.SOURCE_EXTERNAL:
                next_values.update({
                    "owner_user_id": external_account.owner_user_id,
                    "owner_name": external_account.owner_name,
                })
            for field, value in next_values.items():
                if getattr(order, field) != value:
                    setattr(order, field, value)
                    order_fields.append(field)
    elif not order.salesperson_user_id and not order.salesperson_name:
        next_values = {
            "salesperson_user_id": order.owner_user_id,
            "salesperson_name": order.owner_name,
        }
        for field, value in next_values.items():
            if getattr(order, field) != value:
                setattr(order, field, value)
                order_fields.append(field)

    if not order.submitter_user_id and not order.submitter_name:
        if order.source == Order.SOURCE_EXTERNAL:
            next_values = {
                "submitter_user_id": order.external_account_username or order.owner_user_id,
                "submitter_name": order.external_account_name or order.external_account_username or order.owner_name,
            }
        else:
            next_values = {
                "submitter_user_id": order.owner_user_id,
                "submitter_name": order.owner_name,
            }
        for field, value in next_values.items():
            if getattr(order, field) != value:
                setattr(order, field, value)
                order_fields.append(field)

    total_packages = 0
    total_cables = 0
    total_amount = Decimal("0")
    order_packages = list(order.packages.all())
    for order_package in order_packages:
        package_quantity = positive_int(order_package.package_quantity)
        total_packages += package_quantity
        source_package = None
        if order_package.source_package_id:
            source_package = (
                CablePackage.objects
                .filter(pk=order_package.source_package_id, is_archived=False)
                .prefetch_related("items")
                .first()
            )
        if source_package is not None:
            package_fields = []
            next_package_values = {
                "source_project_id": source_package.project_id,
                "project_name": getattr(source_package.project, "name", "") if source_package.project_id else "",
                "classroom_name": source_package.classroom_name,
                "classroom_scope": source_package.classroom_scope,
                "package_name": source_package.name,
                "package_note": source_package.note,
            }
            for field, value in next_package_values.items():
                if getattr(order_package, field) != value:
                    setattr(order_package, field, value)
                    package_fields.append(field)
            if package_fields:
                order_package.save(update_fields=[*set(package_fields)])
            order_package.items.all().delete()
            for package_item in source_package.items.all():
                order_item = create_order_item_from_package_item(order_package, package_item)
                total_cables += order_item.total_quantity
                total_amount += order_item.line_total
            continue

        for order_item in list(order_package.items.all()):
            line_quantity, line_total = refresh_order_item_from_current_product(order_item, package_quantity)
            total_cables += line_quantity
            total_amount += line_total

    next_total_amount = total_amount.quantize(Decimal("0.01"))
    total_fields = {
        "total_packages": total_packages,
        "total_cables": total_cables,
        "total_amount": next_total_amount,
    }
    for field, value in total_fields.items():
        if getattr(order, field) != value:
            setattr(order, field, value)
            order_fields.append(field)
    if order_fields:
        order.save(update_fields=[*set(order_fields), "updated_at"])
    refreshed = Order.objects.prefetch_related("packages", "packages__items").get(pk=order.pk)
    for field, value in refreshed.__dict__.items():
        if not field.startswith("_"):
            setattr(order, field, value)
    order._prefetched_objects_cache = getattr(refreshed, "_prefetched_objects_cache", {})
    return order


def sync_unlocked_orders(orders):
    for order in orders:
        sync_unlocked_order_snapshot(order)
    return orders


def save_order_workflow_file(order, uploaded_file, kind):
    if uploaded_file is None:
        return False
    validate_order_workflow_upload(uploaded_file)
    original_name = get_valid_filename(uploaded_file.name or f"{kind}.dat")
    uploaded_file.name = f"{order.order_no}-{uuid4().hex[:8]}-{original_name}"
    if kind == "contract":
        order.contract_file = uploaded_file
    elif kind == "shipment":
        order.shipment_file = uploaded_file
    elif kind == "invoice":
        order.invoice_file = uploaded_file
    elif kind == "payment":
        order.payment_file = uploaded_file
    else:
        raise ValueError("未知的文件类型")
    return True


def order_workflow_response(order, status_code=200):
    order = Order.objects.prefetch_related("packages", "packages__items").get(pk=order.pk)
    return json_response({"ok": True, "item": order_dict(order)}, status=status_code)


def lock_order_for_contract(order):
    if not order_is_unlocked(order):
        raise ValueError("只有未锁定订单可以锁单")
    sync_unlocked_order_snapshot(order)
    order.status = Order.STATUS_PENDING_CONTRACT
    order.locked_at = timezone.now()
    order.save(update_fields=["status", "locked_at", "updated_at"])
    return order


def ensure_order_progress_mutable(order):
    if order_is_unlocked(order) or order.status == Order.STATUS_DELETED:
        raise ValueError("锁单后才能操作订单进度")


def upload_order_workflow_attachment(order, uploaded_file, kind):
    ensure_order_progress_mutable(order)
    if uploaded_file is None:
        raise ValueError("请选择文件")
    save_order_workflow_file(order, uploaded_file, kind)
    file_field = ORDER_WORKFLOW_FILE_FIELDS.get(kind)
    if not file_field:
        raise ValueError("未知的进度类型")
    order.save(update_fields=[file_field, "updated_at"])
    return order


def complete_order_workflow_step(order, kind):
    ensure_order_progress_mutable(order)
    now = timezone.now()
    if kind == "contract":
        if order.status != Order.STATUS_PENDING_CONTRACT:
            raise ValueError("只有待签合同订单可以完成合同签订")
        order.status = Order.STATUS_PENDING_SHIPMENT
        order.contract_uploaded_at = now
        order.save(update_fields=["contract_uploaded_at", "status", "updated_at"])
        return order
    if kind == "shipment":
        if order.status != Order.STATUS_PENDING_SHIPMENT:
            raise ValueError("只有待发货订单可以完成发货")
        order.status = Order.STATUS_PENDING_RECEIPT
        order.shipped_at = now
        order.save(update_fields=["shipped_at", "status", "updated_at"])
        return order
    if kind == "invoice":
        order.invoice_uploaded_at = now
        order.save(update_fields=["invoice_uploaded_at", "updated_at"])
        return order
    if kind == "payment":
        order.paid_at = now
        order.save(update_fields=["paid_at", "updated_at"])
        return order
    raise ValueError("未知的进度类型")


def update_order_workflow_step(order, kind, *, status_text=None, note=None):
    ensure_order_progress_mutable(order)
    now = timezone.now()
    update_fields = []
    note_fields = {
        "contract": "contract_note",
        "shipment": "shipment_note",
        "invoice": "invoice_note",
        "payment": "payment_note",
    }
    note_field = note_fields.get(kind)
    if not note_field:
        raise ValueError("未知的进度类型")
    if note is not None:
        setattr(order, note_field, str(note or "").strip())
        update_fields.append(note_field)

    status_text = str(status_text or "").strip()
    if status_text:
        if kind == "contract":
            if status_text == "已签合同":
                order.contract_uploaded_at = order.contract_uploaded_at or now
                update_fields.append("contract_uploaded_at")
                if order.status == Order.STATUS_PENDING_CONTRACT:
                    order.status = Order.STATUS_PENDING_SHIPMENT
                    update_fields.append("status")
            elif status_text == "待签合同":
                order.contract_uploaded_at = None
                order.status = Order.STATUS_PENDING_CONTRACT
                update_fields.extend(["contract_uploaded_at", "status"])
        elif kind == "shipment":
            if status_text == "已发货":
                order.shipped_at = order.shipped_at or now
                update_fields.append("shipped_at")
                if order.status in {Order.STATUS_PENDING_CONTRACT, Order.STATUS_PENDING_SHIPMENT}:
                    order.status = Order.STATUS_PENDING_RECEIPT
                    update_fields.append("status")
            elif status_text in {"未发货", "待发货"}:
                order.shipped_at = None
                if order.status == Order.STATUS_PENDING_RECEIPT:
                    order.status = Order.STATUS_PENDING_SHIPMENT
                    update_fields.append("status")
                update_fields.append("shipped_at")
        elif kind == "invoice":
            if status_text == "已开票":
                order.invoice_uploaded_at = order.invoice_uploaded_at or now
                update_fields.append("invoice_uploaded_at")
            elif status_text in {"待开票", "未开票"}:
                order.invoice_uploaded_at = None
                update_fields.append("invoice_uploaded_at")
        elif kind == "payment":
            if status_text == "已收款":
                order.paid_at = order.paid_at or now
                update_fields.append("paid_at")
            elif status_text in {"待收款", "未收款"}:
                order.paid_at = None
                update_fields.append("paid_at")

    if update_fields:
        order.save(update_fields=[*set(update_fields), "updated_at"])
    return order


def upload_order_contract(order, uploaded_file):
    upload_order_workflow_attachment(order, uploaded_file, "contract")
    return order


def complete_order_contract(order):
    complete_order_workflow_step(order, "contract")
    return order


def upload_order_shipment(order, uploaded_file):
    upload_order_workflow_attachment(order, uploaded_file, "shipment")
    return order


def complete_order_shipment(order):
    complete_order_workflow_step(order, "shipment")
    return order


def mark_order_shipped(order, uploaded_file=None):
    if uploaded_file is not None:
        upload_order_shipment(order, uploaded_file)
        return order
    return complete_order_shipment(order)


def receive_order(order):
    if order.status != Order.STATUS_PENDING_RECEIPT:
        raise ValueError("只有待签收订单可以签收")
    order.status = Order.STATUS_COMPLETED
    order.received_at = timezone.now()
    order.save(update_fields=["status", "received_at", "updated_at"])
    return order


def upload_order_invoice(order, uploaded_file):
    upload_order_workflow_attachment(order, uploaded_file, "invoice")
    return order


def complete_order_invoice(order):
    complete_order_workflow_step(order, "invoice")
    return order


def upload_order_payment(order, uploaded_file):
    upload_order_workflow_attachment(order, uploaded_file, "payment")
    return order


def complete_order_payment(order):
    complete_order_workflow_step(order, "payment")
    return order


def delete_unlocked_order(order):
    if order.status != Order.STATUS_UNLOCKED:
        raise ValueError("只有未锁定订单可以删除")
    order.status = Order.STATUS_DELETED
    order.save(update_fields=["status", "updated_at"])
    return order


def restore_deleted_order(order):
    if order.status != Order.STATUS_DELETED:
        raise ValueError("只有已删除订单可以恢复")
    sync_unlocked_order_snapshot(order)
    order.status = Order.STATUS_UNLOCKED
    order.save(update_fields=["status", "updated_at"])
    return order


def handle_order_lock(request, order):
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    try:
        lock_order_for_contract(order)
    except ValueError as exc:
        return bad_request(str(exc))
    return order_workflow_response(order)


def handle_order_delete(request, order):
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    try:
        delete_unlocked_order(order)
    except ValueError as exc:
        return bad_request(str(exc))
    return order_workflow_response(order)


def handle_order_restore(request, order):
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    try:
        restore_deleted_order(order)
    except ValueError as exc:
        return bad_request(str(exc))
    return order_workflow_response(order)


def workflow_request_action(request):
    action = str(request.POST.get("action") or request.GET.get("action") or "").strip().lower()
    if action in {"upload", "complete", "update"}:
        return action
    return "upload" if request.FILES else "complete"


def handle_order_workflow_step(request, order, kind, file_field):
    action = workflow_request_action(request)
    if action == "upload":
        upload_order_workflow_attachment(order, request.FILES.get("file") or request.FILES.get(file_field), kind)
        return order
    if action == "update":
        update_order_workflow_step(
            order,
            kind,
            status_text=request.POST.get("status", ""),
            note=request.POST.get("note", None),
        )
        return order
    if "note" in request.POST:
        update_order_workflow_step(order, kind, note=request.POST.get("note", None))
    complete_order_workflow_step(order, kind)
    return order


def handle_order_contract(request, order):
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    try:
        handle_order_workflow_step(request, order, "contract", "contract_file")
    except ValueError as exc:
        return bad_request(str(exc))
    return order_workflow_response(order)


def handle_order_ship(request, order):
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    try:
        handle_order_workflow_step(request, order, "shipment", "shipment_file")
    except ValueError as exc:
        return bad_request(str(exc))
    return order_workflow_response(order)


def handle_order_receive(request, order):
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    try:
        receive_order(order)
    except ValueError as exc:
        return bad_request(str(exc))
    return order_workflow_response(order)


def handle_order_invoice(request, order):
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    try:
        handle_order_workflow_step(request, order, "invoice", "invoice_file")
    except ValueError as exc:
        return bad_request(str(exc))
    return order_workflow_response(order)


def handle_order_payment(request, order):
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    try:
        handle_order_workflow_step(request, order, "payment", "payment_file")
    except ValueError as exc:
        return bad_request(str(exc))
    return order_workflow_response(order)


def signing_snapshot_changed(order, signing_info):
    if signing_info is None:
        return True
    return any(
        order_snapshot_signing(order)[key] != getattr(signing_info, key, "")
        for key in ["company_name", "opening_bank", "tax_number", "bank_account"]
    )


def address_snapshot_changed(order, address):
    if address is None:
        return True
    snapshot = order_snapshot_address(order)
    return (
        snapshot["receiver_name"] != address.receiver_name
        or snapshot["receiver_phone"] != address.receiver_phone
        or snapshot["detail_address"] != address.detail_address
    )


def order_product_snapshot_changed(order_item, product):
    if product is None:
        return True
    checks = [
        order_item.product_label == product.label,
        order_item.product_brand == product.product_brand,
        order_item.product_model == product.product_model,
        order_item.product_abbr == product.abbr,
        order_item.category_a == product.category_a,
        order_item.category_b == product.category_b,
        order_item.spec_text == product.spec_text,
        order_item.length_m == product.length_m,
        order_item.source_unit == product.quantity_unit,
        order_item.unit_price == product.salesperson_price,
    ]
    return not all(checks)


def order_copy_payload(order, *, shipping_address_qs, signing_info_qs):
    warnings = []
    product_quantities = {}
    current_products = {
        item.product_archive_id: item
        for item in active_cable_products().filter(
            product_archive_id__in=[
                order_item.product_archive_id
                for package in order.packages.all()
                for order_item in package.items.all()
            ],
        )
    }
    changed_product_names = []
    missing_product_names = []
    for package in order.packages.all():
        for order_item in package.items.all():
            product = current_products.get(order_item.product_archive_id)
            label = order_item.product_abbr or order_item.product_label or str(order_item.product_archive_id)
            if product is None:
                missing_product_names.append(label)
                continue
            if order_product_snapshot_changed(order_item, product):
                changed_product_names.append(label)
            product_quantities[product.id] = {
                "product_id": product.id,
                "quantity": product_quantities.get(product.id, {}).get("quantity", 0) + order_item.total_quantity,
                "product": cable_product_dict(product),
            }
    if missing_product_names:
        warnings.append({
            "type": "product_missing",
            "message": f"产品消失：{', '.join(missing_product_names[:6])}",
        })
    if changed_product_names:
        warnings.append({
            "type": "product_changed",
            "message": f"产品信息已修改：{', '.join(changed_product_names[:6])}",
        })

    signing_info = None
    source_signing_id = order.source_signing_info_id or order.signing_info_id
    if source_signing_id:
        signing_info = signing_info_qs.filter(pk=source_signing_id).first()
    if signing_info is None and not source_signing_id:
        snapshot_signing = order_snapshot_signing(order)
        signing_info = signing_info_qs.filter(**snapshot_signing).first()
    if signing_info is None:
        warnings.append({"type": "signing_missing", "message": "签单信息消失，请重新选择签单信息"})
    elif signing_snapshot_changed(order, signing_info):
        warnings.append({"type": "signing_changed", "message": "签单信息已修改，已按当前签单信息重新下单"})

    shipping_address = None
    if order.source_shipping_address_id:
        shipping_address = shipping_address_qs.filter(pk=order.source_shipping_address_id).first()
    if shipping_address is None and not order.source_shipping_address_id:
        snapshot_address = order_snapshot_address(order)
        shipping_address = shipping_address_qs.filter(
            receiver_name=snapshot_address["receiver_name"],
            receiver_phone=snapshot_address["receiver_phone"],
            detail_address=snapshot_address["detail_address"],
        ).first()
    if shipping_address is None:
        warnings.append({"type": "address_missing", "message": "收货地址消失，请重新选择收货地址"})
    elif address_snapshot_changed(order, shipping_address):
        warnings.append({"type": "address_changed", "message": "收货地址已修改，已按当前收货地址重新下单"})

    customer_external_account_id = order.external_account_id or ""
    if not customer_external_account_id and order.external_account_username:
        customer_external_account_id = (
            CableMallExternalAccount.objects
            .filter(username=order.external_account_username)
            .values_list("id", flat=True)
            .first()
        ) or ""

    return {
        "products": list(product_quantities.values()),
        "warnings": warnings,
        "shipping_address_id": shipping_address.id if shipping_address else "",
        "signing_info_id": signing_info.id if signing_info else "",
        "external_account_id": order.external_account_id or "",
        "customer_external_account_id": customer_external_account_id,
        "external_account_name": order.external_account_name or "",
        "external_account_credit_code": getattr(order, "external_account_credit_code", "") or "",
        "customer_name": (shipping_address.receiver_name if shipping_address else order.customer_name) or "",
        "customer_phone": (shipping_address.receiver_phone if shipping_address else order.customer_phone) or "",
        "project_name": (shipping_address.detail_address if shipping_address else order.project_name) or "",
        "shipping_method": order.shipping_method or "",
        "arrival_date": order.arrival_date.isoformat() if order.arrival_date else "",
        "remark": order.remark or "",
        "source_order_no": order.order_no,
    }


def product_bind_result(product):
    parts = [
        product.abbr or product.label,
        product.product_model,
        product.spec_text,
    ]
    text = " / ".join(str(part).strip() for part in parts if str(part or "").strip())
    return f"已绑定：{text or product.label or product.id}"


def health(request):
    return json_response({"ok": True, "service": "线材销售系统", "time": datetime.now().isoformat()})


def cable_mall_current_permission(request):
    scope = request_cable_mall_scope(request)
    permission = scope["permission"]
    return json_response({
        "permission": permission,
        "permissionLabel": CABLE_MALL_PERMISSION_LABELS.get(permission, ""),
        "canAccessCableMall": scope["can_access_cable_mall"],
        "canManageCableMall": scope["can_manage_cable_mall"],
        "isSystemAdmin": scope["is_system_admin"],
        "canUseSystemAdmin": getattr(request, "auth_can_use_system_admin", False) is True,
        "isProxying": bool(getattr(request, "auth_is_proxy", False)),
        "rulesConfigured": scope["rules_configured"],
    })


@csrf_exempt
def cable_mall_permissions_collection(request):
    denied = ensure_cable_mall_admin(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        return json_response({
            "items": list_cable_mall_permission_rules(),
            "revision": _configuration_revision_value(CABLE_MALL_CONFIGURATION_PERMISSIONS),
        })
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    items = payload.get("items", [])
    if not isinstance(items, list):
        return bad_request("权限数据格式错误")
    try:
        sync_result = refresh_auth_organization_snapshot(force=True)
    except AuthOrgClientError as exc:
        return bad_request(str(exc), status=exc.status_code)
    org_conflict = _org_revision_conflict(payload, sync_result.get("orgRevision"))
    if org_conflict is not None:
        return org_conflict
    with transaction.atomic():
        revision_state, conflict = _lock_configuration_revision(
            payload,
            CABLE_MALL_CONFIGURATION_PERMISSIONS,
            "权限配置",
        )
        if conflict is not None:
            return conflict
        try:
            saved_items = replace_cable_mall_permission_rules(items, actor_user_id=_actor(request))
        except ValueError as exc:
            return bad_request(str(exc))
        next_revision = _advance_configuration_revision(revision_state)
    return json_response({
        "ok": True,
        "items": saved_items,
        "revision": next_revision,
        "orgRevision": sync_result.get("orgRevision"),
    })


def cable_mall_permission_directory(request):
    denied = ensure_cable_mall_admin(request)
    if denied is not None:
        return denied
    try:
        directory = build_cable_mall_permission_directory()
    except AuthOrgClientError as exc:
        return bad_request(str(exc), status=exc.status_code)
    return json_response(directory)


@csrf_exempt
def external_accounts(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        qs = internal_external_accounts_queryset(request)
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(display_name__icontains=q)
                | Q(credit_code__icontains=q)
                | Q(phone__icontains=q)
                | Q(owner_name__icontains=q)
                | Q(owner_user_id__icontains=q)
            )
        return json_response({"ok": True, "items": [external_account_dict(item) for item in qs[:300]]})

    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")

    username = payload.get("username", "").strip()
    display_name = payload.get("display_name", "").strip()
    credit_code = payload.get("credit_code", "").strip()
    phone = payload.get("phone", "").strip()
    password = payload.get("password", "").strip()
    if not display_name:
        return bad_request("请填写公司名称")
    if not credit_code:
        return bad_request("请填写统一社会信用代码")
    if not username:
        return bad_request("请填写登录账号")
    if len(username) < 3:
        return bad_request("登录账号至少 3 位")
    if not password:
        return bad_request("请填写登录密码")
    if len(password) < 6:
        return bad_request("登录密码至少 6 位")
    actor = _actor(request)
    if not actor:
        return bad_request("缺少内部用户身份", status=403)
    try:
        item = CableMallExternalAccount.objects.create(
            username=username,
            display_name=display_name,
            credit_code=credit_code,
            phone=phone,
            password_hash=hash_external_password(password),
            password_changed_at=timezone.now(),
            status=CableMallExternalAccount.STATUS_ACTIVE,
            owner_user_id=actor,
            owner_name=_actor_name(request),
            created_by=actor,
        )
    except IntegrityError:
        return bad_request("登录账号已存在，请换一个")
    data = external_account_dict(item)
    data["initial_password"] = password
    return json_response({"ok": True, "item": data}, status=201)


@csrf_exempt
def external_account_detail(request, account_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    item = get_object_or_404(internal_external_accounts_queryset(request), pk=account_id)
    if request.method == "GET":
        return json_response({"ok": True, "item": external_account_dict(item)})
    if request.method not in {"PUT", "PATCH", "DELETE"}:
        return bad_request("方法不允许", status=405)
    if request.method == "DELETE":
        item.status = CableMallExternalAccount.STATUS_DISABLED
        item.save(update_fields=["status", "updated_at"])
        return json_response({"ok": True, "item": external_account_dict(item)})
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    if "display_name" in payload:
        item.display_name = payload.get("display_name", "").strip()
    if "credit_code" in payload:
        item.credit_code = payload.get("credit_code", "").strip()
    if "phone" in payload:
        item.phone = payload.get("phone", "").strip()
    if "status" in payload:
        status = payload.get("status")
        if status not in dict(CableMallExternalAccount.STATUS_CHOICES):
            return bad_request("账号状态不正确")
        item.status = status
    if "password" in payload:
        password = payload.get("password", "").strip()
        if password:
            if len(password) < 6:
                return bad_request("登录密码至少 6 位")
            item.password_hash = hash_external_password(password)
            item.password_changed_at = timezone.now()
    if not item.display_name:
        return bad_request("请填写公司名称")
    if not item.credit_code:
        return bad_request("请填写统一社会信用代码")
    item.save()
    return json_response({"ok": True, "item": external_account_dict(item)})


def source_health_view(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    return json_response(source_health())


@csrf_exempt
def sync_products(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method not in {"POST", "GET"}:
        return bad_request("方法不允许", status=405)
    try:
        result = sync_product_catalog(force=True)
    except CableSourceError as exc:
        return bad_request(str(exc), status=502)
    return json_response({"ok": True, **result})


def _product_thumb_response(request, product_id, *, external=False):
    denied = require_external_account(request)[1] if external else ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method not in {"GET", "HEAD"}:
        return bad_request("方法不允许", status=405)
    product = get_object_or_404(active_cable_products(), pk=product_id)
    if not (product.product_images or []):
        return bad_request("产品暂无图片", status=404)
    cache_path = product_thumb_path(product)
    if cache_path is None or (not cache_path.exists() and not ensure_product_thumbnail(product)):
        return bad_request("图片缩略图生成失败", status=502)
    response = FileResponse(open(cache_path, "rb"), content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=86400"
    return response


def product_thumb(request, product_id):
    return _product_thumb_response(request, product_id)


def external_product_thumb(request, product_id):
    return _product_thumb_response(request, product_id, external=True)


def _product_image_response(request, product_id, *, external=False):
    denied = require_external_account(request)[1] if external else ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method not in {"GET", "HEAD"}:
        return bad_request("方法不允许", status=405)
    product = get_object_or_404(active_cable_products(), pk=product_id)
    variant = str(request.GET.get("variant") or "preview").strip().lower()
    if variant == "thumbnail":
        return _product_thumb_response(request, product_id, external=external)
    if variant != "preview":
        return bad_request("产品图片规格不正确", status=400)
    try:
        source = request_product_image(product.product_archive_id, method=request.method, variant="preview")
    except CableSourceError as exc:
        return bad_request(str(exc), status=502)
    response = HttpResponse(source["body"], content_type=source["content_type"])
    if source.get("content_length") and request.method == "HEAD":
        response["Content-Length"] = str(source["content_length"])
    else:
        response["Content-Length"] = str(len(source["body"]))
    response["Cache-Control"] = source.get("cache_control") or "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def product_image(request, product_id):
    return _product_image_response(request, product_id)


def external_product_image(request, product_id):
    return _product_image_response(request, product_id, external=True)


def products(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    source_error = ""
    if request.GET.get("sync") == "1" or product_catalog_sync_due():
        try:
            sync_product_catalog(force=request.GET.get("sync") == "1")
        except CableSourceError as exc:
            source_error = str(exc)

    qs = active_cable_products()
    q = request.GET.get("q", "").strip()
    category_a = request.GET.get("category_a", "").strip()
    category = request.GET.get("category", "").strip()
    category_b = request.GET.get("category_b", category).strip()
    if q:
        qs = qs.filter(
            Q(label__icontains=q)
            | Q(abbr__icontains=q)
            | Q(product_model__icontains=q)
            | Q(category_a__icontains=q)
            | Q(category_b__icontains=q)
            | Q(kingdee_code__icontains=q)
            | Q(plan_para__icontains=q)
        )
    if category_a:
        qs = qs.filter(category_a=category_a)
    if category_b:
        qs = qs.filter(category_b=category_b)

    package_id = positive_int(request.GET.get("package_id"), 0)
    selected_source_ids = []
    if package_id:
        selected_source_ids = list(
            CablePackageItem.objects
            .filter(package_id=package_id, package__is_archived=False, quantity__gt=0)
            .values_list("product_archive_id", flat=True)
            .distinct()
        )

    total = qs.count()
    page = positive_int(request.GET.get("page"), 1)
    page_size = min(positive_int(request.GET.get("page_size"), 80), 200)
    start = (page - 1) * page_size
    if selected_source_ids:
        qs = qs.annotate(
            selected_rank=Case(
                When(product_archive_id__in=selected_source_ids, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by("selected_rank", "label", "abbr", "product_model", "product_archive_id")
    else:
        qs = qs.order_by("label", "abbr", "product_model", "product_archive_id")
    items = list(qs[start:start + page_size])
    active_products = active_cable_products()
    categories_a = list(
        active_products
        .order_by("category_a")
        .values_list("category_a", flat=True)
        .distinct()
    )
    category_b_source = active_products.filter(category_a=category_a) if category_a else active_products
    categories_b = list(
        category_b_source
        .order_by("category_a", "category_b")
        .values_list("category_b", flat=True)
        .distinct()
    )
    return json_response(
        {
            "ok": not source_error,
            "source_error": source_error,
            "total": total,
            "page": page,
            "page_size": page_size,
            "categories": categories_b,
            "categories_a": categories_a,
            "categories_b": categories_b,
            "items": [cable_product_dict(item) for item in items],
        }
    )


@csrf_exempt
def projects(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        archived = request.GET.get("archived") in {"1", "true", "True"}
        qs = Project.objects.filter(is_archived=archived, external_account__isnull=True).prefetch_related("packages", "packages__items")
        return json_response({"ok": True, "items": [project_dict(item) for item in qs]})

    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    name = payload.get("name", "").strip()
    if not name:
        return bad_request("项目名称不能为空")
    if Project.objects.filter(name=name, is_archived=False, external_account__isnull=True).exists():
        return bad_request("项目名称已存在，请换一个")
    try:
        project = Project.objects.create(
            name=name,
            created_by=payload.get("created_by", "").strip(),
            customer_name=payload.get("customer_name", "").strip(),
            opportunity_info=payload.get("opportunity_info", "").strip(),
            shipping_address=payload.get("shipping_address", "").strip(),
            shipping_contact=payload.get("shipping_contact", "").strip(),
            shipping_phone=payload.get("shipping_phone", "").strip(),
            note=payload.get("note", "").strip(),
        )
    except IntegrityError:
        return bad_request("项目名称已存在，请换一个")
    return json_response({"ok": True, "item": project_dict(project)}, status=201)


@csrf_exempt
def project_detail(request, project_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    project = get_object_or_404(Project.objects.filter(external_account__isnull=True).prefetch_related("packages", "packages__items"), pk=project_id)
    if request.method == "GET":
        return json_response({"ok": True, "item": project_dict(project)})
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        if "name" in payload:
            name = payload.get("name", "").strip()
            if not name:
                return bad_request("项目名称不能为空")
            if Project.objects.filter(name=name, is_archived=False, external_account__isnull=True).exclude(pk=project.pk).exists():
                return bad_request("项目名称已存在，请换一个")
            project.name = name
        if "customer_name" in payload:
            project.customer_name = payload.get("customer_name", "").strip()
        if "opportunity_info" in payload:
            project.opportunity_info = payload.get("opportunity_info", "").strip()
        if "shipping_address" in payload:
            project.shipping_address = payload.get("shipping_address", "").strip()
        if "shipping_contact" in payload:
            project.shipping_contact = payload.get("shipping_contact", "").strip()
        if "shipping_phone" in payload:
            project.shipping_phone = payload.get("shipping_phone", "").strip()
        if "note" in payload:
            project.note = payload.get("note", "").strip()
        if "is_archived" in payload:
            project.is_archived = bool(payload.get("is_archived"))
        try:
            project.save()
        except IntegrityError:
            return bad_request("项目名称已存在，请换一个")
        return json_response({"ok": True, "item": project_dict(project)})
    if request.method == "DELETE":
        project.is_archived = True
        project.save(update_fields=["is_archived", "updated_at"])
        return json_response({"ok": True})
    return bad_request("方法不允许", status=405)


@csrf_exempt
def packages(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        archived = request.GET.get("archived") in {"1", "true", "True"}
        qs = CablePackage.objects.filter(is_archived=archived, external_account__isnull=True).prefetch_related("items")
        project_id = request.GET.get("project_id")
        if project_id:
            qs = qs.filter(project_id=project_id)
        return json_response({"ok": True, "items": [package_dict(item) for item in qs]})

    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    name = payload.get("name", "").strip()
    if not name:
        return bad_request("线材清单名称不能为空")
    project = None
    project_id = payload.get("project_id")
    if project_id:
            project = get_object_or_404(Project, pk=project_id, is_archived=False, external_account__isnull=True)
    package = CablePackage.objects.create(
        project=project,
        name=name,
        created_by=payload.get("created_by", "").strip(),
        owner_name=payload.get("owner_name", "").strip(),
        classroom_name=payload.get("classroom_name", "").strip(),
        classroom_scope=payload.get("classroom_scope", "").strip(),
        note=payload.get("note", "").strip(),
        quantity=positive_int(payload.get("quantity"), 1),
    )
    return json_response({"ok": True, "item": package_dict(package)}, status=201)


@csrf_exempt
def package_detail(request, package_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    package = get_object_or_404(CablePackage.objects.filter(external_account__isnull=True).prefetch_related("items"), pk=package_id)
    if request.method == "GET":
        return json_response({"ok": True, "item": package_dict(package)})
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        if "name" in payload:
            package.name = payload.get("name", "").strip() or package.name
        if "owner_name" in payload:
            package.owner_name = payload.get("owner_name", "").strip()
        if "project_id" in payload:
            project_id = payload.get("project_id")
            package.project = get_object_or_404(Project, pk=project_id, is_archived=False, external_account__isnull=True) if project_id else None
        if "classroom_name" in payload:
            package.classroom_name = payload.get("classroom_name", "").strip()
        if "classroom_scope" in payload:
            package.classroom_scope = payload.get("classroom_scope", "").strip()
        if "note" in payload:
            package.note = payload.get("note", "").strip()
        if "quantity" in payload:
            package.quantity = positive_int(payload.get("quantity"), package.quantity)
        if "is_archived" in payload:
            package.is_archived = bool(payload.get("is_archived"))
        package.save()
        return json_response({"ok": True, "item": package_dict(package)})
    if request.method == "DELETE":
        package.is_archived = True
        package.save(update_fields=["is_archived", "updated_at"])
        return json_response({"ok": True})
    return bad_request("方法不允许", status=405)


@csrf_exempt
def package_copy(request, package_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    source_package = get_object_or_404(CablePackage.objects.filter(external_account__isnull=True).prefetch_related("items"), pk=package_id, is_archived=False)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    name = payload.get("name", "").strip() or f"{source_package.name} 复制"
    with transaction.atomic():
        package = CablePackage.objects.create(
            name=name,
            created_by=payload.get("created_by", "").strip() or source_package.created_by,
            owner_name=source_package.owner_name,
            note=payload.get("note", "").strip() if "note" in payload else source_package.note,
            quantity=source_package.quantity,
            is_default=False,
        )
        CablePackageItem.objects.bulk_create([
            CablePackageItem(
                package=package,
                product=item.product,
                product_archive_id=item.product_archive_id,
                product_label=item.product_label,
                product_brand=item.product_brand,
                product_model=item.product_model,
                product_abbr=item.product_abbr,
                category_a=item.category_a,
                category_b=item.category_b,
                spec_text=item.spec_text,
                length_m=item.length_m,
                source_unit=item.source_unit,
                unit_price=item.unit_price,
                quantity=item.quantity,
                note=item.note,
            )
            for item in source_package.items.all()
        ])
    return json_response({"ok": True, "item": package_dict(package)}, status=201)


@csrf_exempt
def package_items(request, package_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    package = get_object_or_404(CablePackage, pk=package_id, is_archived=False, external_account__isnull=True)
    if request.method == "DELETE":
        CablePackageItem.objects.filter(package=package).delete()
        return json_response({"ok": True, "item": package_dict(package)})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    product_id = payload.get("product_id")
    product_archive_id = payload.get("product_archive_id")
    product_qs = active_cable_products()
    product = (
        product_qs.filter(id=product_id).first()
        if product_id
        else product_qs.filter(product_archive_id=product_archive_id).first()
    )
    if not product:
        return bad_request("未找到可售线材产品", status=404)
    item = snapshot_item_from_product(
        package,
        product,
        quantity=positive_int(payload.get("quantity"), 1),
        note=payload.get("note", "").strip(),
        length_m=to_decimal(payload.get("length_m"), product.length_m),
    )
    return json_response({"ok": True, "item": package_dict(item.package)}, status=201)


@csrf_exempt
def package_item_detail(request, item_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    item = get_object_or_404(CablePackageItem.objects.select_related("package"), pk=item_id, package__external_account__isnull=True)
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        if "quantity" in payload:
            item.quantity = positive_int(payload.get("quantity"), item.quantity)
        if "length_m" in payload:
            item.length_m = to_decimal(payload.get("length_m"), item.length_m)
        if "note" in payload:
            item.note = payload.get("note", "").strip()
        item.save()
        return json_response({"ok": True, "item": package_dict(item.package)})
    if request.method == "DELETE":
        package = item.package
        item.delete()
        return json_response({"ok": True, "item": package_dict(package)})
    return bad_request("方法不允许", status=405)


@csrf_exempt
def cart(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        items = CartItem.objects.select_related("package").prefetch_related("package__items")
        return json_response({"ok": True, "items": [cart_item_dict(item) for item in items]})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    package = get_object_or_404(CablePackage, pk=payload.get("package_id"), is_archived=False)
    if not package.items.exists():
        return bad_request("线材清单为空，不能加入购物车")
    item, _ = CartItem.objects.update_or_create(
        package=package,
        defaults={"quantity": positive_int(payload.get("quantity"), 1)},
    )
    return json_response({"ok": True, "item": cart_item_dict(item)})


@csrf_exempt
def cart_item_detail(request, item_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    item = get_object_or_404(CartItem.objects.select_related("package"), pk=item_id)
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        item.quantity = positive_int(payload.get("quantity"), item.quantity)
        item.save(update_fields=["quantity", "updated_at"])
        return json_response({"ok": True, "item": cart_item_dict(item)})
    if request.method == "DELETE":
        item.delete()
        return json_response({"ok": True})
    return bad_request("方法不允许", status=405)


def product_cart_queryset(*, owner_user_id="", external_account=None):
    qs = ProductCartItem.objects.select_related("product").filter(
        product__is_active=True,
    )
    if external_account is not None:
        return qs.filter(external_account=external_account)
    return qs.filter(owner_user_id=str(owner_user_id or "").strip(), external_account__isnull=True)


def product_cart_collection(request, *, external_account=None):
    owner_user_id = _actor(request)
    if external_account is None and not owner_user_id:
        return bad_request("无法识别当前账号", status=401)
    if request.method == "GET":
        items = product_cart_queryset(owner_user_id=owner_user_id, external_account=external_account)
        return json_response({"ok": True, "items": [product_cart_item_dict(item) for item in items]})
    if request.method == "DELETE":
        product_cart_queryset(owner_user_id=owner_user_id, external_account=external_account).delete()
        return json_response({"ok": True})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    product = get_object_or_404(active_cable_products(), pk=payload.get("product_id"))
    quantity = positive_int(payload.get("quantity"), 1)
    if external_account is not None:
        item, _ = ProductCartItem.objects.update_or_create(
            external_account=external_account,
            product=product,
            defaults={
                "quantity": quantity,
                "owner_user_id": external_account.owner_user_id,
                "owner_name": external_account.display_name or external_account.username,
            },
        )
    else:
        actor = _actor(request)
        if not actor:
            return bad_request("无法识别当前账号", status=401)
        item, _ = ProductCartItem.objects.update_or_create(
            owner_user_id=actor,
            external_account=None,
            product=product,
            defaults={"quantity": quantity, "owner_name": _actor_name(request)},
        )
    return json_response({"ok": True, "item": product_cart_item_dict(item)})


def product_cart_item_mutation(request, item_id, *, external_account=None):
    owner_user_id = _actor(request)
    if external_account is None and not owner_user_id:
        return bad_request("无法识别当前账号", status=401)
    item = get_object_or_404(
        product_cart_queryset(owner_user_id=owner_user_id, external_account=external_account),
        pk=item_id,
    )
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        item.quantity = positive_int(payload.get("quantity"), item.quantity)
        item.save(update_fields=["quantity", "updated_at"])
        return json_response({"ok": True, "item": product_cart_item_dict(item)})
    if request.method == "DELETE":
        item.delete()
        return json_response({"ok": True})
    return bad_request("方法不允许", status=405)


@csrf_exempt
def product_cart(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    return product_cart_collection(request)


@csrf_exempt
def product_cart_item_detail(request, item_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    return product_cart_item_mutation(request, item_id)


def orders(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method != "GET":
        return bad_request("方法不允许", status=405)
    qs = internal_orders_queryset(request)[:100]
    order_rows = sync_unlocked_orders(list(qs))
    return json_response({"ok": True, "items": [order_dict(item, include_packages=False) for item in order_rows]})


@csrf_exempt
def shipping_addresses(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        qs = internal_shipping_addresses_queryset(request)
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(detail_address__icontains=q)
                | Q(receiver_name__icontains=q)
                | Q(receiver_phone__icontains=q)
            )
        qs = qs.order_by("-updated_at")
        return json_response({"ok": True, "items": [shipping_address_dict(item) for item in qs[:300]]})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    detail_address = payload.get("detail_address", "").strip()
    receiver_name = payload.get("receiver_name", "").strip()
    receiver_phone = payload.get("receiver_phone", "").strip()
    if not detail_address:
        return bad_request("请填写详细地址与门牌号")
    if not receiver_name:
        return bad_request("请填写收货人名字")
    if not receiver_phone:
        return bad_request("请填写手机号")
    item = ShippingAddress.objects.create(
        detail_address=detail_address,
        receiver_name=receiver_name,
        receiver_phone=receiver_phone,
        created_by=payload.get("created_by", "").strip(),
        owner_user_id=_actor(request),
        is_default=False,
    )
    return json_response({"ok": True, "item": shipping_address_dict(item)}, status=201)


@csrf_exempt
def shipping_address_detail(request, address_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    item = get_object_or_404(internal_shipping_addresses_queryset(request), pk=address_id)
    if request.method == "GET":
        return json_response({"ok": True, "item": shipping_address_dict(item)})
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        if "detail_address" in payload:
            detail_address = payload.get("detail_address", "").strip()
            if not detail_address:
                return bad_request("请填写详细地址与门牌号")
            item.detail_address = detail_address
        if "receiver_name" in payload:
            receiver_name = payload.get("receiver_name", "").strip()
            if not receiver_name:
                return bad_request("请填写收货人名字")
            item.receiver_name = receiver_name
        if "receiver_phone" in payload:
            receiver_phone = payload.get("receiver_phone", "").strip()
            if not receiver_phone:
                return bad_request("请填写手机号")
            item.receiver_phone = receiver_phone
        item.is_default = False
        item.save()
        return json_response({"ok": True, "item": shipping_address_dict(item)})
    if request.method == "DELETE":
        item.delete()
        return json_response({"ok": True})
    return bad_request("方法不允许", status=405)


@csrf_exempt
def signing_infos(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        qs = internal_signing_infos_queryset(request)
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(company_name__icontains=q)
                | Q(opening_bank__icontains=q)
                | Q(tax_number__icontains=q)
                | Q(bank_account__icontains=q)
            )
        qs = qs.order_by("-updated_at")
        return json_response({"ok": True, "items": [signing_info_dict(item) for item in qs[:300]]})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    try:
        data = parse_signing_info_payload(payload)
    except ValueError as exc:
        return bad_request(str(exc))
    item = SigningInfo.objects.create(
        **data,
        created_by=payload.get("created_by", "").strip(),
        owner_user_id=_actor(request),
    )
    return json_response({"ok": True, "item": signing_info_dict(item)}, status=201)


@csrf_exempt
def signing_info_detail(request, info_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    item = get_object_or_404(internal_signing_infos_queryset(request), pk=info_id)
    if request.method == "GET":
        return json_response({"ok": True, "item": signing_info_dict(item)})
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        try:
            data = parse_signing_info_payload(payload)
        except ValueError as exc:
            return bad_request(str(exc))
        for field, value in data.items():
            setattr(item, field, value)
        item.save()
        return json_response({"ok": True, "item": signing_info_dict(item)})
    if request.method == "DELETE":
        item.delete()
        return json_response({"ok": True})
    return bad_request("方法不允许", status=405)


@csrf_exempt
def checkout(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    scope = request_cable_mall_scope(request)
    try:
        with transaction.atomic():
            if payload.get("products"):
                package = create_snapshot_package_from_products(
                    payload,
                    active_cable_products(),
                    name=f"{_actor_name(request) or _actor(request) or '内部用户'} 直接下单",
                    created_by=_actor_name(request) or _actor(request),
                    owner_name=_actor_name(request),
                )
                order = create_order_from_packages(
                    payload,
                    [(package, 1)],
                    source=Order.SOURCE_INTERNAL,
                    owner_user_id=_actor(request),
                    owner_name=_actor_name(request),
                    allow_all_signing_infos=scope["can_manage_cable_mall"],
                )
                delete_snapshot_package_unless_saved(package, payload)
                ordered_product_ids = [positive_int(item.get("product_id"), 0) for item in payload.get("products") or []]
                ProductCartItem.objects.filter(
                    owner_user_id=_actor(request),
                    external_account__isnull=True,
                    product_id__in=ordered_product_ids,
                ).delete()
            else:
                selected_packages = selected_packages_from_payload(
                    payload,
                    CablePackage.objects.filter(external_account__isnull=True),
                    require_project_source=True,
                )
                if selected_packages:
                    order = create_order_from_packages(
                        payload,
                        selected_packages,
                        source=Order.SOURCE_INTERNAL,
                        owner_user_id=_actor(request),
                        owner_name=_actor_name(request),
                        allow_all_signing_infos=scope["can_manage_cable_mall"],
                    )
                else:
                    order = build_order_from_cart(
                        payload,
                        source=Order.SOURCE_INTERNAL,
                        owner_user_id=_actor(request),
                        owner_name=_actor_name(request),
                        allow_all_signing_infos=scope["can_manage_cable_mall"],
                    )
    except ValueError as exc:
        return bad_request(str(exc))
    order = Order.objects.prefetch_related("packages", "packages__items").get(pk=order.pk)
    sync_unlocked_order_snapshot(order)
    return json_response({"ok": True, "item": order_dict(order)}, status=201)


def order_detail(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        scope = request_cable_mall_scope(request)
        try:
            with transaction.atomic():
                package = create_snapshot_package_from_products(
                    payload,
                    active_cable_products(),
                    name=f"{order.order_no} 订单编辑",
                    created_by=_actor_name(request) or _actor(request),
                    owner_name=_actor_name(request),
                )
                updated = replace_order_from_packages(
                    order,
                    payload,
                    [(package, 1)],
                    owner_user_id=_actor(request),
                    external_account=None,
                    allow_all_signing_infos=scope["can_manage_cable_mall"],
                )
                package.delete()
        except ValueError as exc:
            return bad_request(str(exc))
        updated = Order.objects.prefetch_related("packages", "packages__items").get(pk=updated.pk)
        return json_response({"ok": True, "item": order_dict(updated)})
    if request.method != "GET":
        return bad_request("方法不允许", status=405)
    sync_unlocked_order_snapshot(order)
    return json_response({"ok": True, "item": order_dict(order)})


def order_copy_preview(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method != "GET":
        return bad_request("方法不允许", status=405)
    scope = request_cable_mall_scope(request)
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    sync_unlocked_order_snapshot(order)
    shipping_qs = ShippingAddress.objects.all()
    signing_qs = SigningInfo.objects.all()
    if not scope["can_manage_cable_mall"]:
        actor = _actor(request)
        shipping_qs = shipping_qs.filter(owner_user_id=actor, external_account__isnull=True)
        signing_qs = signing_qs.filter(owner_user_id=actor, external_account__isnull=True)
    return json_response({
        "ok": True,
        "item": order_copy_payload(order, shipping_address_qs=shipping_qs, signing_info_qs=signing_qs),
    })


def order_export_excel(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    sync_unlocked_order_snapshot(order)
    return export_order_excel(order)


def order_export_pdf(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    if not order_status_allows_pdf(order):
        return bad_request("锁单后才能下载 PDF")
    return export_order_pdf(order)


@csrf_exempt
def order_lock(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    return handle_order_lock(request, order)


@csrf_exempt
def order_delete(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    return handle_order_delete(request, order)


@csrf_exempt
def order_restore(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    return handle_order_restore(request, order)


@csrf_exempt
def order_contract(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    return handle_order_contract(request, order)


@csrf_exempt
def order_ship(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    return handle_order_ship(request, order)


@csrf_exempt
def order_invoice(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    return handle_order_invoice(request, order)


@csrf_exempt
def order_payment(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    return handle_order_payment(request, order)


@csrf_exempt
def order_receive(request, order_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    order = get_object_or_404(internal_orders_queryset(request), pk=order_id)
    return handle_order_receive(request, order)


def external_public_products(request):
    if request.method != "GET":
        return bad_request("方法不允许", status=405)
    source_error = ""
    if product_catalog_sync_due():
        try:
            sync_product_catalog()
        except CableSourceError as exc:
            source_error = str(exc)
    qs = active_cable_products()
    q = request.GET.get("q", "").strip()
    category_a = request.GET.get("category_a", "").strip()
    category_b = request.GET.get("category_b", "").strip()
    if q:
        qs = qs.filter(
            Q(label__icontains=q)
            | Q(abbr__icontains=q)
            | Q(product_model__icontains=q)
            | Q(category_a__icontains=q)
            | Q(category_b__icontains=q)
            | Q(plan_para__icontains=q)
        )
    if category_a:
        qs = qs.filter(category_a=category_a)
    if category_b:
        qs = qs.filter(category_b=category_b)
    total = qs.count()
    page = positive_int(request.GET.get("page"), 1)
    page_size = min(positive_int(request.GET.get("page_size"), 60), 120)
    start = (page - 1) * page_size
    qs = qs.order_by("label", "abbr", "product_model", "product_archive_id")
    active_products = active_cable_products()
    categories_a = list(active_products.order_by("category_a").values_list("category_a", flat=True).distinct())
    category_b_source = active_products.filter(category_a=category_a) if category_a else active_products
    categories_b = list(category_b_source.order_by("category_a", "category_b").values_list("category_b", flat=True).distinct())
    return json_response({
        "ok": True,
        "source_error": source_error,
        "total": total,
        "page": page,
        "page_size": page_size,
        "categories_a": categories_a,
        "categories_b": categories_b,
        "items": [cable_product_dict(item) for item in qs[start:start + page_size]],
    })


@csrf_exempt
def external_login(request):
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    username = payload.get("username", "").strip()
    password = payload.get("password", "")
    account = CableMallExternalAccount.objects.filter(username=username).first()
    if not account or not verify_external_password(password, account.password_hash):
        return bad_request("账号或密码错误", status=401)
    if account.status != CableMallExternalAccount.STATUS_ACTIVE:
        return bad_request("账号已停用，请联系提供账号的业务人员", status=403)
    account.last_login_at = timezone.now()
    account.save(update_fields=["last_login_at", "updated_at"])
    token_payload = issue_external_token(account)
    return json_response({"ok": True, "account": external_account_dict(account, include_counts=False), **token_payload})


def external_current_account(request):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    return json_response({"ok": True, "account": external_account_dict(account, include_counts=False)})


@csrf_exempt
def external_account_password(request):
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    old_password = str(payload.get("old_password", "")).strip()
    new_password = str(payload.get("new_password", "")).strip()
    confirm_password = str(payload.get("confirm_password", "")).strip()
    if not old_password:
        return bad_request("请填写原密码")
    if not new_password:
        return bad_request("请填写新密码")
    if len(new_password) < 6:
        return bad_request("新密码至少 6 位")
    if new_password != confirm_password:
        return bad_request("两次输入的新密码不一致")
    if not verify_external_password(old_password, account.password_hash):
        return bad_request("原密码不正确", status=401)
    account.password_hash = hash_external_password(new_password)
    account.password_changed_at = timezone.now()
    account.save(update_fields=["password_hash", "password_changed_at", "updated_at"])
    return json_response({"ok": True, "message": "密码已重置"})


@csrf_exempt
def external_projects(request):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        archived = request.GET.get("archived") in {"1", "true", "True"}
        qs = Project.objects.filter(external_account=account, is_archived=archived).prefetch_related("packages", "packages__items")
        return json_response({"ok": True, "items": [project_dict(item) for item in qs]})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    name = payload.get("name", "").strip()
    if not name:
        return bad_request("项目名称不能为空")
    if Project.objects.filter(external_account=account, name=name, is_archived=False).exists():
        return bad_request("项目名称已存在，请换一个")
    try:
        project = Project.objects.create(
            external_account=account,
            name=name,
            created_by=account.display_name or account.username,
            note=payload.get("note", "").strip(),
        )
    except IntegrityError:
        return bad_request("项目名称已存在，请换一个")
    return json_response({"ok": True, "item": project_dict(project)}, status=201)


@csrf_exempt
def external_project_detail(request, project_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    project = get_object_or_404(Project.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=project_id)
    if request.method == "GET":
        return json_response({"ok": True, "item": project_dict(project)})
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        if "name" in payload:
            name = payload.get("name", "").strip()
            if not name:
                return bad_request("项目名称不能为空")
            if Project.objects.filter(external_account=account, name=name, is_archived=False).exclude(pk=project.pk).exists():
                return bad_request("项目名称已存在，请换一个")
            project.name = name
        if "note" in payload:
            project.note = payload.get("note", "").strip()
        if "is_archived" in payload:
            project.is_archived = bool(payload.get("is_archived"))
        try:
            project.save()
        except IntegrityError:
            return bad_request("项目名称已存在，请换一个")
        return json_response({"ok": True, "item": project_dict(project)})
    if request.method == "DELETE":
        project.is_archived = True
        project.save(update_fields=["is_archived", "updated_at"])
        return json_response({"ok": True})
    return bad_request("方法不允许", status=405)


@csrf_exempt
def external_packages(request):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        archived = request.GET.get("archived") in {"1", "true", "True"}
        project_id = request.GET.get("project_id")
        qs = CablePackage.objects.filter(external_account=account, is_archived=archived).prefetch_related("items")
        if project_id:
            qs = qs.filter(project_id=project_id, project__external_account=account)
        return json_response({"ok": True, "items": [package_dict(item) for item in qs]})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    name = payload.get("name", "").strip()
    if not name:
        return bad_request("线材清单名称不能为空")
    project = None
    project_id = payload.get("project_id")
    if project_id:
      project = get_object_or_404(Project, pk=project_id, external_account=account, is_archived=False)
    package = CablePackage.objects.create(
        project=project,
        external_account=account,
        name=name,
        created_by=account.display_name or account.username,
        owner_name=account.display_name or account.username,
        classroom_name=payload.get("classroom_name", "").strip(),
        classroom_scope=payload.get("classroom_scope", "").strip(),
        note=payload.get("note", "").strip(),
        quantity=positive_int(payload.get("quantity"), 1),
    )
    return json_response({"ok": True, "item": package_dict(package)}, status=201)


@csrf_exempt
def external_package_detail(request, package_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    package = get_object_or_404(CablePackage.objects.filter(external_account=account).prefetch_related("items"), pk=package_id)
    if request.method == "GET":
        return json_response({"ok": True, "item": package_dict(package)})
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        if "name" in payload:
            package.name = payload.get("name", "").strip() or package.name
        if "project_id" in payload:
            project_id = payload.get("project_id")
            package.project = get_object_or_404(Project, pk=project_id, external_account=account, is_archived=False) if project_id else None
        if "classroom_name" in payload:
            package.classroom_name = payload.get("classroom_name", "").strip()
        if "classroom_scope" in payload:
            package.classroom_scope = payload.get("classroom_scope", "").strip()
        if "owner_name" in payload:
            package.owner_name = payload.get("owner_name", "").strip()
        if "note" in payload:
            package.note = payload.get("note", "").strip()
        if "quantity" in payload:
            package.quantity = positive_int(payload.get("quantity"), package.quantity)
        if "is_archived" in payload:
            package.is_archived = bool(payload.get("is_archived"))
        package.save()
        return json_response({"ok": True, "item": package_dict(package)})
    if request.method == "DELETE":
        package.is_archived = True
        package.save(update_fields=["is_archived", "updated_at"])
        return json_response({"ok": True})
    return bad_request("方法不允许", status=405)


@csrf_exempt
def external_package_copy(request, package_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    source_package = get_object_or_404(CablePackage.objects.filter(external_account=account).prefetch_related("items"), pk=package_id, is_archived=False)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    name = payload.get("name", "").strip() or f"{source_package.name} 复制"
    with transaction.atomic():
        package = CablePackage.objects.create(
            external_account=account,
            name=name,
            created_by=account.display_name or account.username,
            owner_name=source_package.owner_name,
            note=payload.get("note", "").strip() if "note" in payload else source_package.note,
            quantity=source_package.quantity,
        )
        CablePackageItem.objects.bulk_create([
            CablePackageItem(
                package=package,
                product=item.product,
                product_archive_id=item.product_archive_id,
                product_label=item.product_label,
                product_brand=item.product_brand,
                product_model=item.product_model,
                product_abbr=item.product_abbr,
                category_a=item.category_a,
                category_b=item.category_b,
                spec_text=item.spec_text,
                length_m=item.length_m,
                source_unit=item.source_unit,
                unit_price=item.unit_price,
                quantity=item.quantity,
                note=item.note,
            )
            for item in source_package.items.all()
        ])
    return json_response({"ok": True, "item": package_dict(package)}, status=201)


@csrf_exempt
def external_package_items(request, package_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    package = get_object_or_404(CablePackage, pk=package_id, external_account=account, is_archived=False)
    if request.method == "DELETE":
        CablePackageItem.objects.filter(package=package).delete()
        return json_response({"ok": True, "item": package_dict(package)})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    product_id = payload.get("product_id")
    product_archive_id = payload.get("product_archive_id")
    product_qs = active_cable_products()
    product = (
        product_qs.filter(id=product_id).first()
        if product_id
        else product_qs.filter(product_archive_id=product_archive_id).first()
    )
    if not product:
        return bad_request("未找到可售线材产品", status=404)
    item = snapshot_item_from_product(
        package,
        product,
        quantity=positive_int(payload.get("quantity"), 1),
        note=payload.get("note", "").strip(),
        length_m=to_decimal(payload.get("length_m"), product.length_m),
    )
    return json_response({"ok": True, "item": package_dict(item.package)}, status=201)


@csrf_exempt
def external_package_item_detail(request, item_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    item = get_object_or_404(CablePackageItem.objects.select_related("package"), pk=item_id, package__external_account=account)
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        if "quantity" in payload:
            item.quantity = positive_int(payload.get("quantity"), item.quantity)
        if "length_m" in payload:
            item.length_m = to_decimal(payload.get("length_m"), item.length_m)
        if "note" in payload:
            item.note = payload.get("note", "").strip()
        item.save()
        return json_response({"ok": True, "item": package_dict(item.package)})
    if request.method == "DELETE":
        package = item.package
        item.delete()
        return json_response({"ok": True, "item": package_dict(package)})
    return bad_request("方法不允许", status=405)


@csrf_exempt
def external_custom_requests(request):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        qs = CustomCableRequest.objects.filter(contact_phone=account.username).select_related("bound_product")[:100]
        return json_response({"ok": True, "items": [custom_request_dict(item) for item in qs]})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    required = ["head_a_type", "head_b_type"]
    if any(not payload.get(field, "").strip() for field in required):
        return bad_request("请填写线材两头类型")
    try:
        category_a, category_b = parse_custom_category_payload(payload)
    except ValueError as exc:
        return bad_request(str(exc))
    length_m = to_decimal(payload.get("length_m"), None)
    if length_m is None:
        return bad_request("请填写定制线长度")
    item = CustomCableRequest.objects.create(
        contact_name=account.display_name or account.username,
        contact_phone=account.username,
        head_a_type=payload.get("head_a_type", "").strip(),
        head_a_gender=payload.get("head_a_gender", "").strip(),
        head_b_type=payload.get("head_b_type", "").strip(),
        head_b_gender=payload.get("head_b_gender", "").strip(),
        length_m=length_m,
        quantity=positive_int(payload.get("quantity"), 1),
        category_a=category_a,
        category_b=category_b,
        scenario=payload.get("scenario", "").strip(),
        note=payload.get("note", "").strip(),
    )
    return json_response({"ok": True, "item": custom_request_dict(item)}, status=201)


@csrf_exempt
def external_custom_request_detail(request, request_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    item = get_object_or_404(CustomCableRequest.objects.select_related("bound_product"), pk=request_id, contact_phone=account.username)
    if request.method == "GET":
        return json_response({"ok": True, "item": custom_request_dict(item)})
    if request.method not in {"PUT", "PATCH"}:
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    next_status = payload.get("status")
    if next_status == "已取消":
        if item.status != "待处理":
            return bad_request("只有待处理需求可以取消")
        item.status = "已取消"
        item.handle_result = payload.get("handle_result", "").strip() or "外部用户取消"
        item.save(update_fields=["status", "handle_result", "updated_at"])
        return json_response({"ok": True, "item": custom_request_dict(item)})
    if next_status == "待处理":
        if item.status != "已取消":
            return bad_request("只有已取消需求可以重启")
        if "内部取消" in (item.handle_result or ""):
            return bad_request("内部取消的定制需求不能重新发起", status=403)
        for field in ["head_a_type", "head_a_gender", "head_b_type", "head_b_gender", "category_a", "category_b", "scenario", "note"]:
            if field in payload:
                setattr(item, field, payload.get(field, "").strip())
        if "length_m" in payload:
            item.length_m = to_decimal(payload.get("length_m"), item.length_m)
        if "quantity" in payload:
            item.quantity = positive_int(payload.get("quantity"), item.quantity)
        item.status = "待处理"
        item.handle_result = payload.get("handle_result", "").strip() or "重新发起"
        item.bound_product = None
        item.save()
        return json_response({"ok": True, "item": custom_request_dict(item)})
    return bad_request("外部账号只能取消或重启自己的定制需求", status=403)


@csrf_exempt
def external_shipping_addresses(request):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        qs = ShippingAddress.objects.filter(external_account=account)
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(detail_address__icontains=q)
                | Q(receiver_name__icontains=q)
                | Q(receiver_phone__icontains=q)
            )
        qs = qs.order_by("-updated_at")
        return json_response({"ok": True, "items": [shipping_address_dict(item) for item in qs[:100]]})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    detail_address = payload.get("detail_address", "").strip()
    receiver_name = payload.get("receiver_name", "").strip()
    receiver_phone = payload.get("receiver_phone", "").strip()
    if not detail_address:
        return bad_request("请填写详细地址与门牌号")
    if not receiver_name:
        return bad_request("请填写收货人名字")
    if not receiver_phone:
        return bad_request("请填写手机号")
    item = ShippingAddress.objects.create(
        detail_address=detail_address,
        receiver_name=receiver_name,
        receiver_phone=receiver_phone,
        created_by=account.username,
        owner_user_id=account.owner_user_id,
        external_account=account,
        is_default=False,
    )
    return json_response({"ok": True, "item": shipping_address_dict(item)}, status=201)


@csrf_exempt
def external_shipping_address_detail(request, address_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    item = get_object_or_404(ShippingAddress, pk=address_id, external_account=account)
    if request.method == "GET":
        return json_response({"ok": True, "item": shipping_address_dict(item)})
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        if "detail_address" in payload:
            detail_address = payload.get("detail_address", "").strip()
            if not detail_address:
                return bad_request("请填写详细地址与门牌号")
            item.detail_address = detail_address
        if "receiver_name" in payload:
            receiver_name = payload.get("receiver_name", "").strip()
            if not receiver_name:
                return bad_request("请填写收货人名字")
            item.receiver_name = receiver_name
        if "receiver_phone" in payload:
            receiver_phone = payload.get("receiver_phone", "").strip()
            if not receiver_phone:
                return bad_request("请填写手机号")
            item.receiver_phone = receiver_phone
        item.is_default = False
        item.save()
        return json_response({"ok": True, "item": shipping_address_dict(item)})
    if request.method == "DELETE":
        item.delete()
        return json_response({"ok": True})
    return bad_request("方法不允许", status=405)


@csrf_exempt
def external_signing_infos(request):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        qs = SigningInfo.objects.filter(external_account=account)
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(company_name__icontains=q)
                | Q(opening_bank__icontains=q)
                | Q(tax_number__icontains=q)
                | Q(bank_account__icontains=q)
            )
        qs = qs.order_by("-updated_at")
        return json_response({"ok": True, "items": [signing_info_dict(item) for item in qs[:100]]})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    try:
        data = parse_signing_info_payload(payload)
    except ValueError as exc:
        return bad_request(str(exc))
    item = SigningInfo.objects.create(
        **data,
        created_by=account.username,
        owner_user_id=account.owner_user_id,
        external_account=account,
    )
    return json_response({"ok": True, "item": signing_info_dict(item)}, status=201)


@csrf_exempt
def external_signing_info_detail(request, info_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    item = get_object_or_404(SigningInfo, pk=info_id, external_account=account)
    if request.method == "GET":
        return json_response({"ok": True, "item": signing_info_dict(item)})
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        try:
            data = parse_signing_info_payload(payload)
        except ValueError as exc:
            return bad_request(str(exc))
        for field, value in data.items():
            setattr(item, field, value)
        item.save()
        return json_response({"ok": True, "item": signing_info_dict(item)})
    if request.method == "DELETE":
        item.delete()
        return json_response({"ok": True})
    return bad_request("方法不允许", status=405)


def external_orders(request):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    if request.method != "GET":
        return bad_request("方法不允许", status=405)
    qs = Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items")[:100]
    order_rows = sync_unlocked_orders(list(qs))
    return json_response({"ok": True, "items": [order_dict(item, include_packages=False) for item in order_rows]})


def external_order_detail(request, order_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    order = get_object_or_404(Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=order_id)
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        try:
            with transaction.atomic():
                package = create_snapshot_package_from_products(
                    payload,
                    active_cable_products(),
                    name=f"{order.order_no} 订单编辑",
                    created_by=account.username,
                    owner_name=account.display_name or account.username,
                    external_account=account,
                )
                updated = replace_order_from_packages(
                    order,
                    payload,
                    [(package, 1)],
                    owner_user_id=account.owner_user_id,
                    external_account=account,
                )
                package.delete()
        except ValueError as exc:
            return bad_request(str(exc))
        updated = Order.objects.prefetch_related("packages", "packages__items").get(pk=updated.pk)
        return json_response({"ok": True, "item": order_dict(updated)})
    if request.method != "GET":
        return bad_request("方法不允许", status=405)
    sync_unlocked_order_snapshot(order)
    return json_response({"ok": True, "item": order_dict(order)})


def external_order_copy_preview(request, order_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    if request.method != "GET":
        return bad_request("方法不允许", status=405)
    order = get_object_or_404(Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=order_id)
    sync_unlocked_order_snapshot(order)
    return json_response({
        "ok": True,
        "item": order_copy_payload(
            order,
            shipping_address_qs=ShippingAddress.objects.filter(external_account=account),
            signing_info_qs=SigningInfo.objects.filter(external_account=account),
        ),
    })


def external_order_export_pdf(request, order_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    order = get_object_or_404(Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=order_id)
    if not order_status_allows_pdf(order):
        return bad_request("锁单后才能下载 PDF")
    return export_order_pdf(order)


@csrf_exempt
def external_order_lock(request, order_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    order = get_object_or_404(Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=order_id)
    return handle_order_lock(request, order)


@csrf_exempt
def external_order_delete(request, order_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    order = get_object_or_404(Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=order_id)
    return handle_order_delete(request, order)


@csrf_exempt
def external_order_restore(request, order_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    order = get_object_or_404(Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=order_id)
    return handle_order_restore(request, order)


@csrf_exempt
def external_order_contract(request, order_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    order = get_object_or_404(Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=order_id)
    return handle_order_contract(request, order)


@csrf_exempt
def external_order_ship(request, order_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    order = get_object_or_404(Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=order_id)
    return handle_order_ship(request, order)


@csrf_exempt
def external_order_invoice(request, order_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    order = get_object_or_404(Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=order_id)
    return handle_order_invoice(request, order)


@csrf_exempt
def external_order_payment(request, order_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    order = get_object_or_404(Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=order_id)
    return handle_order_payment(request, order)


@csrf_exempt
def external_order_receive(request, order_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    order = get_object_or_404(Order.objects.filter(external_account=account).prefetch_related("packages", "packages__items"), pk=order_id)
    return handle_order_receive(request, order)


@csrf_exempt
def external_product_cart(request):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    return product_cart_collection(request, external_account=account)


@csrf_exempt
def external_product_cart_item_detail(request, item_id):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    return product_cart_item_mutation(request, item_id, external_account=account)


@csrf_exempt
def external_checkout(request):
    account, denied = require_external_account(request)
    if denied is not None:
        return denied
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    if not payload.get("customer_name", "").strip():
        return bad_request("请填写收货人")
    if not payload.get("customer_phone", "").strip():
        return bad_request("请填写手机号")
    if not payload.get("project_name", "").strip():
        return bad_request("请填写详细地址与门牌号")

    try:
        with transaction.atomic():
            created_snapshot_package = None
            if payload.get("products"):
                package = create_snapshot_package_from_products(
                    payload,
                    active_cable_products(),
                    name=f"{account.display_name or account.username} 外部商城下单",
                    created_by=account.username,
                    owner_name=account.display_name or account.username,
                    external_account=account,
                )
                created_snapshot_package = package
                selected_packages = [(package, 1)]
            else:
                selected_packages = selected_packages_from_payload(
                    payload,
                    CablePackage.objects.filter(external_account=account),
                    require_project_source=True,
                )
            order = create_order_from_packages(
                payload,
                selected_packages,
                source=Order.SOURCE_EXTERNAL,
                owner_user_id=account.owner_user_id,
                owner_name=account.owner_name,
                external_account=account,
            )
            if created_snapshot_package is not None:
                delete_snapshot_package_unless_saved(created_snapshot_package, payload)
                ordered_product_ids = [positive_int(item.get("product_id"), 0) for item in payload.get("products") or []]
                ProductCartItem.objects.filter(external_account=account, product_id__in=ordered_product_ids).delete()
    except ValueError as exc:
        return bad_request(str(exc))
    order = Order.objects.prefetch_related("packages", "packages__items").get(pk=order.pk)
    sync_unlocked_order_snapshot(order)
    return json_response({"ok": True, "item": order_dict(order)}, status=201)


@csrf_exempt
def custom_requests(request):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        status = request.GET.get("status", "").strip()
        qs = internal_custom_requests_queryset(request)
        if status:
            qs = qs.filter(status=status)
        return json_response({"ok": True, "items": [custom_request_dict(item) for item in qs[:200]]})
    if request.method != "POST":
        return bad_request("方法不允许", status=405)
    payload = parse_body(request)
    if payload is None:
        return bad_request("JSON 格式错误")
    required = ["head_a_type", "head_b_type"]
    if any(not payload.get(field, "").strip() for field in required):
        return bad_request("请填写线材两头类型")
    try:
        category_a, category_b = parse_custom_category_payload(payload)
    except ValueError as exc:
        return bad_request(str(exc))
    length_m = to_decimal(payload.get("length_m"), None)
    if length_m is None:
        return bad_request("请填写定制线长度")
    item = CustomCableRequest.objects.create(
        contact_name=payload.get("contact_name", "").strip(),
        contact_phone=payload.get("contact_phone", "").strip(),
        head_a_type=payload.get("head_a_type", "").strip(),
        head_a_gender=payload.get("head_a_gender", "").strip(),
        head_b_type=payload.get("head_b_type", "").strip(),
        head_b_gender=payload.get("head_b_gender", "").strip(),
        length_m=length_m,
        quantity=positive_int(payload.get("quantity"), 1),
        category_a=category_a,
        category_b=category_b,
        scenario=payload.get("scenario", "").strip(),
        note=payload.get("note", "").strip(),
    )
    return json_response({"ok": True, "item": custom_request_dict(item)}, status=201)


@csrf_exempt
def custom_request_detail(request, request_id):
    denied = ensure_cable_mall_access(request)
    if denied is not None:
        return denied
    item = get_object_or_404(internal_custom_requests_queryset(request), pk=request_id)
    if request.method == "GET":
        return json_response({"ok": True, "item": custom_request_dict(item)})
    if request.method in {"PUT", "PATCH"}:
        payload = parse_body(request)
        if payload is None:
            return bad_request("JSON 格式错误")
        for field in ["contact_name", "contact_phone", "head_a_type", "head_a_gender", "head_b_type", "head_b_gender", "category_a", "category_b", "scenario", "note"]:
            if field in payload:
                setattr(item, field, payload.get(field, "").strip())
        if "length_m" in payload:
            item.length_m = to_decimal(payload.get("length_m"), item.length_m)
        if "quantity" in payload:
            item.quantity = positive_int(payload.get("quantity"), item.quantity)
        requested_status = payload.get("status") if "status" in payload else None
        if "handle_result" in payload:
            item.handle_result = payload.get("handle_result", "").strip()
        if "bound_product_id" in payload:
            bound_product_id = positive_int(payload.get("bound_product_id"), 0)
            if bound_product_id:
                product = get_object_or_404(CableProduct, pk=bound_product_id, is_active=True)
                item.bound_product = product
                if not item.handle_result:
                    item.handle_result = product_bind_result(product)
            else:
                item.bound_product = None
        if requested_status in dict(CustomCableRequest.STATUS_CHOICES):
            item.status = requested_status
            if requested_status == "已取消":
                item.handle_result = "内部取消"
        item.save()
        return json_response({"ok": True, "item": custom_request_dict(item)})
    return bad_request("方法不允许", status=405)

# Create your views here.
