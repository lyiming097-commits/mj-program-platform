"""Every management API checks role/object scope before executing its view.

Lists additionally filter at the queryset layer; attachment access is checked
against its target. Keeping route policy here avoids role checks drifting
between old management endpoints and new ones.
"""
import json

from django.http import JsonResponse

from . import access
from .models import FieldFeedback, ProjectNode, ServiceProject, ServiceResource, ServiceTicket
from .org_client import AuthOrgClientError
from .project_personnel import management_member_q
from .services import DomainValidationError


class BusinessAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.path.startswith("/api/after-sales/") or not access.management_user(request):
            return None
        try:
            self.check(request, request.resolver_match.url_name, view_kwargs)
        except (DomainValidationError, AuthOrgClientError) as exc:
            return JsonResponse({"ok": False, "error": str(exc),
                                 "code": getattr(exc, "code", "AUTH_ORG_UNAVAILABLE")},
                                status=getattr(exc, "status", getattr(exc, "status_code", 503)))

    def check(self, request, name, kwargs):
        if name in {"session", "app-health", "app-health-live", "app-health-ready",
                    "public-demo", "public-provider-tags"}:
            return
        access.require_management(request)
        write = request.method not in {"GET", "HEAD", "OPTIONS"}
        if name in {"settlements", "settlement-item", "settlement-sources", "settlement-companies", "settlement-projects"}:
            if not access.manages_finance(request):
                access.deny("当前账号没有结算中心使用权限", "FINANCE_PERMISSION_REQUIRED")
            return
        if (name in {"rewards", "reward-transition", "reward-prize-options"}
                or (name in {"providers", "provider-item", "capability-catalog"} and write)):
            access.require_service(request)
        payload = {}
        if write and request.content_type == "application/json":
            try:
                payload = json.loads(request.body)
            except (ValueError, UnicodeDecodeError):
                return  # The view reports malformed JSON.
            if not isinstance(payload, dict):
                return
        project = None
        project_id = kwargs.get("project_id")
        if project_id is not None:
            project = ServiceProject.objects.filter(pk=project_id).first()
            if project is None:
                return
            access.require_project(request, project)
            if write:
                if name in {"project-node-autosave", "project-submit-version", "project-node-related-products",
                            "project-round-action", "project-start", "project-advance"}:
                    key = kwargs.get("node_key") or payload.get("nodeKey") or project.current_node_key
                    node = ProjectNode.objects.filter(project=project, node_key=key).first()
                    if node is not None:
                        access.require_node(request, node, {"business_data": payload.get("businessData") or {}})
                elif name not in {"project-messages", "project-messages-read"}:
                    access.require_project(request, project, manage=True)
                elif not access.can_manage_project(request, project) and not project.nodes.filter(
                    management_member_q(request.auth_user_id), enabled=True,
                ).exists():
                    access.deny("当前账号仅可查看项目资料")
        if "ticket_id" in kwargs:
            ticket = ServiceTicket.objects.select_related("project").filter(pk=kwargs["ticket_id"]).first()
            if ticket is not None:
                access.require_project(request, ticket.project)
                if write and not access.can_manage_project(request, ticket.project):
                    if name == "ticket-messages" and request.auth_user_id in {ticket.reporter_user_id, ticket.owner_user_id}:
                        pass
                    elif ticket.owner_user_id != request.auth_user_id:
                        access.deny("只能处理本人负责的工单")
                    if {"ownerUserId", "ownerName"}.intersection(payload):
                        access.deny("只有项目负责人可以更换工单处理人")
        if name == "feedback-review":
            feedback = FieldFeedback.objects.select_related("project").filter(pk=kwargs["feedback_id"]).first()
            if feedback is not None:
                access.require_project(request, feedback.project)
        if name in {"tickets", "feedback", "ratings", "resources", "rewards"} and write:
            project_id = payload.get("projectId")
            if project_id:
                if not str(project_id).isdigit():
                    return
                project = ServiceProject.objects.filter(pk=project_id).first()
                if project is not None:
                    access.require_project(request, project)
                    if name in {"tickets", "feedback"} and not access.scope_projects(
                        request, ServiceProject.objects.filter(pk=project.pk),
                    ).exists():
                        access.deny("当前账号仅可查看项目资料")
                    if name == "ratings" or (name == "tickets" and payload.get("ownerUserId")) or name == "resources":
                        access.require_project(request, project, manage=True)
            elif name == "resources" and not access.manages_business(request):
                access.deny("只有业务管理可以维护公共资料")
        if name == "resource-item":
            resource = ServiceResource.objects.select_related("project").filter(pk=kwargs["resource_id"]).first()
            if resource is not None:
                if resource.project_id:
                    access.require_project(request, resource.project, manage=write)
                elif write and not access.manages_business(request):
                    access.deny("只有业务管理可以维护公共资料")
                if write and payload.get("projectId") and str(payload["projectId"]).isdigit():
                    target = ServiceProject.objects.filter(pk=payload["projectId"]).first()
                    if target is not None:
                        access.require_project(request, target, manage=True)
