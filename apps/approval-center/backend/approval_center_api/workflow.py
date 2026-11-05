from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import uuid

from django.db import transaction
from django.utils import timezone

from .models import (
    ApprovalApplication,
    ApprovalEvent,
    ApprovalTask,
    ApprovalTemplate,
    ApprovalTemplateVersion,
)


MAX_SCHEMA_BYTES = 512 * 1024
MAX_VALUES_BYTES = 1024 * 1024
SUPPORTED_FIELD_TYPES = {
    "text",
    "textarea",
    "number",
    "amount",
    "date",
    "dateRange",
    "select",
    "radio",
    "checkbox",
    "multiselect",
    "user",
    "department",
    "attachment",
    "description",
    "divider",
}
NON_INPUT_FIELD_TYPES = {"description", "divider"}
CHOICE_FIELD_TYPES = {"select", "radio", "checkbox", "multiselect"}
APPROVAL_NODE_TYPES = {"approval", "approver"}
CC_NODE_TYPES = {"cc", "copy"}
PASS_THROUGH_NODE_TYPES = {"start", "initiator", "end"}


class ApprovalDomainError(Exception):
    def __init__(self, message: str, code: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def text(value, *, maximum: int | None = None) -> str:
    result = str(value or "").strip()
    if maximum is not None and len(result) > maximum:
        raise ApprovalDomainError(
            f"内容不能超过 {maximum} 个字符",
            "VALUE_TOO_LONG",
        )
    return result


def ensure_json_object(value, label: str, *, maximum_bytes: int = MAX_SCHEMA_BYTES) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ApprovalDomainError(f"{label}必须是对象", "INVALID_SCHEMA")
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > maximum_bytes:
        raise ApprovalDomainError(f"{label}内容过大", "SCHEMA_TOO_LARGE")
    return value


def normalize_template_payload(payload: dict, *, partial: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise ApprovalDomainError("请求 JSON 格式错误", "INVALID_JSON")
    result: dict = {}
    string_fields = {
        "name": ("name", 120, not partial),
        "description": ("description", 5000, False),
        "category": ("category", 64, False),
        "icon": ("icon", 64, False),
        "color": ("color", 32, False),
    }
    for request_key, (model_key, maximum, required) in string_fields.items():
        if request_key not in payload:
            if required:
                raise ApprovalDomainError("模板名称不能为空", "INVALID_TEMPLATE")
            continue
        value = text(payload.get(request_key), maximum=maximum)
        if request_key == "name" and not value:
            raise ApprovalDomainError("模板名称不能为空", "INVALID_TEMPLATE")
        result[model_key] = value

    for request_key, model_key, label in (
        ("formSchema", "form_schema", "表单配置"),
        ("flowSchema", "flow_schema", "流程配置"),
        ("settings", "settings", "高级设置"),
    ):
        if request_key in payload:
            result[model_key] = ensure_json_object(payload.get(request_key), label)

    if "status" in payload:
        status = text(payload.get("status"))
        if status not in {
            ApprovalTemplate.STATUS_DRAFT,
            ApprovalTemplate.STATUS_PUBLISHED,
            ApprovalTemplate.STATUS_DISABLED,
        }:
            raise ApprovalDomainError("模板状态无效", "INVALID_TEMPLATE_STATUS")
        result["status"] = status
    if "enabled" in payload:
        result["status"] = (
            ApprovalTemplate.STATUS_PUBLISHED
            if bool(payload.get("enabled"))
            else ApprovalTemplate.STATUS_DISABLED
        )
    return result


def _choice_options(field: dict, *, field_label: str, for_publish: bool) -> list[str]:
    options = field.get("options", [])
    if not isinstance(options, list):
        raise ApprovalDomainError(f"字段“{field_label}”的选项格式错误", "INVALID_FORM_SCHEMA")
    normalized: list[str] = []
    for option in options:
        raw_value = (
            option.get("value") or option.get("label")
            if isinstance(option, dict)
            else option
        )
        if isinstance(raw_value, (dict, list, bool)):
            value = ""
        else:
            value = text(raw_value, maximum=200)
        if not value:
            if for_publish:
                raise ApprovalDomainError(f"字段“{field_label}”包含空选项", "INVALID_FORM_SCHEMA")
            continue
        normalized.append(value)
    if for_publish and not normalized:
        raise ApprovalDomainError(f"字段“{field_label}”至少需要一个选项", "INVALID_FORM_SCHEMA")
    if for_publish and len(set(normalized)) != len(normalized):
        raise ApprovalDomainError(f"字段“{field_label}”包含重复选项", "INVALID_FORM_SCHEMA")
    return normalized


def validate_form_schema(schema: dict, *, for_publish: bool) -> list[dict]:
    schema = ensure_json_object(schema, "表单配置")
    fields = schema.get("fields", [])
    if not isinstance(fields, list):
        raise ApprovalDomainError("表单字段必须是数组", "INVALID_FORM_SCHEMA")
    if len(fields) > 200:
        raise ApprovalDomainError("表单字段不能超过 200 个", "INVALID_FORM_SCHEMA")
    normalized: list[dict] = []
    seen: set[str] = set()
    for index, field in enumerate(fields):
        if not isinstance(field, dict):
            raise ApprovalDomainError(f"第 {index + 1} 个字段格式错误", "INVALID_FORM_SCHEMA")
        field_key = text(field.get("key") or field.get("id"), maximum=80)
        field_type = text(field.get("type"), maximum=32)
        label = text(field.get("label") or field.get("name"), maximum=120)
        if not field_key:
            raise ApprovalDomainError(f"第 {index + 1} 个字段缺少标识", "INVALID_FORM_SCHEMA")
        if field_key in seen:
            raise ApprovalDomainError(f"字段标识重复：{field_key}", "INVALID_FORM_SCHEMA")
        if field_type not in SUPPORTED_FIELD_TYPES:
            raise ApprovalDomainError(f"字段类型暂不支持：{field_type or '-'}", "INVALID_FORM_SCHEMA")
        if for_publish and field_type not in NON_INPUT_FIELD_TYPES and not label:
            raise ApprovalDomainError(f"字段 {field_key} 缺少名称", "INVALID_FORM_SCHEMA")
        if for_publish and field_type == "attachment":
            raise ApprovalDomainError(
                f"字段“{label or field_key}”使用了当前版本尚不支持的附件类型",
                "INVALID_FORM_SCHEMA",
            )
        normalized_field = {**field, "key": field_key, "type": field_type, "label": label}
        if field_type in CHOICE_FIELD_TYPES:
            normalized_field["options"] = _choice_options(
                field,
                field_label=label or field_key,
                for_publish=for_publish,
            )
        seen.add(field_key)
        normalized.append(normalized_field)
    return normalized


def _node_assignees(node: dict, initiator: tuple[str, str] | None = None) -> list[tuple[str, str]]:
    assignee_type = text(node.get("assigneeType") or node.get("assignee_type") or "user")
    if assignee_type == "initiator":
        return [initiator] if initiator and initiator[0] else []
    if assignee_type not in {"user", "users", "specified"}:
        return []

    names: dict[str, str] = {}
    rows = node.get("assignees")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            user_id = text(row.get("userId") or row.get("id"), maximum=64)
            if user_id:
                names[user_id] = text(row.get("name"), maximum=128) or user_id
    name_map = node.get("assigneeNames")
    if isinstance(name_map, dict):
        for user_id, name in name_map.items():
            normalized_id = text(user_id, maximum=64)
            if normalized_id:
                names[normalized_id] = text(name, maximum=128) or normalized_id

    raw_ids = (
        node.get("assigneeIds")
        or node.get("assigneeUserIds")
        or node.get("userIds")
        or []
    )
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if isinstance(raw_ids, list):
        for value in raw_ids:
            if isinstance(value, dict):
                user_id = text(value.get("userId") or value.get("id"), maximum=64)
                name = text(value.get("name"), maximum=128)
            else:
                user_id = text(value, maximum=64)
                name = ""
            if user_id and user_id not in names:
                names[user_id] = name or user_id
    single_id = text(node.get("assigneeId") or node.get("userId"), maximum=64)
    if single_id and single_id not in names:
        names[single_id] = text(node.get("assigneeName") or node.get("userName"), maximum=128) or single_id
    return list(names.items())


def workflow_nodes(
    schema: dict,
    *,
    for_publish: bool,
    initiator: tuple[str, str] | None = None,
) -> list[dict]:
    schema = ensure_json_object(schema, "流程配置")
    rows = schema.get("nodes", [])
    if not isinstance(rows, list):
        raise ApprovalDomainError("流程节点必须是数组", "INVALID_FLOW_SCHEMA")
    if len(rows) > 100:
        raise ApprovalDomainError("流程节点不能超过 100 个", "INVALID_FLOW_SCHEMA")
    result: list[dict] = []
    seen: set[str] = set()
    approval_count = 0
    for source_index, node in enumerate(rows):
        if not isinstance(node, dict):
            raise ApprovalDomainError(f"第 {source_index + 1} 个流程节点格式错误", "INVALID_FLOW_SCHEMA")
        node_type = text(node.get("type"), maximum=32)
        if node_type in PASS_THROUGH_NODE_TYPES:
            continue
        if node_type not in APPROVAL_NODE_TYPES | CC_NODE_TYPES:
            raise ApprovalDomainError(f"流程节点类型暂不支持：{node_type or '-'}", "INVALID_FLOW_SCHEMA")
        node_key = text(node.get("key") or node.get("id"), maximum=80)
        if not node_key:
            raise ApprovalDomainError(f"第 {source_index + 1} 个流程节点缺少标识", "INVALID_FLOW_SCHEMA")
        if node_key in seen:
            raise ApprovalDomainError(f"流程节点标识重复：{node_key}", "INVALID_FLOW_SCHEMA")
        seen.add(node_key)
        node_name = text(node.get("name") or node.get("label"), maximum=120)
        if not node_name:
            node_name = "审批人" if node_type in APPROVAL_NODE_TYPES else "抄送人"
        assignees = _node_assignees(node, initiator)
        if for_publish and not assignees and text(node.get("assigneeType")) != "initiator":
            raise ApprovalDomainError(f"节点“{node_name}”尚未选择人员", "INVALID_FLOW_SCHEMA")
        approval_mode = text(node.get("approvalMode") or node.get("mode") or ApprovalTask.MODE_ALL)
        if approval_mode not in {ApprovalTask.MODE_ALL, ApprovalTask.MODE_ANY}:
            raise ApprovalDomainError(f"节点“{node_name}”的审批方式无效", "INVALID_FLOW_SCHEMA")
        task_type = ApprovalTask.TYPE_APPROVAL if node_type in APPROVAL_NODE_TYPES else ApprovalTask.TYPE_CC
        if task_type == ApprovalTask.TYPE_APPROVAL:
            approval_count += 1
        result.append({
            "key": node_key,
            "name": node_name,
            "order": len(result),
            "taskType": task_type,
            "approvalMode": approval_mode,
            "assignees": assignees,
        })
    if for_publish and approval_count == 0:
        raise ApprovalDomainError("流程至少需要一个审批节点", "INVALID_FLOW_SCHEMA")
    return result


def _canonical_flow_schema(
    schema: dict,
    *,
    assignee_directory: dict[str, str],
) -> dict:
    canonical = deepcopy(ensure_json_object(schema, "流程配置"))
    rows = canonical.get("nodes", [])
    if not isinstance(rows, list):
        raise ApprovalDomainError("流程节点必须是数组", "INVALID_FLOW_SCHEMA")
    for node in rows:
        if not isinstance(node, dict):
            continue
        node_type = text(node.get("type"), maximum=32)
        if node_type in PASS_THROUGH_NODE_TYPES:
            continue
        assignee_type = text(node.get("assigneeType") or node.get("assignee_type") or "user")
        if assignee_type == "initiator":
            node["assignees"] = []
            node["assigneeIds"] = []
            node["assigneeNames"] = {}
            continue
        if assignee_type not in {"user", "users", "specified"}:
            continue
        assignees = _node_assignees(node)
        missing = [user_id for user_id, _name in assignees if user_id not in assignee_directory]
        if missing:
            node_name = text(node.get("name") or node.get("label"), maximum=120) or "审批节点"
            raise ApprovalDomainError(
                f"节点“{node_name}”包含不存在、已离职或已停用的人员：{'、'.join(missing)}",
                "INVALID_FLOW_ASSIGNEE",
            )
        canonical_ids = [user_id for user_id, _name in assignees]
        canonical_names = {
            user_id: assignee_directory[user_id] or user_id
            for user_id in canonical_ids
        }
        for key in ("assigneeUserIds", "userIds", "assigneeId", "userId", "assigneeName", "userName"):
            node.pop(key, None)
        node["assigneeType"] = "user"
        node["assigneeIds"] = canonical_ids
        node["assigneeNames"] = canonical_names
        node["assignees"] = [
            {"userId": user_id, "name": canonical_names[user_id]}
            for user_id in canonical_ids
        ]
    workflow_nodes(canonical, for_publish=True)
    return canonical


def validate_template_for_publish(
    template: ApprovalTemplate,
    *,
    assignee_directory: dict[str, str],
) -> dict:
    if not text(template.name):
        raise ApprovalDomainError("模板名称不能为空", "INVALID_TEMPLATE")
    validate_form_schema(template.form_schema, for_publish=True)
    return _canonical_flow_schema(
        template.flow_schema,
        assignee_directory=assignee_directory,
    )


def _invalid_field_value(field: dict, message: str = "格式错误") -> ApprovalDomainError:
    return ApprovalDomainError(
        f"{field['label']}{message}",
        "INVALID_APPLICATION_VALUES",
    )


def _iso_date(value: str, field: dict) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _invalid_field_value(field, "必须是有效日期") from None
    if parsed.isoformat() != value:
        raise _invalid_field_value(field, "必须是 YYYY-MM-DD 格式的日期")
    return parsed


def validate_application_values(
    form_schema: dict,
    values,
    *,
    employee_directory: dict[str, str] | None = None,
    department_directory: set[str] | None = None,
) -> dict:
    values = ensure_json_object(values, "申请内容", maximum_bytes=MAX_VALUES_BYTES)
    fields = validate_form_schema(form_schema, for_publish=True)
    known_keys = {field["key"] for field in fields}
    unknown_keys = [str(key) for key in values if key not in known_keys]
    if unknown_keys:
        raise ApprovalDomainError(
            f"申请内容包含未配置字段：{'、'.join(sorted(unknown_keys))}",
            "INVALID_APPLICATION_VALUES",
        )

    employees = employee_directory or {}
    departments = department_directory or set()
    validated: dict = {}
    for field in fields:
        key = field["key"]
        present = key in values
        value = values.get(key)
        if field["type"] in NON_INPUT_FIELD_TYPES:
            if present and value is not None and value != "" and value != []:
                raise _invalid_field_value(field, "不接受填写值")
            continue

        if not present:
            if bool(field.get("required")):
                raise ApprovalDomainError(f"{field['label']}不能为空", "INVALID_APPLICATION_VALUES")
            continue

        field_type = field["type"]
        if field_type in {"text", "textarea", "date", "user", "department", "select", "radio"}:
            if not isinstance(value, str):
                raise _invalid_field_value(field)
            empty = not value.strip()
        elif field_type in {"checkbox", "multiselect", "dateRange", "attachment"}:
            if not isinstance(value, list):
                raise _invalid_field_value(field)
            empty = not value
        else:
            empty = value is None or value == ""

        if bool(field.get("required")) and empty:
            raise ApprovalDomainError(f"{field['label']}不能为空", "INVALID_APPLICATION_VALUES")
        if empty:
            validated[key] = value
            continue

        if field_type in {"number", "amount"}:
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ApprovalDomainError(f"{field['label']}必须是数字", "INVALID_APPLICATION_VALUES")
            try:
                numeric_value = Decimal(str(value))
            except (InvalidOperation, ValueError):
                raise ApprovalDomainError(f"{field['label']}必须是数字", "INVALID_APPLICATION_VALUES") from None
            if not numeric_value.is_finite():
                raise ApprovalDomainError(f"{field['label']}必须是有限数字", "INVALID_APPLICATION_VALUES")

        if field_type == "date":
            _iso_date(value, field)

        if field_type == "dateRange":
            if len(value) != 2 or any(not isinstance(item, str) for item in value):
                raise _invalid_field_value(field)
            start = _iso_date(value[0], field)
            end = _iso_date(value[1], field)
            if start > end:
                raise _invalid_field_value(field, "的开始日期不能晚于结束日期")

        if field_type in {"checkbox", "multiselect", "attachment"}:
            if any(not isinstance(item, str) or not item.strip() for item in value):
                raise _invalid_field_value(field)
            if len(set(value)) != len(value):
                raise ApprovalDomainError(f"{field['label']}包含重复值", "INVALID_APPLICATION_VALUES")

        if field_type in CHOICE_FIELD_TYPES:
            allowed = set(field.get("options") or [])
            submitted = value if field_type in {"checkbox", "multiselect"} else [value]
            if any(selected not in allowed for selected in submitted):
                raise ApprovalDomainError(f"{field['label']}选项无效", "INVALID_APPLICATION_VALUES")

        if field_type == "user" and value not in employees:
            raise ApprovalDomainError(f"{field['label']}选择的人员不存在或已停用", "INVALID_APPLICATION_VALUES")
        if field_type == "department" and value not in departments:
            raise ApprovalDomainError(f"{field['label']}选择的部门不存在", "INVALID_APPLICATION_VALUES")

        validated[key] = value
    return validated


def publish_template(
    template: ApprovalTemplate,
    *,
    actor_user_id: str,
    actor_name: str,
    assignee_directory: dict[str, str],
    release_note: str = "",
) -> ApprovalTemplateVersion:
    published_flow_schema = validate_template_for_publish(
        template,
        assignee_directory=assignee_directory,
    )
    latest = template.versions.order_by("-version").values_list("version", flat=True).first() or 0
    version = ApprovalTemplateVersion.objects.create(
        template=template,
        version=latest + 1,
        name=template.name,
        description=template.description,
        category=template.category,
        icon=template.icon,
        color=template.color,
        form_schema=template.form_schema,
        flow_schema=published_flow_schema,
        settings=template.settings,
        source_revision=template.revision,
        release_note=text(release_note, maximum=500),
        published_by=actor_user_id,
        published_by_name=actor_name,
    )
    template.published_version = version
    template.published_revision = template.revision
    template.status = ApprovalTemplate.STATUS_PUBLISHED
    template.updated_by = actor_user_id
    template.updated_by_name = actor_name
    template.save(update_fields=[
        "published_version",
        "published_revision",
        "status",
        "updated_by",
        "updated_by_name",
        "updated_at",
    ])
    return version


def _serial_no() -> str:
    return f"SP{timezone.localtime().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


def _event(
    application: ApprovalApplication,
    action: str,
    *,
    task: ApprovalTask | None = None,
    actor_user_id: str = "",
    actor_name: str = "",
    from_status: str = "",
    to_status: str = "",
    comment: str = "",
    data: dict | None = None,
) -> ApprovalEvent:
    return ApprovalEvent.objects.create(
        application=application,
        task=task,
        action=action,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        node_key=task.node_key if task else application.current_node_key,
        node_name=task.node_name if task else application.current_node_name,
        from_status=from_status,
        to_status=to_status,
        comment=comment,
        data=data or {},
    )


def _save_application_progress(application: ApprovalApplication, update_fields: list[str]) -> None:
    application.revision = max(1, int(application.revision or 1)) + 1
    application.save(update_fields=[*update_fields, "revision", "updated_at"])


def _advance(application: ApprovalApplication, *, after_order: int = -1) -> None:
    groups: dict[int, list[ApprovalTask]] = defaultdict(list)
    for task in application.tasks.filter(node_order__gt=after_order).order_by("node_order", "id"):
        groups[task.node_order].append(task)
    now = timezone.now()
    for node_order in sorted(groups):
        tasks = groups[node_order]
        if not tasks:
            continue
        if tasks[0].task_type == ApprovalTask.TYPE_CC:
            for task in tasks:
                if task.status != ApprovalTask.STATUS_WAITING:
                    continue
                task.status = ApprovalTask.STATUS_COPIED
                task.activated_at = now
                task.acted_at = now
                task.save(update_fields=["status", "activated_at", "acted_at", "updated_at"])
                _event(
                    application,
                    ApprovalEvent.ACTION_COPIED,
                    task=task,
                    to_status=application.status,
                )
            continue

        pending_tasks = []
        for task in tasks:
            if task.status == ApprovalTask.STATUS_WAITING:
                task.status = ApprovalTask.STATUS_PENDING
                task.activated_at = now
                task.save(update_fields=["status", "activated_at", "updated_at"])
            if task.status == ApprovalTask.STATUS_PENDING:
                pending_tasks.append(task)
        if pending_tasks:
            first = pending_tasks[0]
            application.current_node_key = first.node_key
            application.current_node_name = first.node_name
            application.current_node_order = first.node_order
            _save_application_progress(
                application,
                ["current_node_key", "current_node_name", "current_node_order"],
            )
            _event(
                application,
                ApprovalEvent.ACTION_NODE_STARTED,
                task=first,
                from_status=application.status,
                to_status=application.status,
                data={"assigneeCount": len(pending_tasks), "approvalMode": first.approval_mode},
            )
            return

    previous_status = application.status
    application.status = ApprovalApplication.STATUS_APPROVED
    application.current_node_key = ""
    application.current_node_name = ""
    application.current_node_order = None
    application.completed_at = now
    _save_application_progress(
        application,
        ["status", "current_node_key", "current_node_name", "current_node_order", "completed_at"],
    )
    _event(
        application,
        ApprovalEvent.ACTION_COMPLETED,
        from_status=previous_status,
        to_status=application.status,
    )


@transaction.atomic
def create_application(
    template: ApprovalTemplate,
    *,
    initiator_user_id: str,
    initiator_name: str,
    title: str,
    values: dict,
    department_id: str = "",
    department_name: str = "",
    actor_user_id: str = "",
    actor_name: str = "",
    is_proxying: bool = False,
    employee_directory: dict[str, str],
    department_directory: set[str],
) -> ApprovalApplication:
    locked_template = (
        ApprovalTemplate.objects.select_for_update(of=("self",))
        .select_related("published_version")
        .get(pk=template.pk)
    )
    if locked_template.deleted_at or locked_template.status != ApprovalTemplate.STATUS_PUBLISHED:
        raise ApprovalDomainError("该审批模板当前不可发起", "TEMPLATE_NOT_AVAILABLE", 409)
    version = locked_template.published_version
    if version is None:
        raise ApprovalDomainError("审批模板尚未发布", "TEMPLATE_NOT_PUBLISHED", 409)
    initiator_user_id = text(initiator_user_id, maximum=64)
    canonical_initiator_name = employee_directory.get(initiator_user_id)
    if not canonical_initiator_name:
        raise ApprovalDomainError(
            "当前发起人不存在、已离职或账号已停用，无法发起审批",
            "FLOW_PARTICIPANT_UNAVAILABLE",
            409,
        )
    canonical_initiator_name = text(canonical_initiator_name, maximum=128)
    validated_values = validate_application_values(
        version.form_schema,
        values,
        employee_directory=employee_directory,
        department_directory=department_directory,
    )
    nodes = workflow_nodes(
        version.flow_schema,
        for_publish=True,
        initiator=(initiator_user_id, canonical_initiator_name),
    )
    unavailable_ids = sorted({
        user_id
        for node in nodes
        for user_id, _name in node["assignees"]
        if user_id not in employee_directory
    })
    if unavailable_ids:
        raise ApprovalDomainError(
            f"流程参与人不存在、已离职或账号已停用：{'、'.join(unavailable_ids)}",
            "FLOW_PARTICIPANT_UNAVAILABLE",
            409,
        )
    for node in nodes:
        node["assignees"] = [
            (user_id, text(employee_directory[user_id], maximum=128) or user_id)
            for user_id, _name in node["assignees"]
        ]
    normalized_title = text(title, maximum=200)
    if not normalized_title:
        normalized_title = f"{version.name} - {canonical_initiator_name or initiator_user_id}"[:200]
    application = ApprovalApplication.objects.create(
        serial_no=_serial_no(),
        template=locked_template,
        template_version=version,
        title=normalized_title,
        values=validated_values,
        initiator_user_id=initiator_user_id,
        initiator_name=canonical_initiator_name,
        initiator_department_id=text(department_id, maximum=64),
        initiator_department_name=text(department_name, maximum=128),
    )
    tasks = []
    for node in nodes:
        for user_id, name in node["assignees"]:
            tasks.append(ApprovalTask(
                application=application,
                node_key=node["key"],
                node_name=node["name"],
                node_order=node["order"],
                task_type=node["taskType"],
                approval_mode=node["approvalMode"],
                assignee_user_id=user_id,
                assignee_name=name,
            ))
    ApprovalTask.objects.bulk_create(tasks)
    effective_actor_user_id = text(actor_user_id or initiator_user_id, maximum=64)
    effective_actor_name = text(
        actor_name or canonical_initiator_name or effective_actor_user_id,
        maximum=128,
    )
    event_data = {"templateVersion": version.version}
    if is_proxying or effective_actor_user_id != initiator_user_id:
        event_data.update({
            "effectiveUserId": initiator_user_id,
            "effectiveUserName": canonical_initiator_name,
            "isProxying": True,
        })
    _event(
        application,
        ApprovalEvent.ACTION_SUBMITTED,
        actor_user_id=effective_actor_user_id,
        actor_name=effective_actor_name,
        to_status=ApprovalApplication.STATUS_PENDING,
        data=event_data,
    )
    _advance(application)
    application.refresh_from_db()
    return application


def _cancel_open_tasks(application: ApprovalApplication, *, exclude_task_id: int | None = None) -> None:
    queryset = application.tasks.filter(
        status__in=[ApprovalTask.STATUS_WAITING, ApprovalTask.STATUS_PENDING],
    )
    if exclude_task_id is not None:
        queryset = queryset.exclude(pk=exclude_task_id)
    queryset.update(status=ApprovalTask.STATUS_CANCELLED, updated_at=timezone.now())


def _check_expected_revision(application: ApprovalApplication, expected_revision) -> None:
    if expected_revision in {None, ""}:
        return
    try:
        expected = int(expected_revision)
    except (TypeError, ValueError):
        raise ApprovalDomainError("申请版本格式错误", "INVALID_REVISION") from None
    if expected != application.revision:
        raise ApprovalDomainError(
            "申请已被其他人处理，请刷新后重试",
            "REVISION_CONFLICT",
            409,
        )


@transaction.atomic
def act_on_application(
    application_id: int,
    action: str,
    *,
    user_id: str,
    user_name: str,
    comment: str = "",
    task_id: int | None = None,
    expected_revision=None,
    actor_user_id: str = "",
    actor_name: str = "",
    is_proxying: bool = False,
) -> ApprovalApplication:
    application = ApprovalApplication.objects.select_for_update().filter(pk=application_id).first()
    if application is None:
        raise ApprovalDomainError("审批申请不存在", "APPLICATION_NOT_FOUND", 404)
    _check_expected_revision(application, expected_revision)
    if application.status != ApprovalApplication.STATUS_PENDING:
        raise ApprovalDomainError("当前申请已不能执行该操作", "ACTION_NOT_AVAILABLE", 409)
    normalized_comment = text(comment, maximum=5000)
    effective_actor_user_id = actor_user_id or user_id
    effective_actor_name = actor_name or user_name or effective_actor_user_id
    audit_data = {}
    if is_proxying or effective_actor_user_id != user_id:
        audit_data = {
            "effectiveUserId": user_id,
            "effectiveUserName": user_name,
            "isProxying": True,
        }

    if action == ApprovalEvent.ACTION_WITHDRAWN:
        if application.initiator_user_id != user_id:
            raise ApprovalDomainError("只有发起人可以撤回申请", "ACTION_FORBIDDEN", 403)
        settings = application.template_version.settings
        if isinstance(settings, dict) and settings.get("allowWithdraw") is False:
            raise ApprovalDomainError("该审批流程不允许发起人撤回", "ACTION_NOT_AVAILABLE", 409)
        previous_status = application.status
        _cancel_open_tasks(application)
        application.status = ApprovalApplication.STATUS_WITHDRAWN
        application.current_node_key = ""
        application.current_node_name = ""
        application.current_node_order = None
        application.completed_at = timezone.now()
        _save_application_progress(
            application,
            ["status", "current_node_key", "current_node_name", "current_node_order", "completed_at"],
        )
        _event(
            application,
            ApprovalEvent.ACTION_WITHDRAWN,
            actor_user_id=effective_actor_user_id,
            actor_name=effective_actor_name,
            from_status=previous_status,
            to_status=application.status,
            comment=normalized_comment,
            data=audit_data,
        )
        return application

    if action not in {
        ApprovalEvent.ACTION_APPROVED,
        ApprovalEvent.ACTION_REJECTED,
        ApprovalEvent.ACTION_RETURNED,
    }:
        raise ApprovalDomainError("审批操作无效", "INVALID_ACTION")
    settings = application.template_version.settings
    settings = settings if isinstance(settings, dict) else {}
    comment_required = (
        (action == ApprovalEvent.ACTION_APPROVED and settings.get("requireApprovalComment") is True)
        or (
            action == ApprovalEvent.ACTION_REJECTED
            and settings.get("requireRejectComment", True) is not False
        )
        or (
            action == ApprovalEvent.ACTION_RETURNED
            and settings.get("requireReturnComment", True) is not False
        )
    )
    if comment_required and not normalized_comment:
        raise ApprovalDomainError("请填写处理意见", "COMMENT_REQUIRED")

    tasks = ApprovalTask.objects.select_for_update().filter(
        application=application,
        task_type=ApprovalTask.TYPE_APPROVAL,
        status=ApprovalTask.STATUS_PENDING,
        node_order=application.current_node_order,
        assignee_user_id=user_id,
    )
    if task_id is not None:
        tasks = tasks.filter(pk=task_id)
    task = tasks.order_by("id").first()
    if task is None:
        raise ApprovalDomainError("当前没有可由你处理的审批任务", "ACTION_FORBIDDEN", 403)

    task_status = {
        ApprovalEvent.ACTION_APPROVED: ApprovalTask.STATUS_APPROVED,
        ApprovalEvent.ACTION_REJECTED: ApprovalTask.STATUS_REJECTED,
        ApprovalEvent.ACTION_RETURNED: ApprovalTask.STATUS_RETURNED,
    }[action]
    task.status = task_status
    task.comment = normalized_comment
    task.acted_by_user_id = effective_actor_user_id
    task.acted_by_name = effective_actor_name
    task.acted_at = timezone.now()
    task.save(update_fields=[
        "status",
        "comment",
        "acted_by_user_id",
        "acted_by_name",
        "acted_at",
        "updated_at",
    ])
    _event(
        application,
        action,
        task=task,
        actor_user_id=effective_actor_user_id,
        actor_name=effective_actor_name,
        from_status=application.status,
        to_status=application.status,
        comment=normalized_comment,
        data=audit_data,
    )

    if action in {ApprovalEvent.ACTION_REJECTED, ApprovalEvent.ACTION_RETURNED}:
        previous_status = application.status
        _cancel_open_tasks(application, exclude_task_id=task.pk)
        application.status = (
            ApprovalApplication.STATUS_REJECTED
            if action == ApprovalEvent.ACTION_REJECTED
            else ApprovalApplication.STATUS_RETURNED
        )
        application.current_node_key = ""
        application.current_node_name = ""
        application.current_node_order = None
        application.completed_at = timezone.now()
        _save_application_progress(
            application,
            ["status", "current_node_key", "current_node_name", "current_node_order", "completed_at"],
        )
        event = application.events.order_by("-id").first()
        if event:
            event.to_status = application.status
            event.from_status = previous_status
            event.save(update_fields=["from_status", "to_status"])
        return application

    sibling_tasks = list(ApprovalTask.objects.select_for_update().filter(
        application=application,
        node_order=task.node_order,
        task_type=ApprovalTask.TYPE_APPROVAL,
    ))
    node_complete = task.approval_mode == ApprovalTask.MODE_ANY or all(
        sibling.status == ApprovalTask.STATUS_APPROVED for sibling in sibling_tasks
    )
    if not node_complete:
        _save_application_progress(application, [])
        return application
    if task.approval_mode == ApprovalTask.MODE_ANY:
        application.tasks.filter(
            node_order=task.node_order,
            task_type=ApprovalTask.TYPE_APPROVAL,
            status=ApprovalTask.STATUS_PENDING,
        ).exclude(pk=task.pk).update(
            status=ApprovalTask.STATUS_CANCELLED,
            updated_at=timezone.now(),
        )
    _advance(application, after_order=task.node_order)
    return application
