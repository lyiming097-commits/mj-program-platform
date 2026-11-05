from __future__ import annotations

from collections.abc import Iterable


PRESALES_FLOW_COLUMNS = {
    "early-approval": 1,
    "early-plan": 2,
    "budget-match": 2,
    "project-filing": 3,
    "early-plan-result": 4,
    "late-approval": 5,
    "late-plan": 6,
    "device-plan": 6,
    "budget": 7,
    "device-budget": 7,
    "cost-control": 8,
    "device-cost-control": 8,
    "rendering": 9,
    "tender-plan": 9,
    "layout": 10,
    "bid-prep": 10,
    "construction-result": 11,
    "construction": 12,
    "project-end": 13,
}

PRESALES_FLOW_DEPENDENCIES = {
    "early-approval": (),
    "early-plan": ("early-approval",),
    "budget-match": ("early-approval",),
    "project-filing": ("budget-match",),
    "early-plan-result": ("early-plan", "project-filing"),
    "late-approval": ("early-plan-result",),
    "late-plan": ("late-approval",),
    "device-plan": ("late-approval",),
    "budget": ("late-plan",),
    "device-budget": ("device-plan",),
    "cost-control": ("budget",),
    "device-cost-control": ("device-budget",),
    "rendering": ("cost-control",),
    "tender-plan": ("device-cost-control",),
    "layout": ("rendering",),
    "bid-prep": ("tender-plan",),
    "construction-result": ("layout", "bid-prep"),
    "construction": ("construction-result",),
    "project-end": ("construction",),
}

APPROVAL_NODES = {"early-approval", "late-approval"}
RESULT_NODES = {"early-plan-result", "construction-result"}

OUTCOME_LABELS = {
    "approved": "立项成功",
    "denied": "立项否决",
    "passed": "通过",
    "won": "中标",
    "failed": "失败",
    "abandoned": "放弃",
    "suspended": "挂起",
}

OUTCOME_ALIASES = {
    "approve": "approved",
    "approved": "approved",
    "pass": "passed",
    "passed": "passed",
    "win": "won",
    "won": "won",
    "fail": "failed",
    "failed": "failed",
    "abandon": "abandoned",
    "abandoned": "abandoned",
    "suspend": "suspended",
    "suspended": "suspended",
    "reject": "denied",
    "rejected": "denied",
    "denied": "denied",
    "立项成功": "approved",
    "立项否决": "denied",
    "通过": "passed",
    "中标": "won",
    "失败": "failed",
    "放弃": "abandoned",
    "挂起": "suspended",
}


def normalized_outcome(value: object) -> str:
    raw = str(value or "").strip()
    return OUTCOME_ALIASES.get(raw, OUTCOME_ALIASES.get(raw.lower(), ""))


def allowed_outcomes(node_key: str) -> set[str]:
    if node_key in APPROVAL_NODES:
        return {"approved", "denied"}
    if node_key == "early-plan-result":
        return {"passed", "failed", "abandoned", "suspended"}
    if node_key == "construction-result":
        return {"won", "failed", "abandoned", "suspended"}
    return set()


def node_outcome(node) -> str:
    data = node.business_data if isinstance(node.business_data, dict) else {}
    return normalized_outcome(data.get("outcome"))


def presales_node_is_successful(node) -> bool:
    if node.node_key in APPROVAL_NODES:
        return node_outcome(node) == "approved"
    if node.node_key == "early-plan-result":
        return node_outcome(node) == "passed"
    if node.node_key == "construction-result":
        return node_outcome(node) == "won"
    return node.status == "completed"


def presales_prerequisites(nodes: Iterable, result_node) -> list:
    prerequisite_keys = set(PRESALES_FLOW_DEPENDENCIES.get(result_node.node_key, ()))
    return [
        node
        for node in nodes
        if node.enabled
        and node.node_key in prerequisite_keys
    ]


def presales_locked(node, nodes: Iterable) -> bool:
    prerequisite_keys = PRESALES_FLOW_DEPENDENCIES.get(node.node_key)
    if prerequisite_keys is None:
        return True
    rows_by_key = {row.node_key: row for row in nodes}
    for prerequisite_key in prerequisite_keys:
        prerequisite = rows_by_key.get(prerequisite_key)
        if prerequisite is None:
            return True
        if prerequisite.enabled and not presales_node_is_successful(prerequisite):
            return True
    return False


def aftersales_dispatch_errors(project_data: object) -> list[str]:
    data = project_data if isinstance(project_data, dict) else {}
    errors = []
    required = {
        "managerContact": "负责人联系方式",
        "expectedDuration": "预计服务时长",
        "feeAgreement": "费用约定",
        "feeRemark": "费用备注",
    }
    for key, label in required.items():
        if not str(data.get(key) or "").strip():
            errors.append(label)

    return errors


def aftersales_completion_errors(project_data: object, node_data: object) -> list[str]:
    errors = aftersales_dispatch_errors(project_data)
    data = node_data if isinstance(node_data, dict) else {}
    required = {
        "actualStartTime": "实际开始时间",
        "actualDuration": "实际服务时长",
    }
    for key, label in required.items():
        if not str(data.get(key) or "").strip():
            errors.append(label)
    return errors
