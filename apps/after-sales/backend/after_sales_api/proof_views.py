from __future__ import annotations

import json

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .attachment_views import _serialize_attachment
from .models import (
    MidsalesProof,
    PrivateAttachment,
    ProjectAssignment,
    ProjectNode,
    ServiceProject,
    ServiceProvider,
)
from .org_client import AuthOrgClientError
from .permissions import APP_PERMISSION_ADMIN, get_request_app_permission
from .services import (
    MIDSALES_PROOF_NODE_KEYS,
    create_audit_fields,
    record_project_event,
    request_identity,
    touch_audit,
)
from . import access
from .crm_source import assert_crm_project_access
from .services import DomainValidationError


def _text(value) -> str:
    return str(value or "").strip()


def _error(message: str, *, status: int, code: str) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message, "code": code}, status=status)


def _json_body(request) -> dict | None:
    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _proof_access(request, project_id: int, node_key: str):
    user_id = _text(getattr(request, "auth_user_id", ""))
    if not user_id:
        return None, False, False, _error("请先登录", status=401, code="AUTH_REQUIRED")
    try:
        is_admin = get_request_app_permission(request) == APP_PERMISSION_ADMIN
    except AuthOrgClientError as exc:
        return None, False, False, _error(
            str(exc),
            status=exc.status_code,
            code="AUTH_ORG_UNAVAILABLE",
        )
    if _text(request.GET.get("source")) == "mobile":
        is_admin = False

    node = ProjectNode.objects.select_related("project").filter(
        project_id=project_id,
        project__service_type=ServiceProject.TYPE_MIDSALES,
        project__deleted_at__isnull=True,
        node_key=node_key,
    ).first()
    if node is None:
        return None, is_admin, False, _error(
            "售中项目节点不存在",
            status=404,
            code="MIDSALES_NODE_NOT_FOUND",
        )
    if node.node_key not in MIDSALES_PROOF_NODE_KEYS:
        return None, is_admin, False, _error(
            "当前节点不使用证明材料",
            status=409,
            code="MIDSALES_PROOF_NOT_APPLICABLE",
        )

    can_upload = False
    if access.management_user(request):
        try:
            access.require_project(request, node.project)
            assert_crm_project_access(request, node.project, write=request.method != "GET")
            is_admin = access.can_manage_project(request, node.project)
        except DomainValidationError as exc:
            return None, False, False, _error(str(exc), code=exc.code, status=exc.status)
        return node, is_admin, False, None
    if not is_admin:
        provider = ServiceProvider.objects.filter(
            auth_user_id=user_id,
            certification_status=ServiceProvider.CERT_CERTIFIED,
        ).first()
        assignment = ProjectAssignment.objects.filter(
            provider=provider,
            project_id=project_id,
            node=node,
        ).exclude(status=ProjectAssignment.STATUS_CANCELLED).first()
        if assignment is None:
            return None, False, False, _error(
                "证明材料不存在或无权访问",
                status=404,
                code="MIDSALES_PROOF_NOT_FOUND",
            )
        can_upload = (
            assignment.status != ProjectAssignment.STATUS_COMPLETED
            and node.enabled
            and node.status != ProjectNode.STATUS_COMPLETED
        )
    return node, is_admin, can_upload, None


def _ensure_proofs(request, node: ProjectNode) -> list[MidsalesProof]:
    defaults = create_audit_fields(request)
    for proof_type, _label in MidsalesProof.TYPE_CHOICES:
        MidsalesProof.objects.get_or_create(
            node=node,
            proof_type=proof_type,
            defaults=defaults,
        )
    proof_by_type = {
        proof.proof_type: proof
        for proof in MidsalesProof.objects.filter(node=node)
    }
    return [proof_by_type[proof_type] for proof_type, _label in MidsalesProof.TYPE_CHOICES]


def _serialize_proof(
    proof: MidsalesProof,
    request,
    *,
    is_admin: bool,
    can_upload: bool,
) -> dict:
    attachments = PrivateAttachment.objects.filter(
        target_type=PrivateAttachment.TARGET_MIDSALES_PROOF,
        target_id=proof.id,
    )
    return {
        "id": proof.id,
        "projectId": proof.node.project_id,
        "nodeId": proof.node_id,
        "nodeKey": proof.node.node_key,
        "proofType": proof.proof_type,
        "proofTypeLabel": proof.get_proof_type_display(),
        "status": proof.status,
        "statusLabel": proof.get_status_display(),
        "reviewOpinion": proof.review_opinion,
        "reviewedByUserId": proof.reviewed_by_user_id,
        "reviewedByName": proof.reviewed_by_name,
        "reviewerName": proof.reviewed_by_name,
        "reviewedActorId": proof.reviewed_actor_id,
        "reviewedAt": proof.reviewed_at.isoformat() if proof.reviewed_at else "",
        "attachments": [
            _serialize_attachment(item, request, is_admin=is_admin, target=proof)
            for item in attachments
        ],
        "canUpload": can_upload and proof.status != MidsalesProof.STATUS_APPROVED,
        "canReview": bool(is_admin and access.node_abilities(request, proof.node)["canEdit"]),
        "createdAt": proof.created_at.isoformat() if proof.created_at else "",
        "updatedAt": proof.updated_at.isoformat() if proof.updated_at else "",
    }


@require_GET
def midsales_proofs(request, project_id: int, node_key: str):
    node, is_admin, can_upload, failure = _proof_access(request, project_id, node_key)
    if failure is not None:
        return failure
    proofs = _ensure_proofs(request, node)
    return JsonResponse({
        "items": [
            _serialize_proof(
                proof,
                request,
                is_admin=is_admin,
                can_upload=can_upload,
            )
            for proof in proofs
        ],
        "projectId": project_id,
        "nodeId": node.id,
        "nodeKey": node.node_key,
        "canUpload": can_upload,
        "canReview": bool(is_admin and access.node_abilities(request, node)["canEdit"]),
    })


@csrf_exempt
@require_POST
@transaction.atomic
def midsales_proof_review(request, project_id: int, node_key: str, proof_type: str):
    node, is_admin, can_upload, failure = _proof_access(request, project_id, node_key)
    if failure is not None:
        return failure
    if not is_admin:
        return _error("只有项目负责人、业务管理或应用管理员可以审核证明材料", status=403, code="APP_ADMIN_REQUIRED")
    project = ServiceProject.objects.select_for_update().get(pk=node.project_id)
    node = ProjectNode.objects.select_for_update().get(pk=node.pk)
    node.project = project
    if not access.node_abilities(request, node)["canEdit"]:
        return _error("已结束的节点资料只读，不能审核证明材料", status=409, code="PROJECT_NODE_READ_ONLY")
    valid_types = {value for value, _label in MidsalesProof.TYPE_CHOICES}
    if proof_type not in valid_types:
        return _error("证明材料类型无效", status=400, code="INVALID_MIDSALES_PROOF_TYPE")
    payload = _json_body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    status = _text(payload.get("status"))
    valid_statuses = {value for value, _label in MidsalesProof.STATUS_CHOICES}
    if status not in valid_statuses:
        return _error("审核状态无效", status=400, code="INVALID_MIDSALES_PROOF_STATUS")
    opinion = _text(payload.get("opinion") or payload.get("reviewOpinion"))
    if len(opinion) > 20_000:
        return _error("审核意见不能超过20000字", status=400, code="MIDSALES_PROOF_OPINION_TOO_LONG")
    if status == MidsalesProof.STATUS_REJECTED and not opinion:
        return _error("驳回时必须填写审核意见", status=400, code="MIDSALES_PROOF_REJECT_REASON_REQUIRED")

    proof, _created = MidsalesProof.objects.select_for_update().get_or_create(
        node=node,
        proof_type=proof_type,
        defaults=create_audit_fields(request),
    )
    attachment_count = PrivateAttachment.objects.filter(
        target_type=PrivateAttachment.TARGET_MIDSALES_PROOF,
        target_id=proof.id,
    ).count()
    if status == MidsalesProof.STATUS_APPROVED and attachment_count == 0:
        return _error("没有上传材料，不能审核通过", status=409, code="MIDSALES_PROOF_FILE_REQUIRED")

    previous = {
        "status": proof.status,
        "opinion": proof.review_opinion,
    }
    identity = request_identity(request)
    proof.status = status
    proof.review_opinion = opinion
    proof.reviewed_by_user_id = identity["user_id"]
    proof.reviewed_by_name = identity["user_name"]
    proof.reviewed_actor_id = identity["actor_id"]
    proof.reviewed_at = timezone.now()
    touch_audit(proof, request)
    proof.save()
    record_project_event(
        request,
        node.project,
        node=node,
        event_type="midsales_proof_review",
        title=f"{proof.get_proof_type_display()}审核：{proof.get_status_display()}",
        detail=opinion,
        before=previous,
        after={
            "proofType": proof.proof_type,
            "status": proof.status,
            "opinion": proof.review_opinion,
            "attachmentCount": attachment_count,
        },
    )
    return JsonResponse({
        "ok": True,
        "item": _serialize_proof(
            proof,
            request,
            is_admin=True,
            can_upload=can_upload,
        ),
    })
