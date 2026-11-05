from __future__ import annotations

import re

import uuid
import json
from datetime import datetime, timezone
from typing import Any

from .errors import HTTPException

from .schemas import default_page_permissions, default_page_settings
from .repositories import FormRepository, UserRepository, WorkflowRepository, WorkflowRunRepository, utc_now
from .schemas import TaskActionPayload, WorkflowRecallPayload, WorkflowRunPayload


def normalize_form_schema(schema: dict) -> dict:
    schema.setdefault("pageSettings", default_page_settings())
    schema.setdefault("permissions", default_page_permissions())
    return schema


def approval_node_config() -> dict:
    return {
        "approvalButtons": [
            {"key": "agree", "name": "同意", "enabled": True, "opinionMode": "optional", "batchEnabled": True},
            {"key": "reject", "name": "拒绝", "enabled": True, "opinionMode": "optional", "batchEnabled": True},
            {"key": "save", "name": "保存", "enabled": False, "opinionMode": "none", "batchEnabled": False},
            {"key": "transfer", "name": "转交", "enabled": False, "opinionMode": "optional", "batchEnabled": False},
            {"key": "countersign", "name": "加签", "enabled": False, "opinionMode": "optional", "batchEnabled": False},
            {"key": "return", "name": "退回", "enabled": False, "opinionMode": "required", "batchEnabled": False},
            {"key": "recall", "name": "收回", "enabled": False, "opinionMode": "none", "batchEnabled": False},
        ],
        "fieldPermissions": [
            {"fieldId": field_id, "permission": "editable"}
            for field_id in ["item-name", "quantity", "unit-price", "address", "total", "scene", "remark"]
        ],
        "approvalMode": "sequential",
    }


def resolve_direct_manager_user(applicant: dict, users: list[dict]) -> dict | None:
    role = applicant.get("role")
    department = applicant.get("department")
    username = applicant.get("username")
    by_username = {user["username"]: user for user in users}
    general_manager = next((user for user in users if user.get("role") == "general_manager"), None)

    if role == "general_manager":
        return None

    if role == "employee":
        manager = by_username.get(applicant.get("managerUsername") or "")
        if manager and manager.get("role") == "manager" and manager.get("department") == department:
            return manager
        department_managers = sorted(
            (user for user in users if user.get("role") == "manager" and user.get("department") == department),
            key=lambda user: user.get("displayName", ""),
        )
        if department_managers:
            return department_managers[0]

    if general_manager and general_manager.get("username") != username:
        return general_manager
    return None


def normalize_workflow_schema(schema: dict) -> dict:
    schema.setdefault("category", "常用流程")
    schema.setdefault("applicantFieldPermissions", [])
    def normalize_nodes(nodes: list[dict]) -> None:
        for node in nodes:
            if node.get("type") == "start":
                node.setdefault("formId", "sample")
            if node.get("type") == "approval":
                for key, value in approval_node_config().items():
                    node.setdefault(key, value)
                node.pop("allowTransfer", None)
                node.pop("allowCountersign", None)
                node.pop("returnTarget", None)
                node.setdefault("fieldPermissions", [])
                node.setdefault("assignees", [])
            elif node.get("type") == "executor":
                node.setdefault("fieldPermissions", [])
                node.setdefault("assignees", [])
            for branch in node.get("branches") or []:
                normalize_nodes(branch.get("nodes") or [])

    normalize_nodes(schema.get("nodes", []))
    schema.setdefault("disabledAt", None)
    schema.setdefault("deletedAt", None)
    schema.setdefault("publishedAt", None)
    schema.setdefault("publishedVersion", 0)
    schema.setdefault("publishedSnapshot", None)
    migrate_legacy_sample_assignments(schema)
    return schema


def migrate_legacy_sample_assignments(schema: dict) -> None:
    """Migrate the original demo's display-name assignees to portable rules.

    The first demo workflow stored fictional display names instead of Auth
    userIds.  Those names cannot be resolved after the app is connected to an
    Auth directory, so migrate the local contract sample to its documented
    fixture identities.  Real workflows still have to use the current Auth
    directory and are never rewritten here.
    """
    if schema.get("id") != "sample":
        return

    def visit(nodes: list[dict]) -> None:
        for node in nodes:
            assignees = node.get("assignees") or []
            if assignees == ["陈主管"] or assignees == ["王经理"]:
                node["assigneeMode"] = "specified"
                node["assignees"] = ["approver"]
            elif assignees == ["钟小康"]:
                node["assigneeMode"] = "specified"
                node["assignees"] = ["employee-a"]
            for branch in node.get("branches") or []:
                visit(branch.get("nodes") or [])

    visit(schema.get("nodes") or [])


def validate_workflow_for_publish(schema: dict, form: dict, users: list[dict]) -> list[str]:
    errors: list[str] = []
    nodes = schema.get("nodes") or []
    if not nodes or nodes[0].get("type") != "start":
        errors.append("流程必须以发起节点开始")
    if not nodes or nodes[-1].get("type") != "end":
        errors.append("流程必须以结束节点结束")
    fields = {field.get("id"): field for field in form.get("fields") or []}
    by_username = {user["username"]: user for user in users}
    by_name = {user["displayName"]: user for user in users}
    departments = {user["department"] for user in users if user["role"] != "admin"}
    operators = {"eq", "neq", "gt", "gte", "lt", "lte", "contains", "empty", "not_empty"}

    def visit(items: list[dict]) -> None:
        for node in items:
            node_name = node.get("name") or node.get("id") or "未命名节点"
            if node.get("type") in {"approval", "executor"}:
                mode = node.get("assigneeMode") or "specified"
                if node.get("type") == "approval":
                    if mode not in {"specified", "direct_manager"}:
                        errors.append(f"“{node_name}”请选择直属主管或指定审批成员")
                    enabled_actions = {button.get("key") for button in node.get("approvalButtons") or [] if button.get("enabled")}
                    if not enabled_actions.intersection({"agree", "reject", "return"}):
                        errors.append(f"“{node_name}”至少需要启用一个审批结果按钮")
                if mode == "specified":
                    assignees = node.get("assignees") or []
                    if not assignees:
                        errors.append(f"“{node_name}”尚未指定处理人")
                    for assignee in assignees:
                        if str(assignee) not in by_name and str(assignee) not in by_username:
                            errors.append(f"“{node_name}”的处理人“{assignee}”不存在或已停用")
                elif mode == "direct_manager" and node.get('type') == 'approval':
                    from .category_supervisors import resolve_category_supervisors
                    try:
                        resolve_category_supervisors(schema.get('category'), users)
                    except HTTPException as error:
                        errors.append(str(error.detail))
                elif mode == "direct_manager":
                    for user in users:
                        if user["role"] in {"admin", "general_manager"}:
                            continue
                        if not resolve_direct_manager_user(user, users):
                            errors.append(f"“{node_name}”无法为“{user['displayName']}”找到本部门主管或总经理")
                            break
                elif mode == "department_manager":
                    for department in departments:
                        if not any(user["role"] == "manager" and user["department"] == department for user in users):
                            errors.append(f"“{node_name}”无法为“{department}”找到部门主管")
                            break
                elif mode == "form_field":
                    member_field = fields.get(node.get("assigneeFieldId"))
                    if not member_field or member_field.get("type") != "member":
                        errors.append(f"“{node_name}”请选择有效的表单成员字段")
                elif mode not in {"initiator", "direct_manager", "department_manager", "form_field", "specified"}:
                    errors.append(f"“{node_name}”的处理人设置无效")
            if node.get("type") == "condition":
                branches = node.get("branches") or []
                defaults = [branch for branch in branches if branch.get("isDefault")]
                if len(defaults) != 1:
                    errors.append(f"“{node_name}”必须有且仅有一个默认出口")
                for branch in branches:
                    if not branch.get("isDefault"):
                        field = fields.get(branch.get("fieldId"))
                        if not field:
                            errors.append(f"“{branch.get('name') or node_name}”请选择有效的判断字段")
                        if branch.get("operator") not in operators:
                            errors.append(f"“{branch.get('name') or node_name}”的判断规则无效")
                        if branch.get("operator") not in {"empty", "not_empty"} and not str(branch.get("value") or "").strip():
                            errors.append(f"“{branch.get('name') or node_name}”尚未填写比较值")
                    visit(branch.get("nodes") or [])

    visit(nodes)
    return errors


def condition_matches(branch: dict, values: dict[str, Any], fields: dict[str, dict]) -> bool:
    field_id = branch.get("fieldId")
    actual = values.get(field_id)
    operator = branch.get("operator") or "eq"
    expected = branch.get("value") or ""
    if operator == "empty":
        return actual is None or actual == "" or actual == []
    if operator == "not_empty":
        return actual is not None and actual != "" and actual != []
    if actual is None:
        return False
    actual_text = ",".join(str(item) for item in actual) if isinstance(actual, list) else str(actual)
    field = fields.get(field_id or "", {})
    numeric = field.get("type") == "number" or operator in {"gt", "gte", "lt", "lte"}
    if operator in {"gt", "gte", "lt", "lte"}:
        try:
            left, right = float(actual_text), float(expected)
        except (TypeError, ValueError):
            return False
        return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[operator]
    if operator == "contains":
        if isinstance(actual, list):
            return any(str(item).casefold() == str(expected).casefold() for item in actual)
        return str(expected).casefold() in actual_text.casefold()
    if numeric:
        try:
            left, right = float(actual_text), float(expected)
        except (TypeError, ValueError):
            left, right = actual_text.casefold(), str(expected).casefold()
    else:
        left, right = actual_text.casefold(), str(expected).casefold()
    return left == right if operator == "eq" else left != right


def resolve_node_assignees(node: dict, applicant: dict, values: dict[str, Any], users: list[dict]) -> list[str]:
    mode = node.get("assigneeMode") or "specified"
    by_username = {user["username"]: user for user in users}
    by_name = {user["displayName"]: user for user in users}
    resolve_names = lambda names: list(dict.fromkeys(
        user["username"] for name in names
        if (user := by_username.get(str(name)) or by_name.get(str(name)))
    ))
    if mode == "specified":
        return resolve_names(node.get("assignees") or [])
    if mode == "initiator":
        return [applicant["username"]]
    if mode == "direct_manager":
        if applicant.get("managerUserIds"):
            return [value for value in applicant["managerUserIds"] if value in by_username]
        manager = resolve_direct_manager_user(applicant, users)
        return [manager["username"]] if manager else []
    if mode == "department_manager":
        if applicant.get("departmentIds"):
            from .organization import organization_snapshot, department_id, manager_ids
            departments, _employees, _revision = organization_snapshot()
            return list(dict.fromkeys(manager for dept in departments if department_id(dept) in applicant['departmentIds'] for manager in manager_ids(dept) if manager in by_username))
        managers = [user["username"] for user in users if user["role"] == "manager" and user["department"] == applicant.get("department")]
        return managers[:1]
    if mode == "form_field":
        value = values.get(node.get("assigneeFieldId"))
        if isinstance(value, list):
            return resolve_names(value)
        return resolve_names([value]) if value is not None and str(value).strip() else []
    return []


def evaluate_workflow_route(schema: dict, values: dict[str, Any], fields: dict[str, dict], applicant: dict, users: list[dict]) -> tuple[list[dict], list[dict]]:
    matched_branches: list[dict] = []
    routed_nodes: list[tuple[dict, list[str]]] = []

    def visit(items: list[dict], branch_path: list[str]) -> None:
        for node in items:
            node_type = node.get("type")
            if node_type == "condition":
                branches = node.get("branches") or []
                selected = next((branch for branch in branches if not branch.get("isDefault") and condition_matches(branch, values, fields)), None)
                if selected is None:
                    selected = next((branch for branch in branches if branch.get("isDefault")), None)
                if selected is None:
                    continue
                matched_branches.append({
                    "nodeId": node.get("id", ""),
                    "conditionName": node.get("name", "条件分支"),
                    "branchId": selected.get("id", ""),
                    "branchName": selected.get("name", "默认出口"),
                })
                visit(selected.get("nodes") or [], [*branch_path, selected.get("name", "默认出口")])
            elif node_type in {"approval", "executor"}:
                routed_nodes.append((node, list(branch_path)))

    visit(schema.get("nodes") or [], [])
    tasks: list[dict] = []
    category_assignees = []
    if any(node.get('type') == 'approval' and node.get('assigneeMode') == 'direct_manager' for node, _path in routed_nodes):
        from .category_supervisors import resolve_category_supervisors
        category_assignees = resolve_category_supervisors(schema.get('category'), users)
    for index, (node, branch_path) in enumerate(routed_nodes):
        assignees = list(category_assignees) if node.get('type') == 'approval' and node.get('assigneeMode') == 'direct_manager' else resolve_node_assignees(node, applicant, values, users)
        if not assignees:
            raise HTTPException(status_code=422, detail=f"“{node.get('name') or '审批/执行节点'}”没有解析到有效处理人")
        user_by_username = {user["username"]: user for user in users}
        permissions = node.get("fieldPermissions") or []
        permission_by_field = {item.get("fieldId"): item.get("permission", "editable") for item in permissions}
        permission_by_field = {field_id: permission_by_field.get(field_id, "editable") for field_id in fields}
        status = "waiting" if index else ("pending" if assignees else "unassigned")
        tasks.append({
            "id": uuid.uuid4().hex,
            "nodeId": node.get("id", ""),
            "nodeName": node.get("name", "审批/执行"),
            "nodeType": node.get("type"),
            "assigneeMode": node.get("assigneeMode") or "specified",
            "assignees": assignees,
            "assigneeNames": [user_by_username[username]["displayName"] for username in assignees],
            "branchPath": branch_path,
            "status": status,
            "approvalMode": node.get("approvalMode", "sequential"),
            **({"executionMode": "sequential"} if node.get("type") == "executor" else {}),
            "approvalButtons": node.get("approvalButtons") or [],
            "fieldPermissions": [{"fieldId": field_id, "permission": level} for field_id, level in permission_by_field.items()],
            "assigneeProgress": {username: "pending" for username in assignees},
            "activeAssigneeIndex": 0,
            "decisions": [],
        })
    return matched_branches, tasks


def seed_workflow(workflow_id: str = "sample") -> dict:
    return {
        "id": workflow_id,
        "name": "物品申请审批流程",
        "nodes": [
            {"id": "start", "type": "start", "name": "发起", "formId": "sample"},
            {"id": "manager-approval", "type": "approval", "name": "主管审批", "assigneeMode": "specified", "assignees": ["approver"], **approval_node_config()},
            {
                "id": "amount-condition",
                "type": "condition",
                "name": "金额条件",
                "branches": [
                    {"id": "high-amount", "name": "高金额申请", "fieldId": "total", "operator": "gt", "value": "1000", "isDefault": False, "nodes": [{"id": "department-approval", "type": "approval", "name": "主管审批", "assigneeMode": "specified", "assignees": ["approver"], **approval_node_config()}]},
                    {"id": "normal-amount", "name": "普通金额申请", "isDefault": True, "nodes": []},
                ],
            },
            {"id": "admin-execution", "type": "executor", "name": "行政执行", "assigneeMode": "specified", "assignees": ["employee-a"]},
            {"id": "end", "type": "end", "name": "结束"},
        ],
    }


def task_is_actionable_by_user(task: dict, username: str) -> bool:
    if task.get("status") != "pending" or username not in task.get("assignees", []):
        return False
    if (task.get("nodeType") == "approval" and task.get("approvalMode", "sequential") == "sequential") or (
        task.get("nodeType") == "executor" and task.get("executionMode") == "sequential"
    ):
        assignees = task.get("assignees") or []
        index = min(int(task.get("activeAssigneeIndex") or 0), max(0, len(assignees) - 1))
        return bool(assignees) and assignees[index] == username
    if task.get("nodeType") == "approval" and task.get("approvalMode") == "all":
        return task.get("assigneeProgress", {}).get(username, "pending") == "pending"
    return True


def can_recall_workflow(run: dict, current_user: dict) -> bool:
    return (run.get("applicantUsername") == current_user["username"]
            and run.get("status") in {"pending", "pending_assignment"})


def apply_workflow_recall(run: dict, comment: str, current_user: dict, now: str) -> None:
    if run.get("applicantUsername") != current_user["username"]:
        raise HTTPException(status_code=403, detail="只有发起人可以撤回流程")
    if run.get("status") not in {"pending", "pending_assignment"}:
        raise HTTPException(status_code=409, detail="当前流程已结束或已撤回，不能撤回，请刷新后查看")
    for task in run.get("tasks") or []:
        if task.get("status") in {"pending", "waiting", "unassigned"}:
            task["status"] = "cancelled"
            task["assigneeProgress"] = {
                user_id: "cancelled" if progress == "pending" else progress
                for user_id, progress in (task.get("assigneeProgress") or {}).items()
            }
    run["status"] = "recalled"
    run["updatedAt"] = now
    run["recall"] = {
        "username": current_user["username"], "displayName": current_user["displayName"],
        "actorUserId": current_user.get("actorUserId", current_user["username"]),
        "actorName": current_user.get("actorName", current_user["displayName"]),
        "comment": comment.strip(), "createdAt": now,
    }


def recall_workflow_run(run_id: str, payload: WorkflowRecallPayload, current_user: dict) -> dict:
    # Use the same row lock as task actions: an approval and a recall cannot
    # overwrite each other or leave an actionable task on a recalled run.
    with WorkflowRunRepository.task_action_transaction() as repository:
        row = repository.get_run_for_update(run_id)
        if not row:
            raise HTTPException(status_code=404, detail="流程实例不存在")
        run = json.loads(row[5])
        apply_workflow_recall(run, payload.comment, current_user, utc_now())
        repository.save_run(run)
    # A mutation response must not bypass own-record or field read permissions.
    return {"ok": True, "runStatus": run["status"], "recall": run["recall"]}


def perform_task_action(run_id: str, task_id: str, payload: TaskActionPayload, current_user: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with WorkflowRunRepository.task_action_transaction() as repository:
        row = repository.get_run_for_update(run_id)
        if not row:
            raise HTTPException(status_code=404, detail="流程实例不存在")
        run = json.loads(row[5])
        if run.get("status") != "pending":
            raise HTTPException(status_code=409, detail="此流程已不在处理中")
        task = next((item for item in run.get("tasks", []) if item.get("id") == task_id), None)
        if not task:
            raise HTTPException(status_code=404, detail="待办任务不存在")
        if not task_is_actionable_by_user(task, current_user["username"]):
            raise HTTPException(status_code=403, detail="当前任务尚未轮到你处理")

        action = payload.action
        if task.get("nodeType") == "approval":
            button = next((item for item in task.get("approvalButtons", []) if item.get("key") == action and item.get("enabled")), None)
            if not button:
                raise HTTPException(status_code=403, detail="此审批操作未在流程中启用")
            if button.get("opinionMode") == "required" and not payload.comment.strip():
                raise HTTPException(status_code=422, detail=f"请填写{button.get('name', '审批')}意见")
            if action == "reject" and payload.rejectBehavior is None:
                raise HTTPException(status_code=422, detail="请选择拒绝后处理方式")
        elif action != "complete":
            raise HTTPException(status_code=400, detail="执行节点只支持完成操作")

        values_json = repository.get_submission_values(row[3], row[2])
        if values_json is None:
            raise HTTPException(status_code=404, detail="关联表单记录不存在")
        values = json.loads(values_json)
        form_json = repository.get_form_schema(row[2])
        form = normalize_form_schema(json.loads(form_json)) if form_json else seed_form(row[2])
        fields = {field.get("id"): field for field in form.get("fields") or []}
        permissions = {item.get("fieldId"): item.get("permission", "editable") for item in task.get("fieldPermissions") or []}
        for field_id, value in payload.values.items():
            field = fields.get(field_id)
            if not field:
                raise HTTPException(status_code=422, detail="提交中包含无效字段")
            current_value = values.get(field_id)
            if permissions.get(field_id, "editable") != "editable" and value != current_value:
                raise HTTPException(status_code=403, detail=f"字段“{field.get('label', '')}”仅可查看")
            if permissions.get(field_id, "editable") == "editable":
                if field.get("type") == "number" and value not in (None, ""):
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=422, detail=f"“{field.get('label', '数字字段')}”必须填写数字")
                values[field_id] = value

        task.setdefault("decisions", []).append({
            "username": current_user["username"],
            "displayName": current_user["displayName"],
            "actorUserId": current_user.get("actorUserId", current_user["username"]),
            "actorName": current_user.get("actorName", current_user["displayName"]),
            "action": action,
            "comment": payload.comment.strip(),
            "createdAt": now,
            **({"rejectBehavior": payload.rejectBehavior} if action == "reject" else {}),
        })
        run["values"] = values
        should_advance = False
        if task.get("nodeType") == "executor" or action == "agree":
            mode = task.get("approvalMode", "sequential")
            if task.get("nodeType") == "approval":
                task.setdefault("assigneeProgress", {})[current_user["username"]] = "approved"
                if mode == "sequential":
                    next_index = int(task.get("activeAssigneeIndex") or 0) + 1
                    if next_index < len(task.get("assignees") or []):
                        task["activeAssigneeIndex"] = next_index
                    else:
                        should_advance = True
                elif mode == "all":
                    should_advance = all(value == "approved" for value in task["assigneeProgress"].values())
                else:
                    should_advance = True
            else:
                task.setdefault("assigneeProgress", {})[current_user["username"]] = "completed"
                if task.get("executionMode") == "sequential":
                    next_index = int(task.get("activeAssigneeIndex") or 0) + 1
                    if next_index < len(task.get("assignees") or []):
                        task["activeAssigneeIndex"] = next_index
                    else:
                        should_advance = True
                else:
                    should_advance = True
        elif action in {"reject", "return"}:
            returned = action == "return" or payload.rejectBehavior == "return"
            task["status"] = "returned" if returned else "rejected"
            for item in run["tasks"]:
                if item.get("status") == "waiting":
                    item["status"] = "cancelled"
            run["status"] = "returned" if returned else "rejected"
        elif action in {"transfer", "countersign"}:
            if not payload.targetUsername:
                raise HTTPException(status_code=422, detail="请选择要转交或加签的成员")
            target = repository.get_active_user(payload.targetUsername)
            if not target or target[0] == current_user["username"]:
                raise HTTPException(status_code=422, detail="请选择有效的其他成员")
            if action == "transfer":
                task["assignees"] = [target[0]]
                task["assigneeNames"] = [target[1]]
                task["assigneeProgress"] = {target[0]: "pending"}
                task["activeAssigneeIndex"] = 0
            else:
                if target[0] in task.get("assignees", []):
                    raise HTTPException(status_code=409, detail="该成员已在当前审批人列表中")
                task.setdefault("assignees", []).append(target[0])
                task.setdefault("assigneeNames", []).append(target[1])
                task.setdefault("assigneeProgress", {})[target[0]] = "pending"
                task["approvalMode"] = "all"
        elif action == "recall":
            apply_workflow_recall(run, payload.comment, current_user, now)
        elif action != "save":
            raise HTTPException(status_code=400, detail="未知的审批操作")

        if should_advance:
            task["status"] = "completed"
            next_task = next((item for item in run["tasks"] if item.get("status") == "waiting"), None)
            if next_task:
                next_task["status"] = "pending"
            else:
                run["status"] = "completed"

        run["updatedAt"] = now
        repository.save_task_action(run_id, row[3], row[2], run, values, now)
    return {"ok": True, "runStatus": run["status"], "taskStatus": task["status"]}


def seed_form(form_id: str = "sample") -> dict:
    fields = [
        {"id": "item-name", "type": "text", "label": "申请物品", "required": True, "placeholder": "例如显示器、键盘、工牌", "width": "half", "options": []},
        {"id": "quantity", "type": "number", "label": "申请数量", "required": True, "placeholder": "请输入数量", "width": "half", "options": [], "defaultValue": "1"},
        {"id": "unit-price", "type": "number", "label": "预计单价", "required": True, "placeholder": "请输入数字", "width": "half", "options": []},
        {"id": "address", "type": "select", "label": "地址", "required": True, "placeholder": "填写地址", "width": "half", "options": ["北京", "上海", "杭州", "深圳"]},
        {"id": "total", "type": "description", "label": "预计总金额", "required": False, "placeholder": "", "width": "half", "options": [], "defaultValue": "--"},
        {"id": "scene", "type": "select", "label": "使用场景", "required": True, "placeholder": "请选择", "width": "half", "options": ["日常办公", "项目需要", "设备更换", "其他"]},
        {"id": "remark", "type": "textarea", "label": "详细说明", "required": False, "placeholder": "请补充申请原因或其他说明", "width": "full", "options": []},
    ]
    return {
        "id": form_id, "name": "物品申请", "description": "", "fields": fields,
        "pageSettings": default_page_settings(), "permissions": default_page_permissions(),
    }


def load_form(form_id: str, current_user: dict) -> dict:
    if current_user["role"] != "admin":
        workflow_rows = WorkflowRepository.list_schemas()
        found = False
        for row in workflow_rows:
            definition = json.loads(row[0])
            if definition.get('deletedAt'):
                continue
            snapshot = definition.get('publishedSnapshot') or {}
            if snapshot.get('formId') != form_id:
                continue
            found = True
            form = snapshot.get('formSchema')
            if not form:
                continue
            permissions = form.get('permissions') or {}
            if permissions.get('accessMode') == 'members' and current_user['username'] not in permissions.get('members', []):
                continue
            hidden = {item.get('fieldId') for item in snapshot.get('applicantFieldPermissions', []) if item.get('permission') == 'hidden'}
            return {**form, 'fields': [field for field in form.get('fields', []) if field.get('id') not in hidden]}
        raise HTTPException(status_code=403 if found else 404, detail='没有可访问的已发布表单')
    row = FormRepository.get_schema(form_id)
    return normalize_form_schema(json.loads(row[0])) if row else seed_form(form_id)


def load_workflow(workflow_id: str) -> dict:
    row = WorkflowRepository.get_schema(workflow_id)
    if row is None:
        if workflow_id == "sample":
            return seed_workflow()
        raise HTTPException(status_code=404, detail="工作流不存在")
    return normalize_workflow_schema(json.loads(row[0]))


def publish_workflow(workflow_id: str, current_user: dict) -> dict:
    schema = load_workflow(workflow_id)
    if schema.get("deletedAt"):
        raise HTTPException(status_code=410, detail="流程已删除，不能发布")
    start_node = next((node for node in schema.get("nodes") or [] if node.get("type") == "start"), None)
    form_id = (start_node or {}).get("formId")
    if not form_id:
        raise HTTPException(status_code=422, detail="请先选择流程发起表单")
    form = load_form(form_id, current_user)
    users = [
        {"username": row[0], "displayName": row[1], "role": row[2], "department": row[3], "managerUsername": row[4], "departmentIds": row[5] if len(row) > 5 else [], "managerUserIds": row[6] if len(row) > 6 else []}
        for row in UserRepository.list_active_for_routing()
    ]
    errors = validate_workflow_for_publish(schema, form, users)
    if errors:
        raise HTTPException(status_code=422, detail="；".join(errors))

    version = int(schema.get("publishedVersion") or 0) + 1
    published_at = utc_now()
    schema["publishedAt"] = published_at
    schema["publishedVersion"] = version
    schema["publishedSnapshot"] = {
        "name": schema["name"],
        "category": schema.get("category") or "常用流程",
        "formId": form_id,
        "formSchema": form,
        "version": version,
        "nodes": schema.get("nodes") or [],
        "applicantFieldPermissions": schema.get("applicantFieldPermissions") or [],
    }
    schema["updatedAt"] = published_at
    WorkflowRepository.save_schema(workflow_id, schema)
    return schema


def redact_run_for_applicant(run: dict) -> dict:
    permissions = {
        item.get("fieldId"): item.get("permission", "editable")
        for item in run.get("applicantFieldPermissions") or []
    }
    hidden_ids = {field_id for field_id, permission in permissions.items() if permission == "hidden"}
    result = dict(run)
    result["values"] = {field_id: value for field_id, value in (run.get("values") or {}).items() if field_id not in hidden_ids}
    form = run.get("formSchema")
    if form:
        result["formSchema"] = {
            **form,
            "fields": [field for field in form.get("fields") or [] if field.get("id") not in hidden_ids],
        }
    return result


def prepare_workflow_application(workflow_id: str, payload: WorkflowRunPayload, current_user: dict, require_complete: bool = True) -> tuple:
    workflow = load_workflow(workflow_id)
    if workflow.get("deletedAt"):
        raise HTTPException(status_code=410, detail="流程已删除，不能发起申请")
    if workflow.get("disabledAt"):
        raise HTTPException(status_code=409, detail="流程已停用，不能发起申请")
    snapshot = workflow.get("publishedSnapshot")
    if not snapshot:
        raise HTTPException(status_code=409, detail="工作流尚未发布")
    form_id = snapshot.get("formId")
    if not form_id:
        raise HTTPException(status_code=409, detail="已发布流程未关联表单")
    form = snapshot.get("formSchema") or load_form(form_id, current_user)
    access = form.get("permissions") or {}
    if access.get("canSubmit") is False or (access.get("accessMode") == "members" and current_user["username"] not in access.get("members", [])):
        raise HTTPException(status_code=403, detail="当前表单不允许你发起申请")
    users = [
        {"username": row[0], "displayName": row[1], "role": row[2], "department": row[3], "managerUsername": row[4], "departmentIds": row[5] if len(row) > 5 else [], "managerUserIds": row[6] if len(row) > 6 else []}
        for row in UserRepository.list_active_for_routing()
    ]
    fields = {field.get("id"): field for field in form.get("fields") or []}
    applicant_permissions = snapshot.get("applicantFieldPermissions") or workflow.get("applicantFieldPermissions") or []
    permission_by_field = {item.get("fieldId"): item.get("permission", "editable") for item in applicant_permissions}
    invalid_field_ids = set(payload.values) - set(fields)
    if invalid_field_ids:
        raise HTTPException(status_code=422, detail="提交中包含无效字段")
    values = {}
    for field in fields.values():
        field_id = field.get("id")
        permission = permission_by_field.get(field_id, "editable")
        default_value = field.get("defaultValue")
        if field.get("type") == "dateRange" and isinstance(default_value, str):
            default_value = re.findall(r"\d{4}-\d{2}-\d{2}", default_value)[:2]
        if permission == "hidden":
            if default_value not in (None, ""):
                values[field_id] = default_value
            continue
        if field_id in payload.values and permission != "readonly":
            values[field_id] = payload.values[field_id]
        elif default_value not in (None, ""):
            values[field_id] = default_value
        value = values.get(field_id)
        empty = application_value_empty(value)
        if require_complete and field.get("required") and field.get("type") != "description" and empty:
            raise HTTPException(status_code=422, detail=f"请填写“{field.get('label') or '必填字段'}”")
        if field.get("type") == "number" and not empty:
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"“{field.get('label') or '数字字段'}”必须填写数字")

        if field.get("type") == "dateRange" and not empty:
            valid_pair = isinstance(value, list) and len(value) == 2 and all(isinstance(item, str) and item for item in value)
            if valid_pair:
                try:
                    dates = [datetime.strptime(item, "%Y-%m-%d") for item in value]
                except ValueError:
                    raise HTTPException(status_code=422, detail=f"“{field.get('label')}”的日期格式不正确")
                if dates[0] > dates[1]:
                    raise HTTPException(status_code=422, detail=f"“{field.get('label')}”的结束日期不能早于开始日期")
            elif require_complete:
                raise HTTPException(status_code=422, detail=f"请选择完整的“{field.get('label')}”")
    return workflow, snapshot, form, fields, values, users, applicant_permissions


def application_value_empty(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, list) and not any(not application_value_empty(item) for item in value))


def preview_workflow_run(workflow_id: str, payload: WorkflowRunPayload, current_user: dict) -> dict:
    """Calculate from the published snapshot; never create business records or expose configuration."""
    workflow, snapshot, form, fields, values, users, permissions = prepare_workflow_application(workflow_id, payload, current_user, require_complete=False)
    hidden = {item.get("fieldId") for item in permissions if item.get("permission") == "hidden"}
    incomplete = any(field.get("required") and field.get("type") != "description" and field_id not in hidden and application_value_empty(values.get(field_id)) for field_id, field in fields.items())
    def routing_incomplete(nodes):
        for node in nodes:
            if node.get("assigneeMode") == "form_field" and application_value_empty(values.get(node.get("assigneeFieldId"))):
                return True
            for branch in node.get("branches") or []:
                if not branch.get("isDefault") and branch.get("fieldId") and application_value_empty(values.get(branch["fieldId"])):
                    return True
                if routing_incomplete(branch.get("nodes") or []):
                    return True
        return False
    incomplete = incomplete or routing_incomplete(snapshot.get("nodes") or [])
    incomplete = incomplete or any(field.get("type") == "dateRange" and not application_value_empty(values.get(field_id)) and (not isinstance(values[field_id], list) or len(values[field_id]) != 2 or not all(values[field_id])) for field_id, field in fields.items())
    _branches, tasks = evaluate_workflow_route({"nodes": snapshot.get("nodes") or [], "category": snapshot.get("category") or "常用流程"}, values, fields, current_user, users)
    return {
        "version": int(snapshot.get("version") or workflow.get("publishedVersion") or 1),
        "incomplete": incomplete,
        "steps": [{"name": task["nodeName"], "type": task["nodeType"], "assigneeNames": task["assigneeNames"]} for task in tasks],
    }


def start_workflow_run(workflow_id: str, payload: WorkflowRunPayload, current_user: dict) -> dict:
    workflow, snapshot, form, fields, values, users, applicant_permissions = prepare_workflow_application(workflow_id, payload, current_user)
    form_id = snapshot["formId"]
    matched_branches, tasks = evaluate_workflow_route(
        {"nodes": snapshot.get("nodes") or [], "category": snapshot.get("category") or "常用流程"}, values, fields, current_user, users,
    )
    version = int(snapshot.get("version") or workflow.get("publishedVersion") or 1)
    run_id = uuid.uuid4().hex
    submission_id = uuid.uuid4().hex
    now = utc_now()
    first_value = next((values.get(field.get("id")) for field in form.get("fields") or []
                        if values.get(field.get("id")) not in (None, "", [])), None)
    if isinstance(first_value, list):
        first_value = ", ".join(str(item) for item in first_value)
    title = str(first_value or form.get("name") or "流程申请")[:200]
    if not tasks:
        status = "completed"
    elif tasks[0]["status"] == "unassigned":
        status = "pending_assignment"
    else:
        status = "pending"
    result = {
        "id": run_id,
        "workflowId": workflow_id,
        "workflowName": snapshot.get("name") or workflow.get("name"),
        "workflowVersion": version,
        "workflowCategory": snapshot.get("category") or workflow.get("category") or "常用流程",
        "formId": form_id,
        "formSchema": form,
        "submissionId": submission_id,
        "title": title,
        "applicant": current_user["displayName"],
        "applicantUsername": current_user["username"],
        "status": status,
        "matchedBranches": matched_branches,
        "tasks": tasks,
        "values": values,
        "applicantFieldPermissions": applicant_permissions,
        "createdAt": now,
    }
    WorkflowRunRepository.create_run(result, now)
    return {**redact_run_for_applicant(result), "canRecall": can_recall_workflow(result, current_user)}


def list_all_workflow_runs() -> list[dict]:
    runs = []
    forms_by_id = {}
    for row in WorkflowRunRepository.list_all():
        run = json.loads(row[0])
        form_id = run.get("formId")
        if not run.get("formSchema") and form_id:
            if form_id not in forms_by_id:
                form_row = FormRepository.get_schema(form_id)
                forms_by_id[form_id] = normalize_form_schema(json.loads(form_row[0])) if form_row else None
            run["formSchema"] = forms_by_id[form_id]
        runs.append(run)
    return runs


def list_my_workflow_runs(current_user: dict) -> list[dict]:
    runs = []
    for applicant, result_json in WorkflowRunRepository.list_for_applicant(current_user["username"]):
        run = json.loads(result_json)
        applicant_username = run.get("applicantUsername")
        if applicant_username and applicant_username != current_user["username"]:
            continue
        if not applicant_username:
            continue
        if not run.get("formSchema") and run.get("formId"):
            form_row = FormRepository.get_schema(run["formId"])
            if form_row:
                run["formSchema"] = normalize_form_schema(json.loads(form_row[0]))
        if ((run.get('formSchema') or {}).get('permissions') or {}).get('canViewOwnRecords') is False:
            continue
        runs.append({**redact_run_for_applicant(run), "canRecall": can_recall_workflow(run, current_user)})
    return runs


def list_task_inbox(current_user: dict) -> list[dict]:
    rows = WorkflowRunRepository.list_pending()
    forms_by_id: dict[str, dict] = {}
    inbox: list[dict] = []
    for row in rows:
        run = json.loads(row[0])
        for task in run.get("tasks") or []:
            if not task_is_actionable_by_user(task, current_user["username"]):
                continue
            form_id = run.get("formId", "")
            if form_id not in forms_by_id and run.get("formSchema"):
                forms_by_id[form_id] = normalize_form_schema(run["formSchema"])
            if form_id not in forms_by_id:
                form_row = FormRepository.get_schema(form_id)
                forms_by_id[form_id] = normalize_form_schema(json.loads(form_row[0])) if form_row else seed_form(form_id)
            form = forms_by_id[form_id]
            permissions = {item.get("fieldId"): item.get("permission", "editable") for item in task.get("fieldPermissions") or []}
            visible_fields = [field for field in form.get("fields") or [] if permissions.get(field.get("id"), "editable") != "hidden"]
            visible_values = {field.get("id"): run.get("values", {}).get(field.get("id")) for field in visible_fields if field.get("id") in run.get("values", {})}
            inbox.append({
                "runId": run["id"],
                "workflowId": run["workflowId"],
                "workflowName": run["workflowName"],
                "workflowVersion": run["workflowVersion"],
                "submissionId": run["submissionId"],
                "title": run["title"],
                "applicant": run["applicant"],
                "createdAt": run["createdAt"],
                "matchedBranches": run.get("matchedBranches", []),
                "task": task,
                "form": {"id": form["id"], "name": form["name"], "fields": visible_fields},
                "values": visible_values,
                "actions": [button for button in task.get("approvalButtons", []) if button.get("enabled")]
                if task.get("nodeType") == "approval" else [{"key": "complete", "name": "完成", "enabled": True, "opinionMode": "none"}],
            })
    return inbox


def list_task_history(current_user: dict) -> list[dict]:
    history: list[dict] = []
    for row in WorkflowRunRepository.list_all():
        run = json.loads(row[0])
        for task in run.get("tasks") or []:
            for decision in task.get("decisions") or []:
                if decision.get("username") != current_user["username"]:
                    continue
                history.append({
                    "runId": run["id"],
                    "workflowName": run["workflowName"],
                    "title": run["title"],
                    "applicant": run["applicant"],
                    "runStatus": run["status"],
                    "nodeName": task["nodeName"],
                    "action": decision["action"],
                    "comment": decision.get("comment", ""),
                    "createdAt": decision["createdAt"],
                })
    return sorted(history, key=lambda item: item["createdAt"], reverse=True)

def approval_record_access(run: dict, current_user: dict) -> tuple[bool, bool, list[dict]]:
    user_id = current_user["username"]
    own = run.get("applicantUsername") == user_id
    participated = [
        task for task in run.get("tasks") or []
        if (run.get("status") == "pending" and task_is_actionable_by_user(task, user_id))
        or any(decision.get("username") == user_id for decision in task.get("decisions") or [])
    ]
    form = run.get("formSchema") or {}
    permissions = form.get("permissions") or {}
    own_allowed = own and permissions.get("canViewOwnRecords") is not False
    if permissions.get("accessMode") == "members" and user_id not in permissions.get("members", []):
        own_allowed = False
    return current_user.get("canManagePermissions") is True, own_allowed, participated


def approval_record_schemas() -> list[dict]:
    # Historical instances keep their own form and category snapshots.
    runs = list_all_workflow_runs()
    categories = {}
    for row in WorkflowRepository.list_schemas():
        workflow = json.loads(row[0])
        categories[workflow["id"]] = (workflow.get("publishedSnapshot") or {}).get("category") or workflow.get("category") or "常用流程"
    for run in runs:
        run.setdefault("workflowCategory", categories.get(run.get("workflowId"), "常用流程"))
    return runs


def approval_record_summary(run: dict, current_user: dict) -> dict:
    user_id = current_user["username"]
    tasks = run.get("tasks") or []
    active = next((task for task in tasks if task.get("status") in {"pending", "unassigned"}), None)
    actionable = [task for task in tasks if run.get("status") == "pending" and task_is_actionable_by_user(task, user_id)]
    handlers = []
    if active:
        assignees = active.get("assignees") or []
        names = active.get("assigneeNames") or assignees
        if active.get("executionMode") == "sequential" or (active.get("nodeType") == "approval" and active.get("approvalMode", "sequential") == "sequential"):
            index = int(active.get("activeAssigneeIndex") or 0)
            handlers = names[index:index + 1]
        elif active.get("approvalMode") == "all":
            handlers = [name for index, name in enumerate(names) if index >= len(assignees) or active.get("assigneeProgress", {}).get(assignees[index], "pending") == "pending"]
        else:
            handlers = names
    stage = run.get("status", "pending")
    if stage == "pending":
        stage = "executing" if active and active.get("nodeType") == "executor" else "approving"
    _admin, _own, related = approval_record_access(run, current_user)
    return {
        "id": run["id"], "title": run.get("title", ""), "workflowId": run.get("workflowId", ""),
        "workflowName": run.get("workflowName", ""), "category": run.get("workflowCategory") or "常用流程",
        "status": run.get("status"), "stage": stage, "applicant": run.get("applicant", ""),
        "createdAt": run.get("createdAt", ""), "currentNode": active.get("nodeName", "") if active else "",
        "currentHandlers": handlers, "mine": run.get("applicantUsername") == user_id,
        "participating": bool(related), "processed": any(any(item.get("username") == user_id for item in task.get("decisions") or []) for task in tasks),
        "approving": any(task.get("nodeType") == "approval" for task in actionable),
        "executing": any(task.get("nodeType") == "executor" for task in actionable),
        "canHandle": bool(actionable),
    }


def list_approval_records(current_user: dict, scope: str = "applications") -> list[dict]:
    if scope not in {"applications", "personal"}:
        raise HTTPException(status_code=422, detail="不支持的审批记录范围")
    records = []
    for run in approval_record_schemas():
        admin, own, related = approval_record_access(run, current_user)
        # The application catalog is owner-only for employees. Task-related
        # records are requested explicitly by the personal task/status page.
        if admin or own or (scope == "personal" and related):
            records.append(approval_record_summary(run, current_user))
    return records


def get_approval_record(run_id: str, current_user: dict) -> dict:
    run = next((item for item in approval_record_schemas() if item["id"] == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="审批记录不存在")
    admin, own, related = approval_record_access(run, current_user)
    if not admin and not own and not related:
        raise HTTPException(status_code=404, detail="审批记录不存在")
    run = {**run, "canRecall": can_recall_workflow(run, current_user)}
    if admin:
        return run
    if own:
        result = redact_run_for_applicant(run)
    else:
        # Only current handlers or actual past decision makers have task access.
        eligible = [task for task in related if task_is_actionable_by_user(task, current_user["username"])
                    or any(item.get("username") == current_user["username"] for item in task.get("decisions") or [])]
        fields = (run.get("formSchema") or {}).get("fields") or []
        visible = set()
        for task in eligible:
            levels = {item.get("fieldId"): item.get("permission") for item in task.get("fieldPermissions") or []}
            visible.update(field["id"] for field in fields if levels.get(field["id"]) != "hidden")
        result = {**run, "values": {key: value for key, value in (run.get("values") or {}).items() if key in visible},
                  "formSchema": {**(run.get("formSchema") or {}), "fields": [field for field in fields if field["id"] in visible]}}
    # Expose progress and decisions, not permission rules or routing predicates.
    result = {**result, "matchedBranches": [], "applicantFieldPermissions": []}
    if result.get("formSchema"):
        result["formSchema"] = {**result["formSchema"], "permissions": {}, "pageSettings": {}}
    result["tasks"] = [
        {key: value for key, value in task.items() if key not in {"fieldPermissions", "approvalButtons", "assigneeMode"}}
        for task in run.get("tasks") or []
    ]
    return result
