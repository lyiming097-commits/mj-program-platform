from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (
    PrivateAttachment,
    ProjectAssignment,
    ProjectNode,
    ServiceProject,
    ServiceProvider,
)
from .serializers import serialize_assignment, serialize_mobile_task_node
from .presales_task_schedule import sync_presales_task_schedules
from .services import merge_presales_scheme_rounds, record_project_event, request_identity, touch_audit


MOBILE_ASSIGNMENT_STATUSES = {
    ProjectAssignment.STATUS_ASSIGNED,
    ProjectAssignment.STATUS_ACCEPTED,
    ProjectAssignment.STATUS_IN_PROGRESS,
}
PRESALES_PROGRESS_MAX_ROUNDS = 30


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


def _datetime(value, label: str):
    raw = _text(value)
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        return _error(f"{label}格式无效", status=400, code="INVALID_DATETIME")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _minute_precision(value):
    return value.replace(second=0, microsecond=0) if value is not None else None


def _ends_before_start(actual_start, actual_end) -> bool:
    return (
        actual_start is not None
        and actual_end is not None
        and _minute_precision(actual_end) < _minute_precision(actual_start)
    )


def _money(value, label: str):
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return _error(f"{label}必须是有效金额", status=400, code="INVALID_AMOUNT")
    if not parsed.is_finite() or parsed < 0 or parsed > Decimal("9999999999.99"):
        return _error(f"{label}超出允许范围", status=400, code="INVALID_AMOUNT")
    return parsed.quantize(Decimal("0.01"))


def _limited_text(payload: dict, key: str, label: str, maximum: int) -> tuple[str, JsonResponse | None]:
    value = _text(payload.get(key))
    if len(value) > maximum:
        return "", _error(f"{label}不能超过{maximum}字", status=400, code="TEXT_TOO_LONG")
    return value, None


def _actual_duration_text(actual_start, actual_end) -> str:
    actual_start = _minute_precision(actual_start)
    actual_end = _minute_precision(actual_end)
    if actual_start is None or actual_end is None or actual_end < actual_start:
        return ""
    minutes = int((actual_end - actual_start).total_seconds() // 60)
    days, remaining = divmod(minutes, 24 * 60)
    hours, minutes = divmod(remaining, 60)
    return f"{days}天{hours}小时{minutes}分钟"


def _presales_progress_rounds(node: ProjectNode, payload: dict) -> tuple[list[dict], JsonResponse | None]:
    if node.project.service_type != ServiceProject.TYPE_PRESALES or node.kind != "delivery":
        return [], None
    raw_rounds = payload.get("schemeRounds", [])
    if not isinstance(raw_rounds, list):
        return [], _error("推进记录格式无效", status=400, code="INVALID_PRESALES_PROGRESS")
    if len(raw_rounds) > PRESALES_PROGRESS_MAX_ROUNDS:
        return [], _error(
            f"推进记录不能超过{PRESALES_PROGRESS_MAX_ROUNDS}轮",
            status=400,
            code="INVALID_PRESALES_PROGRESS",
        )

    parsed_rounds = []
    attachment_ids = set()
    for index, raw_round in enumerate(raw_rounds, start=1):
        if not isinstance(raw_round, dict):
            return [], _error(f"第{index}轮推进记录格式无效", status=400, code="INVALID_PRESALES_PROGRESS")
        work_date = _text(raw_round.get("designDate"))
        if not work_date or parse_date(work_date) is None:
            return [], _error(f"请填写第{index}轮工作日期", status=409, code="MOBILE_COMPLETION_INCOMPLETE")
        note = _text(raw_round.get("note"))
        if len(note) > 5_000:
            return [], _error(f"第{index}轮备注不能超过5000字", status=400, code="TEXT_TOO_LONG")
        raw_attachment_ids = raw_round.get("attachmentIds", [])
        if not isinstance(raw_attachment_ids, list):
            return [], _error(f"第{index}轮附件格式无效", status=400, code="INVALID_PRESALES_PROGRESS")
        normalized_ids = []
        for raw_id in raw_attachment_ids:
            try:
                attachment_id = int(str(raw_id))
            except (TypeError, ValueError):
                return [], _error(f"第{index}轮附件无效", status=400, code="INVALID_PRESALES_PROGRESS")
            if attachment_id <= 0:
                return [], _error(f"第{index}轮附件无效", status=400, code="INVALID_PRESALES_PROGRESS")
            if attachment_id not in normalized_ids:
                normalized_ids.append(attachment_id)
                attachment_ids.add(attachment_id)
        parsed_rounds.append({
            "designDate": work_date,
            "note": note,
            "attachmentIds": normalized_ids,
        })

    attachments = {
        item.id: item
        for item in PrivateAttachment.objects.filter(
            id__in=attachment_ids,
            target_type=PrivateAttachment.TARGET_PROJECT_NODE,
            target_id=node.id,
            category=PrivateAttachment.CATEGORY_SCHEME_SUBMISSION,
        )
    }
    normalized_rounds = []
    for index, item in enumerate(parsed_rounds, start=1):
        if any(attachment_id not in attachments for attachment_id in item["attachmentIds"]):
            return [], _error(
                f"第{index}轮提交附件不存在或不属于当前节点",
                status=409,
                code="MOBILE_COMPLETION_INCOMPLETE",
            )
        latest = max((attachments[attachment_id] for attachment_id in item["attachmentIds"]), key=lambda row: row.created_at) if item["attachmentIds"] else None
        normalized_rounds.append({
            **item,
            "attachmentIds": [str(attachment_id) for attachment_id in item["attachmentIds"]],
            "submitDate": timezone.localtime(latest.created_at).date().isoformat() if latest else "",
            "submittedAt": latest.created_at.isoformat() if latest else "",
        })
    return normalized_rounds, None


def _assigned_task(request, assignment_id: int):
    if (getattr(request, "auth_token_claims", {}) or {}).get("chn") != "wechat-mini":
        return None, _error("该接口仅供微信小程序服务人员使用", status=403, code="WECHAT_PROVIDER_REQUIRED")
    user_id = _text(getattr(request, "auth_user_id", ""))
    provider = ServiceProvider.objects.filter(
        auth_user_id=user_id,
        certification_status=ServiceProvider.CERT_CERTIFIED,
    ).first()
    if provider is None:
        return None, _error("当前服务人员尚未通过认证", status=403, code="SERVICE_PROVIDER_REQUIRED")
    assignment = ProjectAssignment.objects.select_for_update().select_related(
        "project",
        "node",
        "provider",
    ).filter(
        pk=assignment_id,
        provider=provider,
        project__deleted_at__isnull=True,
    ).exclude(
        node__node_key="mail-service",
    ).first()
    if assignment is None:
        return None, _error("现场任务不存在或无权访问", status=404, code="MOBILE_TASK_NOT_FOUND")
    if assignment.project.service_type == ServiceProject.TYPE_PRESALES:
        return None, _error("售前服务由管理端完成，不提供现场任务", status=404, code="MOBILE_TASK_NOT_FOUND")
    if assignment.status not in MOBILE_ASSIGNMENT_STATUSES:
        return None, _error("现场任务已结束，不能继续修改", status=409, code="MOBILE_TASK_READ_ONLY")
    if assignment.node.status == ProjectNode.STATUS_COMPLETED or assignment.project.status in {
        ServiceProject.STATUS_COMPLETED,
        ServiceProject.STATUS_CANCELLED,
    }:
        return None, _error("现场任务已结束，不能继续修改", status=409, code="MOBILE_TASK_READ_ONLY")
    if not assignment.node.enabled:
        return None, _error("现场任务节点已停用", status=409, code="MOBILE_TASK_DISABLED")
    if assignment.node.status != ProjectNode.STATUS_ACTIVE or assignment.node.actual_start_at is None:
        return None, _error("管理端尚未确认节点开始", status=409, code="MOBILE_TASK_NOT_STARTED")
    return assignment, None


def _validate_field_submission(node: ProjectNode, data: dict, submission: dict | None = None) -> JsonResponse | None:
    missing = []
    if not data.get("actualStartTime"):
        missing.append("实际开始时间")
    if not data.get("actualEndTime"):
        missing.append("实际结束时间")
    if not _text(data.get("actualDuration")):
        missing.append("实际服务时长")
    actual_fee = (submission or {}).get("actualFee", data.get("actualFee"))
    requires_actual_fee = not (
        node.project.service_type == ServiceProject.TYPE_PRESALES
        and node.kind == "delivery"
    )
    if requires_actual_fee and actual_fee in (None, ""):
        missing.append("实际费用")
    if node.project.service_type == ServiceProject.TYPE_PRESALES and node.kind == "delivery":
        progress_rounds = (submission or {}).get("schemeRounds", data.get("schemeRounds"))
        if not isinstance(progress_rounds, list) or not progress_rounds:
            missing.append(f"{node.name}推进记录")
    if missing:
        return _error(
            "现场完工资料不完整：" + "、".join(missing),
            status=409,
            code="MOBILE_COMPLETION_INCOMPLETE",
        )
    return None


def _exclude_former_provider_execution(node: ProjectNode, assignment_id: int) -> None:
    data = dict(node.business_data or {})
    record_keys = ("fieldDrafts", "field_drafts", "fieldSubmissions", "field_submissions")
    if not any(
        isinstance(data.get(key), dict)
        and any(str(record_id) != str(assignment_id) for record_id in data[key])
        for key in record_keys
    ):
        return
    own = {}
    for key in record_keys:
        own.update((data.get(key) or {}).get(str(assignment_id)) or {})
    if "actualEndAt" not in own:
        node.actual_end_at = None
        for key in ("actualEndTime", "actual_end_time", "actualDuration", "actual_duration"):
            data.pop(key, None)
    if "actualFee" not in own:
        node.actual_fee = None
    if "actualFeeNote" not in own:
        data.pop("feeActualNote", None)
        data.pop("fee_actual_note", None)
    if "settlementEligible" not in own:
        data.pop("settlementEligible", None)
        data.pop("settlement_eligible", None)
    node.business_data = data


@csrf_exempt
@require_http_methods(["PATCH", "POST"])
@transaction.atomic
def mobile_task_update(request, assignment_id: int):
    assignment, failure = _assigned_task(request, assignment_id)
    if failure is not None:
        return failure
    payload = _json_body(request)
    if payload is None:
        return _error("请求 JSON 格式错误", status=400, code="INVALID_JSON")
    node = assignment.node
    _exclude_former_provider_execution(node, assignment.id)
    if payload.get("progressOnly") is True:
        if assignment.project.service_type != ServiceProject.TYPE_PRESALES or node.kind != "delivery":
            return _error("当前任务不支持方案推进提交", status=409, code="PRESALES_PROGRESS_UNSUPPORTED")
        progress_rounds, failure = _presales_progress_rounds(node, payload)
        if failure is not None:
            return failure
        node_data = dict(node.business_data or {})
        progress_rounds = merge_presales_scheme_rounds(
            node_data.get("schemeRounds"),
            progress_rounds,
            source="field",
        )
        identity = request_identity(request)
        submitted_at = timezone.now()
        node_data.update({
            "schemeRounds": progress_rounds,
            "schemeProgressSubmittedAt": submitted_at.isoformat(),
            "schemeProgressSubmittedRoundCount": len(progress_rounds),
            "schemeProgressSubmittedBy": identity["user_id"],
            "schemeProgressSubmittedByName": identity["user_name"],
        })
        node.business_data = node_data
        touch_audit(node, request)
        node.save(update_fields=["business_data", "updated_by", "updated_actor_id", "updated_at"])
        sync_presales_task_schedules(node)
        record_project_event(
            request,
            node.project,
            node=node,
            event_type="presales_progress_submitted",
            title=f"现场提交{node.name}推进记录",
            detail=f"共提交{len(progress_rounds)}轮推进记录",
            after={"roundCount": len(progress_rounds), "submittedAt": submitted_at.isoformat()},
        )
        node.refresh_from_db()
        return JsonResponse({
            "ok": True,
            "item": {
                "assignment": serialize_assignment(assignment),
                "node": serialize_mobile_task_node(node, assignment.id),
                "progressRounds": progress_rounds,
            },
        })
    if payload.get("draft") is True:
        actual_end = _datetime(payload.get("actualEndAt"), "实际结束时间") if "actualEndAt" in payload else None
        if isinstance(actual_end, JsonResponse):
            return actual_end
        actual_fee = _money(payload.get("actualFee"), "实际费用") if "actualFee" in payload else None
        if isinstance(actual_fee, JsonResponse):
            return actual_fee
        if _ends_before_start(node.actual_start_at, actual_end):
            return _error("实际结束时间不能早于实际开始时间", status=400, code="INVALID_ACTUAL_TIME_RANGE")
        actual_fee_note, failure = _limited_text(payload, "actualFeeNote", "实际费用备注", 5_000)
        if failure is not None:
            return failure
        note, failure = _limited_text(payload, "note", "现场备注", 5_000)
        if failure is not None:
            return failure
        node_data = dict(node.business_data or {})
        drafts = dict(node_data.get("fieldDrafts") or {})
        draft = dict(drafts.get(str(assignment.id)) or {})
        if "actualEndAt" in payload:
            draft["actualEndAt"] = actual_end.isoformat() if actual_end else ""
            node.actual_end_at = actual_end
        if "actualFee" in payload:
            draft["actualFee"] = format(actual_fee, "f") if actual_fee is not None else ""
            node.actual_fee = actual_fee
        if "actualFeeNote" in payload:
            draft["actualFeeNote"] = actual_fee_note
            node_data["feeActualNote"] = actual_fee_note
        if "note" in payload:
            draft["note"] = note
        draft["actualDuration"] = _actual_duration_text(node.actual_start_at, node.actual_end_at)
        # Keep field-owned execution values at the canonical node level while the
        # provider is still editing. Management reads these values from the node
        # business data before the final completion submission.
        node_data["actualStartTime"] = node.actual_start_at.isoformat() if node.actual_start_at else ""
        node_data["actualEndTime"] = node.actual_end_at.isoformat() if node.actual_end_at else ""
        node_data["actualDuration"] = draft["actualDuration"]
        draft["updatedAt"] = timezone.now().isoformat()
        drafts[str(assignment.id)] = draft
        node_data["fieldDrafts"] = drafts
        node.business_data = node_data
        touch_audit(node, request)
        node.save(update_fields=[
            "actual_end_at", "actual_fee", "business_data",
            "updated_by", "updated_actor_id", "updated_at",
        ])
        node.refresh_from_db()
        assignment.refresh_from_db()
        return JsonResponse({
            "ok": True,
            "item": {
                "assignment": serialize_assignment(assignment),
                "node": serialize_mobile_task_node(node, assignment.id),
                "fieldDraft": draft,
            },
        })
    if payload.get("submitted") is not True:
        return _error(
            "请点击确认完工后提交现场资料",
            status=409,
            code="MOBILE_COMPLETION_CONFIRM_REQUIRED",
        )

    actual_start = node.actual_start_at
    if actual_start is None and "actualStartAt" in payload:
        actual_start = _datetime(payload.get("actualStartAt"), "实际开始时间")
        if isinstance(actual_start, JsonResponse):
            return actual_start
    actual_end = _datetime(payload.get("actualEndAt"), "实际结束时间") if "actualEndAt" in payload else node.actual_end_at
    if isinstance(actual_end, JsonResponse):
        return actual_end
    actual_fee = _money(payload.get("actualFee"), "实际费用") if "actualFee" in payload else node.actual_fee
    if isinstance(actual_fee, JsonResponse):
        return actual_fee
    if _ends_before_start(actual_start, actual_end):
        return _error("实际结束时间不能早于实际开始时间", status=400, code="INVALID_ACTUAL_TIME_RANGE")

    actual_duration = _actual_duration_text(actual_start, actual_end)
    actual_fee_note, failure = _limited_text(payload, "actualFeeNote", "实际费用备注", 5_000)
    if failure is not None:
        return failure
    note, failure = _limited_text(payload, "note", "现场备注", 5_000)
    if failure is not None:
        return failure
    if "settlementEligible" in payload and not isinstance(payload.get("settlementEligible"), bool):
        return _error("结算资格必须是布尔值", status=400, code="INVALID_SETTLEMENT_ELIGIBILITY")
    node_data = dict(node.business_data or {})
    if node.project.service_type == ServiceProject.TYPE_PRESALES and node.kind == "delivery":
        saved_rounds = node_data.get("schemeRounds")
        if not isinstance(saved_rounds, list) or not saved_rounds:
            return _error(
                "请先提交方案推进记录",
                status=409,
                code="PRESALES_PROGRESS_SUBMIT_REQUIRED",
            )
        progress_rounds, failure = _presales_progress_rounds(node, {"schemeRounds": saved_rounds})
        if failure is not None:
            return failure
    else:
        progress_rounds, failure = _presales_progress_rounds(node, payload)
        if failure is not None:
            return failure
    submissions = dict(node_data.get("fieldSubmissions") or {})
    submission = dict(submissions.get(str(assignment.id)) or {})
    submission["actualStartAt"] = actual_start.isoformat()
    node_data["actualStartTime"] = submission["actualStartAt"]
    if "actualEndAt" in payload:
        submission["actualEndAt"] = actual_end.isoformat() if actual_end else ""
        node_data["actualEndTime"] = submission["actualEndAt"]
    if "actualFee" in payload:
        submission["actualFee"] = format(actual_fee, "f") if actual_fee is not None else ""
    if {"actualStartAt", "actualEndAt", "actualDuration"}.intersection(payload):
        submission["actualDuration"] = actual_duration
        node_data["actualDuration"] = actual_duration
    if "actualFeeNote" in payload:
        submission["actualFeeNote"] = actual_fee_note
        node_data["feeActualNote"] = actual_fee_note
    if "settlementEligible" in payload:
        submission["settlementEligible"] = payload["settlementEligible"]
        node_data["settlementEligible"] = payload["settlementEligible"]
    if "note" in payload:
        submission["note"] = note
        if node.project.service_type == ServiceProject.TYPE_PRESALES:
            node_data["deliveryNote"] = note
    if node.project.service_type == ServiceProject.TYPE_PRESALES and node.kind == "delivery":
        progress_rounds = [dict(item) for item in progress_rounds if isinstance(item, dict)]
        submission["schemeRounds"] = progress_rounds
        node_data["schemeRounds"] = progress_rounds
        node_data["schemeProgressSubmittedRoundCount"] = len(progress_rounds)
    submitted = True
    completed_at = timezone.now()
    submission["submittedAt"] = completed_at.isoformat()
    identity = request_identity(request)
    submission.update({
        "submitted": submitted or bool(submission.get("submitted")),
        "providerId": assignment.provider_id,
        "providerName": assignment.provider.name,
        "updatedBy": identity["user_id"],
        "updatedActorId": identity["actor_id"],
        "updatedAt": completed_at.isoformat(),
    })
    submissions[str(assignment.id)] = submission
    node_data["fieldSubmissions"] = submissions
    drafts = dict(node_data.get("fieldDrafts") or {})
    drafts.pop(str(assignment.id), None)
    if drafts:
        node_data["fieldDrafts"] = drafts
    else:
        node_data.pop("fieldDrafts", None)
    node_data["managerReviewStatus"] = "submitted"
    node_data.pop("managerReviewNote", None)
    node_data.pop("managerReviewedAt", None)
    node_data.pop("managerReviewedBy", None)

    failure = _validate_field_submission(node, node_data, submission)
    if failure is not None:
        return failure

    node.actual_start_at = actual_start
    node.actual_end_at = actual_end
    node.actual_fee = actual_fee
    node.business_data = node_data
    touch_audit(node, request)
    node.save()
    sync_presales_task_schedules(node)
    assignment.status = ProjectAssignment.STATUS_COMPLETED
    assignment.completed_at = completed_at
    touch_audit(assignment, request)
    assignment.save(update_fields=[
        "status", "completed_at", "updated_by", "updated_actor_id", "updated_at",
    ])
    record_project_event(
        request,
        node.project,
        node=node,
        event_type="field_completion_submitted",
        title="现场完工资料已提交",
        detail=note,
        after={
            "assignmentId": assignment.id,
            "providerId": assignment.provider_id,
            "submitted": submitted,
            "settlementEligible": submission.get("settlementEligible"),
            "actualFee": submission.get("actualFee", ""),
        },
    )
    node.refresh_from_db()
    assignment.refresh_from_db()
    return JsonResponse({
        "ok": True,
        "item": {
            "assignment": serialize_assignment(assignment),
            "node": serialize_mobile_task_node(node, assignment.id),
            "fieldSubmission": submission,
        },
    })
