from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import json
from urllib.parse import urlencode, urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, connection, transaction
from django.db.models import Avg, Case, Count, DateTimeField, Exists, F, IntegerField, JSONField, Max, OuterRef, Prefetch, Q, Subquery, Value, When
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast
from django.http import FileResponse, HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import (
    AppConfigurationRevision,
    FieldFeedback,
    PrivateAttachment,
    ProjectAssignment,
    ProjectMessage,
    ProjectMessageRead,
    ProjectNode,
    Reward,
    RewardPrize,
    ServiceProject,
    ServiceProvider,
    ServiceRating,
    ServiceResource,
    ServiceTicket,
    Settlement,
    TicketMessage,
)
from .manual_renderer import ManualRenderError, is_feishu_document_url, render_feishu_manual_pdf
from .org_client import AuthOrgClientError, build_auth_department_tree, get_auth_organization_snapshot
from .permissions import (
    APP_PERMISSION_ADMIN,
    get_request_app_permission,
    get_request_app_permissions,
    list_app_permission_rules,
    replace_app_permission_rules,
)
from . import access
from .product_catalog_client import (
    MANUAL_KEYS,
    ProductCatalogError,
    fetch_product_catalog,
    fetch_product_image,
    fetch_products_by_ids,
)
from .product_search import filter_queryset_search
from .project_personnel import management_member_q
from .project_areas import normalize_presales_areas, normalize_presales_project_info, presales_project_data_equal
from .reward_prize_views import resolve_active_prize
from .serializers import (
    iso,
    serialize_assignment,
    serialize_active_project_nodes,
    serialize_feedback,
    serialize_message_conversation,
    serialize_mobile_task_node,
    serialize_project,
    project_draft_version,
    serialize_project_message,
    serialize_provider,
    serialize_resource,
    serialize_reward,
    serialize_service_rating,
    serialize_settlement,
    serialize_ticket,
)
from .services import (
    DomainValidationError,
    advance_project,
    assign_provider,
    configure_project_nodes,
    field_completion_submitted,
    create_audit_fields,
    create_feedback_record,
    create_project,
    create_service_rating,
    create_ticket_record,
    generated_code,
    record_project_event,
    reject_aftersales_completion,
    reopen_project_node,
    request_identity,
    review_feedback,
    save_project_node_draft,
    select_aftersales_node,
    start_project_node,
    submit_project_node_version,
    text,
    touch_audit,
    transition_reward,
    transition_ticket,
    validate_presales_project_info_records,
)
from .workflow_rules import aftersales_dispatch_errors
from .crm_source import (
    CRM_PRESALES_STAGES, assert_crm_project_access, crm_sync_status, protect_crm_project_fields,
    refresh_crm_project, scope_crm_queryset, sync_crm_presales,
)
from .presales_task_schedule import annotate_presales_task_deadline, pending_presales_task_schedules


APP_CONFIGURATION_PERMISSIONS = "permissions"
MAX_PAGE_SIZE = 100
PRESALES_TASK_REMINDER_DAYS = 3
CREATABLE_REWARD_TYPES = [choice for choice in Reward.TYPE_CHOICES if choice[0] != Reward.TYPE_POINTS]
SETTLEMENT_TRANSITIONS = {
    # The settlement form is already complete when the user confirms it.
    # Keep pending available for finance workflows, but allow the common
    # one-click draft -> settled path as well.
    Settlement.STATUS_DRAFT: {Settlement.STATUS_PENDING, Settlement.STATUS_SETTLED, Settlement.STATUS_CANCELLED},
    Settlement.STATUS_PENDING: {Settlement.STATUS_SETTLED, Settlement.STATUS_CANCELLED},
    Settlement.STATUS_SETTLED: set(),
    Settlement.STATUS_CANCELLED: set(),
}
MIDSALES_SETTLEMENT_NODE_KEYS = {
    "construction-work",
    "furniture-install",
    "device-install",
    "device-debug",
    "school-support",
}
MIDSALES_RELATED_PRODUCT_NODE_KEYS = {
    "construction-work",
    "furniture-install",
    "device-install",
    "device-debug",
    "school-support",
    "project-acceptance",
}
INSTALLATION_NODE_KEYS = {
    "construction-work",
    "furniture-install",
    "device-install",
    "device-debug",
    "school-support",
    "onsite-service",
    "mail-service",
    "school-inspection",
}
COMPACT_NODE_FIELDS = (
    "id",
    "nodeKey",
    "name",
    "status",
    "statusLabel",
    "description",
    "plannedStartAt",
    "plannedEndAt",
    "actualStartAt",
    "actualEndAt",
    "estimatedFee",
    "actualFee",
    "businessData",
)


def _error(message: str, *, status: int, code: str, **extra) -> JsonResponse:
    payload = {"ok": False, "error": message, "code": code}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _domain_error(exc: DomainValidationError) -> JsonResponse:
    return _error(str(exc), status=exc.status, code=exc.code)


def _body(request) -> dict | None:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _positive_int(value, default: int, *, maximum: int = 2_147_483_647) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(1, parsed))


def _page(request) -> tuple[int, int]:
    return (
        _positive_int(request.GET.get("page"), 1, maximum=100_000),
        _positive_int(request.GET.get("pageSize"), 20, maximum=MAX_PAGE_SIZE),
    )


def _paginated(queryset, request, serializer, *, crm_scoped=False, extra=None) -> JsonResponse:
    # CRM-backed records remain scoped even in settlement/resource/reward lists.
    prefixes = {ServiceProject: [""], ServiceTicket: ["project__"], FieldFeedback: ["project__"],
                Reward: ["project__"], Settlement: ["project__", "related_project__"], ServiceResource: ["project__"]}
    try:
        for prefix in ([] if crm_scoped else prefixes.get(queryset.model, [])):
            queryset = scope_crm_queryset(request, queryset, prefix)
    except DomainValidationError as exc:
        return _domain_error(exc)
    page, page_size = _page(request)
    total = queryset.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    start = (page - 1) * page_size
    return JsonResponse({
        "items": [serializer(item) for item in queryset[start:start + page_size]],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
        **(extra or {}),
    })


def _required_text(payload: dict, key: str, label: str, *, max_length: int = 255) -> str:
    value = text(payload.get(key))
    if not value:
        raise DomainValidationError(f"{label}不能为空", code="FIELD_REQUIRED")
    if len(value) > max_length:
        raise DomainValidationError(f"{label}不能超过 {max_length} 个字符", code="FIELD_TOO_LONG")
    return value


def _optional_text(payload: dict, key: str, label: str, *, max_length: int = 255) -> str:
    value = text(payload.get(key))
    if len(value) > max_length:
        raise DomainValidationError(f"{label}不能超过 {max_length} 个字符", code="FIELD_TOO_LONG")
    return value


def _choice(value, choices, label: str, *, default: str = "") -> str:
    normalized = text(value) or default
    allowed = {row[0] for row in choices}
    if normalized not in allowed:
        raise DomainValidationError(f"{label}无效", code="INVALID_CHOICE")
    return normalized


def _json_dict(value, label: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DomainValidationError(f"{label}格式错误", code="INVALID_JSON_FIELD")
    return value


def _json_list(value, label: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DomainValidationError(f"{label}格式错误", code="INVALID_JSON_FIELD")
    return value


def _date_value(value, label: str) -> date | None:
    normalized = text(value)
    if not normalized:
        return None
    parsed = parse_date(normalized)
    if parsed is None:
        raise DomainValidationError(f"{label}格式应为 YYYY-MM-DD", code="INVALID_DATE")
    return parsed


def _datetime_value(value, label: str) -> datetime | None:
    normalized = text(value)
    if not normalized:
        return None
    parsed = parse_datetime(normalized)
    if parsed is None:
        raise DomainValidationError(f"{label}格式错误", code="INVALID_DATETIME")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _decimal_value(value, label: str, *, default: Decimal | None = None) -> Decimal | None:
    if value is None or value == "":
        return default
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DomainValidationError(f"{label}必须是数字", code="INVALID_NUMBER") from exc
    if parsed < 0:
        raise DomainValidationError(f"{label}不能为负数", code="INVALID_NUMBER")
    return parsed.quantize(Decimal("0.01"))


def _http_url_value(value, label: str) -> str:
    normalized = text(value)
    if not normalized:
        return ""
    try:
        URLValidator(schemes=["http", "https"])(normalized)
    except ValidationError as exc:
        raise DomainValidationError(
            f"{label}必须是有效的 HTTP 或 HTTPS 地址",
            code="INVALID_URL",
        ) from exc
    return normalized


def _bounded_int(value, label: str, *, minimum: int = 0, maximum: int = 2_147_483_647) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(f"{label}必须是整数", code="INVALID_NUMBER") from exc
    if parsed < minimum or parsed > maximum:
        raise DomainValidationError(f"{label}超出允许范围", code="INVALID_NUMBER")
    return parsed


def _search_filter(request) -> str:
    return text(request.GET.get("search") or request.GET.get("q"))


def _org_error(exc: AuthOrgClientError) -> JsonResponse:
    return _error(str(exc), status=exc.status_code, code="AUTH_ORG_UNAVAILABLE")


def _auth_channel(request) -> str:
    claims = getattr(request, "auth_token_claims", {}) or {}
    return text(claims.get("chn")) or "dingtalk"


def _admin_status(request) -> tuple[bool, JsonResponse | None]:
    channel = _auth_channel(request)
    if channel == "wechat-mini":
        return False, None
    if channel != "dingtalk":
        return False, _error("登录渠道无效", status=403, code="AUTH_CHANNEL_FORBIDDEN")
    user_id = text(getattr(request, "auth_user_id", ""))
    if not user_id:
        return False, _error("登录已失效", status=401, code="AUTH_REQUIRED")
    try:
        access.require_management(request)
    except AuthOrgClientError as exc:
        return False, _org_error(exc)
    except DomainValidationError as exc:
        return False, _domain_error(exc)
    # The legacy name identifies an authorized management user; individual
    # business privileges are still checked separately by access policy.
    return True, None


def _ensure_app_admin(request) -> JsonResponse | None:
    # Legacy management guard. Object/role checks also run on management APIs.
    is_admin, failure = _admin_status(request)
    if failure is not None:
        return failure
    if is_admin:
        return None
    return _error("当前账号没有管理端业务权限", status=403, code="APP_ADMIN_REQUIRED")


def _ensure_settings_admin(request) -> JsonResponse | None:
    try:
        permission = get_request_app_permission(request)
    except AuthOrgClientError as exc:
        return _org_error(exc)
    if permission == APP_PERMISSION_ADMIN:
        return None
    return _error("只有系统管理员可以访问设置", status=403, code="APP_ADMIN_REQUIRED")


def _current_provider(request) -> ServiceProvider | None:
    user_id = text(getattr(request, "auth_user_id", ""))
    if not user_id:
        return None
    return ServiceProvider.objects.filter(auth_user_id=user_id).first()


def _ensure_service_manager(request):
    try:
        if access.manages_service(request):
            return None
    except AuthOrgClientError as exc:
        return _org_error(exc)
    return _error("此操作需要服务管理员或系统管理员权限", status=403, code="SERVICE_PERMISSION_REQUIRED")


def _ensure_finance_manager(request):
    try:
        if access.manages_finance(request):
            return None
    except AuthOrgClientError as exc:
        return _org_error(exc)
    return _error("当前账号没有结算中心使用权限", status=403, code="FINANCE_PERMISSION_REQUIRED")


def _provider_required(request) -> tuple[ServiceProvider | None, JsonResponse | None]:
    if _auth_channel(request) != "wechat-mini":
        return None, _error("该接口仅供微信小程序服务人员使用", status=403, code="WECHAT_PROVIDER_REQUIRED")
    provider = _current_provider(request)
    if provider is None:
        return None, _error("当前账号未建立服务人员档案", status=403, code="SERVICE_PROVIDER_REQUIRED")
    if provider.certification_status != ServiceProvider.CERT_CERTIFIED:
        return None, _error("当前服务人员尚未通过认证", status=403, code="SERVICE_PROVIDER_NOT_CERTIFIED")
    return provider, None


def _visible_projects(request, *, include_deleted: bool = False, service_type: str = ""):
    queryset = ServiceProject.objects.all()
    if service_type:
        queryset = queryset.filter(service_type=service_type)
    if not include_deleted:
        queryset = queryset.filter(deleted_at__isnull=True)
    is_admin, failure = _admin_status(request)
    if failure is not None:
        return None, None, failure
    if is_admin:
        queryset = access.scope_projects(request, queryset)
        try:
            queryset = scope_crm_queryset(request, queryset)
        except DomainValidationError as exc:
            return None, None, _domain_error(exc)
        return queryset, None, None
    provider, failure = _provider_required(request)
    if failure is not None:
        return None, None, failure
    return queryset.filter(
        deleted_at__isnull=True,
        assignments__provider=provider,
        assignments__status__in=[
            ProjectAssignment.STATUS_ASSIGNED,
            ProjectAssignment.STATUS_ACCEPTED,
            ProjectAssignment.STATUS_IN_PROGRESS,
            ProjectAssignment.STATUS_COMPLETED,
        ],
    ).distinct(), provider, None


def _project_access(request, project_id: int, *, include_deleted: bool = False):
    is_admin, failure = _admin_status(request)
    if failure is not None:
        return None, None, False, failure
    if is_admin:
        project = access.scope_projects(request, ServiceProject.objects.filter(pk=project_id)).first()
        if project is None or (project.deleted_at and not include_deleted):
            return None, None, False, _error("项目不存在或无权访问", status=404, code="PROJECT_NOT_FOUND")
        try:
            assert_crm_project_access(request, project)
        except DomainValidationError as exc:
            return None, None, False, _domain_error(exc)
        return project, None, True, None
    queryset, provider, failure = _visible_projects(request, include_deleted=include_deleted)
    if failure is not None:
        return None, provider, False, failure
    try:
        project = queryset.get(pk=project_id)
    except ServiceProject.DoesNotExist:
        return None, provider, False, _error("项目不存在或无权访问", status=404, code="PROJECT_NOT_FOUND")
    is_admin = provider is None
    return project, provider, is_admin, None


def _provider_can_operate_node(provider: ServiceProvider, project: ServiceProject, node_key: str) -> bool:
    return ProjectAssignment.objects.filter(
        project=project,
        node__node_key=node_key,
        provider=provider,
        status__in=[
            ProjectAssignment.STATUS_ASSIGNED,
            ProjectAssignment.STATUS_ACCEPTED,
            ProjectAssignment.STATUS_IN_PROGRESS,
            ProjectAssignment.STATUS_COMPLETED,
        ],
    ).exists()


MESSAGE_READ_ASSIGNMENT_STATUSES = [
    ProjectAssignment.STATUS_ASSIGNED,
    ProjectAssignment.STATUS_ACCEPTED,
    ProjectAssignment.STATUS_IN_PROGRESS,
    ProjectAssignment.STATUS_COMPLETED,
]
MESSAGE_WRITE_ASSIGNMENT_STATUSES = [
    ProjectAssignment.STATUS_ASSIGNED,
    ProjectAssignment.STATUS_ACCEPTED,
    ProjectAssignment.STATUS_IN_PROGRESS,
]


def _project_message_access(request, project_id: int, *, node_key: str = "", for_write: bool = False):
    is_admin, failure = _admin_status(request)
    if failure is not None:
        return None, None, None, failure
    project = ServiceProject.objects.filter(pk=project_id, deleted_at__isnull=True).first()
    if project is None:
        return None, None, None, _error(
            "项目不存在或无权访问",
            status=404,
            code="PROJECT_NOT_FOUND",
        )
    try:
        assert_crm_project_access(request, project, write=for_write)
    except DomainValidationError as exc:
        return None, None, None, _domain_error(exc)
    node = None
    if node_key:
        node = ProjectNode.objects.filter(project=project, node_key=node_key).first()
        if node is None:
            return None, None, None, _error(
                "项目节点不存在或无权访问",
                status=404,
                code="PROJECT_NODE_NOT_FOUND",
            )
        if for_write and not node.enabled:
            return None, None, None, _error(
                "该节点会话已只读",
                status=409,
                code="PROJECT_MESSAGE_CONVERSATION_READ_ONLY",
            )
    user_id = text(getattr(request, "auth_user_id", ""))
    if is_admin:
        if not access.can_read_project(request, project):
            return None, None, None, _error("项目不存在或无权访问", status=404, code="PROJECT_NOT_FOUND")
        if for_write and not access.can_manage_project(request, project) and not project.nodes.filter(
            management_member_q(user_id), enabled=True,
        ).exists():
            return None, None, None, _error("当前账号仅可查看项目资料", status=403, code="BUSINESS_PERMISSION_REQUIRED")
        return project, node, None, None

    provider = _current_provider(request)
    if provider is None or provider.certification_status != ServiceProvider.CERT_CERTIFIED:
        return None, None, None, _error(
            "项目不存在或无权访问",
            status=404,
            code="PROJECT_NOT_FOUND",
        )
    statuses = MESSAGE_WRITE_ASSIGNMENT_STATUSES if for_write else MESSAGE_READ_ASSIGNMENT_STATUSES
    assignments = ProjectAssignment.objects.filter(
        project=project,
        provider=provider,
        status__in=statuses,
    )
    if node is not None:
        assignments = assignments.filter(node=node)
    if not assignments.exists():
        return None, None, None, _error(
            "项目会话不存在或无权访问",
            status=404,
            code="PROJECT_MESSAGE_CONVERSATION_NOT_FOUND",
        )
    return project, node, provider, None


def _visible_project_messages(request):
    rows = ProjectMessage.objects.filter(
        project__deleted_at__isnull=True,
    ).select_related("project", "node")
    is_admin, failure = _admin_status(request)
    if failure is not None:
        return None, failure
    if is_admin:
        try:
            rows = rows.filter(project__in=access.scope_projects(request))
            return scope_crm_queryset(request, rows, "project__"), None
        except DomainValidationError as exc:
            return None, _domain_error(exc)

    user_id = text(getattr(request, "auth_user_id", ""))
    owner_filter = Q(project__owner_user_id=user_id) & ~Q(project__owner_user_id="")
    provider = _current_provider(request)
    if provider is None or provider.certification_status != ServiceProvider.CERT_CERTIFIED:
        return rows.filter(owner_filter), None

    project_assignment = ProjectAssignment.objects.filter(
        project_id=OuterRef("project_id"),
        provider=provider,
        status__in=MESSAGE_READ_ASSIGNMENT_STATUSES,
    )
    node_assignment = project_assignment.filter(node_id=OuterRef("node_id"))
    rows = rows.annotate(
        _message_project_assigned=Exists(project_assignment),
        _message_node_assigned=Exists(node_assignment),
    ).filter(
        owner_filter
        | Q(node_id__isnull=True, _message_project_assigned=True)
        | Q(node_id__isnull=False, _message_node_assigned=True)
    )
    return rows, None


def _project_message_rows_with_read_state(rows, user_id: str):
    read_receipt = ProjectMessageRead.objects.filter(
        message_id=OuterRef("pk"),
        user_id=user_id,
    )
    return rows.annotate(_read_by_user=Exists(read_receipt))


def _conversation_data(rows, request, *, page_size_override: int | None = None) -> dict:
    user_id = text(getattr(request, "auth_user_id", ""))
    rows = _project_message_rows_with_read_state(rows, user_id)
    unread_count = rows.filter(_read_by_user=False).exclude(author_user_id=user_id).count()
    grouped = rows.values("project_id", "node_id").annotate(
        last_message_id=Max("id"),
        unread_count=Count(
            "id",
            filter=~Q(author_user_id=user_id) & Q(_read_by_user=False),
        ),
    ).order_by("-last_message_id")
    total = grouped.count()
    page, page_size = _page(request)
    if page_size_override is not None:
        page = 1
        page_size = min(MAX_PAGE_SIZE, page_size_override)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    start = (page - 1) * page_size
    groups = list(grouped[start:start + page_size])
    last_ids = [row["last_message_id"] for row in groups]
    last_messages = {
        item.id: item
        for item in _project_message_rows_with_read_state(
            ProjectMessage.objects.filter(pk__in=last_ids).select_related("project", "node"),
            user_id,
        )
    }
    items = [
        serialize_message_conversation(
            last_messages[row["last_message_id"]],
            unread_count=row["unread_count"],
            user_id=user_id,
        )
        for row in groups
        if row["last_message_id"] in last_messages
    ]
    return {
        "items": items,
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
        "unreadCount": unread_count,
    }


def health(_request):
    return JsonResponse({"ok": True})


def health_live(_request):
    return JsonResponse({"ok": True})


def health_ready(_request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"ok": False, "code": "DATABASE_UNAVAILABLE", "database": "unavailable"}, status=503)
    return JsonResponse({"ok": True, "database": "ok"})


def session(request):
    try:
        permissions = get_request_app_permissions(request)
        app_permission = get_request_app_permission(request)
        can_manage_app = access.can_use_management(request)
    except AuthOrgClientError:
        return _error("无法读取应用权限，请稍后重试", status=503, code="AUTH_ORG_UNAVAILABLE")
    provider = _current_provider(request)
    return JsonResponse({
        "ok": True,
        "userId": request.auth_user_id,
        "name": request.auth_user_name,
        "actorUserId": request.auth_actor_user_id,
        "actorName": request.auth_actor_name,
        "isProxying": request.auth_is_proxy,
        "canUseSystemAdmin": request.auth_can_use_system_admin,
        "appPermission": app_permission,
        "appPermissions": sorted(permissions),
        "canManageApp": can_manage_app,
        "canManageSettings": app_permission == APP_PERMISSION_ADMIN,
        "canManageBusiness": access.manages_business(request),
        "canManageService": access.manages_service(request),
        "canManageSettlements": access.manages_finance(request),
        "canCreateProjects": can_manage_app,
        "serviceProvider": serialize_provider(provider) if provider else None,
    })


def _serialize_project(request, project, **kwargs):
    item = serialize_project(project, **kwargs)
    item["permissions"] = access.project_abilities(request, project)
    if "nodes" in item:
        nodes = {node.node_key: node for node in project.nodes.all()}
        for row in item["nodes"]:
            node = nodes.get(row.get("nodeKey"))
            if node is not None:
                row["permissions"] = access.node_abilities(request, node)
    return item


def _serialize_ticket(request, ticket, **kwargs):
    item = serialize_ticket(ticket, **kwargs)
    manage = access.can_manage_project(request, ticket.project)
    item["permissions"] = {
        "canManage": manage,
        "canProcess": manage or (access.management_user(request) and ticket.owner_user_id == request.auth_user_id),
        "canMessage": manage or request.auth_user_id in {ticket.owner_user_id, ticket.reporter_user_id},
    }
    return item


def _serialize_compact_node(node: ProjectNode, assignment_id: int | None = None) -> dict:
    data = serialize_mobile_task_node(node, assignment_id)
    return {key: data[key] for key in COMPACT_NODE_FIELDS}


def _serialize_mobile_node(node: ProjectNode, assignment_id: int) -> dict:
    data = _serialize_compact_node(node, assignment_id)
    settlements = [
        item for item in node.settlements.all()
        if item.status != Settlement.STATUS_CANCELLED
    ]
    settled = next((item for item in settlements if item.status == Settlement.STATUS_SETTLED), None)
    processing = next((item for item in settlements if item.status in {Settlement.STATUS_DRAFT, Settlement.STATUS_PENDING}), None)
    business_data = data["businessData"]
    if settled:
        status, label, settlement_id = "settled", "已结算", settled.id
    elif processing:
        status, label, settlement_id = "processing", "结算处理中", processing.id
    elif business_data.get("settlementEligible") is False:
        status, label, settlement_id = "ineligible", "不符合结算条件", None
    elif node.status == ProjectNode.STATUS_COMPLETED and data["actualFee"] and node.actual_fee > 0:
        status, label, settlement_id = "eligible_pending", "符合条件待结算", None
    elif business_data.get("settlementEligible") is True:
        status, label, settlement_id = "eligible", "现场申报符合条件", None
    else:
        status, label, settlement_id = "unconfirmed", "待确认结算条件", None
    data.update({
        "settlementStatus": status,
        "settlementStatusLabel": label,
        "settlementId": settlement_id,
    })
    return data


def _dashboard_due_text(planned_end_at: datetime | None) -> str:
    if planned_end_at is None:
        return "未设置截止时间"
    seconds = (planned_end_at - timezone.now()).total_seconds()
    if seconds < 0:
        overdue_days = max(1, (int(-seconds) + 86_399) // 86_400)
        return f"已超时 {overdue_days} 天"
    return f"{timezone.localtime(planned_end_at):%Y-%m-%d %H:%M} 到期"


def _presales_task_end_at(deadline: date | None):
    return timezone.make_aware(datetime.combine(deadline, time(23, 59, 59))) if deadline else None


def _presales_task_due_text(deadline: date | None, today: date) -> str:
    if deadline is None:
        return "未设置预计完成时间"
    days = (deadline - today).days
    if days < 0:
        return f"已超时 {-days} 天"
    if days == 0:
        return "今天到期"
    if days <= PRESALES_TASK_REMINDER_DAYS:
        return f"还有 {days} 天到期"
    return f"{deadline:%Y-%m-%d} 到期"


@require_GET
def dashboard(request):
    is_admin, failure = _admin_status(request)
    if failure is not None:
        return failure
    sync_status = {"crmSyncing": False, "crmSyncedAt": "", "crmSyncError": "", "crmScopeReady": True}
    if is_admin and ServiceProject.objects.filter(deleted_at__isnull=True).exclude(source_crm_id="").exists():
        try:
            sync_crm_presales(request, background=True, force=request.GET.get("crmRefresh") == "1")
            sync_status = crm_sync_status(request)
        except DomainValidationError as exc:
            # Fail closed for CRM projects, but keep independent local work
            # available. Never let a missing/denied scope trigger a full fetch.
            request._after_sales_crm_ids = []
            sync_status.update(crmScopeReady=False, crmSyncError=str(exc))
    projects, provider, failure = _visible_projects(request)
    if failure is not None:
        return failure
    user_id = text(getattr(request, "auth_user_id", ""))
    # The management assignment is a DingTalk user ID, not a field-provider
    # assignment. Match the effective identity, including proxy sessions.
    presales_executor = Q(project__service_type=ServiceProject.TYPE_PRESALES) & management_member_q(user_id)
    current_provider = provider
    active_assignment_statuses = [
        ProjectAssignment.STATUS_ASSIGNED,
        ProjectAssignment.STATUS_ACCEPTED,
        ProjectAssignment.STATUS_IN_PROGRESS,
        ProjectAssignment.STATUS_COMPLETED,
    ]
    global_business = provider is None and access.manages_business(request)
    if provider is None and not global_business:
        personal_tickets = ServiceTicket.objects.filter(project_id=OuterRef("pk")).filter(
            Q(owner_user_id=user_id) | Q(reporter_user_id=user_id)
        )
        personal_assignments = ProjectAssignment.objects.filter(
            project_id=OuterRef("pk"), provider__auth_user_id=user_id,
            status__in=active_assignment_statuses,
        )
        personal_presales_nodes = ProjectNode.objects.filter(
            presales_executor, project_id=OuterRef("pk"), enabled=True,
        )
        # EXISTS avoids multiplying project rows across tickets/assignments.
        projects = projects.alias(
            _personal_ticket=Exists(personal_tickets), _personal_assignment=Exists(personal_assignments),
            _personal_presales_node=Exists(personal_presales_nodes),
        )
        projects = projects.filter(
            Q(owner_user_id=user_id)
            | Q(_personal_ticket=True) | Q(_personal_assignment=True)
            | Q(_personal_presales_node=True)
        )
    tickets, _ticket_provider, failure = _visible_tickets(request, project_scope=(projects, provider))
    if failure is not None:
        return failure
    feedback = FieldFeedback.objects.filter(project__in=projects)
    if provider is not None:
        feedback = feedback.filter(provider=provider)
    rewards = Reward.objects.filter(
        Q(project__in=projects)
        | Q(provider__auth_user_id=user_id)
    ).distinct()
    can_manage_service = access.manages_service(request) if access.management_user(request) else False
    if provider is None and not can_manage_service:
        rewards = rewards.none()
    open_tickets = tickets.exclude(status=ServiceTicket.STATUS_COMPLETED)
    active_nodes = ProjectNode.objects.filter(
        project__in=projects,
        project__status__in=[ServiceProject.STATUS_IN_PROGRESS, ServiceProject.STATUS_BLOCKED],
        enabled=True,
        status=ProjectNode.STATUS_ACTIVE,
    ).select_related("project")
    if provider is not None:
        personal_nodes = ProjectAssignment.objects.filter(
            node_id=OuterRef("pk"), provider=provider, status__in=[
                ProjectAssignment.STATUS_ASSIGNED,
                ProjectAssignment.STATUS_ACCEPTED,
                ProjectAssignment.STATUS_IN_PROGRESS,
            ],
        )
        active_nodes = active_nodes.alias(_personal_node=Exists(personal_nodes)).filter(_personal_node=True)
        risk_nodes = active_nodes
    else:
        personal_nodes = ProjectAssignment.objects.filter(
            node_id=OuterRef("pk"), provider__auth_user_id=user_id, status__in=[
                ProjectAssignment.STATUS_ASSIGNED,
                ProjectAssignment.STATUS_ACCEPTED,
                ProjectAssignment.STATUS_IN_PROGRESS,
            ],
        )
        active_nodes = active_nodes.alias(_personal_node=Exists(personal_nodes))
        # Managers monitor all visible business risks; owners monitor their own
        # projects even without an assignee. Neither grants personal to-do work.
        risk_nodes = active_nodes if global_business else active_nodes.filter(
            Q(project__owner_user_id=user_id)
            | Q(_personal_node=True) | presales_executor
        )
        active_nodes = active_nodes.filter(Q(_personal_node=True) | presales_executor)
    limit = 8
    node_fields = (
        "id", "node_key", "name", "planned_end_at", "project_id", "sequence",
        "project__id", "project__name", "project__service_type",
    )
    node_order = (F("planned_end_at").asc(nulls_last=True), "project_id", "sequence", "id")
    active_nodes = active_nodes.only(*node_fields).order_by(*node_order)
    risk_nodes = risk_nodes.only(*node_fields).order_by(*node_order)
    other_nodes = active_nodes.exclude(project__service_type=ServiceProject.TYPE_PRESALES)
    presales_tasks = pending_presales_task_schedules().filter(
        node_id__in=active_nodes.filter(project__service_type=ServiceProject.TYPE_PRESALES).order_by().values("id"),
    )
    presales_without_tasks = active_nodes.filter(project__service_type=ServiceProject.TYPE_PRESALES).exclude(
        id__in=presales_tasks.order_by().values("node_id"),
    ).order_by("project_id", "sequence", "id")
    presales_risks = pending_presales_task_schedules().filter(
        node_id__in=risk_nodes.filter(project__service_type=ServiceProject.TYPE_PRESALES).order_by().values("id"),
    )
    today = timezone.localdate()
    overdue_tasks = presales_risks.filter(planned_end_date__lt=today)
    due_tasks = presales_risks.filter(
        planned_end_date__gte=today,
        planned_end_date__lte=today + timedelta(days=PRESALES_TASK_REMINDER_DAYS),
    )
    presales_risk_counts = presales_risks.aggregate(
        overdue=Count("pk", filter=Q(planned_end_date__lt=today)),
        due=Count("pk", filter=Q(
            planned_end_date__gte=today,
            planned_end_date__lte=today + timedelta(days=PRESALES_TASK_REMINDER_DAYS),
        )),
    )
    overdue_nodes = risk_nodes.exclude(project__service_type=ServiceProject.TYPE_PRESALES).filter(
        planned_end_at__lt=timezone.now(),
    )
    blocked_projects = projects.filter(status=ServiceProject.STATUS_BLOCKED)
    urgent_tickets = open_tickets.filter(priority=ServiceTicket.PRIORITY_HIGH)
    task_total = other_nodes.count() + presales_without_tasks.count() + presales_tasks.count()
    alert_total = (
        blocked_projects.count() + overdue_nodes.count() + presales_risk_counts["overdue"]
        + presales_risk_counts["due"] + urgent_tickets.count()
    )

    tasks = []
    for node in [*other_nodes[:limit], *presales_without_tasks[:limit]]:
        deadline = None if node.project.service_type == ServiceProject.TYPE_PRESALES else node.planned_end_at
        tasks.append({
            "id": node.id,
            "nodeKey": node.node_key,
            "title": node.name,
            "nodeId": node.id,
            "nodeName": node.name,
            "projectId": node.project_id,
            "projectName": node.project.name,
            "serviceType": node.project.service_type,
            "serviceTypeLabel": node.project.get_service_type_display(),
            "module": node.project.service_type,
            "deadline": iso(deadline),
            "dueText": _dashboard_due_text(deadline),
        })
    task_fields = (
        "id", "round_number", "planned_end_date", "node_id", "node__id", "node__node_key", "node__name",
        "node__project_id", "node__project__id", "node__project__name", "node__project__service_type",
    )
    task_candidates = presales_tasks.select_related("node__project").only(*task_fields).order_by(
        F("planned_end_date").asc(nulls_last=True), "node__project_id", "node_id", "round_number",
    )
    for task in task_candidates[:limit]:
        node = task.node
        tasks.append({
            "id": f"presales-task-{task.id}", "nodeKey": node.node_key,
            "title": f"{node.name} · 第 {task.round_number} 轮", "roundNumber": task.round_number,
            "nodeId": node.id, "nodeName": node.name,
            "projectId": node.project_id, "projectName": node.project.name,
            "serviceType": node.project.service_type, "serviceTypeLabel": node.project.get_service_type_display(),
            "module": node.project.service_type, "deadline": iso(_presales_task_end_at(task.planned_end_date)),
            "dueText": _presales_task_due_text(task.planned_end_date, today),
        })
    tasks = sorted(tasks, key=lambda item: (
        datetime.fromisoformat(item["deadline"]).timestamp() if item["deadline"] else float("inf"),
        item["projectId"], str(item["id"]),
    ))[:limit]

    alerts = []
    for project in blocked_projects.only("id", "name", "service_type", "updated_at").order_by("-updated_at", "-id")[:limit]:
        alerts.append({
            "id": f"blocked-project-{project.id}",
            "type": "blocked_project",
            "level": "high",
            "title": f"{project.name} 异常跟进",
            "description": "项目处于异常跟进状态，请及时确认阻塞原因和处理方案。",
            "projectId": project.id,
            "projectName": project.name,
            "serviceType": project.service_type,
            "module": project.service_type,
            "time": iso(project.updated_at),
        })
    for node in overdue_nodes[:limit]:
        alerts.append({
            "id": f"overdue-node-{node.id}",
            "type": "overdue_node",
            "level": "high",
            "title": f"{node.project.name} / {node.name} 已超时",
            "description": f"计划结束时间为 {iso(node.planned_end_at)}，节点仍在进行中。",
            "projectId": node.project_id,
            "projectName": node.project.name,
            "nodeId": node.id,
            "nodeKey": node.node_key,
            "serviceType": node.project.service_type,
            "module": node.project.service_type,
            "time": iso(node.planned_end_at),
            "dueText": _dashboard_due_text(node.planned_end_at),
        })
    for task in overdue_tasks.select_related("node__project").only(*task_fields).order_by("planned_end_date", "id")[:limit]:
        node = task.node
        alerts.append({
            "id": f"overdue-presales-task-{task.id}", "type": "overdue_presales_task", "level": "high",
            "title": f"{node.project.name} / {node.name} · 第 {task.round_number} 轮已超时",
            "description": f"本轮预计完成时间为 {task.planned_end_date:%Y-%m-%d}，所属节点仍在进行中。",
            "projectId": node.project_id, "projectName": node.project.name,
            "nodeId": node.id, "nodeKey": node.node_key, "roundNumber": task.round_number,
            "serviceType": node.project.service_type, "module": node.project.service_type,
            "time": iso(_presales_task_end_at(task.planned_end_date)),
            "dueText": _presales_task_due_text(task.planned_end_date, today),
        })
    for task in due_tasks.select_related("node__project").only(*task_fields).order_by("planned_end_date", "id")[:limit]:
        node = task.node
        due_text = _presales_task_due_text(task.planned_end_date, today)
        alerts.append({
            "id": f"due-presales-task-{task.id}", "type": "due_presales_task", "level": "medium",
            "title": f"{node.project.name} / {node.name} · 第 {task.round_number} 轮{due_text}",
            "description": f"本轮预计完成时间为 {task.planned_end_date:%Y-%m-%d}，请及时安排并提交任务成果。",
            "projectId": node.project_id, "projectName": node.project.name,
            "nodeId": node.id, "nodeKey": node.node_key, "roundNumber": task.round_number,
            "serviceType": node.project.service_type, "module": node.project.service_type,
            "time": iso(_presales_task_end_at(task.planned_end_date)), "dueText": due_text,
        })
    for ticket in urgent_tickets.only(
        "id", "title", "status", "project_id", "updated_at", "project__id", "project__name", "project__service_type",
    ).select_related(None).select_related("project").order_by("-updated_at", "-id")[:limit]:
        alerts.append({
            "id": f"high-priority-ticket-{ticket.id}",
            "type": "high_priority_ticket",
            "level": "high",
            "title": ticket.title,
            "description": f"{ticket.project.name} · 高优先级工单尚未关闭（{ticket.get_status_display()}）。",
            "projectId": ticket.project_id,
            "projectName": ticket.project.name,
            "ticketId": ticket.id,
            "serviceType": ticket.project.service_type,
            "module": "tickets",
            "time": iso(ticket.updated_at),
        })
    # Include all risk categories without loading every alert; within each
    # category records keep their urgency/recent-update order.
    categories = ("overdue_presales_task", "overdue_node", "high_priority_ticket", "blocked_project", "due_presales_task")
    alert_groups = [[item for item in alerts if item["type"] == category] for category in categories]
    alerts = [group[index] for index in range(limit) for group in alert_groups if index < len(group)][:limit]
    project_status = {row["status"]: row["count"] for row in projects.order_by().values("status").annotate(count=Count("id"))}
    recent_projects = _order_projects_by_creation(projects).only(
        "id", "code", "service_type", "name", "customer", "owner_user_id", "owner_name",
        "status", "current_node_key", "source_crm_id", "crm_snapshot",
    ).prefetch_related(Prefetch("nodes", queryset=ProjectNode.objects.filter(
        enabled=True, status=ProjectNode.STATUS_ACTIVE,
    ).only("id", "project_id", "node_key", "name", "sequence", "enabled", "status"),
        to_attr="active_node_summary",
    ))[:limit]
    recent_tickets = tickets.select_related("project", "node").only(
        "id", "code", "title", "status", "priority", "project_id", "node_id", "updated_at",
        "project__id", "project__name", "project__service_type", "node__id", "node__node_key", "node__name",
    ).order_by("-updated_at", "-id")[:limit]
    return JsonResponse({
        "ok": True,
        "scope": "business" if global_business else "personal",
        "canManageService": can_manage_service,
        **sync_status,
        "taskTotal": task_total,
        "alertTotal": alert_total,
        "listLimit": limit,
        "metrics": {
            "projects": sum(project_status.values()),
            "activeProjects": sum(project_status.get(status, 0) for status in [ServiceProject.STATUS_IN_PROGRESS, ServiceProject.STATUS_BLOCKED]),
            "openTickets": open_tickets.count(),
            "pendingFeedback": feedback.filter(status__in=[FieldFeedback.STATUS_SUBMITTED, FieldFeedback.STATUS_REVIEWING]).count(),
            "pendingRewards": rewards.filter(status__in=[Reward.STATUS_PENDING, Reward.STATUS_APPROVED]).count(),
            "providers": 1 if current_provider is not None else 0,
        },
        "projectStatus": project_status,
        "recentProjects": [{
            "id": item.id, "code": item.code, "serviceType": item.service_type,
            "serviceTypeLabel": item.get_service_type_display(), "name": item.name, "customer": item.customer,
            "ownerUserId": item.owner_user_id, "ownerName": item.owner_name,
            "status": item.status, "statusLabel": item.get_status_display(), "currentNodeKey": item.current_node_key,
            "activeNodes": serialize_active_project_nodes(item),
            "crmCreatedAt": (item.crm_snapshot or {}).get("createdAt", "") if item.source_crm_id else "",
        } for item in recent_projects],
        "recentTickets": [{
            "id": item.id, "ticketId": item.id, "code": item.code, "title": item.title,
            "projectId": item.project_id, "projectName": item.project.name,
            "serviceType": item.project.service_type, "module": "tickets",
            "nodeId": item.node_id, "nodeKey": item.node.node_key if item.node_id else "",
            "nodeName": item.node.name if item.node_id else "",
            "status": item.status, "statusLabel": item.get_status_display(),
            "priority": item.priority, "priorityLabel": item.get_priority_display(), "updatedAt": iso(item.updated_at),
        } for item in recent_tickets],
        "tasks": tasks,
        "alerts": alerts,
    })


def _order_projects_by_creation(projects, *, name_search=False):
    # Source timestamps are normalized on import. Missing CRM dates sort last;
    # importing or editing an old CRM project must never make it new.
    projects = projects.alias(_project_created_at=Case(
        When(source_crm_id="", then=F("created_at")),
        default=Cast(KeyTextTransform("createdAt", "crm_snapshot"), output_field=DateTimeField()),
        output_field=DateTimeField(),
    ))
    relevance = ["_name_search_rank"] if name_search else []
    return projects.order_by(*relevance, F("_project_created_at").desc(nulls_last=True), "-id")


def _project_fields(payload: dict, *, creating: bool) -> dict:
    fields = {}
    if creating or "serviceType" in payload:
        fields["service_type"] = _choice(payload.get("serviceType"), ServiceProject.TYPE_CHOICES, "服务类型")
    if creating or "name" in payload:
        fields["name"] = _required_text(payload, "name", "项目名称")
    if creating or "customer" in payload:
        fields["customer"] = _required_text(payload, "customer", "客户名称")
    text_fields = {
        "ownerUserId": ("owner_user_id", "负责人ID", 64),
        "ownerName": ("owner_name", "负责人", 128),
        "address": ("address", "项目地址", 500),
        "province": ("province", "省份", 64),
        "summary": ("summary", "项目说明", 5000),
    }
    for source, (target, label, limit) in text_fields.items():
        if source in payload:
            fields[target] = _optional_text(payload, source, label, max_length=limit)
    date_fields = {
        "plannedStartDate": ("planned_start_date", "计划开始日期"),
        "plannedEndDate": ("planned_end_date", "计划结束日期"),
        "actualStartDate": ("actual_start_date", "实际开始日期"),
        "actualEndDate": ("actual_end_date", "实际结束日期"),
    }
    for source, (target, label) in date_fields.items():
        if source in payload:
            fields[target] = _date_value(payload.get(source), label)
    if "businessData" in payload:
        fields["business_data"] = _json_dict(payload.get("businessData"), "业务数据")
    if creating:
        fields["code"] = _optional_text(payload, "code", "项目编号", max_length=40) or generated_code(
            {"presales": "PS", "midsales": "MS", "aftersales": "AS"}[fields["service_type"]]
        )
        fields["status"] = ServiceProject.STATUS_IN_PROGRESS
        if fields["service_type"] == ServiceProject.TYPE_AFTERSALES:
            missing = []
            if not fields.get("owner_name"):
                missing.append("负责人")
            if not fields.get("address"):
                missing.append("服务地址")
            missing.extend(aftersales_dispatch_errors(fields.get("business_data")))
            if missing:
                raise DomainValidationError(
                    "售后派单信息不完整：" + "、".join(missing),
                    code="AFTERSALES_DISPATCH_INCOMPLETE",
                )
    elif "status" in payload:
        status = _choice(payload.get("status"), ServiceProject.STATUS_CHOICES, "项目状态")
        if status == ServiceProject.STATUS_COMPLETED:
            raise DomainValidationError("项目必须通过节点推进完成", code="PROJECT_ADVANCE_REQUIRED", status=409)
        fields["status"] = status
    return fields


@csrf_exempt
@require_http_methods(["GET", "POST"])
def projects_collection(request):
    if request.method == "POST":
        denied = _ensure_app_admin(request)
        if denied is not None:
            return denied
        payload = _body(request)
        if payload is None:
            return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
        try:
            fields = _project_fields(payload, creating=True)
            identity = request_identity(request)
            fields["owner_user_id"] = identity["user_id"]
            fields["owner_name"] = identity["user_name"]
            if fields["service_type"] == ServiceProject.TYPE_PRESALES:
                business_data = dict(fields.get("business_data") or {})
                project_info = {
                    **(business_data.get("projectInfo") or {}),
                    "owner": identity["user_name"],
                }
                project_info_records = dict(business_data.get("projectInfoRecords") or {})
                project_info_records["early-approval"] = {
                    **(project_info_records.get("early-approval") or {}),
                    **project_info,
                }
                fields["business_data"] = {
                    **business_data,
                    "projectInfo": project_info,
                    "projectInfoRecords": project_info_records,
                }
            disabled = set(_json_list(payload.get("disabledNodeKeys"), "禁用节点"))
            project = create_project(request, fields, disabled_node_keys=disabled)
        except DomainValidationError as exc:
            return _domain_error(exc)
        except Exception as exc:
            if isinstance(exc, ServiceProject.DoesNotExist):
                return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
            if ServiceProject.objects.filter(code=fields.get("code", "")).exists():
                return _error("项目编号已存在", status=409, code="PROJECT_CODE_CONFLICT")
            raise
        project = ServiceProject.objects.prefetch_related("nodes__settlements", "assignments__provider", "assignments__node", "events").get(pk=project.pk)
        return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True)}, status=201)

    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    service_type = text(request.GET.get("type"))
    sync_status = {}
    if service_type == ServiceProject.TYPE_PRESALES:
        sync_status = {"crmSyncing": False, "crmSyncedAt": "", "crmSyncError": "", "crmScopeReady": False}
        try:
            sync_crm_presales(request, background=True, force=request.GET.get("crmRefresh") == "1")
            sync_status = crm_sync_status(request)
        except DomainValidationError as exc:
            # Local presales projects have independent permissions and remain
            # usable even without a valid CRM scope. Never expose CRM rows
            # through this fallback or retry the source inside the list query.
            request._after_sales_crm_ids = []
            sync_status["crmSyncError"] = str(exc)
    projects, provider, failure = _visible_projects(request, include_deleted=True, service_type=service_type)
    if failure is not None:
        return failure
    deleted = text(request.GET.get("deleted")).lower() in {"1", "true", "yes"}
    if provider is not None:
        deleted = False
    projects = projects.filter(deleted_at__isnull=not deleted)
    projects = _order_projects_by_creation(projects)
    if service_type == ServiceProject.TYPE_PRESALES:
        # Collect distinct stage labels across the authorized list, before any
        # filters or pagination. Do not load full projects or fetch CRM again.
        available_crm_stages = {
            value for value in projects.exclude(source_crm_id="").order_by()
            .values_list("crm_snapshot__stage", flat=True).distinct()
            if isinstance(value, str) and value
        }
        sync_status["crmStageOptions"] = [stage for stage in CRM_PRESALES_STAGES if stage in available_crm_stages]
        crm_stage = text(request.GET.get("crmStage"))
        if crm_stage == "__empty__":
            projects = projects.filter(
                Q(source_crm_id="") | Q(crm_snapshot__stage__isnull=True)
                | Q(crm_snapshot__stage=None) | Q(crm_snapshot__stage="")
            )
        elif crm_stage:
            projects = projects.exclude(source_crm_id="").filter(crm_snapshot__stage=crm_stage)
        projects = projects.annotate(presales_project_leads=Subquery(
            ProjectNode.objects.filter(project_id=OuterRef("pk"), node_key="early-approval")
            .values("business_data__projectLeads")[:1], output_field=JSONField(),
        ))
        for role in ("design", "solution"):
            value = text(request.GET.get(f"{role}OwnerSearch"))
            if value:
                projects = projects.annotate(
                    _lead_name=KeyTextTransform("name", KeyTransform(role, "presales_project_leads")),
                    _lead_user_id=KeyTextTransform("userId", KeyTransform(role, "presales_project_leads")),
                    _lead_user_ids=KeyTextTransform("userIds", KeyTransform(role, "presales_project_leads")),
                )
                projects = filter_queryset_search(projects, value, (
                    "_lead_name", "_lead_user_id", "_lead_user_ids",
                ))
    search = _search_filter(request)
    if search:
        projects = filter_queryset_search(projects, search, ("code", "name", "customer", "owner_name", "address"))
    name_search = text(request.GET.get("nameSearch"))
    if name_search:
        # Column search only matches the visible name, with relevance applied
        # before slicing pages. Internal codes and other columns cannot add hits.
        projects = projects.filter(name__icontains=name_search).alias(_name_search_rank=Case(
            When(name__iexact=name_search, then=Value(0)),
            When(name__istartswith=name_search, then=Value(1)),
            default=Value(2), output_field=IntegerField(),
        ))
        projects = _order_projects_by_creation(projects, name_search=True)
    for param, fields in (("customerSearch", ("customer",)), ("ownerSearch", ("owner_name", "owner_user_id"))):
        value = text(request.GET.get(param))
        if value:
            projects = filter_queryset_search(projects, value, fields)
    status = text(request.GET.get("status"))
    provider_id = text(request.GET.get("providerId"))
    if service_type:
        projects = projects.filter(service_type=service_type)
    if status:
        projects = projects.filter(status=status)
    stage = text(request.GET.get("nodeKey"))
    if stage == "completed":
        projects = projects.filter(status=ServiceProject.STATUS_COMPLETED)
    elif stage and service_type == ServiceProject.TYPE_PRESALES:
        active_node = ProjectNode.objects.filter(
            project_id=OuterRef("pk"), node_key=stage, enabled=True, status=ProjectNode.STATUS_ACTIVE,
        )
        projects = projects.annotate(_matches_active_node=Exists(active_node)).filter(
            Q(status=ServiceProject.STATUS_IN_PROGRESS, _matches_active_node=True)
            | (~Q(status=ServiceProject.STATUS_IN_PROGRESS) & Q(current_node_key=stage))
        )
    elif stage:
        projects = projects.filter(current_node_key=stage)
    if request.GET.get("completion") == "active":
        projects = projects.exclude(status=ServiceProject.STATUS_COMPLETED)
    elif request.GET.get("completion") == "completed":
        projects = projects.filter(status=ServiceProject.STATUS_COMPLETED)
    if provider_id:
        try:
            provider_pk = _bounded_int(provider_id, "服务人员", minimum=1)
        except DomainValidationError as exc:
            return _domain_error(exc)
        projects = projects.filter(
            assignments__provider_id=provider_pk,
            assignments__status__in=[
                ProjectAssignment.STATUS_ASSIGNED,
                ProjectAssignment.STATUS_ACCEPTED,
                ProjectAssignment.STATUS_IN_PROGRESS,
                ProjectAssignment.STATUS_COMPLETED,
            ],
        ).distinct()
    if service_type == ServiceProject.TYPE_MIDSALES:
        projects = projects.prefetch_related("nodes__settlements")
        return _paginated(projects, request, lambda item: _serialize_project(request, item, include_nodes=True), crm_scoped=True)
    projects = annotate_presales_task_deadline(projects)
    projects = projects.prefetch_related(Prefetch("nodes", queryset=ProjectNode.objects.only(
        "id", "project_id", "node_key", "name", "sequence", "status", "enabled", "planned_end_at",
    )))
    return _paginated(projects, request, lambda item: _serialize_project(request, item), crm_scoped=True, extra=sync_status)


@require_GET
def project_presales_materials(request, project_id: int):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    project, _provider, _admin, failure = _project_access(request, project_id)
    if failure is not None:
        return failure
    if project.service_type != ServiceProject.TYPE_MIDSALES:
        return _error("仅售中项目可查看售前交接资料", status=400, code="MIDSALES_PROJECT_REQUIRED")
    if not project.presales_project_id:
        return JsonResponse({"project": None, "groups": [], "attachmentCount": 0})
    source, _provider, _admin, failure = _project_access(request, project.presales_project_id)
    if failure is not None:
        return failure
    if source.service_type != ServiceProject.TYPE_PRESALES:
        return _error("关联售前项目无效", status=409, code="PRESALES_PROJECT_REQUIRED")
    # Collect every round's submissions, keeping the newest upload of each name.
    # Only metadata is loaded here; file lists/previews load when a group opens.
    groups = []
    category_labels = dict(PrivateAttachment.CATEGORY_CHOICES)
    nodes = list(source.nodes.only("id", "node_key", "name", "sequence", "business_data"))
    round_attachment_ids = {}
    for node in nodes:
        rounds = (node.business_data or {}).get("schemeRounds")
        if isinstance(rounds, list) and rounds:
            round_attachment_ids[node.id] = {
                str(value) for item in rounds
                if isinstance(item, dict) and isinstance(item.get("attachmentIds"), list)
                for value in item["attachmentIds"]
            }
    target_groups = [(PrivateAttachment.TARGET_PROJECT_NODE, row.id, row.name, row.node_key) for row in nodes]
    target_groups.append((PrivateAttachment.TARGET_PRESALES_PROJECT, source.id, "项目需求文档", ""))
    for target_type, model, label in (
        (PrivateAttachment.TARGET_TICKET, ServiceTicket, "工单"),
        (PrivateAttachment.TARGET_FEEDBACK, FieldFeedback, "反馈"),
        (PrivateAttachment.TARGET_RESOURCE, ServiceResource, "资料"),
    ):
        target_groups.extend((target_type, row.id, f"{label}：{row.title}", "")
                             for row in model.objects.filter(project=source).only("id", "title"))
    targets = Q(pk__in=[])
    for target_type in {row[0] for row in target_groups}:
        targets |= Q(target_type=target_type, target_id__in=[row[1] for row in target_groups if row[0] == target_type])
    counts, item_ids, submission_names = {}, {}, set()
    for row in PrivateAttachment.objects.filter(targets).order_by("-created_at", "-id").values(
        "id", "target_type", "target_id", "category", "original_name",
    ):
        if (row["target_type"] == PrivateAttachment.TARGET_PROJECT_NODE
                and row["category"] == PrivateAttachment.CATEGORY_SCHEME_SUBMISSION):
            if (row["target_id"] in round_attachment_ids
                    and str(row["id"]) not in round_attachment_ids[row["target_id"]]):
                continue
            # Deduplicate across nodes and rounds, after excluding orphan/reason
            # files. Keep all originals in presales; only the handover is filtered.
            name = row["original_name"]
            if name in submission_names:
                continue
            submission_names.add(name)
        key = (row["target_type"], row["target_id"])
        categories = counts.setdefault(key, {})
        categories[row["category"]] = categories.get(row["category"], 0) + 1
        item_ids.setdefault(key, []).append(row["id"])
    for target_type, target_id, name, node_key in target_groups:
        categories = counts.get((target_type, target_id), {})
        if categories:
            groups.append({
                "targetType": target_type, "targetId": target_id, "name": name, "nodeKey": node_key,
                "attachmentCount": sum(categories.values()), "itemIds": item_ids[(target_type, target_id)],
                "categories": [{"value": category, "label": category_labels.get(category, "附件")}
                               for category in sorted(categories)],
            })
    return JsonResponse({
        "project": {"id": source.id, "name": source.name, "sourceCrmId": source.source_crm_id},
        "groups": groups, "attachmentCount": sum(group["attachmentCount"] for group in groups),
    })


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
def project_item(request, project_id: int):
    if request.method == "GET":
        denied = _ensure_app_admin(request)
        if denied is not None:
            return denied
        project, _provider, _is_admin, failure = _project_access(request, project_id, include_deleted=True)
        if failure is not None:
            return failure
        try:
            project = refresh_crm_project(request, project)
        except DomainValidationError as exc:
            return _domain_error(exc)
        project = ServiceProject.objects.prefetch_related(
            "nodes__settlements", "assignments__provider", "assignments__node", "events",
        ).get(pk=project.pk)
        return JsonResponse({"item": _serialize_project(request, project, detail=True)})

    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    try:
        with transaction.atomic():
            project = ServiceProject.objects.select_for_update().get(pk=project_id)
            access.require_project(request, project, manage=True)
            if request.method == "DELETE" and project.source_crm_id:
                raise DomainValidationError(
                    "CRM 同步项目不能在售后系统删除，请在 CRM 中维护",
                    code="CRM_PROJECT_DELETE_FORBIDDEN",
                    status=403,
                )
            assert_crm_project_access(request, project, write=True)
            if request.method == "DELETE":
                if not project.deleted_at:
                    project.deleted_at = timezone.now()
                    project.deleted_by = request_identity(request)["user_id"]
                    touch_audit(project, request)
                    project.save(update_fields=[
                        "deleted_at", "deleted_by", "updated_by", "updated_actor_id", "updated_at",
                    ])
                    record_project_event(request, project, event_type="project_deleted", title="项目移入回收站")
                return JsonResponse({"ok": True, "item": _serialize_project(request, project)})

            payload = _body(request)
            if payload is None:
                return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
            if "expectedUpdatedAt" in payload and payload["expectedUpdatedAt"] != project.updated_at.isoformat():
                raise DomainValidationError("项目资料已被其他人更新，请核对最新内容后再保存；当前填写已保留",
                                            code="PROJECT_CONFLICT", status=409)
            if "expectedDraftVersion" in payload and payload["expectedDraftVersion"] != project_draft_version(project):
                raise DomainValidationError("项目资料已被其他人更新，请核对最新内容后再保存；当前填写已保留",
                                            code="PROJECT_CONFLICT", status=409)
            fields = _project_fields(payload, creating=False)
            if "presalesAreas" in payload or "presalesProjectInfo" in payload:
                if project.service_type != ServiceProject.TYPE_PRESALES:
                    raise DomainValidationError("仅售前项目支持此项目信息", code="PRESALES_PROJECT_REQUIRED")
                if project.deleted_at:
                    raise DomainValidationError("已删除项目不能修改项目信息", code="PROJECT_DELETED", status=409)
                if not payload.get("expectedDraftVersion"):
                    raise DomainValidationError("请重新读取项目后保存项目信息", code="PROJECT_CONFLICT", status=409)
                if "presalesAreas" in payload and "presalesProjectInfo" in payload:
                    raise DomainValidationError("请勿同时提交两组项目信息", code="INVALID_PROJECT_INFO")
                info = (normalize_presales_project_info(payload["presalesProjectInfo"])
                        if "presalesProjectInfo" in payload else normalize_presales_areas(payload["presalesAreas"]))
                data = dict(fields.get("business_data", project.business_data) or {})
                data["projectInfo"] = {**(data.get("projectInfo") or {}), **info}
                fields["business_data"] = data
            protect_crm_project_fields(project, fields)
            if fields.get("business_data") is not None:
                validate_presales_project_info_records(project, fields["business_data"])
                if (project.service_type == ServiceProject.TYPE_PRESALES
                        and "projectInfoRecords" not in fields["business_data"]
                        and "projectInfoRecords" in (project.business_data or {})):
                    fields["business_data"]["projectInfoRecords"] = project.business_data["projectInfoRecords"]
            if "service_type" in fields and fields["service_type"] != project.service_type:
                raise DomainValidationError(
                    "项目创建后不能变更服务类型",
                    code="PROJECT_TYPE_IMMUTABLE",
                    status=409,
                )
            # Run access, version and business validations even for a redundant
            # autosave, but only persist fields that actually changed.
            fields = {
                field: value for field, value in fields.items()
                if value != getattr(project, field) and not (
                    field == "business_data" and project.service_type == ServiceProject.TYPE_PRESALES
                    and presales_project_data_equal(project.business_data, value)
                )
            }
            if fields:
                before = {field: getattr(project, field) for field in fields}
                for field, value in fields.items():
                    setattr(project, field, value)
                touch_audit(project, request)
                project.save()
                record_project_event(
                    request,
                    project,
                    event_type="project_updated",
                    title="更新项目资料",
                    before={key: str(value or "") for key, value in before.items()},
                    after={key: str(value or "") for key, value in fields.items()},
                )
            if "disabledNodeKeys" in payload:
                configure_project_nodes(
                    request,
                    project.id,
                    set(_json_list(payload.get("disabledNodeKeys"), "禁用节点")),
                )
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    project = ServiceProject.objects.prefetch_related("nodes__settlements", "assignments__provider", "assignments__node", "events").get(pk=project_id)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True)})


def _related_products(data: object) -> list[dict]:
    source = data if isinstance(data, dict) else {}
    return [row for row in source.get("relatedProducts", []) if isinstance(row, dict)]


def _related_product_ids_from_data(data: object) -> list[int]:
    result = []
    for row in _related_products(data):
        try:
            product_id = int(row.get("productId"))
        except (TypeError, ValueError):
            product_id = 0
        if product_id > 0 and product_id not in result:
            result.append(product_id)
    return result


def _related_product_ids(project: ServiceProject) -> list[int]:
    return _related_product_ids_from_data(project.business_data)


def _related_product_snapshot(product: dict) -> dict:
    return {
        key: product.get(key)
        for key in (
            "productId", "kingdeeCode", "name", "brand", "model", "abbr",
            "productDomain", "categoryA", "categoryB", "categoryC", "unit", "lifecycle",
            "productThumb",
        )
    } | {
        "manuals": [
            {"key": manual["key"], "label": manual["label"]}
            for manual in product.get("manuals", [])
            if manual.get("key") in MANUAL_KEYS
        ],
    }


def _validated_related_product_snapshots(payload: dict) -> tuple[list[int], list[dict]]:
    product_ids = []
    for value in _json_list(payload.get("productIds"), "产品编号"):
        try:
            product_id = int(value)
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("产品编号无效", code="PRODUCT_ID_INVALID") from exc
        if product_id <= 0:
            raise DomainValidationError("产品编号无效", code="PRODUCT_ID_INVALID")
        if product_id not in product_ids:
            product_ids.append(product_id)
    if len(product_ids) > 100:
        raise DomainValidationError("单个节点最多关联 100 个产品", code="PRODUCT_LIMIT_EXCEEDED")
    catalog = fetch_products_by_ids(product_ids)
    missing = [str(product_id) for product_id in product_ids if product_id not in catalog]
    if missing:
        raise DomainValidationError(
            "以下产品已不存在或不可用：" + "、".join(missing),
            code="PRODUCT_NOT_FOUND",
            status=409,
        )
    return product_ids, [_related_product_snapshot(catalog[product_id]) for product_id in product_ids]


@csrf_exempt
@require_http_methods(["PATCH"])
def project_related_products(request, project_id: int):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        project = ServiceProject.objects.get(pk=project_id, deleted_at__isnull=True)
        access.require_project(request, project, manage=True)
        assert_crm_project_access(request, project, write=True)
        if project.service_type != ServiceProject.TYPE_AFTERSALES:
            raise DomainValidationError("只有售后服务可以关联产品", code="PROJECT_TYPE_INVALID", status=409)
        product_ids, snapshots = _validated_related_product_snapshots(payload)
        with transaction.atomic():
            project = ServiceProject.objects.select_for_update().get(pk=project_id, deleted_at__isnull=True)
            before_ids = _related_product_ids(project)
            business_data = dict(project.business_data or {})
            business_data.pop("products", None)
            business_data["relatedProducts"] = snapshots
            project.business_data = business_data
            touch_audit(project, request)
            project.save(update_fields=["business_data", "updated_by", "updated_actor_id", "updated_at"])
            record_project_event(
                request,
                project,
                event_type="related_products_updated",
                title="更新相关产品",
                before={"productIds": before_ids},
                after={"productIds": product_ids},
            )
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    except ProductCatalogError as exc:
        return _error(str(exc), status=exc.status_code, code="PRODUCT_CATALOG_UNAVAILABLE")
    project = ServiceProject.objects.prefetch_related(
        "nodes__settlements", "assignments__provider", "assignments__node", "events",
    ).get(pk=project_id)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True)})


@csrf_exempt
@require_http_methods(["PATCH"])
def project_node_related_products(request, project_id: int, node_key: str):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        project = ServiceProject.objects.get(pk=project_id, deleted_at__isnull=True)
        if project.service_type != ServiceProject.TYPE_MIDSALES:
            raise DomainValidationError("只有售中服务节点可以单独关联产品", code="PROJECT_TYPE_INVALID", status=409)
        if node_key not in MIDSALES_RELATED_PRODUCT_NODE_KEYS:
            raise DomainValidationError("当前节点不支持关联产品", code="PROJECT_NODE_INVALID", status=409)
        node = ProjectNode.objects.get(project=project, node_key=node_key)
        access.require_node(request, node)
        assert_crm_project_access(request, project, write=True)
        if not node.enabled:
            raise DomainValidationError("当前项目不包含该节点", code="PROJECT_NODE_DISABLED", status=409)
        if (project.status in {ServiceProject.STATUS_COMPLETED, ServiceProject.STATUS_CANCELLED}
                or node.status in {ProjectNode.STATUS_COMPLETED, ProjectNode.STATUS_SKIPPED}):
            raise DomainValidationError("已结束节点的相关产品只读", code="PROJECT_NODE_READ_ONLY", status=409)
        product_ids, snapshots = _validated_related_product_snapshots(payload)
        with transaction.atomic():
            project = ServiceProject.objects.select_for_update().get(pk=project_id)
            node = ProjectNode.objects.select_for_update().get(project_id=project_id, node_key=node_key)
            if (project.status in {ServiceProject.STATUS_COMPLETED, ServiceProject.STATUS_CANCELLED}
                    or not node.enabled or node.status in {ProjectNode.STATUS_COMPLETED, ProjectNode.STATUS_SKIPPED}):
                raise DomainValidationError("已结束节点的相关产品只读", code="PROJECT_NODE_READ_ONLY", status=409)
            before_ids = _related_product_ids_from_data(node.business_data)
            node.business_data = {**(node.business_data or {}), "relatedProducts": snapshots}
            touch_audit(node, request)
            node.save(update_fields=["business_data", "updated_by", "updated_actor_id", "updated_at"])
            record_project_event(
                request,
                project,
                node=node,
                event_type="node_related_products_updated",
                title=f"更新{node.name}相关产品",
                before={"productIds": before_ids},
                after={"productIds": product_ids},
            )
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    except ProjectNode.DoesNotExist:
        return _error("项目节点不存在", status=404, code="PROJECT_NODE_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    except ProductCatalogError as exc:
        return _error(str(exc), status=exc.status_code, code="PRODUCT_CATALOG_UNAVAILABLE")
    project = ServiceProject.objects.prefetch_related(
        "nodes__settlements", "assignments__provider", "assignments__node", "events",
    ).get(pk=project_id)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True)})


@require_GET
def product_catalog(request):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    try:
        result = fetch_product_catalog({
            "q": _search_filter(request),
            "categoryA": text(request.GET.get("categoryA")),
            "categoryB": text(request.GET.get("categoryB")),
            "categoryC": text(request.GET.get("categoryC")),
            "excludeEliminated": "1",
            "page": _positive_int(request.GET.get("page"), 1, maximum=100_000),
            "pageSize": _positive_int(request.GET.get("pageSize"), 24, maximum=100),
        })
    except ProductCatalogError as exc:
        return _error(str(exc), status=exc.status_code, code="PRODUCT_CATALOG_UNAVAILABLE")
    return JsonResponse({
        **result,
        "items": [
            {
                **item,
                "manuals": [
                    {"key": row["key"], "label": row["label"], "url": row["url"]}
                    for row in item["manuals"]
                ],
            }
            for item in result["items"]
        ],
    })


@require_GET
def product_catalog_item(request, product_id: int):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    try:
        product = fetch_products_by_ids([product_id]).get(product_id)
    except ProductCatalogError as exc:
        return _error(str(exc), status=exc.status_code, code="PRODUCT_CATALOG_UNAVAILABLE")
    if not product:
        return _error("产品档案中未找到该产品", status=404, code="PRODUCT_NOT_FOUND")
    return JsonResponse({"item": product})


def _render_product_manual_pdf(product_id: int, manual_key: str, url: str):
    try:
        pdf_path = render_feishu_manual_pdf(url)
    except ManualRenderError as exc:
        return _error(str(exc), status=503, code="PRODUCT_MANUAL_RENDER_UNAVAILABLE")
    response = FileResponse(
        pdf_path.open("rb"),
        content_type="application/pdf",
        as_attachment=False,
        filename=f"product-{product_id}-{manual_key}.pdf",
    )
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def product_catalog_image(request, product_id: int):
    is_admin, failure = _admin_status(request)
    if failure is not None:
        return failure
    if not is_admin:
        try:
            project_id = int(request.GET.get("projectId") or 0)
        except (TypeError, ValueError):
            project_id = 0
        node_key = text(request.GET.get("nodeKey"))
        project, provider, _is_admin, failure = _project_access(request, project_id)
        if failure is not None:
            return failure
        if provider is not None and node_key and not ProjectAssignment.objects.filter(
            project=project,
            node__node_key=node_key,
            provider=provider,
            status__in=MESSAGE_READ_ASSIGNMENT_STATUSES,
        ).exists():
            return _error("产品图片不存在或无权访问", status=404, code="PRODUCT_IMAGE_NOT_FOUND")
        if project.service_type == ServiceProject.TYPE_AFTERSALES:
            data = project.business_data
        elif project.service_type == ServiceProject.TYPE_MIDSALES and node_key in MIDSALES_RELATED_PRODUCT_NODE_KEYS:
            node = ProjectNode.objects.filter(project=project, node_key=node_key, enabled=True).first()
            data = node.business_data if node is not None else {}
        else:
            data = {}
        if not any(str(row.get("productId")) == str(product_id) for row in _related_products(data)):
            return _error("产品图片不存在或无权访问", status=404, code="PRODUCT_IMAGE_NOT_FOUND")
    try:
        image_kwargs = {"variant": text(request.GET.get("variant")) or "thumbnail"}
        if request.GET.get("slot"):
            image_kwargs["slot"] = text(request.GET.get("slot"))
        body, content_type = fetch_product_image(product_id, **image_kwargs)
    except ProductCatalogError as exc:
        return _error(str(exc), status=exc.status_code, code="PRODUCT_CATALOG_UNAVAILABLE")
    response = HttpResponse(body, content_type=content_type)
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def product_manual(request, product_id: int, manual_key: str):
    try:
        project_id = int(request.GET.get("projectId") or 0)
    except (TypeError, ValueError):
        project_id = 0
    node_key = text(request.GET.get("nodeKey"))
    project, provider, _is_admin, failure = _project_access(request, project_id)
    if failure is not None:
        return failure
    if provider is not None and node_key and not ProjectAssignment.objects.filter(
        project=project,
        node__node_key=node_key,
        provider=provider,
        status__in=MESSAGE_READ_ASSIGNMENT_STATUSES,
    ).exists():
        return _error("产品说明书不存在或无权访问", status=404, code="PRODUCT_MANUAL_NOT_FOUND")
    if project.service_type == ServiceProject.TYPE_AFTERSALES:
        data = project.business_data
    elif project.service_type == ServiceProject.TYPE_MIDSALES and node_key in MIDSALES_RELATED_PRODUCT_NODE_KEYS:
        node = ProjectNode.objects.filter(project=project, node_key=node_key, enabled=True).first()
        data = node.business_data if node is not None else {}
    else:
        data = {}
    related = next(
        (
            row for row in _related_products(data)
            if str(row.get("productId")) == str(product_id)
        ),
        {},
    )
    if not related:
        return _error("产品说明书不存在或无权访问", status=404, code="PRODUCT_MANUAL_NOT_FOUND")
    allowed_manuals = related.get("manuals") if isinstance(related.get("manuals"), list) else []
    if manual_key not in MANUAL_KEYS or not any(row.get("key") == manual_key for row in allowed_manuals if isinstance(row, dict)):
        return _error("产品说明书不存在或无权访问", status=404, code="PRODUCT_MANUAL_NOT_FOUND")
    try:
        product = fetch_products_by_ids([product_id]).get(product_id)
    except ProductCatalogError as exc:
        return _error(str(exc), status=exc.status_code, code="PRODUCT_CATALOG_UNAVAILABLE")
    manual = next((row for row in (product or {}).get("manuals", []) if row.get("key") == manual_key), None)
    url = str((manual or {}).get("url") or "").strip()
    scheme = urlsplit(url).scheme.lower()
    if not url or (not url.startswith("/") and scheme not in {"http", "https"}):
        return _error("该产品说明书当前不可访问", status=404, code="PRODUCT_MANUAL_NOT_FOUND")
    if is_feishu_document_url(url):
        return _render_product_manual_pdf(product_id, manual_key, url)
    return HttpResponseRedirect(url)


@csrf_exempt
@require_POST
def project_restore(request, project_id: int):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    try:
        with transaction.atomic():
            project = ServiceProject.objects.select_for_update().get(pk=project_id)
            access.require_project(request, project, manage=True)
            assert_crm_project_access(request, project, write=True)
            project.deleted_at = None
            project.deleted_by = ""
            touch_audit(project, request)
            project.save(update_fields=["deleted_at", "deleted_by", "updated_by", "updated_actor_id", "updated_at"])
            record_project_event(request, project, event_type="project_restored", title="恢复项目")
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project)})


def _project_node_values(payload: dict, *, note_label: str) -> dict:
    values = {}
    if "expectedUpdatedAt" in payload:
        values["expected_updated_at"] = _optional_text(payload, "expectedUpdatedAt", "节点版本", max_length=128)
    mapping = {
        "plannedStartAt": ("planned_start_at", "计划开始时间"),
        "plannedEndAt": ("planned_end_at", "计划结束时间"),
        "actualStartAt": ("actual_start_at", "实际开始时间"),
        "actualEndAt": ("actual_end_at", "实际结束时间"),
    }
    for source, (target, label) in mapping.items():
        if source in payload:
            values[target] = _datetime_value(payload.get(source), label)
    if "estimatedFee" in payload:
        values["estimated_fee"] = _decimal_value(payload.get("estimatedFee"), "预计费用")
    if "actualFee" in payload:
        values["actual_fee"] = _decimal_value(payload.get("actualFee"), "实际费用")
    if "businessData" in payload:
        business_data = _json_dict(payload.get("businessData"), "节点业务数据")
        for quote_key in ("externalQuote", "external_quote"):
            if quote_key in business_data:
                quote = _decimal_value(business_data.get(quote_key), "对外报价")
                business_data[quote_key] = format(quote, "f") if quote is not None else ""
        values["business_data"] = business_data
    if "outcome" in payload:
        values["outcome"] = _optional_text(payload, "outcome", "处理结果", max_length=32)
    values["note"] = _optional_text(payload, "note", note_label, max_length=5000)
    return values


@csrf_exempt
@require_POST
def project_advance(request, project_id: int):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        values = _project_node_values(payload, note_label="推进说明")
        project = advance_project(
            request,
            project_id,
            expected_node_key=text(payload.get("nodeKey")),
            node_values=values,
        )
    except DomainValidationError as exc:
        return _domain_error(exc)
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    project = ServiceProject.objects.prefetch_related("nodes__settlements", "assignments__provider", "assignments__node", "events").get(pk=project.pk)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True)})


@csrf_exempt
@require_POST
def project_round_action(request, project_id: int, node_key: str, operation: str):
    from .presales_round_actions import prepare_round_forward, process_presales_round

    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    if request.content_type == "multipart/form-data":
        try:
            payload = json.loads(request.POST.get("payload", "{}"))
        except (TypeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            payload = None
    else:
        payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    round_id = ""
    try:
        if operation == "prepare-forward":
            project, round_id = prepare_round_forward(request, project_id, node_key, payload)
        elif operation == "process":
            project = process_presales_round(request, project_id, node_key, payload,
                                            reason_files=request.FILES.getlist("reasonFiles"))
        else:
            return _error("轮次操作不存在", status=404, code="NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    project = ServiceProject.objects.prefetch_related(
        "nodes__settlements", "assignments__provider", "assignments__node", "events",
    ).get(pk=project.pk)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True), "roundId": round_id})


@csrf_exempt
@require_POST
def project_start(request, project_id: int):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        project = start_project_node(
            request,
            project_id,
            expected_node_key=text(payload.get("nodeKey")),
        )
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    project = ServiceProject.objects.prefetch_related(
        "nodes__settlements", "assignments__provider", "assignments__node", "events",
    ).get(pk=project.pk)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True)})


@csrf_exempt
@require_POST
def project_submit_version(request, project_id: int, node_key: str):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        project = submit_project_node_version(
            request,
            project_id,
            node_key=node_key,
            node_values=_project_node_values(payload, note_label="版本说明"),
        )
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    project = ServiceProject.objects.prefetch_related(
        "nodes__settlements", "assignments__provider", "assignments__node", "events",
    ).get(pk=project.pk)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True)})


@csrf_exempt
@require_http_methods(["PATCH"])
def project_node_autosave(request, project_id: int, node_key: str):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        project = save_project_node_draft(
            request,
            project_id,
            node_key=node_key,
            node_values=_project_node_values(payload, note_label="自动保存说明"),
        )
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    project = ServiceProject.objects.prefetch_related(
        "nodes__settlements", "assignments__provider", "assignments__node", "events",
    ).get(pk=project.pk)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True)})


@csrf_exempt
@require_POST
def project_reject_completion(request, project_id: int):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        project = reject_aftersales_completion(
            request,
            project_id,
            node_key=_required_text(payload, "nodeKey", "项目节点", max_length=64),
            note=_required_text(payload, "note", "完工驳回原因", max_length=5000),
        )
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    project = ServiceProject.objects.prefetch_related(
        "nodes__settlements", "assignments__provider", "assignments__node", "events",
    ).get(pk=project.pk)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True)})


@csrf_exempt
@require_POST
def project_reopen(request, project_id: int):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        project = reopen_project_node(
            request,
            project_id,
            node_key=text(payload.get("nodeKey")),
            note=_optional_text(payload, "note", "退回原因", max_length=5000),
        )
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    project = ServiceProject.objects.prefetch_related(
        "nodes__settlements", "assignments__provider", "assignments__node", "events",
    ).get(pk=project.pk)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True)})


@csrf_exempt
@require_POST
def project_select_service(request, project_id: int):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        project = select_aftersales_node(
            request,
            project_id,
            node_key=_required_text(payload, "nodeKey", "售后服务节点", max_length=64),
            note=_optional_text(payload, "note", "切换说明", max_length=5000),
        )
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    project = ServiceProject.objects.prefetch_related(
        "nodes__settlements", "assignments__provider", "assignments__node", "events",
    ).get(pk=project.pk)
    return JsonResponse({"ok": True, "item": _serialize_project(request, project, detail=True)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def project_assignments(request, project_id: int):
    if request.method == "GET":
        denied = _ensure_app_admin(request)
        if denied is not None:
            return denied
        project, _provider, _is_admin, failure = _project_access(request, project_id)
        if failure is not None:
            return failure
        rows = ProjectAssignment.objects.filter(project=project).select_related("provider", "node").order_by(
            "node__sequence", "-assigned_at", "-id",
        )
        return JsonResponse({"items": [serialize_assignment(row) for row in rows]})
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        assignment_values = {}
        if "expectedUpdatedAt" in payload:
            assignment_values["expected_updated_at"] = _optional_text(payload, "expectedUpdatedAt", "节点版本", max_length=128)
        if "plannedStartDate" in payload:
            assignment_values["planned_start_date"] = _date_value(payload.get("plannedStartDate"), "计划开始日期")
        if "standardDuration" in payload:
            assignment_values["standard_duration"] = _optional_text(
                payload,
                "standardDuration",
                "标准工期",
                max_length=64,
            )
        assignment = assign_provider(
            request,
            project_id,
            node_key=_required_text(payload, "nodeKey", "项目节点", max_length=64),
            provider_id=_bounded_int(payload.get("providerId"), "服务人员", minimum=1),
            role=_optional_text(payload, "role", "指派角色", max_length=64),
            note=_optional_text(payload, "note", "指派说明", max_length=5000),
            **assignment_values,
        )
    except DomainValidationError as exc:
        return _domain_error(exc)
    except ServiceProject.DoesNotExist:
        return _error("项目不存在", status=404, code="PROJECT_NOT_FOUND")
    assignment = ProjectAssignment.objects.select_related("provider", "node").get(pk=assignment.pk)
    return JsonResponse({"ok": True, "item": serialize_assignment(assignment)}, status=201)


def _active_employee_directory() -> tuple[list[dict], str]:
    departments, employees, org_revision = get_auth_organization_snapshot()
    department_by_id = {
        text(department.get("deptId") or department.get("id")): department
        for department in departments
        if isinstance(department, dict) and text(department.get("deptId") or department.get("id"))
    }
    items = []
    seen = set()
    for employee in employees:
        if not isinstance(employee, dict):
            continue
        status = text(employee.get("status")).lower()
        account_status = text(employee.get("accountStatus") or employee.get("account_status")).lower()
        if status and status not in {"active", "在职"}:
            continue
        if account_status and account_status not in {"enabled", "启用"}:
            continue
        user_id = text(employee.get("userId") or employee.get("user_id") or employee.get("id"))
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        raw_departments = employee.get("departments")
        if not isinstance(raw_departments, list):
            raw_departments = employee.get("departmentIds")
        if not isinstance(raw_departments, list):
            raw_departments = []
        employee_departments = []
        seen_department_ids = set()
        for raw_department in raw_departments:
            raw_department_id = text(
                raw_department.get("deptId") or raw_department.get("id")
                if isinstance(raw_department, dict)
                else raw_department
            )
            directory_department = department_by_id.get(raw_department_id, {})
            source_department = raw_department if isinstance(raw_department, dict) else directory_department
            department_id = text(
                source_department.get("deptId") or source_department.get("id") or raw_department_id
            )
            if not department_id or department_id in seen_department_ids:
                continue
            seen_department_ids.add(department_id)
            employee_departments.append({
                "deptId": department_id,
                "name": text(source_department.get("name") or directory_department.get("name")) or department_id,
                "pinyin": text(source_department.get("pinyin") or directory_department.get("pinyin")),
                "pinyinInitials": text(
                    source_department.get("pinyinInitials")
                    or source_department.get("pinyin_initials")
                    or directory_department.get("pinyinInitials")
                    or directory_department.get("pinyin_initials")
                ),
                "departmentPathText": text(
                    source_department.get("departmentPathText")
                    or source_department.get("department_path_text")
                    or directory_department.get("departmentPathText")
                    or directory_department.get("department_path_text")
                ),
            })
        items.append({
            "userId": user_id,
            "name": text(employee.get("rawName") or employee.get("raw_name") or employee.get("name")) or user_id,
            "avatarUrl": text(employee.get("avatarUrl") or employee.get("avatar_url")),
            "pinyin": text(employee.get("pinyin")),
            "pinyinInitials": text(employee.get("pinyinInitials") or employee.get("pinyin_initials")),
            "departments": employee_departments,
        })
    items.sort(key=lambda item: (item["name"], item["userId"]))
    return items, org_revision


def _provider_metrics(queryset):
    today = timezone.localdate()
    completed_service = Q(
        assignments__status=ProjectAssignment.STATUS_COMPLETED,
        assignments__node__node_key__in=INSTALLATION_NODE_KEYS,
        assignments__completed_at__isnull=False,
    )
    return queryset.annotate(
        metric_month_orders=Count(
            "assignments",
            filter=completed_service
            & Q(assignments__completed_at__year=today.year, assignments__completed_at__month=today.month),
            distinct=True,
        ),
        metric_total_orders=Count("assignments", filter=completed_service, distinct=True),
        metric_score=Avg("assignments__service_rating__rating"),
        metric_score_count=Count("assignments__service_rating", distinct=True),
    )


def _provider_fields(payload: dict) -> dict:
    fields = {}
    if "authUserId" in payload:
        raise DomainValidationError(
            "服务人员的微信身份绑定不可修改",
            code="PROVIDER_IDENTITY_IMMUTABLE",
            status=409,
        )
    if "name" in payload:
        fields["name"] = _required_text(payload, "name", "姓名", max_length=128)
    if "role" in payload:
        fields["role"] = _choice(payload.get("role"), ServiceProvider.ROLE_CHOICES, "人员角色", default=ServiceProvider.ROLE_INSTALLER)
    if "phone" in payload:
        fields["phone"] = _optional_text(payload, "phone", "联系电话", max_length=32)
    if "city" in payload:
        fields["city"] = _optional_text(payload, "city", "所在城市", max_length=64)
    if "regions" in payload:
        fields["regions"] = [text(row) for row in _json_list(payload.get("regions"), "服务地区") if text(row)]
    if "skills" in payload:
        fields["skills"] = [text(row) for row in _json_list(payload.get("skills"), "服务技能") if text(row)]
    if "certificationStatus" in payload:
        fields["certification_status"] = _choice(
            payload.get("certificationStatus"),
            ServiceProvider.CERT_CHOICES,
            "认证状态",
            default=ServiceProvider.CERT_PENDING,
        )
    if "score" in payload:
        score = _decimal_value(payload.get("score"), "服务评分", default=Decimal("0"))
        if score > Decimal("5"):
            raise DomainValidationError("服务评分不能超过 5", code="INVALID_PROVIDER_SCORE")
        fields["score"] = score
    if "monthOrders" in payload:
        fields["month_orders"] = _bounded_int(payload.get("monthOrders"), "本月订单数")
    if "totalOrders" in payload:
        fields["total_orders"] = _bounded_int(payload.get("totalOrders"), "累计订单数")
    if "bio" in payload:
        fields["bio"] = _optional_text(payload, "bio", "人员简介", max_length=5000)
    return fields


@csrf_exempt
@require_http_methods(["GET", "POST"])
def providers_collection(request):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    if request.method == "POST":
        return _error(
            "服务人员必须通过微信小程序注册，管理端不能手工新增",
            status=405,
            code="PROVIDER_SELF_REGISTRATION_REQUIRED",
        )
    rows = _provider_metrics(ServiceProvider.objects.filter(
        identity_source=ServiceProvider.IDENTITY_WECHAT_MINI,
    ))
    search = _search_filter(request)
    if search:
        rows = filter_queryset_search(rows, search, ("name", "auth_user_id", "phone", "city"))
    role = text(request.GET.get("type") or request.GET.get("role"))
    status = text(request.GET.get("status"))
    if role:
        rows = rows.filter(role=role)
    if status:
        rows = rows.filter(certification_status=status)
    return _paginated(rows, request, serialize_provider)


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def provider_item(request, provider_id: int):
    denied = _ensure_app_admin(request) if request.method == "GET" else _ensure_service_manager(request)
    if denied is not None:
        return denied
    try:
        provider = _provider_metrics(ServiceProvider.objects).get(pk=provider_id)
    except ServiceProvider.DoesNotExist:
        return _error("服务人员不存在", status=404, code="PROVIDER_NOT_FOUND")
    if request.method == "GET":
        return JsonResponse({"item": serialize_provider(provider, detail=True)})
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        fields = _provider_fields(payload)
    except DomainValidationError as exc:
        return _domain_error(exc)
    with transaction.atomic():
        provider = ServiceProvider.objects.select_for_update().get(pk=provider_id)
        for field, value in fields.items():
            setattr(provider, field, value)
        touch_audit(provider, request)
        provider.save()
    provider = _provider_metrics(ServiceProvider.objects).get(pk=provider.pk)
    return JsonResponse({"ok": True, "item": serialize_provider(provider, detail=True)})


@require_GET
def message_conversations(request):
    rows, failure = _visible_project_messages(request)
    if failure is not None:
        return failure
    project_id = text(request.GET.get("projectId"))
    if project_id:
        try:
            rows = rows.filter(project_id=_bounded_int(project_id, "项目", minimum=1))
        except DomainValidationError as exc:
            return _domain_error(exc)
    return JsonResponse(_conversation_data(rows, request))


@csrf_exempt
@require_http_methods(["GET", "POST"])
def project_messages(request, project_id: int):
    payload = None
    if request.method == "POST":
        payload = _body(request)
        if payload is None:
            return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    node_key = text(
        request.GET.get("nodeKey")
        if request.method == "GET"
        else payload.get("nodeKey")
    )
    project, node, _provider, failure = _project_message_access(
        request,
        project_id,
        node_key=node_key,
        for_write=request.method == "POST",
    )
    if failure is not None:
        return failure

    if request.method == "POST":
        try:
            content = _required_text(payload, "content", "消息内容", max_length=10_000)
        except DomainValidationError as exc:
            return _domain_error(exc)
        identity = request_identity(request)
        message = ProjectMessage.objects.create(
            project=project,
            node=node,
            author_user_id=identity["user_id"],
            author_name=identity["user_name"],
            actor_user_id=identity["actor_id"],
            message_type=ProjectMessage.TYPE_TEXT,
            content=content,
        )
        message = ProjectMessage.objects.select_related("project", "node").get(pk=message.pk)
        return JsonResponse({
            "ok": True,
            "item": serialize_project_message(message, user_id=identity["user_id"]),
        }, status=201)

    rows = ProjectMessage.objects.filter(project=project, node=node).select_related("project", "node")
    user_id = text(getattr(request, "auth_user_id", ""))
    rows = _project_message_rows_with_read_state(rows, user_id)
    unread_count = rows.filter(_read_by_user=False).exclude(author_user_id=user_id).count()
    page, page_size = _page(request)
    total = rows.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    start = (page - 1) * page_size
    return JsonResponse({
        "items": [
            serialize_project_message(item, user_id=user_id)
            for item in rows[start:start + page_size]
        ],
        "conversation": {
            "id": f"{project.id}:{node.node_key if node else 'project'}",
            "projectId": project.id,
            "projectName": project.name,
            "nodeId": node.id if node else None,
            "nodeKey": node.node_key if node else "",
            "nodeName": node.name if node else "项目沟通",
            "conversationType": "node" if node else "project",
            "visibility": "node_participants" if node else "project_participants",
        },
        "unreadCount": unread_count,
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
    })


@csrf_exempt
@require_POST
def project_messages_read(request, project_id: int):
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    node_key = text(payload.get("nodeKey"))
    project, node, _provider, failure = _project_message_access(
        request,
        project_id,
        node_key=node_key,
        for_write=False,
    )
    if failure is not None:
        return failure
    rows = ProjectMessage.objects.filter(project=project, node=node)
    try:
        through_id = (
            _bounded_int(payload.get("throughId"), "最后已读消息", minimum=1)
            if payload.get("throughId") not in (None, "")
            else rows.aggregate(value=Max("id"))["value"]
        )
    except DomainValidationError as exc:
        return _domain_error(exc)
    if through_id is None:
        return JsonResponse({"ok": True, "readCount": 0, "unreadCount": 0})
    if not rows.filter(pk=through_id).exists():
        return _error(
            "最后已读消息不属于当前会话",
            status=409,
            code="PROJECT_MESSAGE_READ_TARGET_INVALID",
        )
    user_id = text(getattr(request, "auth_user_id", ""))
    unread_rows = _project_message_rows_with_read_state(
        rows.filter(pk__lte=through_id).exclude(author_user_id=user_id),
        user_id,
    ).filter(_read_by_user=False)
    message_ids = list(unread_rows.values_list("id", flat=True))
    ProjectMessageRead.objects.bulk_create(
        [ProjectMessageRead(message_id=message_id, user_id=user_id) for message_id in message_ids],
        ignore_conflicts=True,
    )
    remaining = _project_message_rows_with_read_state(
        rows.exclude(author_user_id=user_id),
        user_id,
    ).filter(_read_by_user=False).count()
    return JsonResponse({
        "ok": True,
        "throughId": through_id,
        "readCount": len(message_ids),
        "unreadCount": remaining,
    })


def _visible_tickets(request, *, project_scope=None):
    if project_scope is None:
        projects, provider, failure = _visible_projects(request)
        if failure is not None:
            return None, provider, failure
    else:
        projects, provider = project_scope
    rows = ServiceTicket.objects.filter(project__in=projects).select_related("project", "node")
    if provider is None:
        rows = rows.filter(project__in=access.scope_projects(request))
    if provider is not None:
        assigned_node = ProjectAssignment.objects.filter(
            provider=provider,
            project_id=OuterRef("project_id"),
            node_id=OuterRef("node_id"),
        ).exclude(status=ProjectAssignment.STATUS_CANCELLED)
        rows = rows.annotate(_assigned_node=Exists(assigned_node)).filter(
            Q(_assigned_node=True)
            | Q(node_id__isnull=True)
            | Q(reporter_user_id=provider.auth_user_id)
            | Q(owner_user_id=provider.auth_user_id)
        ).distinct()
    return rows, provider, None


@csrf_exempt
@require_http_methods(["GET", "POST"])
def tickets_collection(request):
    if request.method == "GET":
        rows, _provider, failure = _visible_tickets(request)
        if failure is not None:
            return failure
        search = _search_filter(request)
        if search:
            rows = filter_queryset_search(rows, search, ("code", "title", "project__name", "description"))
        ticket_type = text(request.GET.get("type"))
        status = text(request.GET.get("status"))
        project_id = text(request.GET.get("projectId"))
        if project_id:
            rows = rows.filter(project_id=_bounded_int(project_id, "项目", minimum=1))
        if ticket_type:
            rows = rows.filter(ticket_type=ticket_type)
        if status:
            rows = rows.filter(status=status)
        return _paginated(rows, request, lambda item: _serialize_ticket(request, item))

    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        project_id = _bounded_int(payload.get("projectId"), "项目", minimum=1)
        project, provider, is_admin, failure = _project_access(request, project_id)
        if failure is not None:
            return failure
        node = None
        node_key = text(payload.get("nodeKey")) or project.current_node_key
        if node_key:
            node = ProjectNode.objects.filter(project=project, node_key=node_key).first()
            if node is None:
                raise DomainValidationError("项目节点不存在", code="PROJECT_NODE_NOT_FOUND", status=404)
        if not is_admin and not _provider_can_operate_node(provider, project, node_key):
            return _error("当前节点未指派给你", status=403, code="PROJECT_NODE_NOT_ASSIGNED")
        owner_user_id = _optional_text(payload, "ownerUserId", "处理人ID", max_length=64)
        ticket = create_ticket_record(request, {
            "code": _optional_text(payload, "code", "工单编号", max_length=40) or generated_code("TK"),
            "project": project,
            "node": node,
            "title": _required_text(payload, "title", "工单标题"),
            "ticket_type": _required_text(payload, "ticketType", "问题类型", max_length=64),
            "priority": _choice(
                payload.get("priority"),
                ServiceTicket.PRIORITY_CHOICES,
                "优先级",
                default=ServiceTicket.PRIORITY_MEDIUM,
            ),
            "status": ServiceTicket.STATUS_ASSIGNED if owner_user_id else ServiceTicket.STATUS_OPEN,
            "owner_user_id": owner_user_id,
            "owner_name": _optional_text(payload, "ownerName", "处理人", max_length=128),
            "description": _required_text(payload, "description", "工单描述", max_length=10_000),
            "business_data": _json_dict(payload.get("businessData"), "工单业务数据"),
        })
    except DomainValidationError as exc:
        return _domain_error(exc)
    except IntegrityError:
        return _error("工单编号已存在", status=409, code="TICKET_CODE_CONFLICT")
    ticket = ServiceTicket.objects.select_related("project", "node").prefetch_related("messages").get(pk=ticket.pk)
    return JsonResponse({"ok": True, "item": _serialize_ticket(request, ticket, detail=True)}, status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def ticket_item(request, ticket_id: int):
    rows, _provider, failure = _visible_tickets(request)
    if failure is not None:
        return failure
    try:
        ticket = rows.prefetch_related("messages").get(pk=ticket_id)
    except ServiceTicket.DoesNotExist:
        return _error("工单不存在或无权访问", status=404, code="TICKET_NOT_FOUND")
    if request.method == "GET":
        return JsonResponse({"item": _serialize_ticket(request, ticket, detail=True)})
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        fields = {}
        if "title" in payload:
            fields["title"] = _required_text(payload, "title", "工单标题")
        if "ticketType" in payload:
            fields["ticket_type"] = _required_text(payload, "ticketType", "问题类型", max_length=64)
        if "priority" in payload:
            fields["priority"] = _choice(payload.get("priority"), ServiceTicket.PRIORITY_CHOICES, "优先级")
        text_fields = {
            "ownerUserId": ("owner_user_id", "处理人ID", 64),
            "ownerName": ("owner_name", "处理人", 128),
            "description": ("description", "工单描述", 10_000),
        }
        for source, (target, label, limit) in text_fields.items():
            if source in payload:
                parser = _required_text if source == "description" else _optional_text
                fields[target] = parser(payload, source, label, max_length=limit)
        if "businessData" in payload:
            fields["business_data"] = _json_dict(payload.get("businessData"), "工单业务数据")
        with transaction.atomic():
            ticket = ServiceTicket.objects.select_for_update().get(pk=ticket_id)
            if ticket.status == ServiceTicket.STATUS_COMPLETED:
                raise DomainValidationError("已完成工单不能编辑", code="TICKET_EDIT_LOCKED", status=409)
            before = {field: getattr(ticket, field) for field in fields}
            for field, value in fields.items():
                setattr(ticket, field, value)
            touch_audit(ticket, request)
            ticket.save()
            record_project_event(
                request,
                ticket.project,
                node=ticket.node,
                event_type="ticket_updated",
                title=f"更新工单：{ticket.title}",
                before={key: str(value or "") for key, value in before.items()},
                after={key: str(value or "") for key, value in fields.items()},
            )
    except ServiceTicket.DoesNotExist:
        return _error("工单不存在", status=404, code="TICKET_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    ticket = ServiceTicket.objects.select_related("project", "node").prefetch_related("messages").get(pk=ticket_id)
    return JsonResponse({"ok": True, "item": _serialize_ticket(request, ticket, detail=True)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def ticket_messages(request, ticket_id: int):
    rows, _provider, failure = _visible_tickets(request)
    if failure is not None:
        return failure
    try:
        ticket = rows.get(pk=ticket_id)
    except ServiceTicket.DoesNotExist:
        return _error("工单不存在或无权访问", status=404, code="TICKET_NOT_FOUND")
    if request.method == "GET":
        return JsonResponse({"items": [
            {
                "id": row.id,
                "authorUserId": row.author_user_id,
                "authorName": row.author_name,
                "actorUserId": row.actor_user_id,
                "messageType": row.message_type,
                "content": row.content,
                "statusSnapshot": row.status_snapshot,
                "createdAt": row.created_at.isoformat(),
            }
            for row in ticket.messages.all()
        ]})
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        content = _required_text(payload, "content", "消息内容", max_length=10_000)
    except DomainValidationError as exc:
        return _domain_error(exc)
    identity = request_identity(request)
    message = TicketMessage.objects.create(
        ticket=ticket,
        author_user_id=identity["user_id"],
        author_name=identity["user_name"],
        actor_user_id=identity["actor_id"],
        message_type="text",
        content=content,
        status_snapshot=ticket.status,
    )
    return JsonResponse({
        "ok": True,
        "item": {
            "id": message.id,
            "authorUserId": message.author_user_id,
            "authorName": message.author_name,
            "actorUserId": message.actor_user_id,
            "messageType": message.message_type,
            "content": message.content,
            "statusSnapshot": message.status_snapshot,
            "createdAt": message.created_at.isoformat(),
        },
    }, status=201)


@csrf_exempt
@require_POST
def ticket_transition(request, ticket_id: int):
    rows, provider, failure = _visible_tickets(request)
    if failure is not None:
        return failure
    try:
        ticket = rows.get(pk=ticket_id)
    except ServiceTicket.DoesNotExist:
        return _error("工单不存在或无权访问", status=404, code="TICKET_NOT_FOUND")
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        next_status = _choice(payload.get("status"), ServiceTicket.STATUS_CHOICES, "工单状态")
        ticket = transition_ticket(
            request,
            ticket.id,
            next_status=next_status,
            note=_optional_text(payload, "note", "流转说明", max_length=10_000),
            is_admin=provider is None,
        )
    except DomainValidationError as exc:
        return _domain_error(exc)
    ticket = ServiceTicket.objects.select_related("project", "node").prefetch_related("messages").get(pk=ticket.pk)
    return JsonResponse({"ok": True, "item": _serialize_ticket(request, ticket, detail=True)})


@csrf_exempt
@require_POST
def ratings_collection(request):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        service_rating = create_service_rating(
            request,
            project_id=_bounded_int(payload.get("projectId"), "项目", minimum=1),
            node_key=_required_text(payload, "nodeKey", "项目节点", max_length=64),
            provider_id=_bounded_int(payload.get("providerId"), "服务人员", minimum=1),
            rating=_bounded_int(payload.get("rating"), "服务评分", minimum=1, maximum=5),
        )
    except DomainValidationError as exc:
        return _domain_error(exc)
    service_rating = ServiceRating.objects.select_related(
        "assignment__project",
        "assignment__node",
        "assignment__provider",
    ).get(pk=service_rating.pk)
    return JsonResponse({"ok": True, "item": serialize_service_rating(service_rating)}, status=201)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def feedback_collection(request):
    is_admin, failure = _admin_status(request)
    if failure is not None:
        return failure
    current_provider = _current_provider(request)
    provider = None if is_admin else current_provider
    if not is_admin and provider is None:
        return _error("当前账号未建立服务人员档案", status=403, code="SERVICE_PROVIDER_REQUIRED")
    if request.method == "GET":
        rows = FieldFeedback.objects.select_related("project", "node", "provider")
        if provider is not None:
            rows = rows.filter(provider=provider)
        else:
            projects, _provider, failure = _visible_projects(request)
            if failure is not None:
                return failure
            rows = rows.filter(project__in=access.scope_projects(request, projects))
        feedback_type = text(request.GET.get("type"))
        if feedback_type:
            rows = rows.filter(feedback_type=feedback_type)
        else:
            rows = rows.exclude(feedback_type=FieldFeedback.TYPE_REPORT)
        search = _search_filter(request)
        if search:
            rows = filter_queryset_search(rows, search, ("title", "content", "project__name", "provider__name"))
        status = text(request.GET.get("status"))
        project_id = text(request.GET.get("projectId"))
        if project_id:
            rows = rows.filter(project_id=_bounded_int(project_id, "项目", minimum=1))
        if status:
            rows = rows.filter(status=status)
        return _paginated(rows, request, serialize_feedback)

    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        project_id = _bounded_int(payload.get("projectId"), "项目", minimum=1)
        project, access_provider, access_admin, access_failure = _project_access(request, project_id)
        if access_failure is not None:
            return access_failure
        target_provider = current_provider
        if access_admin and payload.get("providerId") not in (None, ""):
            target_provider = ServiceProvider.objects.filter(pk=_bounded_int(payload.get("providerId"), "服务人员", minimum=1)).first()
            if target_provider is None:
                raise DomainValidationError("服务人员不存在", code="PROVIDER_NOT_FOUND", status=404)
        if target_provider is None:
            raise DomainValidationError("请选择服务人员", code="PROVIDER_REQUIRED")
        node_key = text(payload.get("nodeKey")) or project.current_node_key
        node = ProjectNode.objects.filter(project=project, node_key=node_key).first()
        if node is None:
            raise DomainValidationError("项目节点不存在", code="PROJECT_NODE_NOT_FOUND", status=404)
        if not access_admin and not _provider_can_operate_node(access_provider, project, node_key):
            return _error("当前节点未指派给你", status=403, code="PROJECT_NODE_NOT_ASSIGNED")
        feedback_type = _choice(payload.get("feedbackType"), FieldFeedback.TYPE_CHOICES, "反馈类型")
        content = _required_text(payload, "content", "反馈内容", max_length=20_000)
        feedback = create_feedback_record(request, {
            "project": project,
            "node": node,
            "provider": target_provider,
            "title": _optional_text(payload, "title", "反馈标题", max_length=255) or content[:80],
            "feedback_type": feedback_type,
            "content": content,
            "rating": None,
            "business_data": _json_dict(payload.get("businessData"), "反馈业务数据"),
        })
    except DomainValidationError as exc:
        return _domain_error(exc)
    feedback = FieldFeedback.objects.select_related("project", "node", "provider").get(pk=feedback.pk)
    return JsonResponse({"ok": True, "item": serialize_feedback(feedback)}, status=201)


@csrf_exempt
@require_POST
def feedback_review(request, feedback_id: int):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        decision = _choice(payload.get("status") or payload.get("decision"), FieldFeedback.STATUS_CHOICES, "审核结果")
        reward_data = _json_dict(payload.get("reward"), "奖励数据")
        if reward_data and not access.manages_service(request):
            return _error("配置反馈奖励需要服务管理员或系统管理员权限", status=403, code="SERVICE_PERMISSION_REQUIRED")
        reward_values = {
            "code": text(reward_data.get("code")),
            "reward_type": _choice(reward_data.get("rewardType"), CREATABLE_REWARD_TYPES, "奖励类型", default=Reward.TYPE_PRIZE),
            "title": text(reward_data.get("title")),
            "description": text(reward_data.get("description")),
            "amount": _decimal_value(reward_data.get("amount"), "奖励金额") if "amount" in reward_data else None,
            "prize": text(reward_data.get("prize")),
            "prize_id": reward_data.get("prizeId"),
        }
        if _bounded_int(reward_data.get("points"), "奖励积分"):
            raise DomainValidationError("积分奖励已停用", code="INVALID_CHOICE")
        feedback, reward = review_feedback(
            request,
            feedback_id,
            decision=decision,
            review_note=_optional_text(payload, "reviewNote", "审核说明", max_length=10_000),
            reward_values=reward_values,
        )
    except FieldFeedback.DoesNotExist:
        return _error("反馈不存在", status=404, code="FEEDBACK_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    feedback = FieldFeedback.objects.select_related("project", "node", "provider").get(pk=feedback.pk)
    if reward:
        reward = Reward.objects.select_related("provider", "project").get(pk=reward.pk)
    return JsonResponse({
        "ok": True,
        "item": serialize_feedback(feedback),
        "reward": serialize_reward(reward) if reward else None,
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def rewards_collection(request):
    is_admin, failure = _admin_status(request)
    if failure is not None:
        return failure
    if is_admin:
        denied = _ensure_service_manager(request)
        if denied is not None:
            return denied
    provider = None if is_admin else _current_provider(request)
    if not is_admin and provider is None:
        return _error("当前账号未建立服务人员档案", status=403, code="SERVICE_PROVIDER_REQUIRED")
    if request.method == "GET":
        rows = Reward.objects.select_related("provider", "project")
        if provider is not None:
            rows = rows.filter(provider=provider)
        else:
            projects, _provider, failure = _visible_projects(request)
            if failure is not None:
                return failure
            allowed = Q(project__in=projects)
            if access.manages_business(request):
                allowed |= Q(project__isnull=True)
            rows = rows.filter(allowed)
        search = _search_filter(request)
        if search:
            rows = filter_queryset_search(rows, search, ("code", "title", "provider__name", "project__name"))
        reward_type = text(request.GET.get("type"))
        status = text(request.GET.get("status"))
        if reward_type:
            rows = rows.filter(reward_type=reward_type)
        if status:
            rows = rows.filter(status=status)
        return _paginated(rows, request, serialize_reward)
    denied = _ensure_service_manager(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        if _bounded_int(payload.get("points"), "奖励积分"):
            raise DomainValidationError("积分奖励已停用", code="INVALID_CHOICE")
        target_provider = ServiceProvider.objects.filter(pk=_bounded_int(payload.get("providerId"), "服务人员", minimum=1)).first()
        if target_provider is None:
            raise DomainValidationError("服务人员不存在", code="PROVIDER_NOT_FOUND", status=404)
        project = None
        if payload.get("projectId") not in (None, ""):
            project = ServiceProject.objects.filter(pk=_bounded_int(payload.get("projectId"), "项目", minimum=1)).first()
            if project is None:
                raise DomainValidationError("项目不存在", code="PROJECT_NOT_FOUND", status=404)
            assert_crm_project_access(request, project, write=True)
        reward_type = _choice(payload.get("rewardType"), CREATABLE_REWARD_TYPES, "奖励类型", default=Reward.TYPE_PRIZE)
        selected_prize = resolve_active_prize(payload.get("prizeId")) if reward_type == Reward.TYPE_PRIZE else None
        reward = Reward.objects.create(
            code=_optional_text(payload, "code", "奖励编号", max_length=40) or generated_code("RW"),
            provider=target_provider,
            project=project,
            reward_type=reward_type,
            title=_required_text(payload, "title", "奖励名称"),
            description=_optional_text(payload, "description", "奖励说明", max_length=10_000),
            amount=_decimal_value(payload.get("amount"), "奖励金额"),
            points=0,
            prize=selected_prize.name if selected_prize else _optional_text(payload, "prize", "奖品", max_length=255),
            status=Reward.STATUS_PENDING,
            **create_audit_fields(request),
        )
    except DomainValidationError as exc:
        return _domain_error(exc)
    except IntegrityError:
        return _error("奖励编号已存在", status=409, code="REWARD_CODE_CONFLICT")
    reward = Reward.objects.select_related("provider", "project").get(pk=reward.pk)
    return JsonResponse({"ok": True, "item": serialize_reward(reward)}, status=201)


@require_GET
def reward_prize_options(request):
    denied = _ensure_service_manager(request)
    if denied is not None:
        return denied
    return JsonResponse({"items": [
        {"id": prize.id, "name": prize.name}
        for prize in RewardPrize.objects.filter(enabled=True)
    ]})


@csrf_exempt
@require_POST
def reward_transition(request, reward_id: int):
    denied = _ensure_service_manager(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        reward = transition_reward(
            request,
            reward_id,
            next_status=_choice(payload.get("status"), Reward.STATUS_CHOICES, "奖励状态"),
            note=_optional_text(payload, "note", "流转说明", max_length=10_000),
        )
    except Reward.DoesNotExist:
        return _error("奖励不存在", status=404, code="REWARD_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    reward = Reward.objects.select_related("provider", "project").get(pk=reward.pk)
    return JsonResponse({"ok": True, "item": serialize_reward(reward)})


def _validate_settlement_source_node(node: ProjectNode) -> None:
    supported = False
    if node.project.service_type == ServiceProject.TYPE_MIDSALES:
        supported = node.node_key in MIDSALES_SETTLEMENT_NODE_KEYS
    elif node.project.service_type == ServiceProject.TYPE_AFTERSALES:
        supported = node.node_key in {"onsite-service", "mail-service", "school-inspection"}
    if not node.enabled or not supported:
        raise DomainValidationError(
            "该节点不是可结算收费节点",
            code="SETTLEMENT_SOURCE_NOT_CHARGEABLE",
            status=409,
        )
    if node.status != ProjectNode.STATUS_COMPLETED and not (
        node.status == ProjectNode.STATUS_ACTIVE and field_completion_submitted(node)
    ):
        raise DomainValidationError(
            "来源节点尚未提交现场完工，不能生成结算",
            code="SETTLEMENT_SOURCE_NOT_COMPLETED",
            status=409,
        )
    if node.actual_fee is None or node.actual_fee <= 0:
        raise DomainValidationError(
            "来源节点尚未填写有效实际费用",
            code="SETTLEMENT_SOURCE_FEE_REQUIRED",
            status=409,
        )


def _settlement_external_quote(node: ProjectNode) -> Decimal | None:
    values = node.business_data if isinstance(node.business_data, dict) else {}
    raw = values.get("externalQuote", values.get("external_quote"))
    if raw in (None, ""):
        return None
    try:
        amount = Decimal(str(raw).replace(",", "").replace("￥", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() and 0 < amount < Decimal("10000000000") else None


def _settlement_source_content(node: ProjectNode) -> str:
    return f"{node.name}：{node.description}" if node.description else node.name


def _settlement_source_fields(payload: dict) -> dict:
    raw_node_id = payload.get("sourceNodeId", payload.get("nodeId"))
    node_key = text(payload.get("sourceNodeKey") or payload.get("nodeKey"))
    project_id = None
    if payload.get("projectId") not in (None, ""):
        project_id = _bounded_int(payload.get("projectId"), "项目", minimum=1)
    nodes = ProjectNode.objects.select_for_update().select_related("project").filter(
        project__deleted_at__isnull=True,
    )
    if raw_node_id not in (None, ""):
        nodes = nodes.filter(pk=_bounded_int(raw_node_id, "来源节点", minimum=1))
    elif project_id and node_key:
        nodes = nodes.filter(project_id=project_id, node_key=node_key)
    else:
        raise DomainValidationError(
            "必须选择来源收费节点",
            code="SETTLEMENT_SOURCE_REQUIRED",
        )
    node = nodes.first()
    if node is None:
        raise DomainValidationError(
            "来源节点不存在",
            code="SETTLEMENT_SOURCE_NOT_FOUND",
            status=404,
        )
    if project_id is not None and node.project_id != project_id:
        raise DomainValidationError(
            "来源节点不属于所选项目",
            code="SETTLEMENT_SOURCE_PROJECT_MISMATCH",
            status=409,
        )
    _validate_settlement_source_node(node)

    assignment = None
    raw_assignment_id = payload.get("sourceAssignmentId", payload.get("assignmentId"))
    if raw_assignment_id not in (None, ""):
        assignment = ProjectAssignment.objects.select_for_update().select_related("provider").filter(
            pk=_bounded_int(raw_assignment_id, "来源指派", minimum=1),
        ).first()
        if assignment is None:
            raise DomainValidationError(
                "来源指派不存在",
                code="SETTLEMENT_SOURCE_ASSIGNMENT_NOT_FOUND",
                status=404,
            )
        if assignment.project_id != node.project_id or assignment.node_id != node.id:
            raise DomainValidationError(
                "来源指派不属于所选节点",
                code="SETTLEMENT_SOURCE_ASSIGNMENT_MISMATCH",
                status=409,
            )
        if assignment.status != ProjectAssignment.STATUS_COMPLETED:
            raise DomainValidationError(
                "来源指派尚未完成，不能生成结算",
                code="SETTLEMENT_SOURCE_ASSIGNMENT_NOT_COMPLETED",
                status=409,
            )

    if Settlement.objects.filter(source_node=node).exclude(status=Settlement.STATUS_CANCELLED).exists():
        raise DomainValidationError(
            "该收费节点已有结算记录，请在未结算服务中打开原记录后确认结清",
            code="SETTLEMENT_SOURCE_CONFLICT",
            status=409,
        )
    if assignment and Settlement.objects.filter(source_assignment=assignment).exclude(
        status=Settlement.STATUS_CANCELLED,
    ).exists():
        raise DomainValidationError(
            "该来源指派已有结算记录，请在未结算服务中打开原记录后确认结清",
            code="SETTLEMENT_SOURCE_CONFLICT",
            status=409,
        )
    return {"project": node.project, "source_node": node, "source_assignment": assignment}


def _settlement_fields(payload: dict, *, creating: bool, current: Settlement | None = None) -> dict:
    fields = {}
    if creating:
        fields.update(_settlement_source_fields(payload))
        node = fields["source_node"]
        project = fields["project"]
        bearer = _choice(payload.get("bearer"), Settlement.BEARER_CHOICES, "费用承担方")
        actual_amount = node.actual_fee.quantize(Decimal("0.01"))
        budget_amount = (node.estimated_fee or Decimal("0")).quantize(Decimal("0.01"))
        external_quote = _settlement_external_quote(node)
        if bearer == Settlement.BEARER_CUSTOMER and external_quote is None:
            raise DomainValidationError(
                "客户承担结算前，请先在来源节点的费用信息中填写有效对外报价",
                code="SETTLEMENT_SOURCE_QUOTE_REQUIRED",
                status=409,
            )
        order_amount = external_quote if bearer == Settlement.BEARER_CUSTOMER else actual_amount
        invoice_due_amount = order_amount if bearer == Settlement.BEARER_CUSTOMER else Decimal("0")
        derived_amounts = {
            "budgetAmount": budget_amount,
            "finalAmount": actual_amount,
            "orderAmount": order_amount,
            "invoiceDueAmount": invoice_due_amount,
        }
        for key, derived in derived_amounts.items():
            if key in payload and payload.get(key) not in (None, ""):
                supplied = _decimal_value(payload.get(key), key, default=Decimal("0"))
                if supplied != derived:
                    raise DomainValidationError(
                        "结算金额必须与来源节点费用一致",
                        code="SETTLEMENT_SOURCE_AMOUNT_MISMATCH",
                        status=409,
                    )
        fields.update({
            "service_type": project.service_type,
            "customer": project.customer,
            "bearer": bearer,
            "service_content": _settlement_source_content(node),
            "budget_amount": budget_amount,
            "final_amount": actual_amount,
            "order_amount": order_amount,
            "external_quote": external_quote,
            "invoice_due_amount": invoice_due_amount,
            "code": _optional_text(payload, "code", "结算编号", max_length=40) or generated_code("SET"),
        })
    else:
        immutable_fields = {
            "projectId", "sourceNodeId", "sourceNodeKey", "nodeId", "nodeKey",
            "sourceAssignmentId", "assignmentId", "bearer", "serviceContent",
            "budgetAmount", "finalAmount", "orderAmount", "invoiceDueAmount", "externalQuote",
        }
        if immutable_fields.intersection(payload):
            raise DomainValidationError(
                "结算来源及其费用快照不能修改",
                code="SETTLEMENT_SOURCE_IMMUTABLE",
                status=409,
            )

    for source, target in {
        "receivedAmount": "received_amount",
        "invoicedAmount": "invoiced_amount",
    }.items():
        if source in payload:
            try:
                raw_amount = Decimal(str(payload.get(source) or "0"))
                if not raw_amount.is_finite() or not 0 <= raw_amount < Decimal("10000000000"):
                    raise InvalidOperation
            except (InvalidOperation, ValueError, TypeError):
                raise DomainValidationError("财务金额必须是有效的非负金额，且小于 100 亿元", code="INVALID_NUMBER")
            fields[target] = _decimal_value(payload.get(source), source, default=Decimal("0"))
    text_fields = {
        "invoiceType": ("invoice_type", "发票类型", 64),
        "invoiceNumber": ("invoice_number", "发票号码", 128),
        "subjectType": ("subject_type", "结算主体类型", 32),
        "subjectName": ("subject_name", "结算主体", 255),
        "subjectId": ("subject_id", "结算主体 ID", 64),
        "remark": ("remark", "结算说明", 10_000),
    }
    for source, (target, label, limit) in text_fields.items():
        if source in payload:
            fields[target] = _optional_text(payload, source, label, max_length=limit)
    if "relatedProjectId" in payload:
        related_project_id = payload.get("relatedProjectId")
        if related_project_id in (None, ""):
            fields["related_project"] = None
        else:
            related_project = ServiceProject.objects.filter(
                pk=_bounded_int(related_project_id, "关联项目", minimum=1),
                deleted_at__isnull=True,
            ).first()
            if related_project is None:
                raise DomainValidationError("关联项目不存在", code="RELATED_PROJECT_NOT_FOUND", status=404)
            if related_project.service_type == ServiceProject.TYPE_PRESALES:
                raise DomainValidationError("售前项目不参与服务结算", code="SETTLEMENT_PRESALES_NOT_SUPPORTED", status=409)
            fields["related_project"] = related_project
    if creating:
        fields.setdefault("received_amount", Decimal("0"))
        fields.setdefault("invoiced_amount", Decimal("0"))
    order_amount = fields.get("order_amount", current.order_amount if current else Decimal("0"))
    invoice_due_amount = fields.get(
        "invoice_due_amount",
        current.invoice_due_amount if current else Decimal("0"),
    )
    received_amount = fields.get(
        "received_amount",
        current.received_amount if current else Decimal("0"),
    )
    invoiced_amount = fields.get(
        "invoiced_amount",
        current.invoiced_amount if current else Decimal("0"),
    )
    if received_amount > order_amount:
        raise DomainValidationError(
            "已收金额不能超过订单金额",
            code="SETTLEMENT_RECEIVED_AMOUNT_EXCEEDED",
            status=409,
        )
    if invoiced_amount > invoice_due_amount:
        raise DomainValidationError(
            "已开票金额不能超过应开票金额",
            code="SETTLEMENT_INVOICED_AMOUNT_EXCEEDED",
            status=409,
        )
    if fields.get("bearer", current.bearer if current else "") == Settlement.BEARER_COMPANY and (received_amount or invoiced_amount):
        raise DomainValidationError("公司承担不记录客户收款或开票", code="SETTLEMENT_COMPANY_FINANCE_INVALID")
    return fields


def _serialize_settlement_source(node: ProjectNode) -> dict:
    active_settlement = next(
        (row for row in node.settlements.all() if row.status != Settlement.STATUS_CANCELLED),
        None,
    )
    completed_assignments = [
        row for row in node.assignments.all()
        if row.status == ProjectAssignment.STATUS_COMPLETED
    ]
    return {
        "id": node.id,
        "sourceNodeId": node.id,
        "nodeKey": node.node_key,
        "nodeName": node.name,
        "projectId": node.project_id,
        "projectCode": node.project.code,
        "projectName": node.project.name,
        "serviceType": node.project.service_type,
        "serviceTypeLabel": node.project.get_service_type_display(),
        "customer": node.project.customer,
        "ownerName": node.project.owner_name,
        "projectOwnerName": node.project.owner_name,
        "serviceContent": _settlement_source_content(node),
        "estimatedFee": format(node.estimated_fee, "f") if node.estimated_fee is not None else "",
        "actualFee": format(node.actual_fee, "f") if node.actual_fee is not None else "",
        "externalQuote": format(_settlement_external_quote(node), "f") if _settlement_external_quote(node) else "",
        "available": active_settlement is None,
        "settlementId": active_settlement.id if active_settlement else None,
        "settlementStatus": active_settlement.status if active_settlement else "available",
        "assignmentOptions": [
            {
                "id": row.id,
                "sourceAssignmentId": row.id,
                "providerId": row.provider_id,
                "providerName": row.provider.name,
                "role": row.role,
                "status": row.status,
            }
            for row in completed_assignments
        ],
    }


@require_GET
def settlement_sources(request):
    from .settlement_finance import settlement_workspace
    return settlement_workspace(request)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def settlements_collection(request):
    from .settlement_finance import record_finance_event, validate_subject
    denied = _ensure_finance_manager(request)
    if denied is not None:
        return denied
    if request.method == "POST":
        payload = _body(request)
        if payload is None:
            return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
        try:
            with transaction.atomic():
                fields = _settlement_fields(payload, creating=True)
                validate_subject(fields)
                next_status = _choice(payload.get("status"), Settlement.STATUS_CHOICES, "结算状态", default="draft")
                if next_status == "cancelled":
                    raise DomainValidationError("新记录不能直接撤销", code="INVALID_SETTLEMENT_TRANSITION")
                if next_status == "settled" and fields["bearer"] == "customer" and fields["received_amount"] < fields["order_amount"]:
                    raise DomainValidationError("收款未齐，请先保存待结算记录", code="SETTLEMENT_RECEIPT_INCOMPLETE", status=409)
                fields["status"] = next_status
                for project_field in ("project", "related_project"):
                    if fields.get(project_field):
                        assert_crm_project_access(request, fields[project_field], write=True)
                if Settlement.objects.filter(code=fields["code"]).exists():
                    raise DomainValidationError(
                        "结算编号已存在",
                        code="SETTLEMENT_CODE_CONFLICT",
                        status=409,
                    )
                settlement = Settlement.objects.create(
                    **fields,
                    **create_audit_fields(request),
                )
                record_finance_event(settlement, request, kind="created")
                result = serialize_settlement(settlement, detail=True)
        except DomainValidationError as exc:
            return _domain_error(exc)
        except IntegrityError:
            return _error("结算编号或来源已存在", status=409, code="SETTLEMENT_CONFLICT")
        return JsonResponse({"ok": True, "item": result}, status=201)
    rows = Settlement.objects.exclude(project__service_type=ServiceProject.TYPE_PRESALES).exclude(
        service_type=ServiceProject.TYPE_PRESALES,
    ).select_related("project", "related_project", "source_node", "source_assignment__provider")
    try:
        rows = scope_crm_queryset(request, rows, "project__")
        rows = scope_crm_queryset(request, rows, "related_project__")
    except DomainValidationError as exc:
        return _domain_error(exc)
    search = _search_filter(request)
    if search:
        rows = filter_queryset_search(rows, search, ("code", "customer", "project__name", "service_content"))
    service_type = text(request.GET.get("type"))
    status = text(request.GET.get("status"))
    if service_type:
        rows = rows.filter(service_type=service_type)
    if status:
        rows = rows.filter(status=status)
    source_node_id = text(request.GET.get("sourceNodeId"))
    if source_node_id:
        try:
            rows = rows.filter(source_node_id=_bounded_int(source_node_id, "来源节点", minimum=1))
        except DomainValidationError as exc:
            return _domain_error(exc)
    return _paginated(rows, request, serialize_settlement)


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def settlement_item(request, settlement_id: int):
    from .settlement_finance import finance_snapshot, record_finance_event, validate_subject
    denied = _ensure_finance_manager(request)
    if denied is not None:
        return denied
    try:
        settlement = Settlement.objects.select_related(
            "project", "related_project", "source_node", "source_assignment__provider",
        ).get(pk=settlement_id)
        for project in (settlement.project, settlement.related_project):
            if project:
                assert_crm_project_access(request, project, write=request.method != "GET")
    except Settlement.DoesNotExist:
        return _error("结算记录不存在", status=404, code="SETTLEMENT_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    if request.method == "GET":
        return JsonResponse({"item": serialize_settlement(settlement, detail=True)})
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        with transaction.atomic():
            settlement = Settlement.objects.select_for_update().get(pk=settlement_id)
            for project in (settlement.project, settlement.related_project):
                if project:
                    assert_crm_project_access(request, project, write=True)
            if settlement.status == Settlement.STATUS_CANCELLED:
                raise DomainValidationError(
                    "已结束的结算记录不能修改",
                    code="SETTLEMENT_LOCKED",
                    status=409,
                )
            if "expectedRevision" not in payload:
                raise DomainValidationError("缺少结算版本，请刷新记录后重试", code="SETTLEMENT_REVISION_REQUIRED", status=409)
            expected = _bounded_int(payload.get("expectedRevision"), "结算版本", minimum=1)
            if expected != settlement.revision:
                raise DomainValidationError("此记录已被其他人更新。当前填写内容已保留，请先加载最新记录并核对。", code="SETTLEMENT_REVISION_CONFLICT", status=409)
            before = finance_snapshot(settlement)
            fields = _settlement_fields(payload, creating=False, current=settlement)
            if {"subjectId", "subjectType", "subjectName", "relatedProjectId"}.intersection(payload):
                validate_subject(fields, settlement)
            if fields.get("related_project"):
                assert_crm_project_access(request, fields["related_project"], write=True)
            if "status" in payload:
                next_status = _choice(payload.get("status"), Settlement.STATUS_CHOICES, "结算状态")
                if (
                    next_status == Settlement.STATUS_SETTLED
                    and settlement.bearer == Settlement.BEARER_CUSTOMER
                    and fields.get("received_amount", settlement.received_amount) < settlement.order_amount
                ):
                    received_amount = fields.get("received_amount", settlement.received_amount)
                    shortfall = (settlement.order_amount - received_amount).quantize(Decimal("0.01"))
                    raise DomainValidationError(
                        f"客户承担结算未完成：已收金额为￥{received_amount:.2f}，还需收款￥{shortfall:.2f}后才能确认结清",
                        code="SETTLEMENT_RECEIPT_INCOMPLETE",
                        status=409,
                    )
                allowed_reopen = settlement.status == "settled" and next_status in {"pending", "cancelled"}
                if next_status != settlement.status and not allowed_reopen and next_status not in SETTLEMENT_TRANSITIONS.get(settlement.status, set()):
                    status_labels = dict(Settlement.STATUS_CHOICES)
                    allowed = [status_labels.get(value, value) for value in SETTLEMENT_TRANSITIONS.get(settlement.status, set())]
                    allowed_text = "、".join(allowed) or "无"
                    raise DomainValidationError(
                        f"当前结算状态为“{status_labels.get(settlement.status, settlement.status)}”，不能变为“{status_labels.get(next_status, next_status)}”；可流转为：{allowed_text}",
                        code="INVALID_SETTLEMENT_TRANSITION",
                        status=409,
                    )
                fields["status"] = next_status
            reason = _optional_text(payload, "correctionReason", "更正原因", max_length=2000)
            reducing = any(fields.get(field, getattr(settlement, field)) < getattr(settlement, field)
                           for field in ("received_amount", "invoiced_amount"))
            reopening = settlement.status == "settled" and fields.get("status", "settled") != "settled"
            cancelling = fields.get("status") == "cancelled"
            invoice_metadata_correction = any(
                getattr(settlement, field) and fields.get(field, getattr(settlement, field)) != getattr(settlement, field)
                for field in ("invoice_type", "invoice_number")
            ) and fields.get("invoiced_amount", settlement.invoiced_amount) <= settlement.invoiced_amount
            settled_change = settlement.status == "settled" and any(
                key not in {"invoice_type", "invoice_number", "invoiced_amount"} and value != getattr(settlement, key)
                for key, value in fields.items()
            )
            needs_reason = reducing or reopening or cancelling or settled_change or invoice_metadata_correction
            if needs_reason and not reason:
                raise DomainValidationError("更正或撤销结算记录需要填写原因", code="SETTLEMENT_CORRECTION_REASON_REQUIRED")
            if cancelling and (fields.get("received_amount", settlement.received_amount) or fields.get("invoiced_amount", settlement.invoiced_amount)):
                raise DomainValidationError("记录仍有收款或开票余额，请先更正冲回后再撤销", code="SETTLEMENT_CANCEL_HAS_BALANCE", status=409)
            if settlement.status == "settled" and fields.get("status", "settled") == "settled" and settlement.bearer == "customer" and fields.get("received_amount", settlement.received_amount) < settlement.order_amount:
                raise DomainValidationError("更正后未收齐款项，请同时恢复为待结算", code="SETTLEMENT_REOPEN_REQUIRED", status=409)
            for field, value in fields.items():
                setattr(settlement, field, value)
            if finance_snapshot(settlement) != before:
                settlement.revision += 1
                touch_audit(settlement, request)
                settlement.save()
                kind = "cancelled" if cancelling else "correction" if needs_reason else "invoice" if settlement.invoiced_amount != Decimal(before["invoiced_amount"]) else "receipt" if settlement.received_amount != Decimal(before["received_amount"]) else "update"
                record_finance_event(settlement, request, before, reason=reason, kind=kind)
            result = serialize_settlement(settlement, detail=True)
    except DomainValidationError as exc:
        return _domain_error(exc)
    return JsonResponse({"ok": True, "item": result})


def _resource_fields(payload: dict, *, creating: bool, current: ServiceResource | None = None) -> dict:
    fields = {}
    project = current.project if current else None
    if creating or "projectId" in payload:
        project = None
        if payload.get("projectId") not in (None, ""):
            project = ServiceProject.objects.filter(
                pk=_bounded_int(payload.get("projectId"), "项目", minimum=1),
                deleted_at__isnull=True,
            ).first()
            if project is None:
                raise DomainValidationError("项目不存在", code="PROJECT_NOT_FOUND", status=404)
        fields["project"] = project
    node_key = current.node_key if current else ""
    if creating or "nodeKey" in payload:
        node_key = _optional_text(payload, "nodeKey", "节点", max_length=64)
        fields["node_key"] = node_key
    if node_key and (project is None or not ProjectNode.objects.filter(project=project, node_key=node_key).exists()):
        raise DomainValidationError("项目节点不存在", code="PROJECT_NODE_NOT_FOUND", status=404)
    if creating or "title" in payload:
        fields["title"] = _required_text(payload, "title", "资料标题")
    if creating or "resourceType" in payload:
        fields["resource_type"] = _choice(payload.get("resourceType"), ServiceResource.TYPE_CHOICES, "资料类型")
    if creating or "audience" in payload:
        fields["audience"] = _choice(
            payload.get("audience"),
            ServiceResource.AUDIENCE_CHOICES,
            "可见范围",
            default=ServiceResource.AUDIENCE_ASSIGNED,
        )
    text_fields = {
        "summary": ("summary", "资料摘要", 5000),
        "content": ("content", "资料内容", 50_000),
        "authorizationNote": ("authorization_note", "授权说明", 10_000),
    }
    for source, (target, label, limit) in text_fields.items():
        if source in payload:
            fields[target] = _optional_text(payload, source, label, max_length=limit)
    if "externalUrl" in payload:
        external_url = _optional_text(payload, "externalUrl", "外部地址", max_length=500)
        fields["external_url"] = _http_url_value(external_url, "外部地址")
    if text(payload.get("action")) == "authorize" and "note" in payload:
        fields["authorization_note"] = _optional_text(payload, "note", "授权说明", max_length=10_000)
    if "tags" in payload:
        fields["tags"] = [text(row) for row in _json_list(payload.get("tags"), "资料标签") if text(row)]
    if creating or "enabled" in payload:
        enabled = payload.get("enabled", True)
        if not isinstance(enabled, bool):
            raise DomainValidationError("启用状态必须是布尔值", code="INVALID_BOOLEAN")
        fields["enabled"] = enabled

    resulting_audience = fields.get("audience", current.audience if current else ServiceResource.AUDIENCE_ASSIGNED)
    if resulting_audience == ServiceResource.AUDIENCE_ASSIGNED and project is None:
        raise DomainValidationError("项目授权资料必须关联项目", code="RESOURCE_PROJECT_REQUIRED")
    return fields


def _visible_resources(
    *,
    is_admin: bool,
    provider: ServiceProvider | None,
    include_disabled: bool = False,
    assignment_statuses: list[str] | None = None,
):
    rows = ServiceResource.objects.select_related("project")
    if is_admin:
        return rows if include_disabled else rows.filter(enabled=True)
    rows = rows.filter(enabled=True).filter(Q(project__isnull=True) | Q(project__deleted_at__isnull=True))
    if provider is None:
        return rows.filter(audience=ServiceResource.AUDIENCE_PUBLIC)

    rows = rows.filter(Q(project__isnull=True) | ~Q(project__service_type=ServiceProject.TYPE_PRESALES))

    assignment_rows = ProjectAssignment.objects.filter(provider=provider)
    if assignment_statuses is None:
        assignment_rows = assignment_rows.exclude(status=ProjectAssignment.STATUS_CANCELLED)
    else:
        assignment_rows = assignment_rows.filter(status__in=assignment_statuses)
    assigned_node = assignment_rows.filter(
        project_id=OuterRef("project_id"),
        node__node_key=OuterRef("node_key"),
    )
    assigned_project_ids = assignment_rows.values("project_id")
    return rows.annotate(_assigned_node=Exists(assigned_node)).filter(
        Q(audience=ServiceResource.AUDIENCE_PUBLIC)
        | Q(
            audience=ServiceResource.AUDIENCE_ASSIGNED,
            node_key="",
            project_id__in=assigned_project_ids,
        )
        | Q(audience=ServiceResource.AUDIENCE_ASSIGNED, _assigned_node=True)
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def resources_collection(request):
    is_admin, failure = _admin_status(request)
    if failure is not None:
        return failure
    provider = None if is_admin else _current_provider(request)
    if request.method == "POST":
        if not is_admin:
            return _error("只有管理员可以创建服务资料", status=403, code="APP_ADMIN_REQUIRED")
        payload = _body(request)
        if payload is None:
            return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
        try:
            fields = _resource_fields(payload, creating=True)
            if fields.get("project"):
                assert_crm_project_access(request, fields["project"], write=True)
            resource = ServiceResource.objects.create(
                **fields,
                **create_audit_fields(request),
            )
        except DomainValidationError as exc:
            return _domain_error(exc)
        resource = ServiceResource.objects.select_related("project").get(pk=resource.pk)
        return JsonResponse({"ok": True, "item": serialize_resource(resource)}, status=201)

    status = text(request.GET.get("status"))
    rows = _visible_resources(is_admin=is_admin, provider=provider, include_disabled=is_admin)
    if is_admin:
        projects, _provider, failure = _visible_projects(request)
        if failure is not None:
            return failure
        rows = rows.filter(Q(project__in=projects) | Q(project__isnull=True))
    if status in {"enabled", "disabled"}:
        rows = rows.filter(enabled=status == "enabled")
    search = _search_filter(request)
    if search:
        rows = filter_queryset_search(rows, search, ("title", "summary", "content"))
    resource_type = text(request.GET.get("type"))
    if resource_type:
        rows = rows.filter(resource_type=resource_type)
    return _paginated(rows, request, serialize_resource)


@require_GET
def public_demo(request):
    resource = (
        ServiceResource.objects.filter(
            audience=ServiceResource.AUDIENCE_PUBLIC,
            enabled=True,
            project__isnull=True,
            node_key="",
        )
        .order_by("-updated_at", "-id")
        .first()
    )
    if resource is None:
        return JsonResponse({"item": None})
    item = serialize_resource(resource)
    return JsonResponse({
        "item": {
            "id": item["id"],
            "title": item["title"],
            "resourceType": item["resourceType"],
            "resourceTypeLabel": item["resourceTypeLabel"],
            "summary": item["summary"],
            "content": item["content"],
            "externalUrl": item["externalUrl"],
            "tags": item["tags"],
        }
    })


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
def resource_item(request, resource_id: int):
    is_admin, failure = _admin_status(request)
    if failure is not None:
        return failure
    provider = None if is_admin else _current_provider(request)
    if request.method == "GET":
        try:
            resource = _visible_resources(
                is_admin=is_admin,
                provider=provider,
                include_disabled=is_admin,
            ).get(pk=resource_id)
            if resource.project:
                assert_crm_project_access(request, resource.project)
        except ServiceResource.DoesNotExist:
            return _error("服务资料不存在或无权访问", status=404, code="RESOURCE_NOT_FOUND")
        except DomainValidationError as exc:
            return _domain_error(exc)
        return JsonResponse({"item": serialize_resource(resource)})

    if not is_admin:
        return _error("只有管理员可以维护服务资料", status=403, code="APP_ADMIN_REQUIRED")
    payload = _body(request) if request.method == "PATCH" else {}
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        with transaction.atomic():
            resource = ServiceResource.objects.select_for_update(of=("self",)).select_related("project").get(pk=resource_id)
            if resource.project:
                assert_crm_project_access(request, resource.project, write=True)
            if request.method == "DELETE":
                fields = {"enabled": False}
            else:
                fields = _resource_fields(payload, creating=False, current=resource)
                if fields.get("project"):
                    assert_crm_project_access(request, fields["project"], write=True)
            for field, value in fields.items():
                setattr(resource, field, value)
            touch_audit(resource, request)
            resource.save()
            if resource.project_id:
                record_project_event(
                    request,
                    resource.project,
                    event_type="resource_archived" if request.method == "DELETE" else "resource_updated",
                    title=f"维护服务资料：{resource.title}",
                    detail=resource.authorization_note,
                    after={"resourceId": resource.id, "enabled": resource.enabled, "audience": resource.audience},
                )
    except ServiceResource.DoesNotExist:
        return _error("服务资料不存在", status=404, code="RESOURCE_NOT_FOUND")
    except DomainValidationError as exc:
        return _domain_error(exc)
    return JsonResponse({"ok": True, "item": serialize_resource(resource)})


@require_GET
def employee_directory(request):
    denied = _ensure_app_admin(request)
    if denied is not None:
        return denied
    try:
        items, org_revision = _active_employee_directory()
    except AuthOrgClientError as exc:
        return _org_error(exc)
    return JsonResponse({"items": items, "orgRevision": org_revision})


def _related_product_manual_materials(assignments) -> list[dict]:
    result = []
    seen = set()
    for assignment in assignments:
        project = assignment.project
        node = assignment.node
        if project.service_type == ServiceProject.TYPE_AFTERSALES:
            rows = _related_products(project.business_data)
        elif project.service_type == ServiceProject.TYPE_MIDSALES and node.node_key in MIDSALES_RELATED_PRODUCT_NODE_KEYS:
            rows = _related_products(node.business_data)
        else:
            continue
        for product in rows:
            try:
                product_id = int(product.get("productId"))
            except (TypeError, ValueError):
                continue
            manuals = product.get("manuals") if isinstance(product.get("manuals"), list) else []
            for manual in manuals:
                if not isinstance(manual, dict) or manual.get("key") not in MANUAL_KEYS:
                    continue
                key = manual["key"]
                unique_key = (project.id, node.node_key, product_id, key)
                if unique_key in seen:
                    continue
                seen.add(unique_key)
                label = text(manual.get("label")) or "产品说明书"
                product_name = text(product.get("name")) or f"产品 {product_id}"
                product_abbr = text(product.get("abbr")) or product_name
                result.append({
                    "id": f"product-manual-{project.id}-{node.node_key}-{product_id}-{key}",
                    "projectId": project.id,
                    "projectName": project.name,
                    "nodeKey": node.node_key,
                    "productId": product_id,
                    "productName": product_name,
                    "productAbbr": product_abbr,
                    "title": f"{product_abbr} · {label}",
                    "resourceType": "product_manual",
                    "resourceTypeLabel": "产品说明书",
                    "audience": "assigned",
                    "audienceLabel": "当前项目服务人员",
                    "authorizationDisplay": "当前项目服务人员",
                    "externalUrl": (
                        f"/api/after-sales/product-catalog/{product_id}/manual/{key}?"
                        + urlencode({"projectId": project.id, "nodeKey": node.node_key})
                    ),
                    "enabled": True,
                    "status": "enabled",
                    "statusLabel": "已启用",
                })
    return result


@require_GET
def mobile_home(request):
    provider, failure = _provider_required(request)
    if failure is not None:
        return failure
    assignments = ProjectAssignment.objects.filter(
        provider=provider,
        status__in=[
            ProjectAssignment.STATUS_ASSIGNED,
            ProjectAssignment.STATUS_ACCEPTED,
            ProjectAssignment.STATUS_IN_PROGRESS,
            ProjectAssignment.STATUS_COMPLETED,
        ],
        project__deleted_at__isnull=True,
    ).exclude(
        project__service_type=ServiceProject.TYPE_PRESALES,
    ).exclude(
        node__node_key="mail-service",
    ).select_related("project", "node", "provider").prefetch_related(
        "node__settlements",
        "project__nodes",
    )
    project_ids = assignments.values_list("project_id", flat=True)
    resources = _visible_resources(
        is_admin=False,
        provider=provider,
        assignment_statuses=[
            ProjectAssignment.STATUS_ASSIGNED,
            ProjectAssignment.STATUS_ACCEPTED,
            ProjectAssignment.STATUS_IN_PROGRESS,
            ProjectAssignment.STATUS_COMPLETED,
        ],
    )[:20]
    feedback = FieldFeedback.objects.filter(provider=provider).exclude(
        feedback_type=FieldFeedback.TYPE_REPORT,
    ).select_related("project", "node", "provider")
    rewards = Reward.objects.filter(provider=provider).select_related("project", "provider")
    assignment_node_ids = assignments.values_list("node_id", flat=True)
    tickets = ServiceTicket.objects.filter(
        Q(node_id__in=assignment_node_ids)
        | Q(node_id__isnull=True, project_id__in=project_ids)
        | Q(reporter_user_id=provider.auth_user_id)
        | Q(owner_user_id=provider.auth_user_id)
    ).select_related("project", "node").distinct()
    assignment_rows = list(assignments)
    return JsonResponse({
        "ok": True,
        "profile": serialize_provider(provider),
        "tasks": [
            {
                "assignment": serialize_assignment(row),
                "project": serialize_project(row.project),
                "node": _serialize_mobile_node(row.node, row.id),
                "nodes": [
                    _serialize_compact_node(node)
                    for node in row.project.nodes.all()
                    if node.node_key != "mail-service"
                ],
            }
            for row in assignment_rows
        ],
        "resources": [serialize_resource(row) for row in resources],
        "productManuals": _related_product_manual_materials(assignment_rows),
        "feedback": [serialize_feedback(row) for row in feedback[:20]],
        "rewards": [serialize_reward(row) for row in rewards[:20]],
        "tickets": [serialize_ticket(row) for row in tickets[:20]],
        "recordCounts": {"feedback": feedback.count(), "rewards": rewards.count(),
                         "tickets": tickets.filter(reporter_user_id=provider.auth_user_id).count()},
    })


@require_GET
def mobile_records(request, record_type: str):
    provider, failure = _provider_required(request)
    if failure is not None:
        return failure
    if record_type == "feedback":
        rows = FieldFeedback.objects.filter(provider=provider).exclude(feedback_type=FieldFeedback.TYPE_REPORT)
        rows = rows.select_related("project", "node", "provider")
        serializer = serialize_feedback
    elif record_type == "tickets":
        rows, _provider, failure = _visible_tickets(request)
        if failure is not None:
            return failure
        rows = rows.filter(reporter_user_id=provider.auth_user_id)
        serializer = serialize_ticket
    elif record_type == "rewards":
        rows = Reward.objects.filter(provider=provider).select_related("project", "provider")
        serializer = serialize_reward
    else:
        return _error("记录类型不存在", status=404, code="MOBILE_RECORD_TYPE_NOT_FOUND")
    record_id = text(request.GET.get("recordId"))
    if record_id:
        if not record_id.isascii() or not record_id.isdigit() or len(record_id) > 18:
            return _error("记录不存在", status=404, code="MOBILE_RECORD_NOT_FOUND")
        rows = rows.filter(pk=int(record_id))
    return _paginated(rows.order_by("-created_at", "-id"), request, serializer)


def _permission_configuration_snapshot() -> tuple[list[dict], str]:
    with transaction.atomic():
        state, _created = AppConfigurationRevision.objects.select_for_update().get_or_create(
            key=APP_CONFIGURATION_PERMISSIONS,
            defaults={"revision": 1},
        )
        items = list_app_permission_rules()
        revision = str(max(1, int(state.revision or 1)))
    return items, revision


def _lock_configuration_revision(payload: dict):
    expected = text(payload.get("revision"))
    state, _created = AppConfigurationRevision.objects.select_for_update().get_or_create(
        key=APP_CONFIGURATION_PERMISSIONS,
        defaults={"revision": 1},
    )
    current = str(max(1, int(state.revision or 1)))
    if not expected:
        return None, _error("缺少权限配置版本，请刷新后重新编辑", status=400, code="REVISION_REQUIRED", revision=current)
    if expected != current:
        return None, _error("权限配置已被其他人修改，请刷新后重新编辑", status=409, code="REVISION_CONFLICT", revision=current)
    return state, None


def _advance_configuration_revision(state: AppConfigurationRevision) -> str:
    state.revision = max(1, int(state.revision or 1)) + 1
    state.save(update_fields=["revision", "updated_at"])
    return str(state.revision)


def _org_revision_conflict(payload: dict, current_revision: int) -> JsonResponse | None:
    expected = text(payload.get("orgRevision"))
    current = str(current_revision)
    if not expected:
        return _error("缺少组织架构版本，请刷新权限页面后再保存", status=400, code="ORG_REVISION_REQUIRED", orgRevision=current)
    if expected != current:
        return _error("组织架构已发生变化，请刷新权限页面后再保存", status=409, code="ORG_REVISION_CONFLICT", orgRevision=current)
    return None


@csrf_exempt
@require_http_methods(["GET", "POST"])
def permissions_collection(request):
    denied = _ensure_settings_admin(request)
    if denied is not None:
        return denied
    if request.method == "GET":
        items, revision = _permission_configuration_snapshot()
        return JsonResponse({"items": items, "revision": revision})
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    items = payload.get("items")
    if not isinstance(items, list):
        return _error("权限数据格式错误", status=400, code="INVALID_PERMISSION_ITEMS")
    try:
        departments, employees, org_revision = get_auth_organization_snapshot()
    except AuthOrgClientError as exc:
        return _org_error(exc)
    conflict = _org_revision_conflict(payload, org_revision)
    if conflict is not None:
        return conflict
    with transaction.atomic():
        revision_state, conflict = _lock_configuration_revision(payload)
        if conflict is not None:
            return conflict
        try:
            saved_items = replace_app_permission_rules(
                items,
                departments=departments,
                employees=employees,
                actor_user_id=getattr(request, "auth_user_id", ""),
            )
        except ValueError as exc:
            return _error(str(exc), status=400, code="INVALID_PERMISSION_RULE")
        next_revision = _advance_configuration_revision(revision_state)
    return JsonResponse({
        "ok": True,
        "items": saved_items,
        "revision": next_revision,
        "orgRevision": org_revision,
    })


@require_GET
def permission_directory(request):
    denied = _ensure_settings_admin(request)
    if denied is not None:
        return denied
    try:
        departments, employees, org_revision = get_auth_organization_snapshot()
    except AuthOrgClientError as exc:
        return _org_error(exc)
    return JsonResponse({
        "departments": build_auth_department_tree(departments),
        "roles": [],
        "employees": employees,
        "directorySource": "auth",
        "orgRevision": org_revision,
    })
