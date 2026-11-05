from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import math
import re
import uuid

from django.db import IntegrityError, transaction
from django.db.models import Avg
from django.utils import timezone

from .models import (
    FieldFeedback,
    MidsalesProof,
    PrivateAttachment,
    ProjectAssignment,
    ProjectEvent,
    ProjectNode,
    Reward,
    Settlement,
    ServiceProject,
    ServiceProvider,
    ServiceRating,
    ServiceTicket,
    TicketMessage,
)
from .workflow_rules import (
    OUTCOME_LABELS,
    PRESALES_FLOW_DEPENDENCIES,
    allowed_outcomes,
    aftersales_completion_errors,
    node_outcome,
    normalized_outcome,
    presales_locked,
    presales_node_is_successful,
    presales_prerequisites,
)
from .presales_task_schedule import round_date, sync_presales_task_schedules
from .project_personnel import personnel_members, validate_personnel_selection
from . import access


class DomainValidationError(Exception):
    def __init__(self, message: str, *, code: str = "INVALID_REQUEST", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


PRESALES_NODE_TEMPLATE = [
    ("early-approval", "前期立项", "approval", "业务员发起售前项目立项并确认项目机会。"),
    ("early-plan", "前期方案", "delivery", "记录前期方案版本、客户意见和交付时间。"),
    ("budget-match", "预算匹配", "delivery", "核对客户预算、建设规模和方案投入。"),
    ("project-filing", "项目申报", "delivery", "记录项目申报资料和申报进度。"),
    ("early-plan-result", "前期结果", "result", "确认前期方案结果。"),
    ("late-approval", "后期立项", "approval", "进入深化阶段前完成后期立项。"),
    ("late-plan", "后期方案", "delivery", "记录深化方案及修改版本。"),
    ("device-plan", "设备方案", "delivery", "记录设备选型、数量和替代方案。"),
    ("budget", "工程预算", "delivery", "提交工程预算并保留核价过程。"),
    ("device-budget", "设备预算", "delivery", "编制设备预算和数量调整。"),
    ("cost-control", "工程成本管控", "delivery", "跟进工程成本、利润率和风险。"),
    ("device-cost-control", "设备成本管控", "delivery", "跟进设备替代方案和成本风险。"),
    ("rendering", "效果图", "delivery", "提交效果图并记录客户修改意见。"),
    ("tender-plan", "招标方案", "delivery", "准备招标技术和商务方案。"),
    ("layout", "平面设计", "delivery", "确认点位、动线和设备布置。"),
    ("bid-prep", "投标准备", "delivery", "整理投标文件清单和责任人。"),
    ("construction-result", "结项结果", "result", "确认项目是否中标并决定施工图节点。"),
    ("construction", "施工图", "delivery", "中标后完成施工图设计和交付。"),
    ("project-end", "结束标识", "end", "确认售前项目结束并归档。"),
]

PRESALES_APPROVAL_ASSIGNMENT_TARGETS = {
    "early-approval": ("early-plan", "budget-match", "project-filing"),
    "late-approval": (
        "late-plan",
        "device-plan",
        "budget",
        "device-budget",
        "cost-control",
        "device-cost-control",
        "rendering",
        "tender-plan",
        "layout",
        "bid-prep",
    ),
}

MIDSALES_NODE_TEMPLATE = [
    ("midsales-project", "项目立项", "approval", "确认合同、负责人和项目启动资料。"),
    ("construction-work", "工程施工", "delivery", "跟进进场条件、施工进度和现场协调。"),
    ("furniture-install", "家具安装", "delivery", "记录到场、安装进度和完成确认。"),
    ("device-install", "设备安装", "delivery", "记录设备到场、安装人员和安装结果。"),
    ("device-debug", "设备调试", "delivery", "记录联调、平台接入和功能测试。"),
    ("school-support", "开学保障", "delivery", "记录开学前巡检和值守安排。"),
    ("project-acceptance", "项目验收", "approval", "整理验收资料和客户确认。"),
    ("midsales-project-end", "结束标识", "end", "确认售中项目结束并归档。"),
]

MIDSALES_PROOF_NODE_KEYS = {
    "construction-work",
    "furniture-install",
    "device-install",
    "device-debug",
    "school-support",
}
MIDSALES_ASSIGNMENT_NODE_KEYS = {
    "construction-work",
    "furniture-install",
    "device-install",
    "device-debug",
    "school-support",
    "project-acceptance",
}
MIDSALES_FIELD_OWNED_NODE_FIELDS = {
    "actual_start_at",
    "actual_end_at",
    "actual_fee",
}
MIDSALES_FIELD_OWNED_BUSINESS_FIELDS = {
    "actualStartTime",
    "actual_start_time",
    "actualEndTime",
    "actual_end_time",
    "actualDuration",
    "actual_duration",
    "feeActualNote",
    "fee_actual_note",
    "fieldDrafts",
    "field_drafts",
    "fieldSubmissions",
    "field_submissions",
}
AFTERSALES_FIELD_NODE_KEYS = {
    "onsite-service",
    "school-inspection",
}
AFTERSALES_FIELD_OWNED_NODE_FIELDS = {
    "actual_start_at",
    "actual_end_at",
    "actual_fee",
}
AFTERSALES_FIELD_OWNED_BUSINESS_FIELDS = {
    "actualStartTime",
    "actual_start_time",
    "actualEndTime",
    "actual_end_time",
    "actualDuration",
    "actual_duration",
    "feeActualNote",
    "fee_actual_note",
    "settlementEligible",
    "settlement_eligible",
    "fieldDrafts",
    "field_drafts",
    "fieldSubmissions",
    "field_submissions",
}
SETTLEMENT_MIDSALES_NODE_KEYS = {
    "construction-work",
    "furniture-install",
    "device-install",
    "device-debug",
    "school-support",
}
SETTLEMENT_AFTERSALES_NODE_KEYS = {
    "onsite-service",
    "mail-service",
    "school-inspection",
}
ASSIGNMENT_VALUE_UNSET = object()

AFTERSALES_NODE_TEMPLATE = [
    ("onsite-service", "上门售后", "delivery", "记录上门计划、现场反馈和费用。"),
    ("mail-service", "寄件售后", "delivery", "记录寄件、检测、维修、返寄和费用。"),
    ("school-inspection", "开学巡检", "delivery", "记录巡检安排、保障结果和待处理问题。"),
]

PROJECT_NODE_TEMPLATES = {
    ServiceProject.TYPE_PRESALES: PRESALES_NODE_TEMPLATE,
    ServiceProject.TYPE_MIDSALES: MIDSALES_NODE_TEMPLATE,
    ServiceProject.TYPE_AFTERSALES: AFTERSALES_NODE_TEMPLATE,
}

TICKET_TRANSITIONS = {
    ServiceTicket.STATUS_OPEN: {ServiceTicket.STATUS_ASSIGNED, ServiceTicket.STATUS_IN_PROGRESS},
    ServiceTicket.STATUS_ASSIGNED: {ServiceTicket.STATUS_IN_PROGRESS, ServiceTicket.STATUS_REJECTED},
    ServiceTicket.STATUS_IN_PROGRESS: {
        ServiceTicket.STATUS_PENDING_REVIEW,
        ServiceTicket.STATUS_COMPLETED,
        ServiceTicket.STATUS_REJECTED,
    },
    ServiceTicket.STATUS_PENDING_REVIEW: {
        ServiceTicket.STATUS_IN_PROGRESS,
        ServiceTicket.STATUS_COMPLETED,
        ServiceTicket.STATUS_REJECTED,
    },
    ServiceTicket.STATUS_REJECTED: {ServiceTicket.STATUS_IN_PROGRESS},
    ServiceTicket.STATUS_COMPLETED: set(),
}

PROVIDER_TICKET_TRANSITIONS = {
    ServiceTicket.STATUS_ASSIGNED: {ServiceTicket.STATUS_IN_PROGRESS},
    ServiceTicket.STATUS_IN_PROGRESS: {ServiceTicket.STATUS_PENDING_REVIEW},
    ServiceTicket.STATUS_REJECTED: {ServiceTicket.STATUS_IN_PROGRESS},
}

REWARD_TRANSITIONS = {
    Reward.STATUS_PENDING: {Reward.STATUS_APPROVED, Reward.STATUS_REJECTED},
    Reward.STATUS_APPROVED: {Reward.STATUS_ISSUED, Reward.STATUS_REJECTED},
    Reward.STATUS_ISSUED: set(),
    Reward.STATUS_REJECTED: set(),
}


def text(value) -> str:
    return str(value or "").strip()


def presales_rounds_without_results(rounds):
    if not isinstance(rounds, list):
        return rounds
    return [
        {key: value for key, value in item.items() if key != "result"}
        if isinstance(item, dict) else item
        for item in rounds
    ]


def validate_presales_round_schedule(rounds):
    rounds = presales_rounds_without_results(rounds)
    if not isinstance(rounds, list) or any(not isinstance(item, dict) for item in rounds):
        raise DomainValidationError("售前任务轮次格式错误", code="INVALID_PRESALES_TASKS")
    round_ids = set()
    for number, item in enumerate(rounds, 1):
        reason_ids = item.get("reasonAttachmentIds", [])
        if not isinstance(reason_ids, list) or any(
            isinstance(value, bool) or not isinstance(value, (str, int))
            or not str(value).isascii() or not str(value).isdigit()
            or len(str(value)) > 19 or not 0 < int(value) <= 9_223_372_036_854_775_807
            for value in reason_ids
        ):
            raise DomainValidationError("原因附件编号无效", code="INVALID_PRESALES_REASON_ATTACHMENTS")
        round_id = item.get("roundId")
        if round_id is not None:
            if not isinstance(round_id, str) or not round_id.strip() or len(round_id) > 64 or round_id in round_ids:
                raise DomainValidationError("售前任务轮次编号无效或重复", code="INVALID_PRESALES_ROUND_ID")
            round_ids.add(round_id)
        dates = {}
        for key, label in (("plannedStartDate", "计划开始时间"), ("plannedEndDate", "预计完成时间")):
            raw = item.get(key)
            if raw in (None, ""):
                continue
            parsed = round_date(raw)
            if parsed is None:
                raise DomainValidationError(f"第{number}轮任务{label}格式错误", code="INVALID_PRESALES_TASK_DATE")
            dates[key] = parsed
        if dates.get("plannedStartDate") and dates.get("plannedEndDate") and dates["plannedEndDate"] < dates["plannedStartDate"]:
            raise DomainValidationError(f"第{number}轮任务预计完成时间不能早于计划开始时间", code="INVALID_PRESALES_TASK_RANGE")
    return rounds


def _check_node_draft_version(node, values):
    round_draft = (node.project.service_type == ServiceProject.TYPE_PRESALES and node.kind == "delivery"
                   and "schemeRounds" in (values.get("business_data") or {}))
    linked = round_draft and any(isinstance(item, dict) and item.get("roundId")
                                for item in (node.business_data or {}).get("schemeRounds", []))
    if (linked or "expected_updated_at" in values) and values.get("expected_updated_at") != node.updated_at.isoformat():
        raise DomainValidationError("内容已被其他人更新，请核对最新内容后再保存；当前填写已保留",
                                    code="PRESALES_ROUND_CONFLICT" if round_draft else "PROJECT_NODE_CONFLICT", status=409)


def _presales_round_snapshot(item):
    # Older stored rounds omit fields that the UI supplies as empty defaults.
    snapshot = {key: value for key, value in item.items()
                if key != "result" and value not in (None, "", [])}
    for key in ("attachmentIds", "reasonAttachmentIds"):
        if key in snapshot:
            snapshot[key] = [str(value) for value in snapshot[key]]
    return snapshot


def validate_presales_round_update(node, rounds):
    incoming = validate_presales_round_schedule(rounds)
    existing = presales_rounds_without_results((node.business_data or {}).get("schemeRounds", []))
    if not isinstance(existing, list):
        existing = []
    if existing and len(incoming) < max(1, len(existing) - 1):
        raise DomainValidationError("历史轮次只读，只能删除最后一轮", code="PRESALES_ROUND_READ_ONLY", status=409)
    for index, current in enumerate(existing[:len(incoming)]):
        if not isinstance(current, dict):
            continue
        if (index < len(existing) - 1 and _presales_round_snapshot(current) != _presales_round_snapshot(incoming[index])) \
                or (current.get("roundId") and current["roundId"] != incoming[index].get("roundId")):
            raise DomainValidationError("已有新轮次，历史轮次的时间、附件和备注只能查看", code="PRESALES_ROUND_READ_ONLY", status=409)
        if [str(value) for value in current.get("reasonAttachmentIds", [])] != [str(value) for value in incoming[index].get("reasonAttachmentIds", [])]:
            raise DomainValidationError("新增原因附件只能在新增一轮时提交", code="PRESALES_ROUND_READ_ONLY", status=409)
    if any(item.get("reasonAttachmentIds") for item in incoming[len(existing):]):
        raise DomainValidationError("新增原因附件只能在新增一轮时提交", code="PRESALES_ROUND_READ_ONLY", status=409)
    reason_ids = {str(value) for row in existing for value in row.get("reasonAttachmentIds", [])}
    if any(str(value) in reason_ids for row in incoming for value in row.get("attachmentIds", [])):
        raise DomainValidationError("原因附件不能作为推进成果附件", code="PRESALES_ROUND_READ_ONLY", status=409)
    if len(incoming) < len(existing) and existing[-1].get("attachmentIds"):
        raise DomainValidationError("请先删除最后一轮的附件，再删除该轮次", code="PRESALES_ROUND_HAS_ATTACHMENTS", status=409)
    if len(incoming) < len(existing):
        retained = {str(value) for row in incoming for key in ("attachmentIds", "reasonAttachmentIds")
                    for value in row.get(key, [])}
        removed_ids = [str(value) for value in existing[-1].get("reasonAttachmentIds", [])
                       if str(value) not in retained]
        for item in PrivateAttachment.objects.filter(
            target_type=PrivateAttachment.TARGET_PROJECT_NODE, target_id=node.pk,
            category=PrivateAttachment.CATEGORY_SCHEME_SUBMISSION,
            pk__in=removed_ids,
        ):
            storage, name = item.file.storage, item.file.name
            item.delete()
            if name:
                transaction.on_commit(lambda storage=storage, name=name: storage.delete(name), robust=True)
    return incoming


def validate_presales_project_info_records(project, business_data):
    if project.service_type != ServiceProject.TYPE_PRESALES or "projectInfoRecords" not in business_data:
        return
    incoming = business_data.get("projectInfoRecords") or {}
    existing = (project.business_data or {}).get("projectInfoRecords") or {}
    if not isinstance(incoming, dict):
        raise DomainValidationError("项目信息记录格式错误", code="INVALID_PROJECT_INFO_RECORDS")
    closed_keys = project.nodes.filter(status__in=[ProjectNode.STATUS_COMPLETED, ProjectNode.STATUS_SKIPPED]).values_list("node_key", flat=True)
    for key in closed_keys:
        if incoming.get(key) != existing.get(key):
            raise DomainValidationError("已结束节点的项目信息只读，不能修改历史记录", code="PROJECT_NODE_READ_ONLY", status=409)


def merge_presales_scheme_rounds(existing, incoming, *, source: str = "admin") -> list[dict]:
    current_rounds = [item for item in presales_rounds_without_results(existing or []) if isinstance(item, dict)]
    incoming_rounds = [item for item in presales_rounds_without_results(incoming or []) if isinstance(item, dict)]
    if source == "field":
        # Field clients can only update rounds; they cannot remove rounds that
        # were added by the management side while the task was open.
        merged = [dict(item) for item in current_rounds]
        for index, item in enumerate(incoming_rounds):
            current = dict(current_rounds[index]) if index < len(current_rounds) else {}
            current.update(item)
            if index < len(merged):
                merged[index] = current
            else:
                merged.append(current)
        return merged

    return incoming_rounds


def request_identity(request) -> dict[str, str]:
    user_id = text(getattr(request, "auth_user_id", ""))
    return {
        "user_id": user_id,
        "user_name": text(getattr(request, "auth_user_name", "")) or user_id,
        "actor_id": text(getattr(request, "auth_actor_user_id", "")) or user_id,
        "actor_name": text(getattr(request, "auth_actor_name", "")) or text(getattr(request, "auth_user_name", "")) or user_id,
    }


def create_audit_fields(request) -> dict[str, str]:
    identity = request_identity(request)
    return {
        "created_by": identity["user_id"],
        "created_actor_id": identity["actor_id"],
        "updated_by": identity["user_id"],
        "updated_actor_id": identity["actor_id"],
    }


def touch_audit(instance, request) -> None:
    identity = request_identity(request)
    instance.updated_by = identity["user_id"]
    instance.updated_actor_id = identity["actor_id"]


def generated_code(prefix: str) -> str:
    return f"{prefix}-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def _is_settlement_chargeable_node(project: ServiceProject, node: ProjectNode) -> bool:
    if project.service_type == ServiceProject.TYPE_MIDSALES:
        return node.node_key in SETTLEMENT_MIDSALES_NODE_KEYS
    if project.service_type == ServiceProject.TYPE_AFTERSALES:
        return node.node_key in SETTLEMENT_AFTERSALES_NODE_KEYS
    return False


def field_completion_submitted(node: ProjectNode) -> bool:
    business_data = node.business_data if isinstance(node.business_data, dict) else {}
    submissions = business_data.get("fieldSubmissions") or business_data.get("field_submissions") or {}
    if node.project.service_type != ServiceProject.TYPE_PRESALES:
        cached = getattr(node, "_prefetched_objects_cache", {}).get("assignments")
        if cached is None:
            cached = getattr(node.project, "_prefetched_objects_cache", {}).get("assignments")
        active_ids = (
            [row.id for row in cached if row.node_id == node.id and row.status != ProjectAssignment.STATUS_CANCELLED]
            if cached is not None else
            node.assignments.exclude(status=ProjectAssignment.STATUS_CANCELLED).values_list("id", flat=True)
        )
        return any(
            isinstance(submissions.get(str(assignment_id)), dict)
            and submissions[str(assignment_id)].get("submitted") is True
            for assignment_id in active_ids
        )
    return any(
        isinstance(submission, dict) and submission.get("submitted") is True
        for submission in submissions.values()
    )


def unsettled_settlement_nodes(project: ServiceProject, nodes: list[ProjectNode]) -> list[ProjectNode]:
    candidates = [
        node for node in nodes
        if node.enabled
        and (
            node.status == ProjectNode.STATUS_COMPLETED
            or (node.status == ProjectNode.STATUS_ACTIVE and field_completion_submitted(node))
            or (
                project.service_type == ServiceProject.TYPE_PRESALES
                and node.status == ProjectNode.STATUS_ACTIVE
            )
        )
        and node.actual_fee is not None
        and node.actual_fee > 0
        and _is_settlement_chargeable_node(project, node)
    ]
    if not candidates:
        return []
    settled_ids = set(
        Settlement.objects.filter(
            source_node_id__in=[node.id for node in candidates],
            status=Settlement.STATUS_SETTLED,
        ).values_list("source_node_id", flat=True)
    )
    return [node for node in candidates if node.id not in settled_ids]


def record_project_event(
    request,
    project: ServiceProject,
    *,
    event_type: str,
    title: str,
    node: ProjectNode | None = None,
    detail: str = "",
    before: dict | None = None,
    after: dict | None = None,
) -> ProjectEvent:
    identity = request_identity(request)
    return ProjectEvent.objects.create(
        project=project,
        node=node,
        event_type=event_type,
        title=title,
        detail=detail,
        before_values=before or {},
        after_values=after or {},
        auth_user_id=identity["user_id"],
        auth_user_name=identity["user_name"],
        actor_user_id=identity["actor_id"],
        actor_name=identity["actor_name"],
    )


@transaction.atomic
def create_project(request, fields: dict, *, disabled_node_keys: set[str] | None = None) -> ServiceProject:
    service_type = fields.get("service_type")
    template = PROJECT_NODE_TEMPLATES.get(service_type)
    if template is None:
        raise DomainValidationError("服务类型无效", code="INVALID_SERVICE_TYPE")
    disabled = {text(value) for value in (disabled_node_keys or set()) if text(value)}
    valid_keys = {row[0] for row in template}
    if not disabled.issubset(valid_keys):
        raise DomainValidationError("包含未知的禁用节点", code="INVALID_NODE_SELECTION")
    enabled_rows = [row for row in template if row[0] not in disabled]
    if service_type == ServiceProject.TYPE_AFTERSALES:
        if not disabled:
            enabled_rows = [template[0]]
            disabled = valid_keys - {template[0][0]}
        elif len(enabled_rows) != 1:
            raise DomainValidationError(
                "售后项目必须且只能选择一个服务节点",
                code="AFTERSALES_NODE_SELECTION_REQUIRED",
            )
    if not enabled_rows:
        raise DomainValidationError("项目至少需要一个启用节点", code="NO_ENABLED_PROJECT_NODE")

    project = ServiceProject.objects.create(
        **fields,
        current_node_key=enabled_rows[0][0],
        **create_audit_fields(request),
    )
    initial_start = timezone.now() if service_type == ServiceProject.TYPE_PRESALES else None
    for sequence, (node_key, name, kind, description) in enumerate(template, start=1):
        enabled = node_key not in disabled
        status = ProjectNode.STATUS_SKIPPED if not enabled else ProjectNode.STATUS_PENDING
        if node_key == project.current_node_key and service_type != ServiceProject.TYPE_AFTERSALES:
            status = ProjectNode.STATUS_ACTIVE
        node = ProjectNode.objects.create(
            project=project,
            node_key=node_key,
            name=name,
            sequence=sequence,
            kind=kind,
            description=description,
            enabled=enabled,
            status=status,
            actual_start_at=initial_start if status == ProjectNode.STATUS_ACTIVE else None,
            **create_audit_fields(request),
        )
        if (
            project.service_type == ServiceProject.TYPE_PRESALES
            and node_key in {"early-approval", "late-approval"}
        ):
            from .approval_services import ensure_default_approval_steps

            ensure_default_approval_steps(node, request)
        if project.service_type == ServiceProject.TYPE_MIDSALES and node_key in MIDSALES_PROOF_NODE_KEYS:
            for proof_type, _label in MidsalesProof.TYPE_CHOICES:
                MidsalesProof.objects.create(
                    node=node,
                    proof_type=proof_type,
                    **create_audit_fields(request),
                )
    # CRM imports initialize a workflow automatically; they are not manual
    # service-project creations and should not appear in the business history.
    if not project.source_crm_id:
        record_project_event(
            request,
            project,
            event_type="project_created",
            title="创建服务项目",
            detail=f"创建{project.get_service_type_display()}项目，当前节点：{project.current_node_key}",
            after={"status": project.status, "currentNodeKey": project.current_node_key},
        )
    return project


def _locked_project(request, project_id):
    from .crm_source import assert_crm_project_access

    project = ServiceProject.objects.select_for_update().get(pk=project_id)
    access.require_project(request, project)
    assert_crm_project_access(request, project, write=True)
    return project


@transaction.atomic
def configure_project_nodes(request, project_id: int, disabled_node_keys: set[str]) -> ServiceProject:
    project = _locked_project(request, project_id)
    access.require_project(request, project, manage=True)
    if project.deleted_at or project.status in {ServiceProject.STATUS_COMPLETED, ServiceProject.STATUS_CANCELLED}:
        raise DomainValidationError("当前项目不能调整节点", code="PROJECT_NODES_LOCKED", status=409)
    nodes = list(ProjectNode.objects.select_for_update().filter(project=project))
    valid_keys = {node.node_key for node in nodes}
    disabled = {text(value) for value in disabled_node_keys if text(value)}
    if not disabled.issubset(valid_keys):
        raise DomainValidationError("包含未知的禁用节点", code="INVALID_NODE_SELECTION")
    if len(disabled) == len(nodes):
        raise DomainValidationError("项目至少需要一个启用节点", code="NO_ENABLED_PROJECT_NODE")
    if project.service_type == ServiceProject.TYPE_AFTERSALES and len(nodes) - len(disabled) != 1:
        raise DomainValidationError(
            "售后项目必须且只能选择一个服务节点",
            code="AFTERSALES_NODE_SELECTION_REQUIRED",
        )
    changed = []
    for node in nodes:
        should_enable = node.node_key not in disabled
        if node.enabled == should_enable:
            continue
        if node.status in {ProjectNode.STATUS_ACTIVE, ProjectNode.STATUS_COMPLETED}:
            raise DomainValidationError(
                f"节点“{node.name}”已经开始，不能禁用",
                code="PROJECT_NODE_ALREADY_STARTED",
                status=409,
            )
        node.enabled = should_enable
        node.status = ProjectNode.STATUS_PENDING if should_enable else ProjectNode.STATUS_SKIPPED
        touch_audit(node, request)
        node.save(update_fields=["enabled", "status", "updated_by", "updated_actor_id", "updated_at"])
        changed.append(node.node_key)
    if changed:
        touch_audit(project, request)
        project.save(update_fields=["updated_by", "updated_actor_id", "updated_at"])
        record_project_event(
            request,
            project,
            event_type="nodes_configured",
            title="调整项目节点",
            after={"disabledNodeKeys": sorted(disabled)},
        )
    return project


def _refresh_presales_node_states(request, nodes: list[ProjectNode]) -> None:
    now = timezone.now()
    for node in nodes:
        if not node.enabled or node.status == ProjectNode.STATUS_COMPLETED:
            continue
        next_status = ProjectNode.STATUS_PENDING if presales_locked(node, nodes) else ProjectNode.STATUS_ACTIVE
        changed_fields = []
        if node.status != next_status:
            node.status = next_status
            changed_fields.append("status")
        if next_status == ProjectNode.STATUS_ACTIVE and node.actual_start_at is None:
            node.actual_start_at = now
            changed_fields.append("actual_start_at")
        if not changed_fields:
            continue
        touch_audit(node, request)
        node.save(update_fields=[*changed_fields, "updated_by", "updated_actor_id", "updated_at"])


def _validate_presales_completion(
    current: ProjectNode,
    nodes: list[ProjectNode],
    outcome: str,
    *,
    outcome_supplied: bool,
) -> None:
    expected = allowed_outcomes(current.node_key)
    if not expected and outcome_supplied:
        raise DomainValidationError(
            f"节点“{current.name}”不支持设置处理结果",
            code="PRESALES_OUTCOME_NOT_ALLOWED",
        )
    if expected and outcome not in expected:
        choices = "、".join(OUTCOME_LABELS[item] for item in expected)
        raise DomainValidationError(
            f"节点“{current.name}”必须选择处理结果：{choices}",
            code="PRESALES_OUTCOME_REQUIRED",
        )
    if current.node_key in {"early-plan-result", "construction-result"} and outcome in {"passed", "won"}:
        incomplete = [
            node.name for node in presales_prerequisites(nodes, current)
            if not presales_node_is_successful(node)
        ]
        if incomplete:
            raise DomainValidationError(
                f"前置节点尚未完成：{'、'.join(incomplete)}",
                code="PRESALES_RESULT_PREREQUISITES_INCOMPLETE",
                status=409,
            )
    if current.node_key == "project-end":
        construction_result = next((node for node in nodes if node.node_key == "construction-result"), None)
        construction = next((node for node in nodes if node.node_key == "construction"), None)
        if not construction_result or node_outcome(construction_result) != "won":
            raise DomainValidationError("结项结果未中标，不能结束项目", code="PRESALES_NOT_WON", status=409)
        if not construction or construction.status != ProjectNode.STATUS_COMPLETED:
            raise DomainValidationError("施工图节点尚未完成", code="PRESALES_CONSTRUCTION_INCOMPLETE", status=409)


def _standard_duration_days(value) -> int | None:
    match = re.search(r"\d+(?:\.\d+)?", text(value))
    if not match:
        return None
    try:
        amount = float(match.group(0))
        if amount <= 0:
            return None
        return max(1, math.ceil(amount))
    except (TypeError, ValueError):
        return None


def _planned_end_from_start(start, standard_duration):
    if start is None:
        return None
    raw_duration = text(standard_duration)
    match = re.search(r"\d+(?:\.\d+)?", raw_duration)
    if not match:
        return None
    try:
        amount = float(match.group(0))
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    if "分钟" in raw_duration:
        return start + timedelta(minutes=amount)
    if "小时" in raw_duration or "时" in raw_duration:
        return start + timedelta(hours=amount)
    return start + timedelta(days=amount)


def _minute_precision(value):
    return value.replace(second=0, microsecond=0) if value is not None else None


def _aftersales_planned_end(node: ProjectNode):
    assignment_duration = ProjectAssignment.objects.filter(
        project=node.project,
        node=node,
    ).exclude(status=ProjectAssignment.STATUS_CANCELLED).values_list("standard_duration", flat=True).first()
    return _planned_end_from_start(
        node.planned_start_at,
        assignment_duration or (node.project.business_data or {}).get("expectedDuration", ""),
    )


def _presales_approval_personnel_errors(project: ServiceProject, approval_node_key: str, nodes) -> list[str]:
    """Personnel is required for approval; node schedules are not."""
    target_keys = PRESALES_APPROVAL_ASSIGNMENT_TARGETS.get(approval_node_key, ())
    if not target_keys:
        return []

    enabled_nodes = {
        node.node_key: node
        for node in nodes
        if node.enabled and node.node_key in target_keys
    }
    errors = []
    for target_key in target_keys:
        node = enabled_nodes.get(target_key)
        if node is None:
            continue
        label = node.name
        node_data = node.business_data if isinstance(node.business_data, dict) else {}
        assignment = node_data.get("managementAssignment")
        if not personnel_members(assignment):
            errors.append(f"{label}未分派项目人员")
    return errors


@transaction.atomic
def start_project_node(request, project_id: int, *, expected_node_key: str = "") -> ServiceProject:
    project = _locked_project(request, project_id)
    if project.service_type not in {
        ServiceProject.TYPE_PRESALES,
        ServiceProject.TYPE_MIDSALES,
        ServiceProject.TYPE_AFTERSALES,
    }:
        raise DomainValidationError("当前项目不支持确认开始节点", code="PROJECT_NODE_START_UNSUPPORTED", status=409)
    if project.deleted_at or project.status in {
        ServiceProject.STATUS_COMPLETED,
        ServiceProject.STATUS_CANCELLED,
        ServiceProject.STATUS_BLOCKED,
    }:
        raise DomainValidationError("项目已经结束", code="PROJECT_ALREADY_FINISHED", status=409)

    nodes = list(ProjectNode.objects.select_for_update().filter(project=project).order_by("sequence"))
    requested_key = expected_node_key or project.current_node_key
    if project.service_type != ServiceProject.TYPE_PRESALES and requested_key != project.current_node_key:
        raise DomainValidationError(
            "项目已由其他人推进，请刷新后重试",
            code="PROJECT_NODE_CONFLICT",
            status=409,
        )
    node = next((item for item in nodes if item.node_key == requested_key), None)
    if node is None or not node.enabled:
        raise DomainValidationError("项目节点不存在", code="PROJECT_NODE_NOT_FOUND", status=404)
    access.require_node(request, node)
    if node.status == ProjectNode.STATUS_ACTIVE and node.actual_start_at:
        return project
    if project.service_type == ServiceProject.TYPE_PRESALES:
        if node.kind != "delivery" or presales_locked(node, nodes):
            raise DomainValidationError("当前售前节点尚未解锁", code="PRESALES_NODE_LOCKED", status=409)
        if node.status not in {ProjectNode.STATUS_ACTIVE, ProjectNode.STATUS_PENDING}:
            raise DomainValidationError("当前节点不能开始", code="PROJECT_NODE_START_LOCKED", status=409)
    elif node.status != ProjectNode.STATUS_PENDING:
        raise DomainValidationError("当前节点不能开始", code="PROJECT_NODE_START_LOCKED", status=409)

    before = {"status": node.status, "currentNodeKey": project.current_node_key}

    if project.service_type != ServiceProject.TYPE_PRESALES:
        prior = [
            item for item in nodes
            if item.enabled and item.sequence < node.sequence and item.status != ProjectNode.STATUS_COMPLETED
        ]
        if prior:
            raise DomainValidationError(
                f"前置节点尚未完成：{'、'.join(item.name for item in prior)}",
                code="PREVIOUS_NODE_INCOMPLETE",
                status=409,
            )

    assignment = None
    field_assignment_required = (
        project.service_type == ServiceProject.TYPE_MIDSALES
        and node.node_key in MIDSALES_ASSIGNMENT_NODE_KEYS
    ) or (
        project.service_type == ServiceProject.TYPE_AFTERSALES
        and node.node_key != "mail-service"
    )
    if field_assignment_required:
        assignment = ProjectAssignment.objects.select_for_update().filter(
            project=project,
            node=node,
        ).exclude(status=ProjectAssignment.STATUS_CANCELLED).first()
        if assignment is None:
            raise DomainValidationError(
                "请先为当前节点分派现场服务人员",
                code="FIELD_ASSIGNMENT_REQUIRED",
                status=409,
            )

    now = timezone.now()
    node.actual_start_at = now
    planned_start = node.planned_start_at or now
    # 售中/售前的计划结束时间必须由管理端明确填写。售后仍可按服务时长
    # 计算默认结束时间，因为它的派单资料包含预计服务时长。
    if node.planned_end_at is None and project.service_type == ServiceProject.TYPE_AFTERSALES:
        node.planned_end_at = _planned_end_from_start(
            planned_start,
            assignment.standard_duration if assignment is not None and assignment.standard_duration
            else (project.business_data or {}).get("expectedDuration", ""),
        )
    node.status = ProjectNode.STATUS_ACTIVE
    touch_audit(node, request)
    node.save(update_fields=[
        "status", "planned_end_at", "actual_start_at",
        "updated_by", "updated_actor_id", "updated_at",
    ])
    if assignment is not None and assignment.status in {
        ProjectAssignment.STATUS_ASSIGNED,
        ProjectAssignment.STATUS_ACCEPTED,
    }:
        assignment.status = ProjectAssignment.STATUS_IN_PROGRESS
        assignment.accepted_at = assignment.accepted_at or now
        touch_audit(assignment, request)
        assignment.save(update_fields=[
            "status", "accepted_at", "updated_by", "updated_actor_id", "updated_at",
        ])

    project.current_node_key = node.node_key
    project.status = ServiceProject.STATUS_IN_PROGRESS
    touch_audit(project, request)
    project.save(update_fields=["current_node_key", "status", "updated_by", "updated_actor_id", "updated_at"])
    record_project_event(
        request,
        project,
        node=node,
        event_type="node_started",
        title=f"开始节点：{node.name}",
        detail="管理端确认节点开始",
        before=before,
        after={
            "status": node.status,
            "currentNodeKey": project.current_node_key,
            "actualStartAt": node.actual_start_at.isoformat(),
            "plannedEndAt": node.planned_end_at.isoformat() if node.planned_end_at else "",
        },
    )
    return project


@transaction.atomic
def advance_project(request, project_id: int, *, expected_node_key: str = "", node_values: dict | None = None) -> ServiceProject:
    project = _locked_project(request, project_id)
    if project.deleted_at:
        raise DomainValidationError("项目已删除", code="PROJECT_DELETED", status=409)
    if project.status in {
        ServiceProject.STATUS_COMPLETED,
        ServiceProject.STATUS_CANCELLED,
        ServiceProject.STATUS_BLOCKED,
    }:
        raise DomainValidationError("项目已经结束", code="PROJECT_ALREADY_FINISHED", status=409)

    nodes = list(ProjectNode.objects.select_for_update().filter(project=project).order_by("sequence"))
    requested_key = expected_node_key or project.current_node_key
    if project.service_type == ServiceProject.TYPE_AFTERSALES and requested_key != project.current_node_key:
        raise DomainValidationError(
            "项目已由其他人推进，请刷新后重试",
            code="PROJECT_NODE_CONFLICT",
            status=409,
        )
    current = next((node for node in nodes if node.node_key == requested_key), None)
    valid_current_statuses = {ProjectNode.STATUS_ACTIVE}
    if current is None or not current.enabled or current.status not in valid_current_statuses:
        raise DomainValidationError("项目当前节点状态不一致", code="PROJECT_NODE_STATE_INVALID", status=409)
    access.require_node(request, current)

    field_completion_required = (
        project.service_type == ServiceProject.TYPE_MIDSALES
        and current.node_key in MIDSALES_ASSIGNMENT_NODE_KEYS
    ) or (
        project.service_type == ServiceProject.TYPE_AFTERSALES
        and current.node_key != "mail-service"
    )
    if field_completion_required:
        assignment = ProjectAssignment.objects.select_for_update().filter(
            project=project,
            node=current,
        ).exclude(status=ProjectAssignment.STATUS_CANCELLED).first()
        if assignment is None:
            raise DomainValidationError(
                "请先为当前节点分派现场服务人员",
                code="FIELD_ASSIGNMENT_REQUIRED",
                status=409,
            )
        submissions = (current.business_data or {}).get("fieldSubmissions") or {}
        submission = submissions.get(str(assignment.id)) or {}
        if submission.get("submitted") is not True:
            raise DomainValidationError(
                "现场人员尚未确认完工，不能通过当前节点",
                code="FIELD_COMPLETION_REQUIRED",
                status=409,
            )
        if (
            project.service_type == ServiceProject.TYPE_AFTERSALES
            and current.node_key in AFTERSALES_FIELD_NODE_KEYS
            and (current.actual_start_at is None or current.actual_end_at is None)
        ):
            raise DomainValidationError(
                "现场实际服务时间尚未同步完成",
                code="FIELD_EXECUTION_TIME_REQUIRED",
                status=409,
            )

    values = node_values or {}
    _check_node_draft_version(current, values)
    if project.service_type == ServiceProject.TYPE_PRESALES and current.node_key == "project-end":
        from .midsales_handover import midsales_node_keys

        handover_data = {**(current.business_data or {}), **(values.get("business_data") or {})}
        midsales_node_keys(handover_data.get("midsalesNodeKeys"))
    if project.service_type == ServiceProject.TYPE_PRESALES:
        if presales_locked(current, nodes):
            raise DomainValidationError("当前售前节点尚未解锁", code="PRESALES_NODE_LOCKED", status=409)
        outcome = normalized_outcome(values.get("outcome"))
        if outcome == "approved" and current.node_key in PRESALES_APPROVAL_ASSIGNMENT_TARGETS:
            personnel_errors = _presales_approval_personnel_errors(project, current.node_key, nodes)
            if personnel_errors:
                raise DomainValidationError(
                    "立项成功前请补齐项目人员配置：" + "；".join(personnel_errors),
                    code="PRESALES_PERSONNEL_INCOMPLETE",
                    status=409,
                )
        _validate_presales_completion(
            current,
            nodes,
            outcome,
            outcome_supplied=bool(text(values.get("outcome"))),
        )
    elif project.service_type == ServiceProject.TYPE_AFTERSALES:
        outcome = ""
        incomplete_prior = [
            node for node in nodes
            if node.enabled and node.sequence < current.sequence and node.status != ProjectNode.STATUS_COMPLETED
        ]
        if incomplete_prior:
            raise DomainValidationError("前置节点尚未完成", code="PREVIOUS_NODE_INCOMPLETE", status=409)
    else:
        outcome = ""
        if current.kind != "approval" and current.actual_start_at is None:
            raise DomainValidationError(
                "请先由管理端确认节点开始",
                code="PROJECT_NODE_NOT_STARTED",
                status=409,
            )
        if current.kind == "end":
            incomplete_prior = [
                node for node in nodes
                if node.enabled
                and node.pk != current.pk
                and node.status != ProjectNode.STATUS_COMPLETED
            ]
            if incomplete_prior:
                raise DomainValidationError(
                    "前面节点工作未完成，不能结束项目",
                    code="MIDSALES_NODES_INCOMPLETE",
                    status=409,
                )

    before = {"status": current.status, "currentNodeKey": project.current_node_key}
    now = timezone.now()
    if values.get("business_data") is not None:
        business_data = dict(values["business_data"])
        if project.service_type == ServiceProject.TYPE_PRESALES:
            for key in ("externalQuote", "external_quote", "earlyFeeDetail", "early_fee_detail"):
                business_data.pop(key, None)
        validate_presales_project_info_records(project, business_data)
        if "managementAssignment" in business_data:
            business_data["managementAssignment"] = validate_personnel_selection(business_data["managementAssignment"])
        if "projectLeads" in business_data:
            business_data["projectLeads"] = _merge_presales_project_leads(current, business_data["projectLeads"])
        if (project.service_type == ServiceProject.TYPE_PRESALES
                and current.kind == "delivery" and "schemeRounds" in business_data):
            business_data["schemeRounds"] = validate_presales_round_update(current, business_data["schemeRounds"])
        if project.service_type == ServiceProject.TYPE_MIDSALES:
            for key in MIDSALES_FIELD_OWNED_BUSINESS_FIELDS:
                business_data.pop(key, None)
        elif (
            project.service_type == ServiceProject.TYPE_AFTERSALES
            and current.node_key in AFTERSALES_FIELD_NODE_KEYS
        ):
            for key in AFTERSALES_FIELD_OWNED_BUSINESS_FIELDS:
                business_data.pop(key, None)
        current.business_data = {**(current.business_data or {}), **business_data}
    if outcome:
        current.business_data = {
            **(current.business_data or {}),
            "outcome": outcome,
            "outcomeLabel": OUTCOME_LABELS[outcome],
        }
    if project.service_type == ServiceProject.TYPE_AFTERSALES:
        completion_errors = aftersales_completion_errors(project.business_data, current.business_data)
        if completion_errors:
            raise DomainValidationError(
                "售后完工信息不完整：" + "、".join(completion_errors),
                code="AFTERSALES_COMPLETION_INCOMPLETE",
                status=409,
            )
    for field in ("planned_start_at", "planned_end_at", "actual_start_at", "actual_end_at", "estimated_fee", "actual_fee"):
        if (
            field in values
            and not (project.service_type == ServiceProject.TYPE_PRESALES and field in {"planned_start_at", "planned_end_at", "estimated_fee", "actual_fee"})
            and not (
                project.service_type == ServiceProject.TYPE_MIDSALES
                and field in MIDSALES_FIELD_OWNED_NODE_FIELDS
            )
            and not (
                project.service_type == ServiceProject.TYPE_AFTERSALES
                and current.node_key in AFTERSALES_FIELD_NODE_KEYS
                and field in AFTERSALES_FIELD_OWNED_NODE_FIELDS
            )
        ):
            setattr(current, field, values[field])
    if project.service_type == ServiceProject.TYPE_AFTERSALES and "planned_start_at" in values:
        current.planned_end_at = _aftersales_planned_end(current)
    current.actual_start_at = current.actual_start_at or now
    current.actual_end_at = current.actual_end_at or now
    if project.service_type != ServiceProject.TYPE_PRESALES and current.planned_start_at and current.planned_end_at and current.planned_end_at < current.planned_start_at:
        raise DomainValidationError(
            "计划结束时间不能早于计划开始时间",
            code="INVALID_PLANNED_TIME_RANGE",
        )
    if _minute_precision(current.actual_end_at) < _minute_precision(current.actual_start_at):
        raise DomainValidationError(
            "实际结束时间不能早于实际开始时间",
            code="INVALID_ACTUAL_TIME_RANGE",
        )
    current.status = ProjectNode.STATUS_COMPLETED
    current.completed_at = now
    identity = request_identity(request)
    current.completed_by = identity["user_id"]
    current.completed_actor_id = identity["actor_id"]
    touch_audit(current, request)
    current.save()
    if project.service_type == ServiceProject.TYPE_PRESALES and "schemeRounds" in (values.get("business_data") or {}):
        sync_presales_task_schedules(current)

    identity = request_identity(request)
    if project.service_type != ServiceProject.TYPE_PRESALES:
        ProjectAssignment.objects.filter(
            project=project,
            node=current,
            status__in=[
                ProjectAssignment.STATUS_ASSIGNED,
                ProjectAssignment.STATUS_ACCEPTED,
                ProjectAssignment.STATUS_IN_PROGRESS,
            ],
        ).update(
            status=ProjectAssignment.STATUS_COMPLETED,
            completed_at=now,
            updated_by=identity["user_id"],
            updated_actor_id=identity["actor_id"],
            updated_at=now,
        )

    terminal_outcome = outcome in {"denied", "failed", "abandoned", "suspended"}
    if project.service_type == ServiceProject.TYPE_PRESALES and terminal_outcome:
        project.current_node_key = current.node_key
        project.status = (
            ServiceProject.STATUS_BLOCKED if outcome == "suspended" else ServiceProject.STATUS_CANCELLED
        )
        project.actual_end_date = date.today()
        project.business_data = {
            **(project.business_data or {}),
            "terminalOutcome": outcome,
            "terminalOutcomeLabel": OUTCOME_LABELS[outcome],
            "terminalNodeKey": current.node_key,
        }
    else:
        if project.service_type == ServiceProject.TYPE_PRESALES:
            _refresh_presales_node_states(request, nodes)
            next_node = next(
                (node for node in nodes if node.enabled and node.status == ProjectNode.STATUS_ACTIVE),
                None,
            )
        elif project.service_type == ServiceProject.TYPE_AFTERSALES:
            next_node = next(
                (
                    node for node in nodes
                    if node.enabled and node.sequence > current.sequence and node.status == ProjectNode.STATUS_PENDING
                ),
                None,
            )
            if next_node:
                next_node.status = ProjectNode.STATUS_ACTIVE
                next_node.actual_start_at = next_node.actual_start_at or now
                touch_audit(next_node, request)
                next_node.save(update_fields=[
                    "status", "actual_start_at", "updated_by", "updated_actor_id", "updated_at",
                ])
        else:
            next_node = next(
                (
                    node for node in nodes
                    if node.enabled and node.sequence > current.sequence and node.status == ProjectNode.STATUS_PENDING
                ),
                None,
            )
        if next_node:
            project.current_node_key = next_node.node_key
            project.status = ServiceProject.STATUS_IN_PROGRESS
        else:
            project.current_node_key = ""
            project.status = ServiceProject.STATUS_COMPLETED
            project.actual_end_date = date.today()
    touch_audit(project, request)
    project.save()
    outcome_detail = OUTCOME_LABELS.get(outcome, "")
    record_project_event(
        request,
        project,
        node=current,
        event_type="node_decided" if outcome else "node_completed",
        title=f"完成节点：{current.name}" + (f"（{outcome_detail}）" if outcome_detail else ""),
        detail=text(values.get("note")),
        before=before,
        after={
            "status": project.status,
            "currentNodeKey": project.current_node_key,
            "outcome": outcome,
        },
    )
    if project.service_type == ServiceProject.TYPE_PRESALES and current.node_key == "project-end":
        from .midsales_handover import handover_to_midsales

        handover_to_midsales(request, project, current)
    return project


def _merge_presales_project_leads(node: ProjectNode, incoming) -> dict:
    if node.project.service_type != ServiceProject.TYPE_PRESALES or node.node_key != "early-approval":
        raise DomainValidationError("设计负责人和方案负责人只能在前期立项设置", code="PROJECT_LEADS_NODE_REQUIRED")
    if not isinstance(incoming, dict) or set(incoming) - {"design", "solution"}:
        raise DomainValidationError("项目负责人格式不正确", code="INVALID_PROJECT_LEADS")
    existing = (node.business_data or {}).get("projectLeads")
    leads = dict(existing) if isinstance(existing, dict) else {}
    for role, member in incoming.items():
        if isinstance(member, dict) and "members" in member:
            selection = validate_personnel_selection(member)
            if len(selection["members"]) > 1:
                raise DomainValidationError("每个项目负责人只能选择一人", code="INVALID_PROJECT_LEADS")
            leads[role] = selection
            continue
        if not isinstance(member, dict):
            raise DomainValidationError("项目负责人格式不正确", code="INVALID_PROJECT_LEADS")
        user_id, name = member.get("userId", ""), member.get("name", "")
        if (not isinstance(user_id, str) or not isinstance(name, str)
                or len(user_id) > 128 or len(name) > 128 or bool(user_id.strip()) != bool(name.strip())):
            raise DomainValidationError("请选择有效的项目负责人", code="INVALID_PROJECT_LEADS")
        leads[role] = {"userId": user_id.strip(), "name": name.strip()}
    return leads


def _apply_node_values(request, node: ProjectNode, values: dict) -> None:
    access.require_node(request, node, values)
    _check_node_draft_version(node, values)
    if values.get("business_data") is not None:
        business_data = dict(values["business_data"])
        if node.project.service_type == ServiceProject.TYPE_PRESALES:
            for key in ("externalQuote", "external_quote", "earlyFeeDetail", "early_fee_detail"):
                business_data.pop(key, None)
        validate_presales_project_info_records(node.project, business_data)
        if "managementAssignment" in business_data:
            business_data["managementAssignment"] = validate_personnel_selection(business_data["managementAssignment"])
        if "projectLeads" in business_data:
            business_data["projectLeads"] = _merge_presales_project_leads(node, business_data["projectLeads"])
        if (node.project.service_type == ServiceProject.TYPE_PRESALES
                and node.kind == "delivery" and "schemeRounds" in business_data):
            business_data["schemeRounds"] = validate_presales_round_update(node, business_data["schemeRounds"])
        if node.project.service_type == ServiceProject.TYPE_MIDSALES:
            for key in MIDSALES_FIELD_OWNED_BUSINESS_FIELDS:
                business_data.pop(key, None)
        elif (
            node.project.service_type == ServiceProject.TYPE_AFTERSALES
            and node.node_key in AFTERSALES_FIELD_NODE_KEYS
        ):
            for key in AFTERSALES_FIELD_OWNED_BUSINESS_FIELDS:
                business_data.pop(key, None)
        node.business_data = {**(node.business_data or {}), **business_data}
    for field in (
        "planned_start_at",
        "planned_end_at",
        "actual_start_at",
        "actual_end_at",
        "estimated_fee",
        "actual_fee",
    ):
        if (
            field in values
            and not (node.project.service_type == ServiceProject.TYPE_PRESALES and field in {"planned_start_at", "planned_end_at", "estimated_fee", "actual_fee"})
            and not (
                node.project.service_type == ServiceProject.TYPE_MIDSALES
                and field in MIDSALES_FIELD_OWNED_NODE_FIELDS
            )
            and not (
                node.project.service_type == ServiceProject.TYPE_AFTERSALES
                and node.node_key in AFTERSALES_FIELD_NODE_KEYS
                and field in AFTERSALES_FIELD_OWNED_NODE_FIELDS
            )
        ):
            setattr(node, field, values[field])
    if node.project.service_type == ServiceProject.TYPE_AFTERSALES and "planned_start_at" in values:
        node.planned_end_at = _aftersales_planned_end(node)
    if node.project.service_type != ServiceProject.TYPE_PRESALES and node.planned_start_at and node.planned_end_at and node.planned_end_at < node.planned_start_at:
        raise DomainValidationError(
            "计划结束时间不能早于计划开始时间",
            code="INVALID_PLANNED_TIME_RANGE",
        )
    if node.actual_start_at and node.actual_end_at and node.actual_end_at < node.actual_start_at:
        raise DomainValidationError(
            "实际结束时间不能早于实际开始时间",
            code="INVALID_ACTUAL_TIME_RANGE",
        )
    touch_audit(node, request)
    if node.project.service_type == ServiceProject.TYPE_PRESALES and "schemeRounds" in (values.get("business_data") or {}):
        sync_presales_task_schedules(node)


@transaction.atomic
def save_project_node_draft(
    request,
    project_id: int,
    *,
    node_key: str,
    node_values: dict | None = None,
) -> ServiceProject:
    project = _locked_project(request, project_id)
    if project.deleted_at or project.status in {
        ServiceProject.STATUS_COMPLETED,
        ServiceProject.STATUS_CANCELLED,
    }:
        raise DomainValidationError("当前项目不能自动保存", code="PROJECT_AUTOSAVE_LOCKED", status=409)
    try:
        node = ProjectNode.objects.select_for_update().get(project=project, node_key=node_key)
    except ProjectNode.DoesNotExist as exc:
        raise DomainValidationError("项目节点不存在", code="PROJECT_NODE_NOT_FOUND", status=404) from exc
    if not node.enabled or node.status in {ProjectNode.STATUS_COMPLETED, ProjectNode.STATUS_SKIPPED}:
        raise DomainValidationError("当前节点不能自动保存", code="PROJECT_NODE_AUTOSAVE_LOCKED", status=409)

    draft_fields = (
        "business_data", "planned_start_at", "planned_end_at", "actual_start_at",
        "actual_end_at", "estimated_fee", "actual_fee",
    )
    before = {field: deepcopy(getattr(node, field)) for field in draft_fields}
    _apply_node_values(request, node, node_values or {})
    if all(getattr(node, field) == value for field, value in before.items()):
        return project
    node.save()
    touch_audit(project, request)
    project.save(update_fields=["updated_by", "updated_actor_id", "updated_at"])
    return project


@transaction.atomic
def submit_project_node_version(
    request,
    project_id: int,
    *,
    node_key: str,
    node_values: dict | None = None,
) -> ServiceProject:
    project = _locked_project(request, project_id)
    if project.deleted_at or project.status in {
        ServiceProject.STATUS_COMPLETED,
        ServiceProject.STATUS_CANCELLED,
        ServiceProject.STATUS_BLOCKED,
    }:
        raise DomainValidationError("当前项目不能提交版本", code="PROJECT_VERSION_LOCKED", status=409)
    try:
        node = ProjectNode.objects.select_for_update().get(project=project, node_key=node_key)
    except ProjectNode.DoesNotExist as exc:
        raise DomainValidationError("项目节点不存在", code="PROJECT_NODE_NOT_FOUND", status=404) from exc
    if not node.enabled or node.status in {ProjectNode.STATUS_COMPLETED, ProjectNode.STATUS_SKIPPED}:
        raise DomainValidationError("当前节点不能提交版本", code="PROJECT_NODE_VERSION_LOCKED", status=409)
    if node.kind == "end":
        raise DomainValidationError("结束标识不提交普通版本", code="PROJECT_END_VERSION_UNSUPPORTED", status=409)
    if project.service_type == ServiceProject.TYPE_MIDSALES and node.status != ProjectNode.STATUS_ACTIVE:
        raise DomainValidationError(
            "请先由管理端确认节点开始",
            code="PROJECT_NODE_NOT_STARTED",
            status=409,
        )

    values = node_values or {}
    _apply_node_values(request, node, values)
    now = timezone.now()
    node.business_data = {
        **(node.business_data or {}),
        "versionStatus": "submitted",
        "versionNumber": int((node.business_data or {}).get("versionNumber") or 0) + 1,
        "versionSubmittedAt": now.isoformat(),
        "versionSubmittedBy": request_identity(request)["user_id"],
    }
    if node.status == ProjectNode.STATUS_PENDING:
        node.status = ProjectNode.STATUS_ACTIVE
    node.save()
    project.current_node_key = node.node_key
    project.status = ServiceProject.STATUS_IN_PROGRESS
    touch_audit(project, request)
    project.save(update_fields=["current_node_key", "status", "updated_by", "updated_actor_id", "updated_at"])
    record_project_event(
        request,
        project,
        node=node,
        event_type="node_version_submitted",
        title=f"提交当前版本：{node.name}",
        detail=text(values.get("note")),
        after={
            "versionNumber": node.business_data["versionNumber"],
            "status": node.status,
        },
    )
    return project


@transaction.atomic
def reject_aftersales_completion(
    request,
    project_id: int,
    *,
    node_key: str,
    note: str,
) -> ServiceProject:
    project = ServiceProject.objects.select_for_update().get(pk=project_id)
    access.require_project(request, project, manage=True)
    if project.service_type != ServiceProject.TYPE_AFTERSALES:
        raise DomainValidationError("只有售后项目可以驳回完工资料", code="NOT_AFTERSALES_PROJECT", status=409)
    if project.deleted_at or project.status != ServiceProject.STATUS_IN_PROGRESS:
        raise DomainValidationError("当前售后项目不能驳回", code="AFTERSALES_REVIEW_LOCKED", status=409)
    reason = text(note)
    if not reason:
        raise DomainValidationError("请填写完工驳回原因", code="AFTERSALES_REJECT_REASON_REQUIRED")
    try:
        node = ProjectNode.objects.select_for_update().get(project=project, node_key=node_key)
    except ProjectNode.DoesNotExist as exc:
        raise DomainValidationError("项目节点不存在", code="PROJECT_NODE_NOT_FOUND", status=404) from exc
    if not node.enabled or node.status != ProjectNode.STATUS_ACTIVE:
        raise DomainValidationError("当前节点不能驳回", code="AFTERSALES_REVIEW_LOCKED", status=409)
    identity = request_identity(request)
    node_data = dict(node.business_data or {})
    submissions = dict(node_data.get("fieldSubmissions") or {})
    for assignment_id, submission in submissions.items():
        if not isinstance(submission, dict) or submission.get("submitted") is not True:
            continue
        submissions[assignment_id] = {
            **submission,
            "submitted": False,
            "rejectedAt": timezone.now().isoformat(),
            "rejectedReason": reason,
        }
    node.business_data = {
        **node_data,
        "fieldSubmissions": submissions,
        "managerReviewStatus": "rejected",
        "managerReviewNote": reason,
        "managerReviewedAt": timezone.now().isoformat(),
        "managerReviewedBy": identity["user_id"],
    }
    touch_audit(node, request)
    node.save(update_fields=["business_data", "updated_by", "updated_actor_id", "updated_at"])
    ProjectAssignment.objects.filter(
        project=project,
        node=node,
        status=ProjectAssignment.STATUS_COMPLETED,
    ).update(
        status=ProjectAssignment.STATUS_IN_PROGRESS,
        completed_at=None,
        updated_by=identity["user_id"],
        updated_actor_id=identity["actor_id"],
        updated_at=timezone.now(),
    )
    record_project_event(
        request,
        project,
        node=node,
        event_type="aftersales_completion_rejected",
        title="驳回现场完工资料",
        detail=reason,
        after={"managerReviewStatus": "rejected"},
    )
    return project


@transaction.atomic
def select_aftersales_node(request, project_id: int, *, node_key: str, note: str = "") -> ServiceProject:
    project = ServiceProject.objects.select_for_update().get(pk=project_id)
    access.require_project(request, project, manage=True)
    if project.service_type != ServiceProject.TYPE_AFTERSALES:
        raise DomainValidationError("只有售后项目可以选择服务节点", code="NOT_AFTERSALES_PROJECT", status=409)
    if project.deleted_at or project.status in {ServiceProject.STATUS_COMPLETED, ServiceProject.STATUS_CANCELLED}:
        raise DomainValidationError("当前售后项目不能切换服务节点", code="AFTERSALES_NODE_LOCKED", status=409)

    nodes = list(ProjectNode.objects.select_for_update().filter(project=project).order_by("sequence"))
    target = next((node for node in nodes if node.node_key == node_key), None)
    if target is None:
        raise DomainValidationError("售后服务节点不存在", code="PROJECT_NODE_NOT_FOUND", status=404)
    if target.node_key == project.current_node_key and target.enabled and target.status == ProjectNode.STATUS_ACTIVE:
        return project

    before_key = project.current_node_key
    now = timezone.now()
    identity = request_identity(request)
    previous_node_ids = []
    for node in nodes:
        selected = node.pk == target.pk
        if not selected and node.enabled:
            previous_node_ids.append(node.pk)
        node.enabled = selected
        node.status = ProjectNode.STATUS_PENDING if selected else ProjectNode.STATUS_SKIPPED
        if selected:
            node.actual_start_at = None
            node.actual_end_at = None
            node.completed_at = None
            node.completed_by = ""
            node.completed_actor_id = ""
        touch_audit(node, request)
        node.save()

    if previous_node_ids:
        ProjectAssignment.objects.filter(
            project=project,
            node_id__in=previous_node_ids,
            status__in=[
                ProjectAssignment.STATUS_ASSIGNED,
                ProjectAssignment.STATUS_ACCEPTED,
                ProjectAssignment.STATUS_IN_PROGRESS,
            ],
        ).update(
            status=ProjectAssignment.STATUS_CANCELLED,
            updated_by=identity["user_id"],
            updated_actor_id=identity["actor_id"],
            updated_at=now,
        )

    project.current_node_key = target.node_key
    project.status = ServiceProject.STATUS_IN_PROGRESS
    project.actual_end_date = None
    project.business_data = {**(project.business_data or {}), "serviceNodeKey": target.node_key}
    touch_audit(project, request)
    project.save()
    record_project_event(
        request,
        project,
        node=target,
        event_type="aftersales_node_selected",
        title=f"切换售后服务：{target.name}",
        detail=text(note),
        before={"currentNodeKey": before_key},
        after={"currentNodeKey": target.node_key},
    )
    return project


@transaction.atomic
def reopen_project_node(request, project_id: int, *, node_key: str = "", note: str = "") -> ServiceProject:
    project = _locked_project(request, project_id)
    access.require_project(request, project, manage=True)
    if project.deleted_at:
        raise DomainValidationError("当前项目不能退回节点", code="PROJECT_REOPEN_LOCKED", status=409)

    nodes = list(ProjectNode.objects.select_for_update().filter(project=project).order_by("sequence"))
    current = next((node for node in nodes if node.node_key == project.current_node_key), None)
    target = next((node for node in nodes if node.node_key == node_key), None) if node_key else None
    if node_key and target is None:
        raise DomainValidationError("项目节点不存在", code="PROJECT_NODE_NOT_FOUND", status=404)
    if target is not None and not target.enabled:
        raise DomainValidationError("不能退回到未启用节点", code="PROJECT_NODE_NOT_ENABLED", status=409)

    terminal_presales = (
        project.service_type == ServiceProject.TYPE_PRESALES
        and project.status in {ServiceProject.STATUS_CANCELLED, ServiceProject.STATUS_BLOCKED}
    )
    if project.status == ServiceProject.STATUS_CANCELLED and not terminal_presales:
        raise DomainValidationError("当前项目不能退回节点", code="PROJECT_REOPEN_LOCKED", status=409)
    if terminal_presales:
        terminal_key = text((project.business_data or {}).get("terminalNodeKey"))
        target = target or next((node for node in nodes if node.node_key == terminal_key), None)
        if target is None or target.node_key != terminal_key:
            raise DomainValidationError(
                "只能恢复导致项目终止的售前节点",
                code="PRESALES_RESTORE_TARGET_INVALID",
                status=409,
            )
        before_status = project.status
        identity = request_identity(request)
        now = timezone.now()
        target_data = dict(target.business_data or {})
        target_data.pop("outcome", None)
        target_data.pop("outcomeLabel", None)
        target.business_data = target_data
        target.status = ProjectNode.STATUS_ACTIVE
        target.actual_end_at = None
        target.completed_at = None
        target.completed_by = ""
        target.completed_actor_id = ""
        touch_audit(target, request)
        target.save()
        ProjectAssignment.objects.filter(
            project=project,
            node=target,
            status=ProjectAssignment.STATUS_COMPLETED,
        ).update(
            status=ProjectAssignment.STATUS_ASSIGNED,
            completed_at=None,
            updated_by=identity["user_id"],
            updated_actor_id=identity["actor_id"],
            updated_at=now,
        )
        project_data = dict(project.business_data or {})
        for key in ("terminalOutcome", "terminalOutcomeLabel", "terminalNodeKey"):
            project_data.pop(key, None)
        project.business_data = project_data
        project.current_node_key = target.node_key
        project.status = ServiceProject.STATUS_IN_PROGRESS
        project.actual_end_date = None
        touch_audit(project, request)
        project.save()
        _refresh_presales_node_states(request, nodes)
        record_project_event(
            request,
            project,
            node=target,
            event_type="presales_terminal_restored",
            title=f"恢复售前节点：{target.name}",
            detail=text(note),
            before={"status": before_status, "terminalNodeKey": terminal_key},
            after={"status": project.status, "currentNodeKey": target.node_key},
        )
        return project

    if project.service_type == ServiceProject.TYPE_MIDSALES:
        target = target or next(
            (node for node in reversed(nodes) if node.enabled and node.status == ProjectNode.STATUS_COMPLETED),
            None,
        )
        if target is None or target.status != ProjectNode.STATUS_COMPLETED:
            raise DomainValidationError("请选择已关闭的售中节点", code="MIDSALES_REOPEN_TARGET_INVALID", status=409)
        before_status = project.status
        identity = request_identity(request)
        now = timezone.now()
        target.status = ProjectNode.STATUS_ACTIVE
        target.actual_end_at = None
        target.completed_at = None
        target.completed_by = ""
        target.completed_actor_id = ""
        touch_audit(target, request)
        target.save()
        ProjectAssignment.objects.filter(
            project=project,
            node=target,
            status=ProjectAssignment.STATUS_COMPLETED,
        ).update(
            status=ProjectAssignment.STATUS_ASSIGNED,
            completed_at=None,
            updated_by=identity["user_id"],
            updated_actor_id=identity["actor_id"],
            updated_at=now,
        )
        project.current_node_key = target.node_key
        project.status = ServiceProject.STATUS_IN_PROGRESS
        project.actual_end_date = None
        touch_audit(project, request)
        project.save()
        record_project_event(
            request,
            project,
            node=target,
            event_type="project_node_reopened",
            title=f"打开节点：{target.name}",
            detail=text(note),
            before={"status": before_status},
            after={"status": project.status, "currentNodeKey": target.node_key},
        )
        return project

    if project.service_type == ServiceProject.TYPE_PRESALES:
        selected = target or current or next(
            (node for node in reversed(nodes) if node.enabled and node.status == ProjectNode.STATUS_COMPLETED),
            None,
        )
        if selected is not None and selected.status == ProjectNode.STATUS_ACTIVE:
            # A parallel branch can be ahead of current_node_key. Return its
            # actual predecessor, not the previous item in the numbered list.
            target = next((node for node in reversed(presales_prerequisites(nodes, selected))
                           if node.status == ProjectNode.STATUS_COMPLETED and presales_node_is_successful(node)), None)
        elif selected is not None and selected.status == ProjectNode.STATUS_COMPLETED:
            target = selected
        elif selected is not None:
            raise DomainValidationError("当前售前节点尚未解锁", code="PRESALES_NODE_LOCKED", status=409)
    elif project.status == ServiceProject.STATUS_COMPLETED:
        target = target or next((node for node in reversed(nodes) if node.enabled and node.status == ProjectNode.STATUS_COMPLETED), None)
    elif current is None:
        raise DomainValidationError("项目当前节点状态不一致", code="PROJECT_NODE_STATE_INVALID", status=409)
    elif target is None or target.pk == current.pk:
        target = next(
            (node for node in reversed(nodes) if node.enabled and node.sequence < current.sequence and node.status == ProjectNode.STATUS_COMPLETED),
            None,
        )
    elif target.sequence > current.sequence:
        raise DomainValidationError("不能退回到当前节点之后", code="PROJECT_REOPEN_TARGET_INVALID", status=409)

    if target is None:
        raise DomainValidationError("当前项目没有可退回节点", code="PROJECT_NO_PREVIOUS_NODE", status=409)

    if project.service_type == ServiceProject.TYPE_PRESALES and presales_locked(target, nodes):
        raise DomainValidationError("当前售前节点尚未解锁", code="PRESALES_NODE_LOCKED", status=409)

    before_key = project.current_node_key
    before_status = project.status
    now = timezone.now()
    identity = request_identity(request)
    reopened_node_ids = []
    affected_keys = {target.node_key}
    if project.service_type == ServiceProject.TYPE_PRESALES:
        while True:
            descendants = {key for key, parents in PRESALES_FLOW_DEPENDENCIES.items()
                           if any(parent in affected_keys for parent in parents)}
            if descendants.issubset(affected_keys):
                break
            affected_keys.update(descendants)
    for node in nodes:
        if not node.enabled:
            continue
        if (project.service_type == ServiceProject.TYPE_PRESALES and node.node_key not in affected_keys
                or project.service_type != ServiceProject.TYPE_PRESALES and node.sequence < target.sequence):
            continue
        reopened_node_ids.append(node.pk)
        node.status = ProjectNode.STATUS_ACTIVE if node.pk == target.pk else ProjectNode.STATUS_PENDING
        if project.service_type == ServiceProject.TYPE_PRESALES:
            node_data = dict(node.business_data or {})
            node_data.pop("outcome", None)
            node_data.pop("outcomeLabel", None)
            node.business_data = node_data
        node.actual_end_at = None
        node.completed_at = None
        node.completed_by = ""
        node.completed_actor_id = ""
        touch_audit(node, request)
        node.save()

    if project.service_type == ServiceProject.TYPE_PRESALES:
        _refresh_presales_node_states(request, nodes)

    ProjectAssignment.objects.filter(
        project=project,
        node_id__in=reopened_node_ids,
        status=ProjectAssignment.STATUS_COMPLETED,
    ).update(
        status=ProjectAssignment.STATUS_ASSIGNED,
        completed_at=None,
        updated_by=identity["user_id"],
        updated_actor_id=identity["actor_id"],
        updated_at=now,
    )
    project.current_node_key = target.node_key
    project.status = ServiceProject.STATUS_IN_PROGRESS
    project.actual_end_date = None
    touch_audit(project, request)
    project.save()
    record_project_event(
        request,
        project,
        node=target,
        event_type="project_node_reopened",
        title=f"退回节点：{target.name}",
        detail=text(note),
        before={"status": before_status, "currentNodeKey": before_key},
        after={"status": project.status, "currentNodeKey": target.node_key},
    )
    return project


@transaction.atomic
def assign_provider(
    request,
    project_id: int,
    *,
    node_key: str,
    provider_id: int,
    role: str = "",
    note: str = "",
    planned_start_date: date | None | object = ASSIGNMENT_VALUE_UNSET,
    standard_duration: str | object = ASSIGNMENT_VALUE_UNSET,
    expected_updated_at: str | object = ASSIGNMENT_VALUE_UNSET,
) -> ProjectAssignment:
    project = _locked_project(request, project_id)
    access.require_project(request, project, manage=True)
    if project.deleted_at or project.status in {ServiceProject.STATUS_COMPLETED, ServiceProject.STATUS_CANCELLED}:
        raise DomainValidationError("当前项目不能指派", code="PROJECT_ASSIGNMENT_LOCKED", status=409)
    if project.service_type == ServiceProject.TYPE_PRESALES:
        raise DomainValidationError(
            "售前项目人员必须从钉钉组织人员中选择",
            code="PRESALES_PROVIDER_ASSIGNMENT_FORBIDDEN",
            status=409,
        )
    try:
        node = ProjectNode.objects.select_for_update().get(project=project, node_key=node_key)
    except ProjectNode.DoesNotExist as exc:
        raise DomainValidationError("项目节点不存在", code="PROJECT_NODE_NOT_FOUND", status=404) from exc
    if expected_updated_at is not ASSIGNMENT_VALUE_UNSET:
        _check_node_draft_version(node, {"expected_updated_at": expected_updated_at})
    if not node.enabled or node.status in {ProjectNode.STATUS_SKIPPED, ProjectNode.STATUS_COMPLETED}:
        raise DomainValidationError("该节点不能指派", code="PROJECT_NODE_NOT_ASSIGNABLE", status=409)
    if project.service_type == ServiceProject.TYPE_MIDSALES and node.node_key not in MIDSALES_ASSIGNMENT_NODE_KEYS:
        raise DomainValidationError(
            "该售中节点不在项目人员配置范围内",
            code="MIDSALES_NODE_NOT_ASSIGNABLE",
            status=409,
        )
    try:
        provider = ServiceProvider.objects.select_for_update().get(pk=provider_id)
    except ServiceProvider.DoesNotExist as exc:
        raise DomainValidationError("服务人员不存在", code="PROVIDER_NOT_FOUND", status=404) from exc
    if provider.identity_source != ServiceProvider.IDENTITY_WECHAT_MINI:
        raise DomainValidationError(
            "售中、售后任务只能指派给通过微信小程序注册的服务人员",
            code="PROVIDER_SOURCE_NOT_WECHAT",
            status=409,
        )
    if provider.certification_status != ServiceProvider.CERT_CERTIFIED:
        raise DomainValidationError("只能指派已认证服务人员", code="PROVIDER_NOT_CERTIFIED", status=409)
    values = {
        "role": text(role),
        "note": text(note),
        "status": ProjectAssignment.STATUS_ASSIGNED,
    }
    if planned_start_date is not ASSIGNMENT_VALUE_UNSET:
        values["planned_start_date"] = planned_start_date
    if standard_duration is not ASSIGNMENT_VALUE_UNSET:
        values["standard_duration"] = text(standard_duration)
    node_assignments = ProjectAssignment.objects.select_for_update().filter(project=project, node=node)
    assignment = node_assignments.filter(provider=provider).first()
    current_assignment = node_assignments.exclude(status=ProjectAssignment.STATUS_CANCELLED).first()
    replacing_provider = current_assignment is not None and current_assignment.provider_id != provider.id
    reactivating_assignment = assignment is not None and assignment.status == ProjectAssignment.STATUS_CANCELLED
    previous_record = {}
    if reactivating_assignment:
        data = node.business_data if isinstance(node.business_data, dict) else {}
        for key in ("fieldDrafts", "field_drafts", "fieldSubmissions", "field_submissions"):
            record = (data.get(key) or {}).get(str(assignment.id))
            if record is not None:
                previous_record[key] = record
    created = assignment is None
    if assignment is None:
        values.setdefault(
            "planned_start_date",
            current_assignment.planned_start_date
            if current_assignment is not None
            else node.planned_start_at.date() if node.planned_start_at else None,
        )
        values.setdefault(
            "standard_duration",
            current_assignment.standard_duration
            if current_assignment is not None and current_assignment.standard_duration
            else "",
        )
        assignment = ProjectAssignment.objects.create(
            project=project,
            node=node,
            provider=provider,
            **values,
            **create_audit_fields(request),
        )
    else:
        if assignment.status == ProjectAssignment.STATUS_CANCELLED and current_assignment is not None:
            values.setdefault("planned_start_date", current_assignment.planned_start_date)
            values.setdefault("standard_duration", current_assignment.standard_duration)
        for field, value in values.items():
            setattr(assignment, field, value)
        assignment.accepted_at = None
        assignment.completed_at = None
        touch_audit(assignment, request)
        assignment.save()

    replaced_ids = []
    for previous in node_assignments.exclude(pk=assignment.pk).exclude(status=ProjectAssignment.STATUS_CANCELLED):
        previous.status = ProjectAssignment.STATUS_CANCELLED
        touch_audit(previous, request)
        previous.save(update_fields=["status", "updated_by", "updated_actor_id", "updated_at"])
        replaced_ids.append(previous.id)
    if replacing_provider or reactivating_assignment:
        node.actual_end_at = None
        node.actual_fee = None
        data = dict(node.business_data or {})
        mirror_keys = (
            MIDSALES_FIELD_OWNED_BUSINESS_FIELDS | AFTERSALES_FIELD_OWNED_BUSINESS_FIELDS
        ) - {"fieldDrafts", "field_drafts", "fieldSubmissions", "field_submissions"}
        for key in mirror_keys | {
            "managerReviewStatus", "managerReviewNote", "managerReviewedAt", "managerReviewedBy",
        }:
            data.pop(key, None)
        if reactivating_assignment:
            for key in ("fieldDrafts", "field_drafts", "fieldSubmissions", "field_submissions"):
                records = dict(data.get(key) or {})
                records.pop(str(assignment.id), None)
                if records:
                    data[key] = records
                else:
                    data.pop(key, None)
        node.business_data = data
        touch_audit(node, request)
        node.save(update_fields=[
            "actual_end_at", "actual_fee", "business_data",
            "updated_by", "updated_actor_id", "updated_at",
        ])
    touch_audit(node, request)
    node.save(update_fields=["updated_by", "updated_actor_id", "updated_at"])
    record_project_event(
        request,
        project,
        node=node,
        event_type="provider_assigned",
        title=f"指派服务人员：{provider.name}",
        detail=text(note),
        before={"previousAssignmentRecord": previous_record} if previous_record else {},
        after={
            "providerId": provider.id,
            "providerUserId": provider.auth_user_id,
            "created": created,
            "plannedStartDate": assignment.planned_start_date.isoformat() if assignment.planned_start_date else "",
            "standardDuration": assignment.standard_duration,
            "replacedAssignmentIds": replaced_ids,
        },
    )
    return assignment


@transaction.atomic
def create_ticket_record(request, fields: dict) -> ServiceTicket:
    identity = request_identity(request)
    ticket = ServiceTicket.objects.create(
        **fields,
        reporter_user_id=identity["user_id"],
        reporter_name=identity["user_name"],
        **create_audit_fields(request),
    )
    TicketMessage.objects.create(
        ticket=ticket,
        author_user_id=identity["user_id"],
        author_name=identity["user_name"],
        actor_user_id=identity["actor_id"],
        message_type="system",
        content="创建售后工单",
        status_snapshot=ticket.status,
    )
    record_project_event(
        request,
        ticket.project,
        node=ticket.node,
        event_type="ticket_created",
        title=f"创建工单：{ticket.title}",
        after={"ticketCode": ticket.code, "status": ticket.status},
    )
    return ticket


@transaction.atomic
def create_feedback_record(request, fields: dict) -> FieldFeedback:
    feedback = FieldFeedback.objects.create(**fields, **create_audit_fields(request))
    record_project_event(
        request,
        feedback.project,
        node=feedback.node,
        event_type="feedback_created",
        title=f"提交反馈：{feedback.get_feedback_type_display()}",
        after={"feedbackId": feedback.id, "providerId": feedback.provider_id},
    )
    return feedback


@transaction.atomic
def create_service_rating(
    request,
    *,
    project_id: int,
    node_key: str,
    provider_id: int,
    rating: int,
) -> ServiceRating:
    assignment = ProjectAssignment.objects.select_for_update().select_related(
        "project",
        "node",
        "provider",
    ).filter(
        project_id=project_id,
        project__deleted_at__isnull=True,
        project__service_type__in=[ServiceProject.TYPE_MIDSALES, ServiceProject.TYPE_AFTERSALES],
        node__node_key=node_key,
        provider_id=provider_id,
        status=ProjectAssignment.STATUS_COMPLETED,
    ).first()
    if assignment is None:
        raise DomainValidationError(
            "只有完成该服务节点后才能评分",
            code="SERVICE_RATING_COMPLETION_REQUIRED",
            status=409,
        )
    if rating < 1 or rating > 5:
        raise DomainValidationError("服务评分必须为1到5分", code="INVALID_SERVICE_RATING")

    service_rating, created = ServiceRating.objects.select_for_update().get_or_create(
        assignment=assignment,
        defaults={"rating": rating, **create_audit_fields(request)},
    )
    if not created and service_rating.rating != rating:
        service_rating.rating = rating
        touch_audit(service_rating, request)
        service_rating.save(update_fields=["rating", "updated_by", "updated_actor_id", "updated_at"])

    average = ServiceRating.objects.filter(
        assignment__provider_id=provider_id,
    ).aggregate(value=Avg("rating"))["value"]
    provider = ServiceProvider.objects.select_for_update().get(pk=provider_id)
    provider.score = Decimal(str(average)).quantize(Decimal("0.01")) if average is not None else Decimal("0")
    touch_audit(provider, request)
    provider.save(update_fields=["score", "updated_by", "updated_actor_id", "updated_at"])
    record_project_event(
        request,
        assignment.project,
        node=assignment.node,
        event_type="service_rated",
        title=f"服务人员评分：{assignment.provider.name} {rating}分",
        after={"assignmentId": assignment.id, "providerId": provider_id, "rating": rating},
    )
    return service_rating


@transaction.atomic
def transition_ticket(
    request,
    ticket_id: int,
    *,
    next_status: str,
    note: str = "",
    is_admin: bool,
) -> ServiceTicket:
    ticket = ServiceTicket.objects.select_for_update().get(pk=ticket_id)
    allowed = TICKET_TRANSITIONS.get(ticket.status, set())
    if next_status not in allowed:
        raise DomainValidationError("工单状态不能这样流转", code="INVALID_TICKET_TRANSITION", status=409)
    if not is_admin and next_status not in PROVIDER_TICKET_TRANSITIONS.get(ticket.status, set()):
        raise DomainValidationError("当前服务人员不能执行该工单流转", code="TICKET_TRANSITION_FORBIDDEN", status=403)
    previous = ticket.status
    ticket.status = next_status
    if next_status == ServiceTicket.STATUS_COMPLETED:
        ticket.completed_at = timezone.now()
        ticket.resolution = text(note) or ticket.resolution
    touch_audit(ticket, request)
    ticket.save()
    identity = request_identity(request)
    TicketMessage.objects.create(
        ticket=ticket,
        author_user_id=identity["user_id"],
        author_name=identity["user_name"],
        actor_user_id=identity["actor_id"],
        message_type="status",
        content=text(note) or f"工单状态由 {previous} 变更为 {next_status}",
        status_snapshot=next_status,
    )
    record_project_event(
        request,
        ticket.project,
        node=ticket.node,
        event_type="ticket_transition",
        title=f"工单状态：{ticket.get_status_display()}",
        detail=text(note),
        before={"status": previous},
        after={"status": next_status, "ticketCode": ticket.code},
    )
    return ticket


@transaction.atomic
def review_feedback(
    request,
    feedback_id: int,
    *,
    decision: str,
    review_note: str = "",
    reward_values: dict | None = None,
) -> tuple[FieldFeedback, Reward | None]:
    feedback = FieldFeedback.objects.select_for_update().get(pk=feedback_id)
    from .crm_source import assert_crm_project_access

    assert_crm_project_access(request, feedback.project, write=True)
    if feedback.status not in {FieldFeedback.STATUS_SUBMITTED, FieldFeedback.STATUS_REVIEWING}:
        raise DomainValidationError("反馈已经完成审核", code="FEEDBACK_ALREADY_REVIEWED", status=409)
    if decision not in {FieldFeedback.STATUS_ACCEPTED, FieldFeedback.STATUS_REJECTED}:
        raise DomainValidationError("反馈审核结果无效", code="INVALID_FEEDBACK_DECISION")
    feedback.status = decision
    feedback.review_note = text(review_note)
    feedback.reviewed_by = request_identity(request)["user_id"]
    feedback.reviewed_at = timezone.now()
    touch_audit(feedback, request)

    reward = None
    values = reward_values or {}
    reward_requested = any(
        values.get(key) not in (None, "", 0)
        for key in ("code", "title", "description", "amount", "points", "prize", "prize_id")
    )
    if decision == FieldFeedback.STATUS_ACCEPTED and not feedback.reward_generated and reward_requested:
        reward_type = text(values.get("reward_type")) or Reward.TYPE_PRIZE
        from .reward_prize_views import resolve_active_prize
        selected_prize = resolve_active_prize(values.get("prize_id")) if reward_type == Reward.TYPE_PRIZE else None
        try:
            reward = Reward.objects.create(
                code=text(values.get("code")) or generated_code("RW"),
                provider=feedback.provider,
                project=feedback.project,
                feedback=feedback,
                reward_type=reward_type,
                title=text(values.get("title")) or "有效服务反馈奖励",
                description=text(values.get("description")) or feedback.review_note or "现场反馈审核通过，生成服务奖励。",
                amount=values.get("amount"),
                points=values.get("points") or 0,
                prize=selected_prize.name if selected_prize else "",
                status=Reward.STATUS_PENDING,
                **create_audit_fields(request),
            )
        except IntegrityError as exc:
            raise DomainValidationError("奖励编号已存在", code="REWARD_CODE_CONFLICT", status=409) from exc
        feedback.reward_generated = True
    feedback.save()
    record_project_event(
        request,
        feedback.project,
        node=feedback.node,
        event_type="feedback_reviewed",
        title=f"反馈审核：{feedback.get_status_display()}",
        detail=feedback.review_note,
        after={"feedbackId": feedback.id, "rewardId": reward.id if reward else None},
    )
    return feedback, reward


@transaction.atomic
def transition_reward(request, reward_id: int, *, next_status: str, note: str = "") -> Reward:
    reward = Reward.objects.select_for_update().get(pk=reward_id)
    if reward.project_id:
        from .crm_source import assert_crm_project_access

        assert_crm_project_access(request, reward.project, write=True)
    if next_status not in REWARD_TRANSITIONS.get(reward.status, set()):
        raise DomainValidationError("奖励状态不能这样流转", code="INVALID_REWARD_TRANSITION", status=409)
    previous = reward.status
    reward.status = next_status
    reward.transition_note = text(note)
    if next_status == Reward.STATUS_ISSUED:
        reward.issued_at = timezone.now()
    touch_audit(reward, request)
    reward.save()
    if reward.project_id:
        record_project_event(
            request,
            reward.project,
            event_type="reward_transition",
            title=f"奖励状态：{reward.get_status_display()}",
            detail=reward.transition_note,
            before={"status": previous},
            after={"status": next_status, "rewardCode": reward.code},
        )
    return reward
