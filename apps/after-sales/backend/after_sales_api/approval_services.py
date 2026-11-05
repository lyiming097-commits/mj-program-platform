from __future__ import annotations

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .approval_models import PresalesApprovalRevision, PresalesApprovalStep
from .models import ProjectNode, ServiceProject
from .services import (
    DomainValidationError,
    create_audit_fields,
    record_project_event,
    request_identity,
    text,
    touch_audit,
)


PRESALES_APPROVAL_NODE_KEYS = {"early-approval", "late-approval"}
DEFAULT_APPROVAL_STEPS = [
    ("组长审批", "组长-陈明"),
    ("区域经理审批", "区域经理-周宁"),
]
MAX_APPROVAL_STEPS = 20
MAX_OPINION_LENGTH = 5000


def _required(value, label: str, *, max_length: int) -> str:
    normalized = text(value)
    if not normalized:
        raise DomainValidationError(f"{label}不能为空", code="FIELD_REQUIRED")
    if len(normalized) > max_length:
        raise DomainValidationError(f"{label}不能超过 {max_length} 个字符", code="FIELD_TOO_LONG")
    return normalized


def _optional(value, label: str, *, max_length: int) -> str:
    normalized = text(value)
    if len(normalized) > max_length:
        raise DomainValidationError(f"{label}不能超过 {max_length} 个字符", code="FIELD_TOO_LONG")
    return normalized


def _approval_status(value, *, default: str = "") -> str:
    normalized = text(value) or default
    choices = {choice[0] for choice in PresalesApprovalStep.STATUS_CHOICES}
    if normalized not in choices:
        raise DomainValidationError("审批结果无效", code="INVALID_APPROVAL_STATUS")
    return normalized


def validate_approval_node(node: ProjectNode) -> None:
    if (
        node.project.service_type != ServiceProject.TYPE_PRESALES
        or node.node_key not in PRESALES_APPROVAL_NODE_KEYS
        or node.kind != "approval"
    ):
        raise DomainValidationError(
            "只有售前立项节点可以维护审批流程",
            code="PRESALES_APPROVAL_NODE_REQUIRED",
            status=409,
        )


def _approval_read_only(node):
    return (node.project.deleted_at or node.project.status in {ServiceProject.STATUS_COMPLETED, ServiceProject.STATUS_CANCELLED}
            or not node.enabled or node.status in {ProjectNode.STATUS_COMPLETED, ProjectNode.STATUS_SKIPPED})


def _locked_approval_node(node, *, write=True):
    project = ServiceProject.objects.select_for_update().get(pk=node.project_id)
    node = ProjectNode.objects.select_for_update().get(pk=node.pk)
    node.project = project
    validate_approval_node(node)
    if write and _approval_read_only(node):
        raise DomainValidationError("已结束的节点资料只读，不能修改审批记录", code="PROJECT_NODE_READ_ONLY", status=409)
    return node


def _append_revision(step: PresalesApprovalStep, request) -> PresalesApprovalRevision:
    identity = request_identity(request)
    next_revision = (
        PresalesApprovalRevision.objects.filter(step=step).aggregate(value=Max("revision"))["value"] or 0
    ) + 1
    return PresalesApprovalRevision.objects.create(
        step=step,
        revision=next_revision,
        title=step.title,
        approver_user_id=step.approver_user_id,
        approver_name=step.approver_name,
        status=step.status,
        opinion=step.opinion,
        decided_at=step.decided_at,
        recorded_by_user_id=identity["user_id"],
        recorded_by_name=identity["user_name"],
        recorded_actor_id=identity["actor_id"],
    )


def _sync_node_business_data(node: ProjectNode) -> None:
    rows = PresalesApprovalStep.objects.filter(node=node).order_by("sequence", "id")
    data = dict(node.business_data) if isinstance(node.business_data, dict) else {}
    data["approvalSteps"] = [
        {
            "id": row.id,
            "sequence": row.sequence,
            "title": row.title,
            "approverUserId": row.approver_user_id,
            "approverName": row.approver_name,
            "status": row.status,
            "opinion": row.opinion,
            "decidedAt": row.decided_at.isoformat() if row.decided_at else None,
        }
        for row in rows
    ]
    ProjectNode.objects.filter(pk=node.pk).update(business_data=data)


@transaction.atomic
def ensure_default_approval_steps(node: ProjectNode, request) -> list[PresalesApprovalStep]:
    node = _locked_approval_node(node, write=False)
    existing = list(PresalesApprovalStep.objects.filter(node=node).prefetch_related("revisions"))
    if _approval_read_only(node):
        return existing
    node_data = node.business_data if isinstance(node.business_data, dict) else {}
    if existing or "approvalSteps" in node_data:
        _sync_node_business_data(node)
        return existing

    for sequence, (title, approver_name) in enumerate(DEFAULT_APPROVAL_STEPS, start=1):
        step = PresalesApprovalStep.objects.create(
            node=node,
            sequence=sequence,
            title=title,
            approver_name=approver_name,
            **create_audit_fields(request),
        )
        _append_revision(step, request)
    _sync_node_business_data(node)
    return list(
        PresalesApprovalStep.objects.filter(node=node).prefetch_related("revisions")
    )


@transaction.atomic
def create_approval_step(request, node: ProjectNode, values: dict) -> PresalesApprovalStep:
    node = _locked_approval_node(node)
    current_count = PresalesApprovalStep.objects.filter(node=node).count()
    if current_count >= MAX_APPROVAL_STEPS:
        raise DomainValidationError(
            f"审批行不能超过 {MAX_APPROVAL_STEPS} 条",
            code="APPROVAL_STEP_LIMIT_REACHED",
            status=409,
        )
    sequence = (
        PresalesApprovalStep.objects.filter(node=node).aggregate(value=Max("sequence"))["value"] or 0
    ) + 1
    status = _approval_status(values.get("status"), default=PresalesApprovalStep.STATUS_PENDING)
    opinion = _optional(values.get("opinion"), "审批意见", max_length=MAX_OPINION_LENGTH)
    if status == PresalesApprovalStep.STATUS_REJECTED and not opinion:
        raise DomainValidationError("驳回时必须填写审批意见", code="APPROVAL_OPINION_REQUIRED")
    step = PresalesApprovalStep.objects.create(
        node=node,
        sequence=sequence,
        title=_required(values.get("title"), "审批节点", max_length=128),
        approver_user_id=_optional(values.get("approverUserId"), "审批人ID", max_length=64),
        approver_name=_required(values.get("approverName"), "审批人", max_length=128),
        status=status,
        opinion=opinion,
        decided_at=timezone.now() if status != PresalesApprovalStep.STATUS_PENDING else None,
        **create_audit_fields(request),
    )
    _append_revision(step, request)
    _sync_node_business_data(node)
    record_project_event(
        request,
        node.project,
        node=node,
        event_type="presales_approval_step_added",
        title=f"增加审批行：{step.title}",
        detail=step.approver_name,
        after={"approvalStepId": step.id, "sequence": step.sequence, "status": step.status},
    )
    return PresalesApprovalStep.objects.prefetch_related("revisions").get(pk=step.pk)


@transaction.atomic
def update_approval_step(
    request,
    node: ProjectNode,
    step_id: int,
    values: dict,
    *,
    expected_revision: int | None = None,
) -> PresalesApprovalStep:
    node = _locked_approval_node(node)
    try:
        step = PresalesApprovalStep.objects.select_for_update().get(pk=step_id, node=node)
    except PresalesApprovalStep.DoesNotExist as exc:
        raise DomainValidationError("审批行不存在", code="APPROVAL_STEP_NOT_FOUND", status=404) from exc

    latest_revision = (
        PresalesApprovalRevision.objects.filter(step=step).aggregate(value=Max("revision"))["value"] or 0
    )
    if expected_revision is not None and expected_revision != latest_revision:
        raise DomainValidationError(
            "审批行已被其他人修改，请刷新后重试",
            code="APPROVAL_REVISION_CONFLICT",
            status=409,
        )

    title = (
        _required(values.get("title"), "审批节点", max_length=128)
        if "title" in values
        else step.title
    )
    approver_user_id = (
        _optional(values.get("approverUserId"), "审批人ID", max_length=64)
        if "approverUserId" in values
        else step.approver_user_id
    )
    approver_name = (
        _required(values.get("approverName"), "审批人", max_length=128)
        if "approverName" in values
        else step.approver_name
    )
    status = (
        _approval_status(values.get("status"))
        if "status" in values
        else step.status
    )
    opinion = (
        _optional(values.get("opinion"), "审批意见", max_length=MAX_OPINION_LENGTH)
        if "opinion" in values
        else step.opinion
    )
    if status == PresalesApprovalStep.STATUS_REJECTED and not opinion:
        raise DomainValidationError("驳回时必须填写审批意见", code="APPROVAL_OPINION_REQUIRED")

    before = {
        "title": step.title,
        "approverUserId": step.approver_user_id,
        "approverName": step.approver_name,
        "status": step.status,
        "opinion": step.opinion,
    }
    after = {
        "title": title,
        "approverUserId": approver_user_id,
        "approverName": approver_name,
        "status": status,
        "opinion": opinion,
    }
    if before == after:
        _sync_node_business_data(node)
        return PresalesApprovalStep.objects.prefetch_related("revisions").get(pk=step.pk)

    decision_changed = (
        status != step.status
        or opinion != step.opinion
        or approver_user_id != step.approver_user_id
        or approver_name != step.approver_name
    )
    step.title = title
    step.approver_user_id = approver_user_id
    step.approver_name = approver_name
    step.status = status
    step.opinion = opinion
    if status == PresalesApprovalStep.STATUS_PENDING:
        step.decided_at = None
    elif decision_changed:
        step.decided_at = timezone.now()
    touch_audit(step, request)
    step.save()
    revision = _append_revision(step, request)
    _sync_node_business_data(node)
    record_project_event(
        request,
        node.project,
        node=node,
        event_type="presales_approval_recorded",
        title=f"审批更新：{step.title}（{step.get_status_display()}）",
        detail=step.opinion,
        before=before,
        after={**after, "approvalStepId": step.id, "revision": revision.revision},
    )
    return PresalesApprovalStep.objects.prefetch_related("revisions").get(pk=step.pk)


@transaction.atomic
def delete_approval_step(request, node: ProjectNode, step_id: int) -> list[PresalesApprovalStep]:
    node = _locked_approval_node(node)
    try:
        step = PresalesApprovalStep.objects.select_for_update().get(pk=step_id, node=node)
    except PresalesApprovalStep.DoesNotExist as exc:
        raise DomainValidationError("审批行不存在", code="APPROVAL_STEP_NOT_FOUND", status=404) from exc

    if step.status != PresalesApprovalStep.STATUS_PENDING:
        raise DomainValidationError("已完成审批的节点不能删除", code="DECIDED_APPROVAL_STEP_DELETE_DENIED", status=409)

    deleted = {
        "approvalStepId": step.id,
        "sequence": step.sequence,
        "title": step.title,
        "approverUserId": step.approver_user_id,
        "approverName": step.approver_name,
        "status": step.status,
    }
    deleted_sequence = step.sequence
    step.delete()

    following = list(
        PresalesApprovalStep.objects.select_for_update()
        .filter(node=node, sequence__gt=deleted_sequence)
        .order_by("sequence", "id")
    )
    for sequence, row in enumerate(following, start=deleted_sequence):
        row.sequence = sequence
        touch_audit(row, request)
        row.save(update_fields=["sequence", "updated_by", "updated_actor_id", "updated_at"])

    _sync_node_business_data(node)
    record_project_event(
        request,
        node.project,
        node=node,
        event_type="presales_approval_step_deleted",
        title=f"删除审批行：{deleted['title']}",
        detail=deleted["approverName"],
        before=deleted,
    )
    return list(PresalesApprovalStep.objects.filter(node=node).prefetch_related("revisions"))
