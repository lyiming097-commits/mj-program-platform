"""Application abilities and object scope, independent of authentication."""
from .models import ServiceProject
from .project_personnel import personnel_members
from .permissions import (
    APP_PERMISSION_ADMIN, APP_PERMISSION_SERVICE, APP_PERMISSION_LABELS, get_request_app_permissions,
)


def management_user(request):
    claims = getattr(request, "auth_token_claims", {}) or {}
    return bool(getattr(request, "auth_user_id", "")) and claims.get("chn", "dingtalk") == "dingtalk"


def can_use_management(request):
    return management_user(request) and bool(get_request_app_permissions(request) & APP_PERMISSION_LABELS.keys())


def require_management(request):
    if not can_use_management(request):
        deny("当前账号没有迈杰服务使用权限，请联系系统管理员分配权限", "APP_ACCESS_DENIED")


def has_permission(request, permission):
    roles = get_request_app_permissions(request)
    return APP_PERMISSION_ADMIN in roles or permission in roles


def manages_business(request):
    return can_use_management(request)


def manages_service(request):
    return management_user(request) and has_permission(request, APP_PERMISSION_SERVICE)


def require_service(request):
    if not manages_service(request):
        deny("此操作需要服务管理员或系统管理员权限", "SERVICE_PERMISSION_REQUIRED")


def manages_finance(request):
    return can_use_management(request)


def scope_projects(request, queryset=None):
    queryset = ServiceProject.objects.all() if queryset is None else queryset
    if not can_use_management(request):
        return queryset.none()
    return queryset


def can_read_project(request, project):
    return scope_projects(request, ServiceProject.objects.filter(pk=project.pk)).exists()


def can_manage_project(request, project):
    return can_use_management(request)


def can_edit_node(request, node):
    assignment = (node.business_data or {}).get("managementAssignment") or {}
    return can_manage_project(request, node.project) or (
        can_use_management(request) and node.enabled
        and any(row["userId"] == request.auth_user_id for row in personnel_members(assignment))
    )


def deny(message="当前账号没有此项操作权限", code="BUSINESS_PERMISSION_REQUIRED"):
    from .services import DomainValidationError
    raise DomainValidationError(message, code=code, status=403)


def require_project(request, project, *, manage=False):
    if not (can_manage_project(request, project) if manage else can_read_project(request, project)):
        deny("没有此项目的管理权限" if manage else "项目不存在或无权访问", "PROJECT_PERMISSION_DENIED")


def require_node(request, node, values=None):
    if not can_edit_node(request, node):
        deny("只能处理本人负责的节点", "PROJECT_NODE_PERMISSION_DENIED")
    # Executors must not change assignment/identity/project data via a JSON draft.
    if values and not can_manage_project(request, node.project):
        business_data = values.get("business_data") or {}
        protected = {"managementAssignment", "projectLeads", "projectInfo", "projectInfoRecords", "midsalesNodeKeys"}
        for key in protected.intersection(business_data):
            if business_data[key] != (node.business_data or {}).get(key):
                deny("人员安排和项目信息只能由项目负责人维护", "PROJECT_ASSIGNMENT_PERMISSION_DENIED")


def project_abilities(request, project):
    manage = can_manage_project(request, project)
    return {"canManage": manage, "canDelete": manage and not project.source_crm_id,
            "canSettle": manages_finance(request)}


def node_abilities(request, node):
    editable = can_edit_node(request, node)
    ended = (node.project.deleted_at or node.project.status in {"completed", "cancelled"}
             or not node.enabled or node.status in {"completed", "skipped"})
    return {"canEdit": bool(editable and not ended), "canAssign": can_manage_project(request, node.project)}
