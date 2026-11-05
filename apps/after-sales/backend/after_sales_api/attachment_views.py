from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .models import (
    FieldFeedback,
    MidsalesProof,
    PrivateAttachment,
    ProjectAssignment,
    ProjectNode,
    ServiceProject,
    ServiceProvider,
    ServiceResource,
    ServiceTicket,
)
from .org_client import AuthOrgClientError
from .permissions import APP_PERMISSION_ADMIN, get_request_app_permission
from .crm_source import assert_crm_project_access
from . import access
from .services import DomainValidationError


MAX_ATTACHMENT_SIZE = 200 * 1024 * 1024
MAX_DATABASE_ID = 9_223_372_036_854_775_807
MAX_DATABASE_ID_TEXT = str(MAX_DATABASE_ID)
TARGET_TYPES = {
    value
    for value, _label in PrivateAttachment.TARGET_CHOICES
    if value != PrivateAttachment.TARGET_CASE
}
ATTACHMENT_CATEGORIES = {value for value, _label in PrivateAttachment.CATEGORY_CHOICES}
MIDSALES_FIELD_ATTACHMENT_NODE_KEYS = {
    "construction-work",
    "furniture-install",
    "device-install",
    "device-debug",
    "school-support",
    "project-acceptance",
}
AFTERSALES_FIELD_ATTACHMENT_NODE_KEYS = {
    "onsite-service",
    "school-inspection",
}
AFTERSALES_FIELD_ATTACHMENT_CATEGORIES = {
    PrivateAttachment.CATEGORY_GENERAL,
    PrivateAttachment.CATEGORY_PACKAGE,
    PrivateAttachment.CATEGORY_MODEL_LABEL,
    PrivateAttachment.CATEGORY_APPEARANCE,
    PrivateAttachment.CATEGORY_INSTALLATION,
    PrivateAttachment.CATEGORY_DEBUGGING,
    PrivateAttachment.CATEGORY_OTHER,
    PrivateAttachment.CATEGORY_FEE_ACTUAL,
}
def _text(value) -> str:
    return str(value or "").strip()


def _error(message: str, *, status: int, code: str) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message, "code": code}, status=status)


def _request_is_admin(request) -> tuple[bool, JsonResponse | None]:
    try:
        permission = get_request_app_permission(request)
    except AuthOrgClientError as exc:
        return False, _error(str(exc), status=exc.status_code, code="AUTH_ORG_UNAVAILABLE")
    return permission == APP_PERMISSION_ADMIN, None


def _database_id(value) -> int:
    normalized = _text(value)
    if not normalized or not normalized.isascii() or not normalized.isdigit():
        return 0
    normalized = normalized.lstrip("0")
    if not normalized:
        return 0
    if len(normalized) > len(MAX_DATABASE_ID_TEXT):
        return 0
    if len(normalized) == len(MAX_DATABASE_ID_TEXT) and normalized > MAX_DATABASE_ID_TEXT:
        return 0
    return int(normalized)


def _parse_target(target_type_value, target_id_value) -> tuple[str, int, JsonResponse | None]:
    target_type = _text(target_type_value)
    if target_type not in TARGET_TYPES:
        return "", 0, _error("附件目标类型无效", status=400, code="INVALID_ATTACHMENT_TARGET_TYPE")
    target_id = _database_id(target_id_value)
    if not target_id:
        return "", 0, _error("附件目标ID无效", status=400, code="INVALID_ATTACHMENT_TARGET_ID")
    return target_type, target_id, None


def _current_provider(user_id: str) -> ServiceProvider | None:
    if not user_id:
        return None
    return ServiceProvider.objects.filter(auth_user_id=user_id).first()


def _has_node_assignment(provider: ServiceProvider | None, *, project_id: int, node_id: int) -> bool:
    if provider is None:
        return False
    return ProjectAssignment.objects.filter(
        provider=provider,
        project_id=project_id,
        node_id=node_id,
    ).exclude(status=ProjectAssignment.STATUS_CANCELLED).exists()


def _can_read_resource(resource: ServiceResource, provider: ServiceProvider | None) -> bool:
    if not resource.enabled or (resource.project_id and resource.project.deleted_at):
        return False
    if resource.audience == ServiceResource.AUDIENCE_PUBLIC:
        return True
    if resource.audience != ServiceResource.AUDIENCE_ASSIGNED or provider is None or not resource.project_id:
        return False

    assignments = ProjectAssignment.objects.filter(
        provider=provider,
        project_id=resource.project_id,
    ).exclude(status=ProjectAssignment.STATUS_CANCELLED)
    if resource.node_key:
        assignments = assignments.filter(node__node_key=resource.node_key)
    return assignments.exists()


def _provider_can_write_node(provider, node):
    return bool(provider and node.enabled and node.status == ProjectNode.STATUS_ACTIVE and ProjectAssignment.objects.filter(
        provider=provider, project_id=node.project_id, node_id=node.pk,
        status__in=[ProjectAssignment.STATUS_ASSIGNED, ProjectAssignment.STATUS_ACCEPTED, ProjectAssignment.STATUS_IN_PROGRESS],
    ).exists())


def _writable_node_target(target_type, target, is_admin, write, provider=None):
    if write and target_type == PrivateAttachment.TARGET_PRESALES_PROJECT:
        project = ServiceProject.objects.select_for_update().get(pk=target.pk)
        if project.deleted_at:
            return None, is_admin, _error("已删除项目不能修改需求文档", status=409, code="PROJECT_DELETED")
        return project, is_admin, None
    if not write or target_type not in {PrivateAttachment.TARGET_PROJECT_NODE, PrivateAttachment.TARGET_MIDSALES_PROOF}:
        return target, is_admin, None
    node = target.node if target_type == PrivateAttachment.TARGET_MIDSALES_PROOF else target
    # Serialize attachment writes with node/round advancement, in the same lock order.
    project = ServiceProject.objects.select_for_update().get(pk=node.project_id)
    node = ProjectNode.objects.select_for_update().get(pk=node.pk)
    if (project.deleted_at or project.status in {ServiceProject.STATUS_COMPLETED, ServiceProject.STATUS_CANCELLED}
            or not node.enabled or node.status in {ProjectNode.STATUS_COMPLETED, ProjectNode.STATUS_SKIPPED}):
        return None, is_admin, _error("已结束的节点资料只读，不能上传或删除附件", status=409, code="PROJECT_NODE_READ_ONLY")
    if provider is not None and not _provider_can_write_node(provider, node):
        return None, is_admin, _error("任务已提交或尚未开始，附件只能查看", status=409, code="PROJECT_TASK_READ_ONLY")
    if target_type == PrivateAttachment.TARGET_PROJECT_NODE:
        node.project = project
        target = node
    else:
        target = MidsalesProof.objects.select_for_update().get(pk=target.pk)
        target.node = node
        if target.status == MidsalesProof.STATUS_APPROVED:
            return None, is_admin, _error("审核通过的证明材料只读，不能上传或删除", status=409, code="MIDSALES_PROOF_APPROVED_READ_ONLY")
    return target, is_admin, None


def _historical_round_attachment(node, item):
    if node.project.service_type != ServiceProject.TYPE_PRESALES:
        return False
    rounds = (node.business_data or {}).get("schemeRounds", [])
    if not isinstance(rounds, list):
        return False
    # Reasons are part of the recorded decision, even for the current round.
    return any(isinstance(row, dict) and str(item.id) in {str(value) for value in row.get("reasonAttachmentIds", [])}
               for row in rounds) or any(
        isinstance(row, dict) and str(item.id) in {str(value) for value in row.get("attachmentIds", [])}
        for row in rounds[:-1]
    )


def _target_access(
    request,
    target_type: str,
    target_id: int,
    *,
    write: bool = False,
) -> tuple[object | None, bool, JsonResponse | None]:
    user_id = _text(getattr(request, "auth_user_id", ""))
    if not user_id:
        return None, False, _error("请先登录", status=401, code="AUTH_REQUIRED")

    is_admin, failure = _request_is_admin(request)
    if failure is not None:
        return None, False, failure

    if target_type not in TARGET_TYPES:
        return None, is_admin, _error(
            "附件目标不存在或无权访问",
            status=404,
            code="ATTACHMENT_TARGET_NOT_FOUND",
        )

    model_by_target = {
        PrivateAttachment.TARGET_TICKET: ServiceTicket,
        PrivateAttachment.TARGET_FEEDBACK: FieldFeedback,
        PrivateAttachment.TARGET_PROJECT_NODE: ProjectNode,
        PrivateAttachment.TARGET_PRESALES_PROJECT: ServiceProject,
        PrivateAttachment.TARGET_RESOURCE: ServiceResource,
        PrivateAttachment.TARGET_PROVIDER_APPLICATION: ServiceProvider,
        PrivateAttachment.TARGET_MIDSALES_PROOF: MidsalesProof,
    }
    queryset = model_by_target[target_type].objects.all()
    if target_type == PrivateAttachment.TARGET_RESOURCE:
        queryset = queryset.select_related("project")
    elif target_type == PrivateAttachment.TARGET_MIDSALES_PROOF:
        queryset = queryset.select_related("node__project")
    target = queryset.filter(pk=target_id).first()
    if target is None:
        return None, is_admin, _error(
            "附件目标不存在或无权访问",
            status=404,
            code="ATTACHMENT_TARGET_NOT_FOUND",
        )
    if access.management_user(request):
        project = target if target_type == PrivateAttachment.TARGET_PRESALES_PROJECT else (
            target.node.project if target_type == PrivateAttachment.TARGET_MIDSALES_PROOF else getattr(target, "project", None)
        )
        try:
            if not _management_target_allowed(request, target_type, target, write):
                return None, False, _error("附件目标不存在或无权访问", status=403, code="ATTACHMENT_PERMISSION_DENIED")
            if project is not None:
                assert_crm_project_access(request, project, write=write)
        except DomainValidationError as exc:
            return None, False, _error(str(exc), status=exc.status, code=exc.code)
        except AuthOrgClientError as exc:
            return None, False, _error(str(exc), status=exc.status_code, code="AUTH_ORG_UNAVAILABLE")
        return _writable_node_target(target_type, target, True, write)

    provider = _current_provider(user_id)
    if target_type != PrivateAttachment.TARGET_PROVIDER_APPLICATION and (
        provider is None or provider.certification_status != ServiceProvider.CERT_CERTIFIED
    ):
        return None, False, _error("服务人员尚未审核通过或已暂停", status=403, code="SERVICE_PROVIDER_NOT_CERTIFIED")
    allowed = False
    if target_type == PrivateAttachment.TARGET_TICKET:
        allowed = user_id in {target.reporter_user_id, target.owner_user_id}
        if not allowed and target.node_id:
            allowed = _has_node_assignment(
                provider,
                project_id=target.project_id,
                node_id=target.node_id,
            )
    elif target_type == PrivateAttachment.TARGET_FEEDBACK:
        allowed = provider is not None and target.provider_id == provider.id
    elif target_type == PrivateAttachment.TARGET_PROJECT_NODE:
        allowed = target.project.service_type != ServiceProject.TYPE_PRESALES and _has_node_assignment(
            provider,
            project_id=target.project_id,
            node_id=target.id,
        )
        if write and target.project.service_type == ServiceProject.TYPE_AFTERSALES:
            if target.node_key in AFTERSALES_FIELD_ATTACHMENT_NODE_KEYS:
                allowed = allowed and target.enabled and target.status == ProjectNode.STATUS_ACTIVE and ProjectAssignment.objects.filter(
                    provider=provider,
                    project_id=target.project_id,
                    node_id=target.id,
                    status__in=[
                        ProjectAssignment.STATUS_ASSIGNED,
                        ProjectAssignment.STATUS_ACCEPTED,
                        ProjectAssignment.STATUS_IN_PROGRESS,
                    ],
                ).exists()
    elif target_type == PrivateAttachment.TARGET_RESOURCE:
        allowed = not write and _can_read_resource(target, provider)
    elif target_type == PrivateAttachment.TARGET_PROVIDER_APPLICATION:
        allowed = target.auth_user_id == user_id
    elif target_type == PrivateAttachment.TARGET_MIDSALES_PROOF:
        allowed = (
            provider is not None
            and provider.certification_status == ServiceProvider.CERT_CERTIFIED
            and _has_node_assignment(
                provider,
                project_id=target.node.project_id,
                node_id=target.node_id,
            )
        )
        if write:
            allowed = allowed and target.node.enabled and target.node.status != ProjectNode.STATUS_COMPLETED

    if not allowed:
        return None, False, _error(
            "附件目标不存在或无权访问",
            status=404,
            code="ATTACHMENT_TARGET_NOT_FOUND",
        )
    return _writable_node_target(target_type, target, False, write, provider=provider)


def _management_target_allowed(request, target_type, target, write):
    if target_type == PrivateAttachment.TARGET_PRESALES_PROJECT:
        return (target.service_type == ServiceProject.TYPE_PRESALES
                and access.can_read_project(request, target)
                and (not write or access.can_manage_project(request, target)))
    if target_type == PrivateAttachment.TARGET_PROVIDER_APPLICATION:
        return access.manages_service(request) if write else access.can_use_management(request)
    node = target.node if target_type == PrivateAttachment.TARGET_MIDSALES_PROOF else None
    project = node.project if node else getattr(target, "project", None)
    if project is not None and not access.can_read_project(request, project):
        return False
    if not write:
        return True
    if target_type == PrivateAttachment.TARGET_PROJECT_NODE:
        return access.can_edit_node(request, target)
    if node is not None:
        return access.can_manage_project(request, project)
    if target_type == PrivateAttachment.TARGET_TICKET:
        return access.can_manage_project(request, project) or request.auth_user_id in {target.owner_user_id, target.reporter_user_id}
    if target_type == PrivateAttachment.TARGET_FEEDBACK:
        return access.manages_business(request)
    return access.can_manage_project(request, project) if project else access.manages_business(request)


def _safe_original_name(value: str) -> str:
    return _text(value).replace("\\", "/").rsplit("/", 1)[-1]


def _validate_upload(upload) -> tuple[str, str, JsonResponse | None]:
    original_name = _safe_original_name(getattr(upload, "name", ""))
    if not original_name or len(original_name) > 255 or "\x00" in original_name:
        return "", "", _error("文件名无效或过长", status=400, code="INVALID_ATTACHMENT_NAME")

    size = getattr(upload, "size", 0) or 0
    if size <= 0:
        return "", "", _error("不能上传空文件", status=400, code="EMPTY_ATTACHMENT")
    if size > MAX_ATTACHMENT_SIZE:
        return "", "", _error("单个附件不能超过200MB", status=400, code="ATTACHMENT_TOO_LARGE")

    mime_type = _text(getattr(upload, "content_type", "")).lower().split(";", 1)[0].strip()
    if not mime_type or len(mime_type) > 127 or "\r" in mime_type or "\n" in mime_type:
        mime_type = "application/octet-stream"
    return original_name, mime_type, None


def _serialize_attachment(item: PrivateAttachment, request, *, is_admin: bool, target) -> dict:
    user_id = _text(getattr(request, "auth_user_id", ""))
    management = access.management_user(request)
    is_admin = is_admin or management
    node = target if item.target_type == PrivateAttachment.TARGET_PROJECT_NODE else (
        target.node if item.target_type == PrivateAttachment.TARGET_MIDSALES_PROOF else None
    )
    field_owned = item.target_type == PrivateAttachment.TARGET_MIDSALES_PROOF
    if item.target_type == PrivateAttachment.TARGET_PROJECT_NODE:
        field_owned = (
            node.project.service_type == ServiceProject.TYPE_MIDSALES and (
                item.category == PrivateAttachment.CATEGORY_FEE_ACTUAL or (
                    item.category == PrivateAttachment.CATEGORY_GENERAL
                    and node.node_key in MIDSALES_FIELD_ATTACHMENT_NODE_KEYS
                )
            )
        ) or (
            node.project.service_type == ServiceProject.TYPE_AFTERSALES
            and node.node_key in AFTERSALES_FIELD_ATTACHMENT_NODE_KEYS
            and item.category in AFTERSALES_FIELD_ATTACHMENT_CATEGORIES
        )
    can_delete = not (is_admin and field_owned) and (
        is_admin
        or (item.target_type != PrivateAttachment.TARGET_RESOURCE and item.uploaded_by == user_id)
    )
    if management:
        can_delete = can_delete and _management_target_allowed(request, item.target_type, target, True)
    if item.target_type == PrivateAttachment.TARGET_PRESALES_PROJECT:
        can_delete = can_delete and not target.deleted_at
    if node is not None:
        can_delete = can_delete and node.enabled and node.status not in {ProjectNode.STATUS_COMPLETED, ProjectNode.STATUS_SKIPPED} \
            and not node.project.deleted_at and node.project.status not in {ServiceProject.STATUS_COMPLETED, ServiceProject.STATUS_CANCELLED} \
            and not _historical_round_attachment(node, item)
        if not management:
            can_delete = can_delete and _provider_can_write_node(_current_provider(user_id), node)
        if item.target_type == PrivateAttachment.TARGET_MIDSALES_PROOF:
            can_delete = can_delete and target.status != MidsalesProof.STATUS_APPROVED
    return {
        "id": item.id,
        "targetType": item.target_type,
        "targetId": item.target_id,
        "category": item.category,
        "categoryLabel": item.get_category_display(),
        "originalName": item.original_name,
        "mimeType": item.mime_type,
        "size": item.size,
        "uploadedBy": item.uploaded_by,
        "uploadedActorId": item.uploaded_actor_id,
        "createdAt": item.created_at.isoformat() if item.created_at else "",
        "downloadUrl": f"/api/after-sales/attachments/{item.id}/download",
        "canDelete": can_delete,
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
@transaction.atomic
def attachments_collection(request):
    values = request.GET if request.method == "GET" else request.POST
    target_type, target_id, failure = _parse_target(
        values.get("targetType") or values.get("target_type"),
        values.get("targetId") or values.get("target_id"),
    )
    if failure is not None:
        return failure

    target, is_admin, failure = _target_access(
        request,
        target_type,
        target_id,
        write=request.method == "POST",
    )
    if failure is not None:
        return failure

    if request.method == "GET":
        rows = PrivateAttachment.objects.filter(target_type=target_type, target_id=target_id)
        originals = {}
        if target_type == PrivateAttachment.TARGET_PRESALES_PROJECT:
            # Preserve the original approval documents without moving files or
            # weakening the read-only protection of completed approval nodes.
            originals = {node.pk: node for node in ProjectNode.objects.filter(
                project=target, node_key="early-approval", enabled=True,
            ).select_related("project")}
            rows = PrivateAttachment.objects.filter(
                Q(target_type=target_type, target_id=target_id)
                | Q(target_type=PrivateAttachment.TARGET_PROJECT_NODE, target_id__in=originals),
                category=PrivateAttachment.CATEGORY_GENERAL,
            )
        return JsonResponse({
            "items": [_serialize_attachment(row, request, is_admin=is_admin, target=(
                originals[row.target_id] if row.target_type == PrivateAttachment.TARGET_PROJECT_NODE and originals else target
            )) for row in rows],
            "targetType": target_type,
            "targetId": target_id,
        })

    upload = request.FILES.get("file")
    if upload is None:
        return _error("请选择要上传的文件", status=400, code="ATTACHMENT_FILE_REQUIRED")
    original_name, mime_type, failure = _validate_upload(upload)
    if failure is not None:
        return failure

    category = _text(values.get("category")) or PrivateAttachment.CATEGORY_GENERAL
    if category not in ATTACHMENT_CATEGORIES:
        return _error("附件分类无效", status=400, code="INVALID_ATTACHMENT_CATEGORY")
    if target_type == PrivateAttachment.TARGET_PRESALES_PROJECT and category != PrivateAttachment.CATEGORY_GENERAL:
        return _error("项目需求文档不支持此附件分类", status=400, code="INVALID_ATTACHMENT_CATEGORY")
    if (target_type == PrivateAttachment.TARGET_PROJECT_NODE
            and target.project.service_type == ServiceProject.TYPE_PRESALES
            and category == PrivateAttachment.CATEGORY_SCHEME_SUBMISSION):
        rounds = (target.business_data or {}).get("schemeRounds", [])
        latest_index = max(0, len(rounds) - 1)
        raw_index = values.get("roundIndex")
        if raw_index is None and len(rounds) <= 1:
            round_index = latest_index
        elif isinstance(raw_index, str) and raw_index.isascii() and raw_index.isdigit() and len(raw_index) <= 10:
            round_index = int(raw_index)
        else:
            round_index = -1
        requested_id = _text(values.get("roundId"))
        if round_index != latest_index or (requested_id and (not rounds or rounds[-1].get("roundId") != requested_id)):
            return _error("历史轮次只读，请打开最新一轮上传附件", status=409, code="PRESALES_ROUND_READ_ONLY")
    midsales_project_node = (
        target_type == PrivateAttachment.TARGET_PROJECT_NODE
        and target.project.service_type == ServiceProject.TYPE_MIDSALES
    )
    if midsales_project_node and not is_admin and category == PrivateAttachment.CATEGORY_FEE_ESTIMATED:
        return _error(
            "售中预计费用清单由管理端维护，现场端只能查看",
            status=403,
            code="MIDSALES_ESTIMATED_FEE_ADMIN_ONLY",
        )
    aftersales_field_node = (
        target_type == PrivateAttachment.TARGET_PROJECT_NODE
        and target.project.service_type == ServiceProject.TYPE_AFTERSALES
        and target.node_key in AFTERSALES_FIELD_ATTACHMENT_NODE_KEYS
    )
    if aftersales_field_node and not is_admin and category not in AFTERSALES_FIELD_ATTACHMENT_CATEGORIES:
        return _error(
            "售后现场端只能上传实际费用和完工资料",
            status=403,
            code="AFTERSALES_ATTACHMENT_CATEGORY_FORBIDDEN",
        )
    admin_field_upload = is_admin and (
        target_type == PrivateAttachment.TARGET_MIDSALES_PROOF
        or (
            midsales_project_node
            and (
                category == PrivateAttachment.CATEGORY_FEE_ACTUAL
                or (
                    category == PrivateAttachment.CATEGORY_GENERAL
                    and target.node_key in MIDSALES_FIELD_ATTACHMENT_NODE_KEYS
                )
            )
            )
        or (
            target_type == PrivateAttachment.TARGET_PROJECT_NODE
            and target.project.service_type == ServiceProject.TYPE_AFTERSALES
            and target.node_key in AFTERSALES_FIELD_ATTACHMENT_NODE_KEYS
            and category in AFTERSALES_FIELD_ATTACHMENT_CATEGORIES
        )
    )
    if admin_field_upload:
        return _error(
            "现场交付附件由现场人员上传，管理端只能查看",
            status=403,
            code="MIDSALES_ATTACHMENT_FIELD_UPLOAD_ONLY",
        )

    user_id = _text(getattr(request, "auth_user_id", ""))
    actor_id = _text(getattr(request, "auth_actor_user_id", "")) or user_id
    item = PrivateAttachment.objects.create(
        target_type=target_type,
        target_id=target_id,
        category=category,
        file=upload,
        original_name=original_name,
        mime_type=mime_type,
        size=upload.size,
        uploaded_by=user_id,
        uploaded_actor_id=actor_id,
    )
    return JsonResponse(
        {"ok": True, "item": _serialize_attachment(item, request, is_admin=is_admin, target=target)},
        status=201,
    )


@require_GET
def attachment_download(request, attachment_id: int):
    attachment_id = _database_id(attachment_id)
    if not attachment_id:
        return _error("附件不存在或无权访问", status=404, code="ATTACHMENT_NOT_FOUND")
    item = PrivateAttachment.objects.filter(pk=attachment_id).first()
    if item is None:
        return _error("附件不存在或无权访问", status=404, code="ATTACHMENT_NOT_FOUND")
    _target, _is_admin, failure = _target_access(request, item.target_type, item.target_id)
    if failure is not None:
        return _error("附件不存在或无权访问", status=404, code="ATTACHMENT_NOT_FOUND") if failure.status_code in {403, 404} else failure
    try:
        file_handle = item.file.open("rb")
    except (FileNotFoundError, OSError):
        return _error("附件文件不存在", status=404, code="ATTACHMENT_FILE_NOT_FOUND")
    response = FileResponse(
        file_handle,
        as_attachment=True,
        filename=item.original_name,
        content_type=item.mime_type or "application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@csrf_exempt
@require_http_methods(["DELETE"])
@transaction.atomic
def attachment_item(request, attachment_id: int):
    attachment_id = _database_id(attachment_id)
    if not attachment_id:
        return _error("附件不存在或无权访问", status=404, code="ATTACHMENT_NOT_FOUND")
    item = PrivateAttachment.objects.filter(pk=attachment_id).first()
    if item is None:
        return _error("附件不存在或无权访问", status=404, code="ATTACHMENT_NOT_FOUND")
    _target, is_admin, failure = _target_access(
        request,
        item.target_type,
        item.target_id,
        write=True,
    )
    if failure is not None:
        return _error("附件不存在或无权访问", status=404, code="ATTACHMENT_NOT_FOUND") if failure.status_code in {403, 404} else failure

    if item.target_type == PrivateAttachment.TARGET_PROJECT_NODE and _historical_round_attachment(_target, item):
        return _error("历史轮次附件只读，不能删除", status=409, code="PRESALES_ROUND_READ_ONLY")

    user_id = _text(getattr(request, "auth_user_id", ""))
    if is_admin and not _serialize_attachment(item, request, is_admin=True, target=_target)["canDelete"]:
        return _error(
            "现场交付附件由现场人员维护，管理端不能删除",
            status=403,
            code="MIDSALES_ATTACHMENT_FIELD_UPLOAD_ONLY",
        )
    if not is_admin and item.uploaded_by != user_id:
        return _error("只能删除自己上传的附件", status=403, code="ATTACHMENT_DELETE_FORBIDDEN")

    storage = item.file.storage
    stored_name = item.file.name
    item.delete()
    if stored_name:
        storage.delete(stored_name)
    return JsonResponse({"ok": True})
