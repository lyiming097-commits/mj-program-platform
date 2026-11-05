"""Round links and processing reuse the project's management/CRM permissions."""
import uuid
import logging

from django.db import transaction

from .models import PrivateAttachment, ProjectNode, ServiceProject
from .presales_task_schedule import sync_presales_task_schedules
from .services import (
    DomainValidationError, _locked_project, advance_project, record_project_event,
    text, touch_audit, validate_presales_round_schedule,
)
from .workflow_rules import presales_locked
from .access import require_node

logger = logging.getLogger(__name__)


def process_presales_round(request, project_id, node_key, payload, *, reason_files=()):
    # Storage is not transactional. Clean up every file if any part of the
    # round/event/database commit fails, so retries never leave partial uploads.
    stored_files = []
    try:
        return _process_presales_round(request, project_id, node_key, payload,
                                      reason_files=reason_files, stored_files=stored_files)
    except Exception:
        for storage, name in stored_files:
            try:
                storage.delete(name)
            except Exception:
                logger.exception("Could not remove rolled-back round reason attachment")
        raise


def _save_reason_files(request, node, uploads, stored_files):
    from .attachment_views import MAX_ATTACHMENT_SIZE, _validate_upload

    validated = []
    for upload in uploads:
        name, mime, failure = _validate_upload(upload)
        if failure is not None:
            import json
            error = json.loads(failure.content)
            raise DomainValidationError(error["error"], code=error["code"], status=failure.status_code)
        validated.append((upload, name, mime))
    if sum(upload.size for upload, _name, _mime in validated) > MAX_ATTACHMENT_SIZE:
        raise DomainValidationError("本次原因附件合计不能超过200MB", code="ATTACHMENT_TOO_LARGE")
    ids = []
    user_id = text(getattr(request, "auth_user_id", ""))
    actor_id = text(getattr(request, "auth_actor_user_id", "")) or user_id
    for upload, name, mime in validated:
        item = PrivateAttachment(
            target_type=PrivateAttachment.TARGET_PROJECT_NODE, target_id=node.pk,
            category=PrivateAttachment.CATEGORY_SCHEME_SUBMISSION,
            original_name=name, mime_type=mime, size=upload.size,
            uploaded_by=user_id, uploaded_actor_id=actor_id,
        )
        item.file.save(name, upload, save=False)
        stored_files.append((item.file.storage, item.file.name))
        item.save()
        ids.append(str(item.pk))
    return ids


def _editable_node(request, project_id, node_key):
    project = _locked_project(request, project_id)
    nodes = list(project.nodes.select_for_update().order_by("sequence"))
    node = next((item for item in nodes if item.node_key == node_key), None)
    if project.service_type != ServiceProject.TYPE_PRESALES or node is None or node.kind != "delivery":
        raise DomainValidationError("仅售前推进节点支持轮次处理", code="PRESALES_ROUND_NODE_INVALID", status=404)
    require_node(request, node)
    if (project.deleted_at or project.status != ServiceProject.STATUS_IN_PROGRESS
            or not node.enabled or node.status != ProjectNode.STATUS_ACTIVE
            or presales_locked(node, nodes)):
        raise DomainValidationError("当前节点已完成或尚未解锁，请刷新项目查看最新状态", code="PRESALES_ROUND_LOCKED", status=409)
    return project, node


def _check_version(node, value):
    if not isinstance(value, str) or value != node.updated_at.isoformat():
        raise DomainValidationError("本轮内容已变动，请刷新项目后重新处理", code="PRESALES_ROUND_CONFLICT", status=409)


@transaction.atomic
def prepare_round_forward(request, project_id, node_key, payload):
    project, node = _editable_node(request, project_id, node_key)
    _check_version(node, payload.get("expectedUpdatedAt"))
    rounds = validate_presales_round_schedule((node.business_data or {}).get("schemeRounds", []))
    index = payload.get("roundIndex")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(rounds):
        raise DomainValidationError("所选轮次已不存在", code="PRESALES_ROUND_NOT_FOUND", status=404)
    requested_id = text(payload.get("roundId"))
    if requested_id and requested_id != rounds[index].get("roundId"):
        raise DomainValidationError("轮次已变动，请重新打开项目", code="PRESALES_ROUND_CONFLICT", status=409)
    changed = False
    for item in rounds:
        if not item.get("roundId"):
            item["roundId"] = str(uuid.uuid4())
            changed = True
    if len({item["roundId"] for item in rounds}) != len(rounds):
        raise DomainValidationError("轮次编号重复，请重新打开项目", code="PRESALES_ROUND_CONFLICT", status=409)
    if changed:
        node.business_data = {**(node.business_data or {}), "schemeRounds": rounds}
        touch_audit(node, request)
        node.save()
        touch_audit(project, request)
        project.save(update_fields=["updated_by", "updated_actor_id", "updated_at"])
    # Preparing a link does not claim that DingTalk delivered a message.
    return project, rounds[index]["roundId"]


@transaction.atomic
def _process_presales_round(request, project_id, node_key, payload, *, reason_files, stored_files):
    project, node = _editable_node(request, project_id, node_key)
    _check_version(node, payload.get("expectedUpdatedAt"))
    rounds = validate_presales_round_schedule((node.business_data or {}).get("schemeRounds", []))
    round_id = text(payload.get("roundId"))
    index = next((i for i, item in enumerate(rounds) if round_id and item.get("roundId") == round_id), None)
    if index is None:
        raise DomainValidationError("该轮次已删除，请查看项目中的最新轮次", code="PRESALES_ROUND_NOT_FOUND", status=404)
    if index != len(rounds) - 1:
        raise DomainValidationError("已有新的轮次，请查看最新一轮后处理", code="PRESALES_ROUND_NOT_LATEST", status=409)
    action = payload.get("action")
    if reason_files and action != "add_round":
        raise DomainValidationError("仅新增一轮时可提交原因附件", code="PRESALES_ROUND_ACTION_INVALID")
    if action == "add_round":
        reason = payload.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 5000:
            raise DomainValidationError("请填写新增一轮的原因（最多5000字）", code="PRESALES_ROUND_REASON_REQUIRED")
        reason_attachment_ids = _save_reason_files(request, node, reason_files, stored_files)
        rounds.append({
            "roundId": str(uuid.uuid4()), "reason": reason.strip(),
            "reasonAttachmentIds": reason_attachment_ids,
            "plannedStartDate": "", "plannedEndDate": "", "submitDate": "",
            "submittedAt": "", "note": "", "attachmentIds": [],
        })
        title = f"{node.name}：新增第{len(rounds)}轮"
        detail = reason.strip()
    elif action == "remove_attachment":
        attachment_id = text(payload.get("attachmentId"))
        current_ids = [str(value) for value in rounds[-1].get("attachmentIds", [])]
        if (attachment_id not in current_ids or not attachment_id.isascii() or not attachment_id.isdigit()
                or len(attachment_id) > 19 or not 0 < int(attachment_id) <= 9_223_372_036_854_775_807):
            raise DomainValidationError("本轮附件已不存在，请刷新后重试", code="PRESALES_ROUND_ATTACHMENT_NOT_FOUND", status=404)
        item = PrivateAttachment.objects.filter(
            pk=int(attachment_id), target_type=PrivateAttachment.TARGET_PROJECT_NODE,
            target_id=node.pk, category=PrivateAttachment.CATEGORY_SCHEME_SUBMISSION,
        ).first()
        if item is None:
            raise DomainValidationError("本轮附件已不存在，请刷新后重试", code="PRESALES_ROUND_ATTACHMENT_NOT_FOUND", status=404)
        rounds[-1]["attachmentIds"] = [value for value in rounds[-1].get("attachmentIds", [])
                                       if str(value) != attachment_id]
        # Inherited attachments share the original file. Removing a reference
        # from this round must never destroy an earlier round's materials.
        historical = any(attachment_id in {str(value) for value in row.get("attachmentIds", [])}
                         for row in rounds[:-1]) or any(
            attachment_id in {str(value) for value in row.get("reasonAttachmentIds", [])} for row in rounds)
        title = f"{node.name}：第{index + 1}轮移除附件"
        detail = item.original_name
        if not historical:
            storage, stored_name = item.file.storage, item.file.name
            item.delete()
            if stored_name:
                transaction.on_commit(lambda: storage.delete(stored_name))
    elif action == "pass":
        # Keep workflow prerequisites, parallel branches and completion events.
        project = advance_project(request, project_id, expected_node_key=node_key)
        title = f"{node.name}：第{index + 1}轮通过"
        detail = "通过本轮提交并完成当前节点"
    else:
        raise DomainValidationError("不支持的轮次操作", code="PRESALES_ROUND_ACTION_INVALID")
    if action in {"add_round", "remove_attachment"}:
        node.business_data = {**(node.business_data or {}), "schemeRounds": rounds}
        touch_audit(node, request)
        node.save()
        sync_presales_task_schedules(node)
        touch_audit(project, request)
        project.save(update_fields=["updated_by", "updated_actor_id", "updated_at"])
    record_project_event(request, project, node=node, event_type="presales_round_processed",
                         title=title, detail=detail,
                         after={"roundId": round_id, "roundNumber": index + 1, "action": action,
                                **({"newRoundId": rounds[-1]["roundId"],
                                    "reasonAttachmentIds": reason_attachment_ids} if action == "add_round" else {}),
                                **({"attachmentId": attachment_id} if action == "remove_attachment" else {})})
    return project
