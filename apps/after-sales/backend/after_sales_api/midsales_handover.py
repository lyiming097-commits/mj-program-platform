"""Preserve presales history while handing a completed workflow to midsales."""
from .models import ServiceProject
from .services import (
    MIDSALES_NODE_TEMPLATE, DomainValidationError, create_project,
    generated_code, record_project_event,
)


def midsales_node_keys(value):
    valid = {row[0] for row in MIDSALES_NODE_TEMPLATE}
    required = {"midsales-project", "midsales-project-end"}
    if (not isinstance(value, list) or not value
            or any(not isinstance(key, str) or key not in valid for key in value)
            or len(set(value)) != len(value) or not required.issubset(value)):
        raise DomainValidationError(
            "请选择售中包含的节点，并保留项目立项和售中项目结束",
            code="MIDSALES_HANDOVER_NODES_REQUIRED",
        )
    return [row[0] for row in MIDSALES_NODE_TEMPLATE if row[0] in value]


def handover_to_midsales(request, project, node):
    # The caller holds the presales row lock through completion and creation.
    # The unique relation also prevents duplicate handovers across requests.
    existing = ServiceProject.objects.filter(presales_project=project).first()
    if existing is not None:
        if existing.deleted_at:
            raise DomainValidationError(
                "关联售中项目已删除，请先恢复该售中项目",
                code="MIDSALES_HANDOVER_PROJECT_DELETED", status=409,
            )
        return existing
    selected = midsales_node_keys((node.business_data or {}).get("midsalesNodeKeys"))
    target = create_project(request, {
        "code": generated_code("MS"), "service_type": ServiceProject.TYPE_MIDSALES,
        "presales_project": project,
        "name": project.name, "customer": project.customer,
        "owner_user_id": project.owner_user_id, "owner_name": project.owner_name,
        "address": project.address, "province": project.province, "summary": project.summary,
    }, disabled_node_keys={row[0] for row in MIDSALES_NODE_TEMPLATE} - set(selected))
    record_project_event(
        request, project, node=node, event_type="midsales_handover",
        title="售前结束，转入售中服务",
        after={"midsalesProjectId": target.id, "enabledNodeKeys": selected},
    )
    record_project_event(
        request, target, event_type="presales_handover",
        title="承接售前项目", detail=project.name,
        after={"presalesProjectId": project.id},
    )
    return target
