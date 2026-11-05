"""Read-only presales reporting over the same project/CRM scope as the list."""
from decimal import Decimal, InvalidOperation

from django.db.models import Count, JSONField, OuterRef, Q, Subquery
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import PresalesTaskSchedule, PrivateAttachment, ProjectNode, ServiceProject
from .project_personnel import personnel_members
from .services import DomainValidationError, text


DIMENSIONS = {"all", "nature", "stage", "sales", "design"}
PHASE_NODES = {
    "earlyTasks": {"early-plan", "budget-match"},
    "filingTasks": {"project-filing"},
    "tenderBaseTasks": {"late-plan", "device-plan", "budget", "device-budget", "cost-control",
                        "device-cost-control", "rendering", "tender-plan", "layout"},
    "bidTasks": {"bid-prep"},
    "constructionTasks": {"construction"},
}


def _number(value):
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        amount = Decimal(str(value).strip().replace(",", "").removeprefix("￥").removeprefix("¥"))
        if amount.is_finite() and 0 <= amount <= Decimal("999999999999999.99"):
            return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        pass
    return None


def _tags(value):
    rows = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return list(dict.fromkeys(text(row) for row in rows if isinstance(row, str) and text(row)))


def _project(row):
    snapshot = row["crm_snapshot"] if isinstance(row["crm_snapshot"], dict) else {}
    info = row["business_data__projectInfo"]
    info = info if isinstance(info, dict) else {}
    leads = row["_project_leads"] if isinstance(row["_project_leads"], dict) else {}
    crm = bool(row["source_crm_id"])
    amount = _number(snapshot.get("amount") if crm else info.get("amount"))
    area = _number(snapshot.get("integrationEngineeringArea") if crm else info.get("area"))
    started = row["actual_start_date"] or timezone.localdate(row["created_at"])
    return {
        "id": row["id"], "name": row["name"], "customer": row["customer"],
        "ownerUserId": row["owner_user_id"], "ownerName": row["owner_name"],
        "status": row["status"], "statusLabel": dict(ServiceProject.STATUS_CHOICES).get(row["status"], row["status"]),
        "crmStage": text(snapshot.get("stage")) if crm else "",
        "crmCreatedAt": text(snapshot.get("createdAt")) if crm else "",
        "natures": _tags(snapshot.get("integrationWorkTypes") if crm else info.get("nature")),
        "designOwners": personnel_members(leads.get("design")),
        "solutionOwners": personnel_members(leads.get("solution")),
        "projectLevel": text(info.get("projectLevel")),
        "amount": format(amount, "f") if amount is not None else None,
        "area": format(area, "f") if area is not None else None,
        "startedAt": started.isoformat(),
        "currentNodeKey": row["current_node_key"],
    }


def _members(project, dimension):
    if dimension == "all":
        return []
    if dimension == "nature":
        return [("nature:" + value, value) for value in project["natures"]] or [("nature:__empty__", "未填写性质")]
    if dimension == "stage":
        stage = project["crmStage"]
        return [("stage:" + stage, stage or "未关联 CRM 阶段")]
    if dimension == "sales":
        user_id, name = project["ownerUserId"], project["ownerName"]
        return [("sales:" + (user_id or "name:" + name), name or user_id or "未分派销售")]
    return [("design:" + row["userId"], row["name"]) for row in project["designOwners"]] or [
        ("design:__empty__", "未分派设计负责人"),
    ]


def _totals(projects):
    amounts = [_number(row["amount"]) for row in projects if row["amount"] is not None]
    areas = [_number(row["area"]) for row in projects if row["area"] is not None]
    return {
        "count": len(projects),
        "activeCount": sum(row["status"] == ServiceProject.STATUS_IN_PROGRESS for row in projects),
        "completedCount": sum(row["status"] == ServiceProject.STATUS_COMPLETED for row in projects),
        "amount": format(sum(amounts, Decimal("0")), ".2f") if amounts else None,
        "area": format(sum(areas, Decimal("0")), ".2f") if areas else None,
        "knownAmountCount": len(amounts), "knownAreaCount": len(areas),
    }


@require_GET
def presales_statistics(request):
    # Local import reuses list guards and CRM recovery without a circular import.
    from . import views

    denied = views._ensure_app_admin(request)
    if denied is not None:
        return denied
    dimension = text(request.GET.get("groupBy")) or "all"
    if dimension not in DIMENSIONS:
        return views._error("不支持的统计分类", code="INVALID_STATISTICS_DIMENSION", status=400)
    status = text(request.GET.get("status"))
    if status and status not in dict(ServiceProject.STATUS_CHOICES):
        return views._error("无效的项目状态", code="INVALID_PROJECT_STATUS", status=400)
    sync_status = {"crmSyncing": False, "crmSyncError": "", "crmScopeReady": False}
    try:
        views.sync_crm_presales(request, background=True)
        sync_status.update(views.crm_sync_status(request))
    except DomainValidationError as exc:
        request._after_sales_crm_ids = []
        sync_status["crmSyncError"] = str(exc)
    queryset, _provider, failure = views._visible_projects(request, service_type=ServiceProject.TYPE_PRESALES)
    if failure is not None:
        return failure
    if status:
        queryset = queryset.filter(status=status)
    search = text(request.GET.get("search"))[:200]
    if search:
        queryset = views.filter_queryset_search(queryset, search, ("name", "customer", "owner_name"))
    leads = ProjectNode.objects.filter(project_id=OuterRef("pk"), node_key="early-approval")
    queryset = views._order_projects_by_creation(queryset).annotate(_project_leads=Subquery(
        leads.values("business_data__projectLeads")[:1], output_field=JSONField(),
    ))
    projects = [_project(row) for row in queryset.values(
        "id", "name", "customer", "owner_user_id", "owner_name", "status", "source_crm_id",
        "current_node_key", "created_at", "actual_start_date", "crm_snapshot",
        "business_data__projectInfo", "_project_leads",
    ).iterator(chunk_size=500)]
    groups = {}
    for project in projects:
        for key, label in _members(project, dimension):
            group = groups.setdefault(key, {"key": key, "label": label, "projects": []})
            group["projects"].append(project)
    summary = _totals(projects)
    group_rows = [{"key": value["key"], "label": value["label"], **_totals(value["projects"])}
                  for value in groups.values()]
    group_rows.sort(key=lambda row: (-row["count"], row["label"], row["key"]))
    group_key = text(request.GET.get("groupKey")) if dimension != "all" else ""
    selected = groups.get(group_key, {}).get("projects", []) if group_key else projects
    page, page_size = views._page(request)
    total = len(selected)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    items = [dict(row) for row in selected[(page - 1) * page_size:page * page_size]]
    _add_page_details(items)
    return JsonResponse({
        "summary": summary, "groups": group_rows, "groupBy": dimension, "items": items,
        "groupMembershipCount": sum(row["count"] for row in group_rows),
        "page": page, "pageSize": page_size, "total": total, "totalPages": total_pages,
        **sync_status,
    })


def _add_page_details(items):
    """Read descriptions, task schedules and attachment counts only for this page."""
    by_id = {item["id"]: item for item in items}
    for row in ServiceProject.objects.filter(pk__in=by_id).values("id", "summary", "business_data__projectInfo"):
        item = by_id[row["id"]]
        info = row["business_data__projectInfo"]
        info = info if isinstance(info, dict) else {}
        item.update({
            "description": text(info.get("info")) or row["summary"],
            "totalArea": _decimal_string(info.get("totalArea")),
            "designArea": _decimal_string(info.get("designArea")),
            "expectedBidAt": text(info.get("expectedBidAt")),
            "urgency": text(info.get("urgency")), "note": text(info.get("reason")),
            "tasks": [], "participants": [], "nodeNames": [],
            "requirementNodeId": None, "requirementCount": 0,
        })
    node_map, originals = {}, {}
    for node in ProjectNode.objects.filter(project_id__in=by_id, enabled=True).values(
        "id", "project_id", "node_key", "name", "status", "completed_at", "business_data__managementAssignment",
    ):
        node_map[node["id"]] = node
        item = by_id[node["project_id"]]
        item["participants"].extend(personnel_members(node["business_data__managementAssignment"]))
        if node["status"] == ProjectNode.STATUS_ACTIVE and item["status"] == ServiceProject.STATUS_IN_PROGRESS:
            item["nodeNames"].append(node["name"])
        if node["node_key"] == item["currentNodeKey"]:
            item["_currentNodeName"] = node["name"]
        if node["node_key"] == "early-approval":
            item["requirementNodeId"] = node["id"]
            originals[node["id"]] = item
    for row in PrivateAttachment.objects.filter(
        Q(target_type=PrivateAttachment.TARGET_PRESALES_PROJECT, target_id__in=by_id)
        | Q(target_type=PrivateAttachment.TARGET_PROJECT_NODE, target_id__in=originals),
        category=PrivateAttachment.CATEGORY_GENERAL,
    ).values("target_type", "target_id").annotate(count=Count("id")):
        project = by_id if row["target_type"] == PrivateAttachment.TARGET_PRESALES_PROJECT else originals
        project[row["target_id"]]["requirementCount"] += row["count"]
    for task in PresalesTaskSchedule.objects.filter(node_id__in=node_map).values(
        "node_id", "round_number", "planned_start_date", "planned_end_date",
    ):
        node = node_map[task["node_id"]]
        completed = node["status"] == ProjectNode.STATUS_COMPLETED
        completed_at = node["completed_at"] if completed else None
        by_id[node["project_id"]]["tasks"].append({
            "nodeKey": node["node_key"], "nodeName": node["name"], "roundNumber": task["round_number"],
            "name": f'{node["name"]} · 第 {task["round_number"]} 轮',
            "plannedStartDate": task["planned_start_date"], "plannedEndDate": task["planned_end_date"],
            # Historical designDate is no longer a completion signal. The
            # workflow records completion when the node passes.
            "isCompleted": completed,
            "actualEndDate": timezone.localdate(completed_at).isoformat() if completed_at else None,
        })
    for item in items:
        current_name = item.pop("_currentNodeName", "未设置")
        item["nodeNames"] = item["nodeNames"] or [current_name]
        item["latestStage"] = "、".join(item["nodeNames"])
        members = [*item["designOwners"], *item["solutionOwners"], *item["participants"]]
        item["participants"] = list({row["userId"]: row for row in members}.values())
        item["taskCount"] = len(item["tasks"])
        item["completedTaskCount"] = sum(task["isCompleted"] for task in item["tasks"])
        for key, node_keys in PHASE_NODES.items():
            item[key] = [task for task in item["tasks"] if task["nodeKey"] in node_keys]


def _decimal_string(value):
    number = _number(value)
    return format(number, "f") if number is not None else None
