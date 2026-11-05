from __future__ import annotations

import json

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .models import (
    ApprovalApplication,
    ApprovalDraft,
    ApprovalEvent,
    ApprovalTask,
    ApprovalCategory,
    ApprovalCategoryPermission,
    ApprovalTemplate,
    ApprovalTemplateVersion,
    AppConfigurationRevision,
)
from .org_client import AuthOrgClientError, get_auth_organization_snapshot
from .permissions import (
    APP_PERMISSION_ADMIN,
    get_request_app_permission,
    get_user_category_ids,
    get_user_category_permission,
    list_category_permission_rules,
    replace_category_permission_rules,
)
from .workflow import (
    ApprovalDomainError,
    act_on_application,
    create_application,
    ensure_json_object,
    normalize_template_payload,
    publish_template,
    text,
    validate_form_schema,
    workflow_nodes,
)


MAX_DIRECTORY_ID_LENGTH = 64
MAX_DIRECTORY_NAME_LENGTH = 128
ACTIVE_EMPLOYEE_STATUSES = {"active", "在职"}
ENABLED_ACCOUNT_STATUSES = {"enabled", "启用"}


def _bounded_directory_text(value, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def _auth_employee_directories(employees: list[dict]) -> tuple[dict[str, str], dict[str, dict]]:
    names: dict[str, str] = {}
    rows: dict[str, dict] = {}
    for row in employees:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().lower()
        account_status = str(
            row.get("accountStatus") or row.get("account_status") or ""
        ).strip().lower()
        if status and status not in ACTIVE_EMPLOYEE_STATUSES:
            continue
        if account_status and account_status not in ENABLED_ACCOUNT_STATUSES:
            continue
        user_id = str(row.get("userId") or row.get("id") or "").strip()
        if not user_id or len(user_id) > MAX_DIRECTORY_ID_LENGTH:
            continue
        name = _bounded_directory_text(
            row.get("rawName") or row.get("name") or user_id,
            MAX_DIRECTORY_NAME_LENGTH,
        ) or user_id
        names[user_id] = name
        rows[user_id] = row
    return names, rows


def _auth_department_directories(
    departments: list[dict],
) -> tuple[set[str], dict[str, tuple[str, str]]]:
    accepted_values: set[str] = set()
    rows: dict[str, tuple[str, str]] = {}
    for row in departments:
        if not isinstance(row, dict):
            continue
        department_id = str(row.get("deptId") or row.get("id") or "").strip()
        if not department_id or len(department_id) > MAX_DIRECTORY_ID_LENGTH:
            continue
        name = _bounded_directory_text(
            row.get("name") or department_id,
            MAX_DIRECTORY_NAME_LENGTH,
        ) or department_id
        rows[department_id] = (department_id, name)
        accepted_values.update({department_id, name})
    return accepted_values, rows


def _primary_employee_department(
    employee: dict | None,
    departments_by_id: dict[str, tuple[str, str]],
) -> tuple[str, str]:
    if not isinstance(employee, dict):
        return "", ""
    nested = employee.get("departments")
    if isinstance(nested, list):
        for department in nested:
            if not isinstance(department, dict):
                continue
            department_id = str(department.get("deptId") or department.get("id") or "").strip()
            if not department_id or len(department_id) > MAX_DIRECTORY_ID_LENGTH:
                continue
            canonical = departments_by_id.get(department_id)
            name = canonical[1] if canonical else _bounded_directory_text(
                department.get("name") or department_id,
                MAX_DIRECTORY_NAME_LENGTH,
            )
            return department_id, name or department_id
    raw_ids = employee.get("departmentIds")
    if isinstance(raw_ids, list):
        for raw_id in raw_ids:
            department_id = str(raw_id or "").strip()
            if not department_id or len(department_id) > MAX_DIRECTORY_ID_LENGTH:
                continue
            return departments_by_id.get(department_id, (department_id, department_id))
    return "", ""


def _error(message: str, *, status: int, code: str, **extra) -> JsonResponse:
    payload = {"ok": False, "error": message, "code": code}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _domain_error(exc: ApprovalDomainError) -> JsonResponse:
    return _error(str(exc), status=exc.status, code=exc.code)


def _body(request) -> dict | None:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _user_id(request) -> str:
    return str(getattr(request, "auth_user_id", "") or "").strip()


def _user_name(request) -> str:
    return _bounded_directory_text(
        str(getattr(request, "auth_user_name", "") or "").strip()
        or _user_id(request)
        or "当前用户",
        MAX_DIRECTORY_NAME_LENGTH,
    )


def _actor_id(request) -> str:
    return (
        str(getattr(request, "auth_actor_user_id", "") or "").strip()
        or _user_id(request)
    )


def _actor_name(request) -> str:
    return _bounded_directory_text(
        str(getattr(request, "auth_actor_name", "") or "").strip()
        or _user_name(request),
        MAX_DIRECTORY_NAME_LENGTH,
    )


def _is_admin(request) -> bool:
    return get_request_app_permission(request) == APP_PERMISSION_ADMIN


def _ensure_admin(request) -> JsonResponse | None:
    try:
        admin = _is_admin(request)
    except AuthOrgClientError:
        return _error(
            "组织架构服务暂不可用，无法确认管理权限",
            status=503,
            code="AUTH_ORG_UNAVAILABLE",
        )
    if admin:
        return None
    return _error("只有审批管理员可以执行此操作", status=403, code="APP_ADMIN_REQUIRED")


def _category_revision_key(category_id: int | None = None) -> str:
    return "categories" if category_id is None else f"category_permissions:{category_id}"


def _category_revision_snapshot(category_id: int | None = None) -> str:
    state, _created = AppConfigurationRevision.objects.get_or_create(
        key=_category_revision_key(category_id),
        defaults={"revision": 1},
    )
    return str(max(1, int(state.revision or 1)))


def _category_revision_advance(category_id: int | None = None, expected: str = ""):
    state, _created = AppConfigurationRevision.objects.select_for_update().get_or_create(
        key=_category_revision_key(category_id),
        defaults={"revision": 1},
    )
    current = str(max(1, int(state.revision or 1)))
    if expected and expected != current:
        return None, _error(
            "分类配置已被其他人修改，请刷新后重试",
            status=409,
            code="REVISION_CONFLICT",
            revision=current,
        )
    state.revision = int(current) + 1
    state.save(update_fields=["revision", "updated_at"])
    return str(state.revision), None


@transaction.atomic
def _touch_category_revision() -> str:
    state, _created = AppConfigurationRevision.objects.select_for_update().get_or_create(
        key=_category_revision_key(),
        defaults={"revision": 1},
    )
    state.revision = max(1, int(state.revision or 1)) + 1
    state.save(update_fields=["revision", "updated_at"])
    return str(state.revision)


def _template_order_revision_snapshot(category_id: int) -> str:
    state, _created = AppConfigurationRevision.objects.get_or_create(
        key=f"template_order:{category_id}",
        defaults={"revision": 1},
    )
    return str(max(1, int(state.revision or 1)))


def _category_from_id(category_id, *, include_deleted: bool = False):
    try:
        parsed = int(category_id)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    queryset = ApprovalCategory.objects
    if not include_deleted:
        queryset = queryset.filter(deleted_at__isnull=True)
    return queryset.filter(pk=parsed).first()


def _category_from_payload(payload: dict, *, allow_create: bool = False, request=None):
    """Resolve categoryId/category while retaining legacy string clients."""
    raw_id = payload.get("categoryId")
    if raw_id in (None, ""):
        raw_id = payload.get("category_id")
    if raw_id not in (None, ""):
        category = _category_from_id(raw_id)
        if category is None:
            raise ApprovalDomainError("审批分类不存在", "CATEGORY_NOT_FOUND", 404)
        return category

    raw_name = str(payload.get("category") or "").strip()[:64]
    if not raw_name:
        raw_name = "通用"
    category = ApprovalCategory.objects.filter(
        name__iexact=raw_name,
        deleted_at__isnull=True,
    ).first()
    if category is not None:
        return category
    if not allow_create:
        raise ApprovalDomainError("审批分类不存在，请先创建分类", "CATEGORY_NOT_FOUND", 404)
    actor_id = _actor_id(request) if request is not None else ""
    actor_name = _actor_name(request) if request is not None else ""
    deleted_category = ApprovalCategory.objects.filter(
        name__iexact=raw_name,
        deleted_at__isnull=False,
    ).first()
    if deleted_category is not None:
        deleted_category.deleted_at = None
        deleted_category.updated_by = actor_id
        deleted_category.updated_by_name = actor_name
        deleted_category.save(update_fields=["deleted_at", "updated_by", "updated_by_name", "updated_at"])
        return deleted_category
    try:
        category = ApprovalCategory.objects.create(
            name=raw_name,
            sort_order=(
                ApprovalCategory.objects.filter(deleted_at__isnull=True)
                .order_by("-sort_order")
                .values_list("sort_order", flat=True)
                .first()
                or 0
            ) + 1,
            created_by=actor_id,
            created_by_name=actor_name,
            updated_by=actor_id,
            updated_by_name=actor_name,
        )
    except IntegrityError:
        category = ApprovalCategory.objects.filter(
            name__iexact=raw_name,
            deleted_at__isnull=True,
        ).first()
        if category is None:
            raise ApprovalDomainError("审批分类已存在", "CATEGORY_EXISTS", 409)
    return category


def _template_category(template: ApprovalTemplate):
    category = getattr(template, "category_ref", None)
    if category is not None and category.deleted_at is None:
        return category
    # Legacy rows created before category_ref was introduced are resolved by
    # their denormalized category label until the next write/migration.
    return ApprovalCategory.objects.filter(
        name__iexact=(template.category or "通用").strip()[:64] or "通用",
        deleted_at__isnull=True,
    ).first()


def _managed_category_ids(request) -> tuple[list[int] | None, JsonResponse | None]:
    """Return None for global admins, or category IDs for scoped admins."""
    try:
        if _is_admin(request):
            request._approval_is_global_admin = True
            request._approval_managed_category_ids = None
            return None, None
        ids = get_user_category_ids(_user_id(request))
        request._approval_is_global_admin = False
        request._approval_managed_category_ids = ids
    except AuthOrgClientError:
        return [], _error(
            "组织架构服务暂不可用，无法确认管理权限",
            status=503,
            code="AUTH_ORG_UNAVAILABLE",
        )
    if not ids:
        return [], _error("只有审批管理员可以执行此操作", status=403, code="APP_ADMIN_REQUIRED")
    return ids, None


def _ensure_template_admin(request, template=None, category=None) -> JsonResponse | None:
    """Authorize global admins or managers of the relevant category."""
    try:
        if _is_admin(request):
            return None
        category = category or (_template_category(template) if template is not None else None)
        if category is not None and get_user_category_permission(
            _user_id(request), category.pk,
        ) == APP_PERMISSION_ADMIN:
            return None
    except AuthOrgClientError:
        return _error(
            "组织架构服务暂不可用，无法确认管理权限",
            status=503,
            code="AUTH_ORG_UNAVAILABLE",
        )
    return _error("你没有该审批分类的管理权限", status=403, code="CATEGORY_ADMIN_REQUIRED")


def _category_order_from_payload(payload: dict, default: int = 0) -> int:
    value = payload.get("categoryOrder")
    if value is None:
        value = payload.get("sortOrder")
    if value is None:
        value = payload.get("order")
    if value is None or value == "":
        return default
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ApprovalDomainError("表单排序值必须是整数", "INVALID_SORT_ORDER", 400) from exc
    if value < 0 or value > 2_147_483_647:
        raise ApprovalDomainError("表单排序值超出范围", "INVALID_SORT_ORDER", 400)
    return value


def _positive_int(value, default: int, *, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(1, parsed))


def _paginate(queryset, request, serializer) -> dict:
    page = _positive_int(request.GET.get("page"), 1, maximum=100_000)
    page_size = _positive_int(request.GET.get("pageSize"), 20, maximum=100)
    total = queryset.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    start = (page - 1) * page_size
    return {
        "items": [serializer(row) for row in queryset[start:start + page_size]],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
    }


def _template_values(template: ApprovalTemplate) -> dict:
    return {
        "name": template.name,
        "description": template.description,
        "category": template.category,
        "icon": template.icon,
        "color": template.color,
        "formSchema": template.form_schema,
        "flowSchema": template.flow_schema,
        "settings": template.settings,
    }


def _serialize_template(template: ApprovalTemplate, *, include_schema: bool = True) -> dict:
    published_version = template.published_version
    category = _template_category(template)
    item = {
        "id": template.pk,
        "name": template.name,
        "description": template.description,
        "category": template.category,
        "categoryId": category.pk if category is not None else None,
        "categoryName": category.name if category is not None else template.category,
        "categoryOrder": template.category_order,
        "sortOrder": template.category_order,
        "icon": template.icon,
        "color": template.color,
        "status": template.status,
        "enabled": template.status == ApprovalTemplate.STATUS_PUBLISHED,
        "revision": str(template.revision),
        "publishedRevision": str(template.published_revision),
        "publishedVersion": published_version.version if published_version else None,
        "hasUnpublishedChanges": bool(
            published_version and template.revision != template.published_revision
        ),
        "createdBy": template.created_by,
        "createdByName": template.created_by_name,
        "updatedBy": template.updated_by,
        "updatedByName": template.updated_by_name,
        "createdAt": template.created_at.isoformat() if template.created_at else "",
        "updatedAt": template.updated_at.isoformat() if template.updated_at else "",
    }
    if hasattr(template, "application_count"):
        item["applicationCount"] = template.application_count
    if include_schema:
        item.update({
            "formSchema": template.form_schema,
            "flowSchema": template.flow_schema,
            "settings": template.settings,
        })
    return item


def _serialize_version(version: ApprovalTemplateVersion, *, include_schema: bool = True) -> dict:
    item = {
        "id": version.pk,
        "templateId": version.template_id,
        "version": version.version,
        "name": version.name,
        "description": version.description,
        "category": version.category,
        "icon": version.icon,
        "color": version.color,
        "sourceRevision": str(version.source_revision),
        "releaseNote": version.release_note,
        "publishedBy": version.published_by,
        "publishedByName": version.published_by_name,
        "publishedAt": version.published_at.isoformat() if version.published_at else "",
    }
    if include_schema:
        item.update({
            "formSchema": version.form_schema,
            "flowSchema": version.flow_schema,
            "settings": version.settings,
        })
    return item


def _serialize_published_template(template: ApprovalTemplate, *, include_schema: bool = True) -> dict:
    version = template.published_version
    if version is None:
        return _serialize_template(template, include_schema=include_schema)
    category = _template_category(template)
    item = {
        "id": template.pk,
        "name": version.name,
        "description": version.description,
        "category": version.category,
        "categoryId": category.pk if category is not None else None,
        "categoryName": category.name if category is not None else version.category,
        "categoryOrder": template.category_order,
        "sortOrder": template.category_order,
        "icon": version.icon,
        "color": version.color,
        "status": template.status,
        "enabled": template.status == ApprovalTemplate.STATUS_PUBLISHED,
        "revision": str(template.revision),
        "publishedRevision": str(template.published_revision),
        "publishedVersion": version.version,
        "hasUnpublishedChanges": bool(template.revision != template.published_revision),
        "createdBy": template.created_by,
        "createdByName": template.created_by_name,
        "updatedBy": template.updated_by,
        "updatedByName": template.updated_by_name,
        "createdAt": template.created_at.isoformat() if template.created_at else "",
        "updatedAt": version.published_at.isoformat() if version.published_at else "",
    }
    if hasattr(template, "application_count"):
        item["applicationCount"] = template.application_count
    if include_schema:
        item.update({
            "formSchema": version.form_schema,
            "flowSchema": version.flow_schema,
            "settings": version.settings,
        })
    return item


def _serialize_task(task: ApprovalTask, *, current_user_id: str = "") -> dict:
    return {
        "id": task.pk,
        "applicationId": task.application_id,
        "nodeKey": task.node_key,
        "nodeName": task.node_name,
        "nodeOrder": task.node_order,
        "taskType": task.task_type,
        "approvalMode": task.approval_mode,
        "assigneeUserId": task.assignee_user_id,
        "assigneeName": task.assignee_name,
        "status": task.status,
        "comment": task.comment,
        "actedByUserId": task.acted_by_user_id,
        "actedByName": task.acted_by_name,
        "canAct": bool(
            current_user_id
            and task.assignee_user_id == current_user_id
            and task.task_type == ApprovalTask.TYPE_APPROVAL
            and task.status == ApprovalTask.STATUS_PENDING
        ),
        "activatedAt": task.activated_at.isoformat() if task.activated_at else "",
        "actedAt": task.acted_at.isoformat() if task.acted_at else "",
        "createdAt": task.created_at.isoformat() if task.created_at else "",
        "updatedAt": task.updated_at.isoformat() if task.updated_at else "",
    }


def _serialize_event(event: ApprovalEvent) -> dict:
    return {
        "id": event.pk,
        "taskId": event.task_id,
        "action": event.action,
        "actionLabel": event.get_action_display(),
        "actorUserId": event.actor_user_id,
        "actorName": event.actor_name,
        "nodeKey": event.node_key,
        "nodeName": event.node_name,
        "fromStatus": event.from_status,
        "toStatus": event.to_status,
        "comment": event.comment,
        "data": event.data if isinstance(event.data, dict) else {},
        "createdAt": event.created_at.isoformat() if event.created_at else "",
    }


def _available_actions(application: ApprovalApplication, user_id: str) -> list[str]:
    if application.status != ApprovalApplication.STATUS_PENDING:
        return []
    result = []
    settings = application.template_version.settings
    allow_withdraw = not isinstance(settings, dict) or settings.get("allowWithdraw") is not False
    if application.initiator_user_id == user_id and allow_withdraw:
        result.append("withdraw")
    if application.tasks.filter(
        assignee_user_id=user_id,
        task_type=ApprovalTask.TYPE_APPROVAL,
        status=ApprovalTask.STATUS_PENDING,
        node_order=application.current_node_order,
    ).exists():
        result.extend(["approve", "reject", "return"])
    return result


def _serialize_application(
    application: ApprovalApplication,
    *,
    current_user_id: str = "",
    detail: bool = False,
) -> dict:
    item = {
        "id": application.pk,
        "serialNo": application.serial_no,
        "title": application.title,
        "status": application.status,
        "statusLabel": application.get_status_display(),
        "templateId": application.template_id,
        "templateName": application.template_version.name,
        "templateVersion": application.template_version.version,
        "initiatorUserId": application.initiator_user_id,
        "initiatorName": application.initiator_name,
        "initiatorDepartmentId": application.initiator_department_id,
        "initiatorDepartmentName": application.initiator_department_name,
        "currentNodeKey": application.current_node_key,
        "currentNodeName": application.current_node_name,
        "revision": str(application.revision),
        "exceptionMessage": application.exception_message,
        "errorMessage": application.exception_message,
        "submittedAt": application.submitted_at.isoformat() if application.submitted_at else "",
        "createdAt": application.submitted_at.isoformat() if application.submitted_at else "",
        "completedAt": application.completed_at.isoformat() if application.completed_at else "",
        "updatedAt": application.updated_at.isoformat() if application.updated_at else "",
    }
    if hasattr(application, "current_user_task_count"):
        item["currentUserTaskCount"] = application.current_user_task_count
    if detail:
        item.update({
            "values": application.values,
            "formSchema": application.template_version.form_schema,
            "flowSchema": application.template_version.flow_schema,
            "settings": application.template_version.settings,
            "tasks": [
                _serialize_task(task, current_user_id=current_user_id)
                for task in application.tasks.all()
            ],
            "events": [_serialize_event(event) for event in application.events.all()],
            "availableActions": _available_actions(application, current_user_id),
        })
    return item


def _related_applications(user_id: str):
    return ApprovalApplication.objects.filter(
        Q(initiator_user_id=user_id)
        | Q(tasks__assignee_user_id=user_id, tasks__activated_at__isnull=False),
    ).distinct()


def _can_view_application(application: ApprovalApplication, request) -> bool:
    user_id = _user_id(request)
    if application.initiator_user_id == user_id:
        return True
    if application.tasks.filter(
        assignee_user_id=user_id,
        activated_at__isnull=False,
    ).exists():
        return True
    try:
        return _is_admin(request)
    except AuthOrgClientError:
        return False


@require_GET
def workspace(request):
    user_id = _user_id(request)
    related = _related_applications(user_id)
    pending_tasks = ApprovalTask.objects.filter(
        assignee_user_id=user_id,
        task_type=ApprovalTask.TYPE_APPROVAL,
        status=ApprovalTask.STATUS_PENDING,
    )
    copied = ApprovalTask.objects.filter(
        assignee_user_id=user_id,
        task_type=ApprovalTask.TYPE_CC,
        status=ApprovalTask.STATUS_COPIED,
    )
    recent_templates = ApprovalTemplate.objects.filter(
        deleted_at__isnull=True,
        status=ApprovalTemplate.STATUS_PUBLISHED,
        published_version__isnull=False,
    ).select_related("published_version", "category_ref")[:8]
    recent_applications = related.select_related("template_version")[:8]
    return JsonResponse({
        "ok": True,
        "counts": {
            "pending": pending_tasks.count(),
            "initiated": ApprovalApplication.objects.filter(initiator_user_id=user_id).count(),
            "returned": ApprovalApplication.objects.filter(
                initiator_user_id=user_id,
                status=ApprovalApplication.STATUS_RETURNED,
            ).count(),
            "copied": copied.count(),
            "drafts": ApprovalDraft.objects.filter(owner_user_id=user_id).count(),
        },
        "recentTemplates": [_serialize_published_template(item, include_schema=False) for item in recent_templates],
        "recentApplications": [
            _serialize_application(item, current_user_id=user_id)
            for item in recent_applications
        ],
    })


def _serialize_category(
    category: ApprovalCategory,
    *,
    include_permission: bool = False,
    request=None,
) -> dict:
    template_count = getattr(category, "template_count", None)
    if template_count is None:
        template_count = ApprovalTemplate.objects.filter(
            category_ref=category,
            deleted_at__isnull=True,
        ).count()
    permission_count = getattr(category, "permission_count", None)
    if permission_count is None:
        permission_count = category.permission_rules.filter(
            permission=ApprovalCategoryPermission.PERMISSION_ADMIN,
        ).count()
    can_manage = False
    if include_permission and request is not None:
        try:
            cached_global = getattr(request, "_approval_is_global_admin", None)
            cached_ids = getattr(request, "_approval_managed_category_ids", None)
            if cached_global is True:
                can_manage = True
            elif cached_global is False and cached_ids is not None:
                can_manage = category.pk in cached_ids
            else:
                can_manage = _is_admin(request) or (
                    get_user_category_permission(_user_id(request), category.pk)
                    == APP_PERMISSION_ADMIN
                )
        except AuthOrgClientError:
            can_manage = False
    return {
        "id": category.pk,
        "name": category.name,
        "description": category.description,
        "sortOrder": category.sort_order,
        "templateCount": template_count,
        "permissionCount": permission_count if include_permission else 0,
        "canManage": can_manage,
        "managePermission": ({
            "permission": APP_PERMISSION_ADMIN,
            "permissionLabel": "管理员权限",
            "count": permission_count,
        } if include_permission else None),
        "createdAt": category.created_at.isoformat() if category.created_at else "",
        "updatedAt": category.updated_at.isoformat() if category.updated_at else "",
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def templates_collection(request):
    if request.method == "POST":
        payload = _body(request)
        if payload is None:
            return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
        try:
            if not _is_admin(request):
                # Preserve the historical APP_ADMIN_REQUIRED response for
                # ordinary users before attempting to resolve a legacy label.
                managed_ids, managed_denied = _managed_category_ids(request)
                if managed_denied is not None and not managed_ids:
                    return managed_denied
            # A global admin may continue using the legacy category string and
            # implicitly create its category. Scoped managers must select an
            # existing category they are allowed to manage.
            category = _category_from_payload(
                payload,
                allow_create=_is_admin(request),
                request=request,
            )
            denied = _ensure_template_admin(request, category=category)
            if denied is not None:
                return denied
            fields = normalize_template_payload(payload)
            fields.pop("status", None)
            fields["category"] = category.name
            validate_form_schema(fields.get("form_schema", {}), for_publish=False)
            workflow_nodes(fields.get("flow_schema", {}), for_publish=False)
            fields["category_ref"] = category
            fields["category_order"] = _category_order_from_payload(
                payload,
                default=(
                    ApprovalTemplate.objects.filter(category_ref=category)
                    .order_by("-category_order")
                    .values_list("category_order", flat=True)
                    .first()
                    or 0
                ) + 1,
            )
        except ApprovalDomainError as exc:
            return _domain_error(exc)
        except AuthOrgClientError:
            return _error(
                "组织架构服务暂不可用，无法确认管理权限",
                status=503,
                code="AUTH_ORG_UNAVAILABLE",
            )
        actor_user_id = _actor_id(request)
        actor_name = _actor_name(request)
        template = ApprovalTemplate.objects.create(
            **fields,
            status=ApprovalTemplate.STATUS_DRAFT,
            created_by=actor_user_id,
            created_by_name=actor_name,
            updated_by=actor_user_id,
            updated_by_name=actor_name,
        )
        return JsonResponse({"ok": True, "item": _serialize_template(template)}, status=201)

    manage = str(request.GET.get("scope") or "").strip().lower() in {"manage", "admin", "all"}
    managed_category_ids = None
    if manage:
        managed_category_ids, denied = _managed_category_ids(request)
        if denied is not None:
            return denied
    queryset = ApprovalTemplate.objects.filter(
        deleted_at__isnull=True,
    ).select_related("published_version", "category_ref")
    if manage:
        if managed_category_ids is not None:
            queryset = queryset.filter(category_ref_id__in=managed_category_ids)
    else:
        queryset = queryset.filter(
            status=ApprovalTemplate.STATUS_PUBLISHED,
            published_version__isnull=False,
        )
    status = str(request.GET.get("status") or "").strip()
    category = str(request.GET.get("category") or "").strip()
    category_id = str(request.GET.get("categoryId") or request.GET.get("category_id") or "").strip()
    keyword = str(request.GET.get("q") or "").strip()
    if status:
        queryset = queryset.filter(status=status)
    if category:
        queryset = queryset.filter(category=category)
    if category_id.isdigit():
        queryset = queryset.filter(category_ref_id=int(category_id))
    if keyword:
        queryset = queryset.filter(Q(name__icontains=keyword) | Q(description__icontains=keyword))
    queryset = queryset.annotate(application_count=Count("applications"))
    if manage or category_id.isdigit() or category:
        queryset = queryset.order_by(
            "category_ref__sort_order",
            "category_order",
            "-updated_at",
            "-id",
        )
    data = _paginate(
        queryset,
        request,
        lambda item: (
            _serialize_template(item, include_schema=False)
            if manage
            else _serialize_published_template(item, include_schema=False)
        ),
    )
    category_queryset = ApprovalCategory.objects.filter(deleted_at__isnull=True)
    if manage and managed_category_ids is not None:
        category_queryset = category_queryset.filter(pk__in=managed_category_ids)
    elif not manage:
        category_queryset = category_queryset.filter(
            templates__deleted_at__isnull=True,
            templates__status=ApprovalTemplate.STATUS_PUBLISHED,
        ).distinct()
    data["categories"] = list(
        category_queryset.values_list("name", flat=True).distinct().order_by("name")
    )
    data["categoryItems"] = [
        _serialize_category(item, include_permission=manage, request=request)
        for item in category_queryset.order_by("sort_order", "name", "id")
    ]
    if category_id.isdigit() and ApprovalCategory.objects.filter(
        pk=int(category_id),
        deleted_at__isnull=True,
    ).exists():
        data["templateRevision"] = _template_order_revision_snapshot(int(category_id))
    return JsonResponse(data)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
def template_item(request, template_id: int):
    template = ApprovalTemplate.objects.select_related("published_version", "category_ref").filter(
        pk=template_id,
        deleted_at__isnull=True,
    ).first()
    if template is None:
        return _error("审批模板不存在", status=404, code="TEMPLATE_NOT_FOUND")

    if request.method == "GET":
        manage = str(request.GET.get("scope") or "").strip().lower() in {"manage", "admin"}
        if manage:
            denied = _ensure_template_admin(request, template=template)
            if denied is not None:
                return denied
            return JsonResponse({"item": _serialize_template(template)})
        if template.status != ApprovalTemplate.STATUS_PUBLISHED or template.published_version is None:
            return _error("该审批模板当前不可用", status=404, code="TEMPLATE_NOT_AVAILABLE")
        return JsonResponse({"item": _serialize_published_template(template)})

    denied = _ensure_template_admin(request, template=template)
    if denied is not None:
        return denied
    if request.method == "DELETE":
        with transaction.atomic():
            locked = ApprovalTemplate.objects.select_for_update().get(pk=template.pk)
            locked.status = ApprovalTemplate.STATUS_ARCHIVED
            locked.deleted_at = timezone.now()
            locked.updated_by = _actor_id(request)
            locked.updated_by_name = _actor_name(request)
            locked.revision += 1
            locked.save(update_fields=[
                "status", "deleted_at", "updated_by", "updated_by_name", "revision", "updated_at",
            ])
        return JsonResponse({"ok": True})

    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        fields = normalize_template_payload(payload, partial=True)
        category_payload_present = any(
            key in payload for key in ("categoryId", "category_id", "category", "categoryOrder", "sortOrder", "order")
        )
        target_category = _template_category(template)
        if any(key in payload for key in ("categoryId", "category_id", "category")):
            target_category = _category_from_payload(
                payload,
                allow_create=_is_admin(request),
                request=request,
            )
        if target_category is None:
            raise ApprovalDomainError("审批分类不存在", "CATEGORY_NOT_FOUND", 404)
        target_denied = _ensure_template_admin(request, category=target_category)
        if target_denied is not None:
            return target_denied
        if category_payload_present:
            fields["category_ref"] = target_category
            fields["category"] = target_category.name
            fields["category_order"] = _category_order_from_payload(
                payload,
                default=template.category_order,
            )
    except ApprovalDomainError as exc:
        return _domain_error(exc)
    except AuthOrgClientError:
        return _error(
            "组织架构服务暂不可用，无法确认管理权限",
            status=503,
            code="AUTH_ORG_UNAVAILABLE",
        )
    expected_revision = str(payload.get("revision") or "").strip()
    with transaction.atomic():
        locked = (
            ApprovalTemplate.objects.select_for_update(of=("self",))
            .select_related("published_version")
            .get(pk=template.pk)
        )
        if expected_revision and expected_revision != str(locked.revision):
            return _error(
                "模板已被其他人修改，请刷新后重试",
                status=409,
                code="REVISION_CONFLICT",
                revision=str(locked.revision),
            )
        preview = _template_values(locked)
        preview.update({
            "formSchema": fields.get("form_schema", preview["formSchema"]),
            "flowSchema": fields.get("flow_schema", preview["flowSchema"]),
        })
        try:
            validate_form_schema(preview["formSchema"], for_publish=False)
            workflow_nodes(preview["flowSchema"], for_publish=False)
        except ApprovalDomainError as exc:
            return _domain_error(exc)
        for key, value in fields.items():
            setattr(locked, key, value)
        if fields.get("status") == ApprovalTemplate.STATUS_PUBLISHED and locked.published_version_id is None:
            return _error(
                "模板需要先发布才能启用",
                status=409,
                code="TEMPLATE_NOT_PUBLISHED",
            )
        locked.updated_by = _actor_id(request)
        locked.updated_by_name = _actor_name(request)
        locked.revision += 1
        locked.save()
    return JsonResponse({"ok": True, "item": _serialize_template(locked)})


@csrf_exempt
@require_http_methods(["POST"])
def template_publish(request, template_id: int):
    existing = ApprovalTemplate.objects.select_related("category_ref").filter(
        pk=template_id,
        deleted_at__isnull=True,
    ).first()
    if existing is None:
        return _error("审批模板不存在", status=404, code="TEMPLATE_NOT_FOUND")
    denied = _ensure_template_admin(request, template=existing)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        _departments, employees, _org_revision = get_auth_organization_snapshot()
    except AuthOrgClientError:
        return _error(
            "组织架构服务暂不可用，无法校验流程人员",
            status=503,
            code="AUTH_ORG_UNAVAILABLE",
        )
    assignee_directory, _employee_rows = _auth_employee_directories(employees)
    try:
        with transaction.atomic():
            template = (
                ApprovalTemplate.objects.select_for_update(of=("self",))
                .select_related("published_version", "category_ref")
                .filter(
                    pk=template_id,
                    deleted_at__isnull=True,
                )
                .first()
            )
            if template is None:
                raise ApprovalDomainError("审批模板不存在", "TEMPLATE_NOT_FOUND", 404)
            expected_revision = str(payload.get("revision") or "").strip()
            if expected_revision and expected_revision != str(template.revision):
                raise ApprovalDomainError(
                    "模板已被其他人修改，请刷新后重试",
                    "REVISION_CONFLICT",
                    409,
                )
            version = publish_template(
                template,
                actor_user_id=_actor_id(request),
                actor_name=_actor_name(request),
                assignee_directory=assignee_directory,
                release_note=payload.get("releaseNote") or "",
            )
    except ApprovalDomainError as exc:
        return _domain_error(exc)
    return JsonResponse({
        "ok": True,
        "item": _serialize_template(template),
        "version": _serialize_version(version),
    })


@require_GET
def template_versions(request, template_id: int):
    template = ApprovalTemplate.objects.select_related("category_ref").filter(
        pk=template_id,
        deleted_at__isnull=True,
    ).first()
    if template is None:
        return _error("审批模板不存在", status=404, code="TEMPLATE_NOT_FOUND")
    denied = _ensure_template_admin(request, template=template)
    if denied is not None:
        return denied
    rows = ApprovalTemplateVersion.objects.filter(template_id=template_id)
    return JsonResponse({
        "items": [_serialize_version(row, include_schema=False) for row in rows],
        "total": rows.count(),
    })


@require_GET
def template_version_item(request, template_id: int, version: int):
    template = ApprovalTemplate.objects.select_related("category_ref").filter(
        pk=template_id,
        deleted_at__isnull=True,
    ).first()
    if template is None:
        return _error("审批模板不存在", status=404, code="TEMPLATE_NOT_FOUND")
    denied = _ensure_template_admin(request, template=template)
    if denied is not None:
        return denied
    item = ApprovalTemplateVersion.objects.filter(
        template_id=template_id,
        version=version,
    ).first()
    if item is None:
        return _error("模板版本不存在", status=404, code="TEMPLATE_VERSION_NOT_FOUND")
    return JsonResponse({"item": _serialize_version(item)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def categories_collection(request):
    if request.method == "POST":
        denied = _ensure_admin(request)
        if denied is not None:
            return denied
        payload = _body(request)
        if payload is None:
            return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
        name = str(payload.get("name") or "").strip()
        description = str(payload.get("description") or "").strip()
        if not name:
            return _error("分类名称不能为空", status=400, code="INVALID_CATEGORY")
        if len(name) > 64:
            return _error("分类名称不能超过 64 个字符", status=400, code="INVALID_CATEGORY")
        if len(description) > 5000:
            return _error("分类说明不能超过 5000 个字符", status=400, code="INVALID_CATEGORY")
        existing = ApprovalCategory.objects.filter(name__iexact=name).first()
        if existing is not None:
            if existing.deleted_at is not None:
                with transaction.atomic():
                    existing = ApprovalCategory.objects.select_for_update().get(pk=existing.pk)
                    existing.deleted_at = None
                    existing.description = description
                    existing.updated_by = _actor_id(request)
                    existing.updated_by_name = _actor_name(request)
                    existing.save(update_fields=[
                        "deleted_at", "description", "updated_by", "updated_by_name", "updated_at",
                    ])
                    revision = _touch_category_revision()
                return JsonResponse({
                    "ok": True,
                    "item": _serialize_category(existing, include_permission=True, request=request),
                    "revision": revision,
                }, status=201)
            return _error("审批分类已存在", status=409, code="CATEGORY_EXISTS")
        next_order = (
            ApprovalCategory.objects.filter(deleted_at__isnull=True)
            .order_by("-sort_order")
            .values_list("sort_order", flat=True)
            .first()
            or 0
        ) + 1
        with transaction.atomic():
            try:
                category = ApprovalCategory.objects.create(
                    name=name,
                    description=description,
                    sort_order=next_order,
                    created_by=_actor_id(request),
                    created_by_name=_actor_name(request),
                    updated_by=_actor_id(request),
                    updated_by_name=_actor_name(request),
                )
            except IntegrityError:
                return _error("审批分类已存在", status=409, code="CATEGORY_EXISTS")
            revision = _touch_category_revision()
        return JsonResponse({
            "ok": True,
            "item": _serialize_category(category, include_permission=True, request=request),
            "revision": revision,
        }, status=201)

    manage = str(request.GET.get("scope") or "").strip().lower() in {"manage", "admin", "all"}
    managed_ids = None
    if manage:
        managed_ids, denied = _managed_category_ids(request)
        if denied is not None:
            return denied
    queryset = ApprovalCategory.objects.filter(deleted_at__isnull=True)
    if managed_ids is not None:
        queryset = queryset.filter(pk__in=managed_ids)
    template_count_filter = Q(templates__deleted_at__isnull=True)
    if not manage:
        template_count_filter &= Q(
            templates__status=ApprovalTemplate.STATUS_PUBLISHED,
            templates__published_version__isnull=False,
        )
    queryset = queryset.annotate(
        template_count=Count(
            "templates",
            filter=template_count_filter,
            distinct=True,
        ),
        permission_count=Count("permission_rules", distinct=True),
    )
    if not manage:
        queryset = queryset.filter(template_count__gt=0)
    queryset = queryset.order_by("sort_order", "name", "id")
    return JsonResponse({
        "items": [
            _serialize_category(item, include_permission=manage, request=request)
            for item in queryset
        ],
        "categories": [
            _serialize_category(item, include_permission=manage, request=request)
            for item in queryset
        ],
        "revision": _category_revision_snapshot(),
    })


@csrf_exempt
@require_http_methods(["PATCH"])
def category_item(request, category_id: int):
    denied = _ensure_admin(request)
    if denied is not None:
        return denied
    category = _category_from_id(category_id)
    if category is None:
        return _error("审批分类不存在", status=404, code="CATEGORY_NOT_FOUND")
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    name = str(payload.get("name") if "name" in payload else category.name).strip()
    description = str(payload.get("description") if "description" in payload else category.description).strip()
    if not name or len(name) > 64 or len(description) > 5000:
        return _error("分类名称或说明格式无效", status=400, code="INVALID_CATEGORY")
    duplicate = ApprovalCategory.objects.filter(name__iexact=name).exclude(pk=category.pk).first()
    if duplicate is not None:
        return _error("审批分类已存在", status=409, code="CATEGORY_EXISTS")
    with transaction.atomic():
        locked = ApprovalCategory.objects.select_for_update().get(pk=category.pk)
        old_name = locked.name
        locked.name = name
        locked.description = description
        locked.updated_by = _actor_id(request)
        locked.updated_by_name = _actor_name(request)
        locked.save(update_fields=["name", "description", "updated_by", "updated_by_name", "updated_at"])
        if old_name != name:
            ApprovalTemplate.objects.filter(category_ref_id=locked.pk).update(category=name)
        revision = _touch_category_revision()
    return JsonResponse({
        "ok": True,
        "item": _serialize_category(locked, include_permission=True, request=request),
        "revision": revision,
    })


@csrf_exempt
@require_http_methods(["POST"])
def categories_reorder(request):
    denied = _ensure_admin(request)
    if denied is not None:
        return denied
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    rows = payload.get("items")
    if rows is None:
        rows = payload.get("orders")
    if not isinstance(rows, list):
        return _error("分类排序数据格式错误", status=400, code="INVALID_SORT_ORDER")
    expected = str(payload.get("revision") or "").strip()
    with transaction.atomic():
        current = _category_revision_snapshot()
        if expected and expected != current:
            return _error(
                "分类配置已被其他人修改，请刷新后重试",
                status=409,
                code="REVISION_CONFLICT",
                revision=current,
            )
        active_ids = set(
            ApprovalCategory.objects.filter(deleted_at__isnull=True).values_list("id", flat=True)
        )
        seen = set()
        updates = []
        try:
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise ValueError("分类排序项格式错误")
                raw_id = row.get("id")
                parsed_id = int(raw_id)
                if parsed_id not in active_ids or parsed_id in seen:
                    raise ValueError("分类排序项无效或重复")
                raw_order = row.get("sortOrder", row.get("order", index))
                parsed_order = int(raw_order)
                if parsed_order < 0 or parsed_order > 2_147_483_647:
                    raise ValueError("分类排序值超出范围")
                seen.add(parsed_id)
                updates.append((parsed_id, parsed_order))
        except (TypeError, ValueError) as exc:
            return _error(str(exc), status=400, code="INVALID_SORT_ORDER")
        next_revision, conflict = _category_revision_advance(None, expected=current)
        if conflict is not None:
            return conflict
        for parsed_id, parsed_order in updates:
            ApprovalCategory.objects.filter(pk=parsed_id).update(
                sort_order=parsed_order,
                updated_by=_actor_id(request),
                updated_by_name=_actor_name(request),
                updated_at=timezone.now(),
            )
    categories = ApprovalCategory.objects.filter(
        deleted_at__isnull=True,
    ).order_by("sort_order", "name", "id")
    return JsonResponse({
        "ok": True,
        "items": [_serialize_category(item, include_permission=True, request=request) for item in categories],
        "revision": next_revision,
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def category_permissions(request, category_id: int):
    denied = _ensure_admin(request)
    if denied is not None:
        return denied
    category = _category_from_id(category_id)
    if category is None:
        return _error("审批分类不存在", status=404, code="CATEGORY_NOT_FOUND")
    if request.method == "GET":
        try:
            _departments, _employees, org_revision = get_auth_organization_snapshot()
        except AuthOrgClientError:
            # Reading already-saved rules remains useful while the directory is
            # temporarily unavailable; the next save will fail closed.
            org_revision = None
        saved_items = list_category_permission_rules(category.pk)
        return JsonResponse({
            "items": saved_items,
            "rules": saved_items,
            "revision": _category_revision_snapshot(category.pk),
            "orgRevision": org_revision,
        })
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    items = payload.get("items")
    if items is None:
        items = payload.get("rules")
    if not isinstance(items, list):
        return _error("权限数据格式错误", status=400, code="INVALID_PERMISSION_ITEMS")
    try:
        departments, employees, org_revision = get_auth_organization_snapshot()
    except AuthOrgClientError:
        return _error(
            "组织架构服务暂不可用，无法配置分类权限",
            status=503,
            code="AUTH_ORG_UNAVAILABLE",
        )
    expected_org = str(payload.get("orgRevision") or "").strip()
    if expected_org and expected_org != str(org_revision):
        return _error(
            "组织架构已发生变化，请刷新权限页面后再保存",
            status=409,
            code="ORG_REVISION_CONFLICT",
            orgRevision=str(org_revision),
        )
    expected_revision = str(payload.get("revision") or "").strip()
    with transaction.atomic():
        current = _category_revision_snapshot(category.pk)
        if expected_revision and expected_revision != current:
            return _error(
                "分类权限配置已被其他人修改，请刷新后重试",
                status=409,
                code="REVISION_CONFLICT",
                revision=current,
            )
        next_revision, conflict = _category_revision_advance(category.pk, expected=current)
        if conflict is not None:
            return conflict
        try:
            saved_items = replace_category_permission_rules(
                category.pk,
                items,
                departments=departments,
                employees=employees,
                actor_user_id=_actor_id(request),
            )
        except ValueError as exc:
            return _error(str(exc), status=400, code="INVALID_PERMISSION_RULE")
    return JsonResponse({
        "ok": True,
        "items": saved_items,
        "rules": saved_items,
        "revision": next_revision,
        "orgRevision": org_revision,
    })


@csrf_exempt
@require_http_methods(["POST"])
def templates_reorder(request):
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    category_id = payload.get("categoryId")
    category = _category_from_id(category_id)
    if category is None:
        return _error("审批分类不存在", status=404, code="CATEGORY_NOT_FOUND")
    denied = _ensure_template_admin(request, category=category)
    if denied is not None:
        return denied
    move_template_id = payload.get("templateId", payload.get("template_id"))
    move_direction = str(payload.get("direction") or "").strip().lower()
    rows = payload.get("items")
    if rows is None:
        rows = payload.get("orders")
    if move_template_id in (None, "") and not isinstance(rows, list):
        return _error("表单排序数据格式错误", status=400, code="INVALID_SORT_ORDER")
    if move_template_id not in (None, "") and move_direction not in {"up", "down"}:
        return _error("表单移动方向无效", status=400, code="INVALID_SORT_DIRECTION")
    revision_key = f"template_order:{category.pk}"
    with transaction.atomic():
        state, _created = AppConfigurationRevision.objects.select_for_update().get_or_create(
            key=revision_key,
            defaults={"revision": 1},
        )
        current = str(max(1, int(state.revision or 1)))
        expected = str(payload.get("revision") or "").strip()
        if expected and expected != current:
            return _error(
                "表单排序已被其他人修改，请刷新后重试",
                status=409,
                code="REVISION_CONFLICT",
                revision=current,
            )
        seen = set()
        updates = []
        try:
            if move_template_id not in (None, ""):
                parsed_id = int(move_template_id)
                ordered_templates = list(
                    ApprovalTemplate.objects.select_for_update().filter(
                        category_ref_id=category.pk,
                        deleted_at__isnull=True,
                    ).order_by("category_order", "-updated_at", "-id")
                )
                source_index = next(
                    (index for index, item in enumerate(ordered_templates) if item.pk == parsed_id),
                    -1,
                )
                if source_index < 0:
                    raise ValueError("表单不属于该审批分类")
                target_index = source_index + (-1 if move_direction == "up" else 1)
                if 0 <= target_index < len(ordered_templates):
                    ordered_templates[source_index], ordered_templates[target_index] = (
                        ordered_templates[target_index],
                        ordered_templates[source_index],
                    )
                    updates = [
                        (item.pk, index)
                        for index, item in enumerate(ordered_templates)
                        if item.category_order != index
                    ]
            else:
                for index, row in enumerate(rows):
                    if not isinstance(row, dict):
                        raise ValueError("表单排序项格式错误")
                    parsed_id = int(row.get("id"))
                    if parsed_id in seen:
                        raise ValueError("表单排序项重复")
                    if not ApprovalTemplate.objects.filter(
                        pk=parsed_id,
                        category_ref_id=category.pk,
                        deleted_at__isnull=True,
                    ).exists():
                        raise ValueError("表单不属于该审批分类")
                    parsed_order = int(row.get("sortOrder", row.get("order", index)))
                    if parsed_order < 0 or parsed_order > 2_147_483_647:
                        raise ValueError("表单排序值超出范围")
                    seen.add(parsed_id)
                    updates.append((parsed_id, parsed_order))
        except (TypeError, ValueError) as exc:
            return _error(str(exc), status=400, code="INVALID_SORT_ORDER")
        for parsed_id, parsed_order in updates:
            ApprovalTemplate.objects.filter(pk=parsed_id).update(
                category_order=parsed_order,
            )
        if updates:
            state.revision = int(current) + 1
            state.save(update_fields=["revision", "updated_at"])
        next_revision = str(state.revision)
    templates = ApprovalTemplate.objects.filter(
        category_ref_id=category.pk,
        deleted_at__isnull=True,
    ).select_related("published_version", "category_ref").order_by("category_order", "-updated_at", "-id")
    return JsonResponse({
        "ok": True,
        "categoryId": category.pk,
        "items": [_serialize_template(item, include_schema=False) for item in templates],
        "revision": next_revision,
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def applications_collection(request):
    user_id = _user_id(request)
    if request.method == "POST":
        payload = _body(request)
        if payload is None:
            return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
        try:
            template_id = int(payload.get("templateId"))
        except (TypeError, ValueError):
            return _error("请选择审批模板", status=400, code="TEMPLATE_REQUIRED")
        draft_id = payload.get("draftId")
        if draft_id not in {None, ""}:
            try:
                draft_id = int(draft_id)
            except (TypeError, ValueError):
                return _error("草稿编号无效", status=400, code="INVALID_DRAFT_ID")
        try:
            departments, employees, _org_revision = get_auth_organization_snapshot()
        except AuthOrgClientError:
            return _error(
                "组织架构服务暂不可用，无法校验申请人员",
                status=503,
                code="AUTH_ORG_UNAVAILABLE",
            )
        employee_directory, employee_rows = _auth_employee_directories(employees)
        department_directory, departments_by_id = _auth_department_directories(departments)
        department_id, department_name = _primary_employee_department(
            employee_rows.get(user_id),
            departments_by_id,
        )
        try:
            with transaction.atomic():
                template = ApprovalTemplate.objects.filter(
                    pk=template_id,
                    deleted_at__isnull=True,
                ).first()
                if template is None:
                    raise ApprovalDomainError("审批模板不存在", "TEMPLATE_NOT_FOUND", 404)
                draft = None
                if draft_id is not None:
                    draft = ApprovalDraft.objects.select_for_update().filter(
                        pk=draft_id,
                        owner_user_id=user_id,
                    ).first()
                    if draft is None:
                        raise ApprovalDomainError("草稿不存在", "DRAFT_NOT_FOUND", 404)
                    if draft.template_id != template_id:
                        raise ApprovalDomainError(
                            "草稿与审批模板不匹配",
                            "DRAFT_TEMPLATE_MISMATCH",
                            409,
                        )
                application = create_application(
                    template,
                    initiator_user_id=user_id,
                    initiator_name=employee_directory.get(user_id, _user_name(request)),
                    title=payload.get("title") or "",
                    values=payload.get("values"),
                    department_id=department_id,
                    department_name=department_name,
                    actor_user_id=_actor_id(request),
                    actor_name=_actor_name(request),
                    is_proxying=bool(getattr(request, "auth_is_proxy", False)),
                    employee_directory=employee_directory,
                    department_directory=department_directory,
                )
                if draft is not None:
                    draft.delete()
        except ApprovalDomainError as exc:
            return _domain_error(exc)
        application = ApprovalApplication.objects.select_related("template_version").prefetch_related(
            "tasks", "events",
        ).get(pk=application.pk)
        return JsonResponse({
            "ok": True,
            "item": _serialize_application(application, current_user_id=user_id, detail=True),
        }, status=201)

    view = str(request.GET.get("view") or "initiated").strip().lower()
    base = ApprovalApplication.objects.select_related("template_version")
    if view in {"initiated", "mine", "created"}:
        queryset = base.filter(initiator_user_id=user_id)
    elif view in {"pending", "todo"}:
        queryset = base.filter(
            tasks__assignee_user_id=user_id,
            tasks__task_type=ApprovalTask.TYPE_APPROVAL,
            tasks__status=ApprovalTask.STATUS_PENDING,
        ).distinct()
    elif view in {"processed", "done"}:
        queryset = base.filter(
            tasks__assignee_user_id=user_id,
            tasks__status__in=[
                ApprovalTask.STATUS_APPROVED,
                ApprovalTask.STATUS_REJECTED,
                ApprovalTask.STATUS_RETURNED,
            ],
        ).distinct()
    elif view in {"copied", "cc"}:
        queryset = base.filter(
            tasks__assignee_user_id=user_id,
            tasks__task_type=ApprovalTask.TYPE_CC,
            tasks__status=ApprovalTask.STATUS_COPIED,
        ).distinct()
    elif view == "all":
        denied = _ensure_admin(request)
        if denied is not None:
            return denied
        queryset = base.all()
    else:
        return _error("申请列表类型无效", status=400, code="INVALID_VIEW")

    status = str(request.GET.get("status") or "").strip()
    template_id = str(request.GET.get("templateId") or "").strip()
    keyword = str(request.GET.get("q") or "").strip()
    if status:
        queryset = queryset.filter(status=status)
    if template_id.isdigit():
        queryset = queryset.filter(template_id=int(template_id))
    if keyword:
        queryset = queryset.filter(
            Q(title__icontains=keyword)
            | Q(serial_no__icontains=keyword)
            | Q(initiator_name__icontains=keyword)
            | Q(template_version__name__icontains=keyword)
        )
    queryset = queryset.annotate(
        current_user_task_count=Count(
            "tasks",
            filter=Q(
                tasks__assignee_user_id=user_id,
                tasks__status=ApprovalTask.STATUS_PENDING,
            ),
        )
    ).order_by("-submitted_at", "-id")
    return JsonResponse(_paginate(
        queryset,
        request,
        lambda item: _serialize_application(item, current_user_id=user_id),
    ))


@require_GET
def application_item(request, application_id: int):
    application = ApprovalApplication.objects.select_related(
        "template_version",
    ).prefetch_related("tasks", "events").filter(pk=application_id).first()
    if application is None:
        return _error("审批申请不存在", status=404, code="APPLICATION_NOT_FOUND")
    if not _can_view_application(application, request):
        return _error("你无权查看该审批申请", status=403, code="APPLICATION_FORBIDDEN")
    return JsonResponse({
        "item": _serialize_application(
            application,
            current_user_id=_user_id(request),
            detail=True,
        ),
    })


@csrf_exempt
@require_http_methods(["POST"])
def application_action(request, application_id: int, action: str):
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    action_map = {
        "approve": ApprovalEvent.ACTION_APPROVED,
        "reject": ApprovalEvent.ACTION_REJECTED,
        "return": ApprovalEvent.ACTION_RETURNED,
        "withdraw": ApprovalEvent.ACTION_WITHDRAWN,
    }
    normalized_action = action_map.get(action)
    if normalized_action is None:
        return _error("审批操作无效", status=400, code="INVALID_ACTION")
    task_id = payload.get("taskId")
    if task_id not in {None, ""}:
        try:
            task_id = int(task_id)
        except (TypeError, ValueError):
            return _error("审批任务编号无效", status=400, code="INVALID_TASK_ID")
    try:
        application = act_on_application(
            application_id,
            normalized_action,
            user_id=_user_id(request),
            user_name=_user_name(request),
            comment=payload.get("comment") or payload.get("reason") or "",
            task_id=task_id,
            expected_revision=payload.get("revision") or payload.get("expectedRevision"),
            actor_user_id=_actor_id(request),
            actor_name=_actor_name(request),
            is_proxying=bool(getattr(request, "auth_is_proxy", False)),
        )
    except ApprovalDomainError as exc:
        return _domain_error(exc)
    application = ApprovalApplication.objects.select_related("template_version").prefetch_related(
        "tasks", "events",
    ).get(pk=application.pk)
    return JsonResponse({
        "ok": True,
        "item": _serialize_application(
            application,
            current_user_id=_user_id(request),
            detail=True,
        ),
    })


@require_GET
def tasks_collection(request):
    user_id = _user_id(request)
    view = str(request.GET.get("view") or "pending").strip().lower()
    queryset = ApprovalTask.objects.filter(
        assignee_user_id=user_id,
        task_type=ApprovalTask.TYPE_APPROVAL,
    ).select_related("application__template_version")
    if view in {"pending", "todo"}:
        queryset = queryset.filter(status=ApprovalTask.STATUS_PENDING)
    elif view in {"processed", "done"}:
        queryset = queryset.filter(status__in=[
            ApprovalTask.STATUS_APPROVED,
            ApprovalTask.STATUS_REJECTED,
            ApprovalTask.STATUS_RETURNED,
        ])
    else:
        return _error("任务列表类型无效", status=400, code="INVALID_VIEW")
    status = str(request.GET.get("status") or "").strip()
    if status:
        queryset = queryset.filter(application__status=status)
    keyword = str(request.GET.get("q") or "").strip()
    if keyword:
        queryset = queryset.filter(
            Q(application__title__icontains=keyword)
            | Q(application__serial_no__icontains=keyword)
            | Q(application__initiator_name__icontains=keyword)
        )
    queryset = queryset.order_by("-activated_at", "-id")

    def serialize(row):
        item = _serialize_task(row, current_user_id=user_id)
        item["application"] = _serialize_application(row.application, current_user_id=user_id)
        return item

    return JsonResponse(_paginate(queryset, request, serialize))


def _serialize_draft(draft: ApprovalDraft) -> dict:
    return {
        "id": draft.pk,
        "templateId": draft.template_id,
        "templateName": draft.template.name if draft.template else "",
        "title": draft.title,
        "values": draft.values,
        "createdAt": draft.created_at.isoformat() if draft.created_at else "",
        "updatedAt": draft.updated_at.isoformat() if draft.updated_at else "",
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def drafts_collection(request):
    user_id = _user_id(request)
    if request.method == "GET":
        queryset = ApprovalDraft.objects.filter(owner_user_id=user_id).select_related("template")
        keyword = str(request.GET.get("q") or "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(title__icontains=keyword) | Q(template__name__icontains=keyword)
            )
        return JsonResponse(_paginate(queryset, request, _serialize_draft))
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    template = None
    template_id = payload.get("templateId")
    if template_id not in {None, ""}:
        try:
            template = ApprovalTemplate.objects.get(
                pk=int(template_id),
                deleted_at__isnull=True,
                status=ApprovalTemplate.STATUS_PUBLISHED,
                published_version__isnull=False,
            )
        except (TypeError, ValueError, ApprovalTemplate.DoesNotExist):
            return _error("审批模板不存在", status=404, code="TEMPLATE_NOT_FOUND")
    try:
        values = ensure_json_object(payload.get("values"), "草稿内容")
        title = text(payload.get("title"), maximum=200)
    except ApprovalDomainError as exc:
        return _domain_error(exc)
    draft = ApprovalDraft.objects.create(
        template=template,
        owner_user_id=user_id,
        owner_name=_user_name(request),
        title=title,
        values=values,
    )
    return JsonResponse({"ok": True, "item": _serialize_draft(draft)}, status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
def draft_item(request, draft_id: int):
    draft = ApprovalDraft.objects.select_related("template").filter(
        pk=draft_id,
        owner_user_id=_user_id(request),
    ).first()
    if draft is None:
        return _error("草稿不存在", status=404, code="DRAFT_NOT_FOUND")
    if request.method == "GET":
        return JsonResponse({"item": _serialize_draft(draft)})
    if request.method == "DELETE":
        draft.delete()
        return JsonResponse({"ok": True})
    payload = _body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    try:
        if "title" in payload:
            draft.title = text(payload.get("title"), maximum=200)
        if "values" in payload:
            draft.values = ensure_json_object(payload.get("values"), "草稿内容")
    except ApprovalDomainError as exc:
        return _domain_error(exc)
    draft.save(update_fields=["title", "values", "updated_at"])
    return JsonResponse({"ok": True, "item": _serialize_draft(draft)})


@require_GET
def exceptions_collection(request):
    denied = _ensure_admin(request)
    if denied is not None:
        return denied
    queryset = ApprovalApplication.objects.filter(
        status=ApprovalApplication.STATUS_EXCEPTION,
    ).select_related("template_version")
    keyword = str(request.GET.get("q") or "").strip()
    if keyword:
        queryset = queryset.filter(
            Q(title__icontains=keyword)
            | Q(serial_no__icontains=keyword)
            | Q(initiator_name__icontains=keyword)
            | Q(template_version__name__icontains=keyword)
            | Q(exception_message__icontains=keyword)
        )
    return JsonResponse(_paginate(
        queryset,
        request,
        lambda item: _serialize_application(item, current_user_id=_user_id(request)),
    ))
