import json
from importlib import import_module
from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from django.apps import apps
from django.db import connection
from django.urls import resolve
from django.utils import timezone

from . import access, attachment_views, permissions, services, views
from .access_middleware import BusinessAccessMiddleware
from .models import AppConfigurationRevision, AppPermissionRule, FieldFeedback, PrivateAttachment, ProjectNode, Reward, ServiceProject, ServiceProvider, ServiceTicket
from .tests import CleanDomainMixin


class BusinessAccessTests(CleanDomainMixin, TestCase):
    def setUp(self):
        self.clear_domain()
        self.factory = RequestFactory()
        self.project = ServiceProject.objects.create(
            code="ACL-1", name="负责项目", customer="客户", service_type="presales",
            owner_user_id="owner", current_node_key="early-plan",
        )
        self.node = ProjectNode.objects.create(
            project=self.project, node_key="early-plan", name="前期方案", kind="delivery",
            sequence=1, status="active", business_data={"managementAssignment": {"userId": "executor"}},
        )
        self.other_node = ProjectNode.objects.create(
            project=self.project, node_key="budget-match", name="预算匹配", kind="delivery",
            sequence=2, status="active", business_data={"managementAssignment": {"userId": "another"}},
        )
        self.other_project = ServiceProject.objects.create(
            code="ACL-2", name="无关项目", customer="其他客户", service_type="midsales", owner_user_id="another",
        )

    def request(self, path="/api/after-sales/projects", method="get", payload=None, user="outsider", **identity):
        request = getattr(self.factory, method)(path, data=json.dumps(payload or {}), content_type="application/json") if method != "get" else self.factory.get(path)
        request.auth_user_id = user
        request.auth_user_name = user
        request.auth_actor_user_id = identity.get("actor", user)
        request.auth_actor_name = request.auth_actor_user_id
        request.auth_is_proxy = request.auth_actor_user_id != user
        request.auth_can_use_system_admin = identity.get("superuser", False)
        request.auth_token_claims = {"chn": identity.get("channel", "dingtalk")}
        return request

    def grant(self, user, *roles):
        for role in roles:
            AppPermissionRule.objects.create(permission=role, scope_type="employee", target_id=user)

    def call(self, request):
        match = resolve(request.path)
        request.resolver_match = match
        denied = BusinessAccessMiddleware(lambda request: None).process_view(request, match.func, match.args, match.kwargs)
        return denied if denied is not None else match.func(request, *match.args, **match.kwargs)

    def test_admin_includes_every_application_ability(self):
        self.grant("admin", "admin")
        request = self.request(user="admin")
        self.assertTrue(access.manages_business(request))
        self.assertTrue(access.manages_finance(request))
        self.assertTrue(access.can_manage_project(request, self.other_project))
        self.assertIsNone(views._ensure_settings_admin(request))
        data = json.loads(views.session(request).content)
        for key in ("canManageApp", "canCreateProjects", "canManageSettings", "canManageBusiness", "canManageService", "canManageSettlements"):
            self.assertTrue(data[key])

    def test_roles_stack_without_inheriting_administration(self):
        self.grant("both", "service", "sales")
        request = self.request(user="both")
        self.assertTrue(access.manages_business(request))
        self.assertTrue(access.manages_finance(request))
        self.assertEqual(views._ensure_settings_admin(request).status_code, 403)
        self.assertEqual(permissions.get_request_app_permissions(request), {"service", "sales"})

    def test_exclusion_is_per_role_and_overrides_direct_grants(self):
        self.grant("both", "service", "sales")
        AppPermissionRule.objects.create(permission="service", scope_type="excludedEmployee", target_id="both")
        self.assertEqual(permissions.get_user_app_permissions("both"), {"sales"})

    @patch("after_sales_api.permissions.get_auth_user_department_scope", return_value={
        "directDepartmentIds": {"20"}, "ancestorDepartmentIds": {"10", "20"},
    })
    def test_department_subtree_direct_department_and_exclusion(self, scope):
        AppPermissionRule.objects.create(permission="service", scope_type="departmentSub", target_id="10")
        AppPermissionRule.objects.create(permission="sales", scope_type="department", target_id="10")
        self.assertEqual(permissions.get_user_app_permissions("worker"), {"service"})
        AppPermissionRule.objects.create(permission="service", scope_type="excludedEmployee", target_id="worker")
        self.grant("worker", "service", "sales")
        self.assertEqual(permissions.get_user_app_permissions("worker"), {"sales"})

    def test_proxy_uses_effective_user_and_preserves_target_admin(self):
        self.grant("actor", "admin")
        self.assertFalse(access.manages_business(self.request(user="outsider", actor="actor")))
        self.grant("target", "admin")
        self.assertTrue(access.manages_finance(self.request(user="target", actor="actor")))
        self.assertTrue(access.manages_finance(self.request(user="target", actor="actor", superuser=True)))

    def test_wechat_cannot_acquire_management_by_application_grant(self):
        self.grant("wechat", "admin")
        request = self.request(user="wechat", channel="wechat-mini", superuser=True)
        self.assertEqual(permissions.get_request_app_permissions(request), set())
        self.assertFalse(access.manages_business(request))
        self.assertEqual(views._ensure_app_admin(request).status_code, 403)

    def test_project_relationships_do_not_grant_module_access(self):
        self.other_project.created_by = "outsider"
        self.other_project.save()
        for user in ("owner", "executor", "outsider"):
            with self.subTest(user=user):
                request = self.request(user=user)
                self.assertFalse(access.can_use_management(request))
                self.assertFalse(access.scope_projects(request).exists())
                self.assertFalse(access.can_read_project(request, self.project))
                data = json.loads(self.call(self.request("/api/after-sales/session/", user=user)).content)
                self.assertFalse(data["canManageApp"])
                self.assertFalse(data["canCreateProjects"])
                self.assertEqual(data["appPermissions"], [])
                response = self.call(self.request(user=user))
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(json.loads(response.content)["code"], "APP_ACCESS_DENIED")

    def test_ungranted_owner_and_executor_cannot_edit_even_their_own_work(self):
        self.assertFalse(access.can_manage_project(self.request(user="owner"), self.project))
        self.assertFalse(access.can_manage_project(self.request(user="executor"), self.project))
        for user in ("owner", "executor"):
            self.assertFalse(access.can_edit_node(self.request(user=user), self.node))
            for key in ("early-plan", "budget-match"):
                response = self.call(self.request(
                    f"/api/after-sales/projects/{self.project.id}/nodes/{key}", "patch",
                    {"businessData": {"deliveryNote": "执行进展"}}, user=user,
                ))
                self.assertEqual(response.status_code, 403, response.content)
        self.node.refresh_from_db()
        self.assertNotIn("deliveryNote", self.node.business_data)

    def test_ungranted_management_users_cannot_read_or_write_any_business_api(self):
        for path, method in (
            ("/api/after-sales/dashboard", "get"),
            ("/api/after-sales/projects", "post"),
            (f"/api/after-sales/projects/{self.project.id}", "get"),
            ("/api/after-sales/employees/directory", "get"),
            ("/api/after-sales/product-catalog", "get"),
            ("/api/after-sales/providers", "get"),
            ("/api/after-sales/providers/me", "get"),
            ("/api/after-sales/providers/apply", "post"),
            ("/api/after-sales/tickets", "get"),
            ("/api/after-sales/feedback", "get"),
            ("/api/after-sales/ratings", "get"),
            ("/api/after-sales/rewards", "get"),
            ("/api/after-sales/reward-prizes", "get"),
            ("/api/after-sales/resources", "get"),
            ("/api/after-sales/attachments?source=mobile", "get"),
            ("/api/after-sales/attachments/1/download", "get"),
            ("/api/after-sales/attachments", "post"),
            ("/api/after-sales/messages", "get"),
            ("/api/after-sales/settlements", "get"),
            ("/api/after-sales/permissions", "get"),
            ("/api/after-sales/mobile/v1/home", "get"),
        ):
            with self.subTest(path=path, method=method):
                response = self.call(self.request(path, method, user="owner"))
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(json.loads(response.content)["code"], "APP_ACCESS_DENIED")
        self.assertEqual(ServiceProject.objects.count(), 2)

    def test_any_of_the_three_roles_grants_admission_without_promoting_other_roles(self):
        for role in ("admin", "service", "sales"):
            self.grant(role, role)
            response = self.call(self.request("/api/after-sales/session/", user=role))
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertTrue(data["canManageApp"])
            self.assertEqual(data["appPermissions"], [role])
            self.assertEqual(data["canManageSettings"], role == "admin")
            self.assertTrue(data["canManageBusiness"])
            self.assertTrue(data["canManageSettlements"])
            self.assertEqual(data["canManageService"], role in {"admin", "service"})

    def test_executor_cannot_change_assignment_by_autosave_or_manage_project(self):
        for payload in ({"managementAssignment": {"userId": "outsider"}}, {"projectInfoRecords": {"early-approval": {}}}):
            response = self.call(self.request(
                f"/api/after-sales/projects/{self.project.id}/nodes/early-plan", "patch",
                {"businessData": payload}, user="executor",
            ))
            self.assertEqual(response.status_code, 403, response.content)
        for path in (f"/api/after-sales/projects/{self.project.id}", f"/api/after-sales/projects/{self.project.id}/assignments"):
            response = self.call(self.request(path, "patch" if path.endswith(str(self.project.id)) else "post", {}, user="executor"))
            self.assertEqual(response.status_code, 403, response.content)

    def test_sales_and_service_roles_can_manage_projects_and_settle(self):
        self.grant("sales", "sales")
        self.grant("service", "service")
        self.assertTrue(access.can_read_project(self.request(user="sales"), self.project))
        self.assertTrue(access.can_edit_node(self.request(user="sales"), self.node))
        response = self.call(self.request(
            f"/api/after-sales/projects/{self.project.id}/nodes/early-plan", "patch", {}, user="sales",
        ))
        self.assertEqual(response.status_code, 200, response.content)
        for user in ("owner", "executor", "outsider"):
            self.assertEqual(self.call(self.request("/api/after-sales/settlements", user=user)).status_code, 403)
        self.assertEqual(self.call(self.request("/api/after-sales/settlements", user="service")).status_code, 200)
        self.assertEqual(self.call(self.request("/api/after-sales/settlements", user="sales")).status_code, 200)

    def test_global_operations_require_business_permission(self):
        for path, payload in (("/api/after-sales/rewards", {}), ("/api/after-sales/providers/1", {"certificationStatus": "certified"})):
            for user in ("owner", "executor", "outsider"):
                response = self.call(self.request(path, "patch" if "providers/" in path else "post", payload, user=user))
                self.assertEqual(response.status_code, 403)

    def test_sales_can_read_tickets_and_feedback(self):
        self.grant("sales", "sales")
        for path in ("/api/after-sales/tickets", "/api/after-sales/feedback"):
            response = self.call(self.request(path, user="sales"))
            self.assertEqual(response.status_code, 200, response.content)

    def test_sales_can_create_ticket_and_review_feedback_but_cannot_configure_rewards(self):
        self.grant("sales", "sales")
        response = self.call(self.request("/api/after-sales/tickets", "post", {
            "projectId": self.project.id, "title": "现场问题", "ticketType": "设备故障", "description": "需要排查",
        }, user="sales"))
        self.assertEqual(response.status_code, 201, response.content)
        provider = ServiceProvider.objects.create(auth_user_id="wxmini:feedback", name="反馈人员")
        feedback = FieldFeedback.objects.create(
            project=self.project, provider=provider, feedback_type=FieldFeedback.TYPE_RESOURCE, content="资料建议",
        )
        response = self.call(self.request(f"/api/after-sales/feedback/{feedback.id}/review", "post", {
            "status": "accepted", "reward": {"amount": "200", "rewardType": "cash"},
        }, user="sales"))
        self.assertEqual(response.status_code, 403, response.content)
        self.assertFalse(Reward.objects.filter(feedback=feedback).exists())
        feedback.refresh_from_db()
        self.assertEqual(feedback.status, "submitted")
        response = self.call(self.request(f"/api/after-sales/feedback/{feedback.id}/review", "post", {
            "status": "accepted", "reviewNote": "已采纳",
        }, user="sales"))
        self.assertEqual(response.status_code, 200, response.content)
        feedback.refresh_from_db()
        self.assertEqual(feedback.status, "accepted")

    def test_sales_team_is_read_only_and_service_pages_are_denied(self):
        self.grant("sales", "sales")
        provider = ServiceProvider.objects.create(
            auth_user_id="wxmini:pending", name="待审人员", certification_status="pending",
            identity_source=ServiceProvider.IDENTITY_WECHAT_MINI,
        )
        attachment = PrivateAttachment.objects.create(
            target_type=PrivateAttachment.TARGET_PROVIDER_APPLICATION, target_id=provider.id,
            original_name="资质.pdf", mime_type="application/pdf", size=10, file="unused.pdf",
        )
        for path in ("/api/after-sales/providers", f"/api/after-sales/providers/{provider.id}",
                     f"/api/after-sales/attachments?targetType=provider_application&targetId={provider.id}"):
            response = self.call(self.request(path, user="sales"))
            self.assertEqual(response.status_code, 200, response.content)
        items = json.loads(response.content)["items"]
        self.assertEqual(items[0]["id"], attachment.id)
        self.assertFalse(items[0]["canDelete"])
        response = self.call(self.request(f"/api/after-sales/providers/{provider.id}", "patch",
                                          {"certificationStatus": "certified"}, user="sales"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["code"], "SERVICE_PERMISSION_REQUIRED")
        provider.refresh_from_db()
        self.assertEqual(provider.certification_status, "pending")
        for path in ("/api/after-sales/rewards", "/api/after-sales/reward-prizes/options"):
            response = self.call(self.request(path, user="sales"))
            self.assertEqual(response.status_code, 403, response.content)
            self.assertEqual(json.loads(response.content)["code"], "SERVICE_PERMISSION_REQUIRED")
        for path in ("/api/after-sales/permissions", "/api/after-sales/permissions/directory", "/api/after-sales/reward-prizes"):
            self.assertEqual(self.call(self.request(path, user="sales")).status_code, 403)

    def test_service_admin_can_audit_team_and_use_service_pages_without_settings(self):
        self.grant("service", "service")
        provider = ServiceProvider.objects.create(auth_user_id="wxmini:audit", name="待审人员", certification_status="pending")
        response = self.call(self.request(f"/api/after-sales/providers/{provider.id}", "patch",
                                          {"certificationStatus": "certified"}, user="service"))
        self.assertEqual(response.status_code, 200, response.content)
        provider.refresh_from_db()
        self.assertEqual(provider.certification_status, "certified")
        for path in ("/api/after-sales/tickets", "/api/after-sales/feedback", "/api/after-sales/rewards",
                     "/api/after-sales/reward-prizes/options", "/api/after-sales/settlements"):
            response = self.call(self.request(path, user="service"))
            self.assertEqual(response.status_code, 200, response.content)
        for path in ("/api/after-sales/permissions", "/api/after-sales/permissions/directory", "/api/after-sales/reward-prizes"):
            self.assertEqual(self.call(self.request(path, user="service")).status_code, 403)

    def test_legacy_role_migration_preserves_sources_exclusions_and_invalidates_drafts(self):
        rows = [
            AppPermissionRule.objects.create(permission=role, scope_type=scope, target_id=target)
            for role, scope, target in (
                ("admin", "employee", "admin"), ("business", "departmentSub", "10"),
                ("business", "excludedEmployee", "worker"), ("finance", "employee", "worker"),
            )
        ]
        state = AppConfigurationRevision.objects.create(key="permissions", revision=7)
        migration = import_module("after_sales_api.migrations.0029_management_roles")
        editor = SimpleNamespace(connection=connection)
        migration.forwards(apps, editor)
        self.assertEqual(list(AppPermissionRule.objects.filter(pk__in=[row.pk for row in rows]).order_by("id").values_list(
            "permission", "scope_type", "target_id",
        )), [("admin", "employee", "admin"), ("service", "departmentSub", "10"),
             ("service", "excludedEmployee", "worker"), ("sales", "employee", "worker")])
        self.assertEqual(permissions.get_user_app_permissions("worker"), {"sales"})
        state.refresh_from_db()
        self.assertEqual(state.revision, 8)
        migration.backwards(apps, editor)
        self.assertEqual(set(AppPermissionRule.objects.values_list("permission", flat=True)), {"admin", "business", "finance"})

    def test_attachment_delete_button_matches_actual_business_scope(self):
        ticket = ServiceTicket.objects.create(
            code="ACL-ATTACHMENT", project=self.project, title="工单资料", ticket_type="问题",
            owner_user_id="handler", reporter_user_id="reporter",
        )
        item = PrivateAttachment.objects.create(
            target_type=PrivateAttachment.TARGET_TICKET, target_id=ticket.id,
            original_name="说明.pdf", mime_type="application/pdf", size=10, file="unused-test-file.pdf",
        )
        self.grant("sales", "sales")
        self.grant("service", "service")
        for user, status, allowed in (("owner", 403, False), ("handler", 403, False),
                                      ("executor", 403, False), ("sales", 200, True), ("service", 200, True)):
            response = self.call(self.request(
                f"/api/after-sales/attachments?targetType=ticket&targetId={ticket.id}", user=user,
            ))
            self.assertEqual(response.status_code, status, response.content)
            if status == 200:
                self.assertEqual(json.loads(response.content)["items"][0]["canDelete"], allowed, user)
        self.assertTrue(PrivateAttachment.objects.filter(pk=item.pk).exists())

    def test_local_project_creation_keeps_creator_as_owner(self):
        self.grant("outsider", "service")
        response = self.call(self.request("/api/after-sales/projects", "post", {
            "serviceType": "presales", "name": "自建项目", "customer": "本地客户", "ownerUserId": "someone-else",
        }))
        self.assertEqual(response.status_code, 201, response.content)
        item = json.loads(response.content)["item"]
        self.assertEqual(item["ownerUserId"], "outsider")
        self.assertTrue(item["permissions"]["canManage"])

    def test_attachments_follow_project_and_node_scope(self):
        for user, node, write, expected in (
            ("owner", self.other_node, True, False), ("executor", self.node, True, False),
            ("executor", self.other_node, False, False), ("executor", self.other_node, True, False),
            ("outsider", self.node, False, False),
        ):
            _target, _is_management, failure = attachment_views._target_access(
                self.request(user=user), PrivateAttachment.TARGET_PROJECT_NODE, node.id, write=write,
            )
            self.assertEqual(failure is None, expected, (user, write, failure))

    def test_admin_cannot_edit_completed_node_without_reopening(self):
        self.grant("admin", "admin")
        self.node.status = "completed"
        self.node.save()
        response = self.call(self.request(
            f"/api/after-sales/projects/{self.project.id}/nodes/early-plan", "patch",
            {"businessData": {"deliveryNote": "越过只读"}}, user="admin",
        ))
        self.assertEqual(response.status_code, 409, response.content)

    def test_ticket_assignment_does_not_grant_module_access(self):
        ticket = ServiceTicket.objects.create(
            code="ACL-TICKET", project=self.project, title="工单", ticket_type="问题",
            owner_user_id="handler", reporter_user_id="reporter", status="assigned",
        )
        self.assertFalse(access.can_read_project(self.request(user="handler"), self.project))
        response = self.call(self.request(f"/api/after-sales/tickets/{ticket.id}", "patch", {"ownerUserId": "outsider"}, user="handler"))
        self.assertEqual(response.status_code, 403)
        response = self.call(self.request(f"/api/after-sales/tickets/{ticket.id}/transition", "post", {"status": "in_progress"}, user="handler"))
        self.assertEqual(response.status_code, 403, response.content)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "assigned")

    @patch("after_sales_api.views.assert_crm_project_access", side_effect=services.DomainValidationError("CRM 无权访问", code="CRM_DENIED", status=403))
    def test_application_admin_does_not_bypass_crm_authorization(self, check):
        self.grant("admin", "admin")
        self.project.source_crm_id = "CRM-private"
        self.project.save()
        _project, _provider, _admin, failure = views._project_access(self.request(user="admin"), self.project.id)
        self.assertEqual(failure.status_code, 403)
        self.assertEqual(json.loads(failure.content)["code"], "CRM_DENIED")

    @patch("after_sales_api.views.get_auth_organization_snapshot", return_value=(
        [{"deptId": "10", "name": "技术部"}],
        [{"userId": "admin", "name": "管理员", "status": "active", "accountStatus": "enabled"},
         {"userId": "both", "name": "业务财务兼任", "status": "active", "accountStatus": "enabled"}], 7,
    ))
    def test_multi_role_save_is_atomic_and_checks_both_revisions(self, _snapshot):
        self.grant("admin", "admin")
        AppConfigurationRevision.objects.create(key="permissions", revision=3)
        payload = {"revision": "3", "orgRevision": "7", "items": [
            {"permission": "admin", "scopeType": "employee", "targetId": "admin"},
            {"permission": "service", "scopeType": "departmentSub", "targetId": "10"},
            {"permission": "sales", "scopeType": "employee", "targetId": "both"},
            {"permission": "service", "scopeType": "excludedEmployee", "targetId": "both"},
        ]}
        path = "/api/after-sales/permissions"
        for changed, code in (({"revision": "2"}, "REVISION_CONFLICT"), ({"orgRevision": "6"}, "ORG_REVISION_CONFLICT")):
            response = self.call(self.request(path, "post", {**payload, **changed}, user="admin"))
            self.assertEqual(response.status_code, 409, response.content)
            self.assertEqual(json.loads(response.content)["code"], code)
            self.assertEqual(AppPermissionRule.objects.count(), 1)
        response = self.call(self.request(path, "post", payload, user="admin"))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(json.loads(response.content)["items"]), 4)
        self.assertEqual(json.loads(response.content)["revision"], "4")
        self.assertEqual(permissions.get_user_app_permissions("both"), {"sales"})

    def test_permission_revocation_applies_on_next_request(self):
        self.grant("manager", "service", "sales")
        self.assertTrue(access.manages_business(self.request(user="manager")))
        AppPermissionRule.objects.filter(target_id="manager", permission="service").delete()
        response = self.call(self.request("/api/after-sales/providers/1", "patch", {}, user="manager"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.call(self.request("/api/after-sales/settlements", user="manager")).status_code, 200)
        self.assertTrue(json.loads(self.call(self.request("/api/after-sales/session/", user="manager")).content)["canManageApp"])
        self.project.owner_user_id = "manager"
        self.project.save()
        AppPermissionRule.objects.filter(target_id="manager").delete()
        self.assertFalse(json.loads(self.call(self.request("/api/after-sales/session/", user="manager")).content)["canManageApp"])
        self.assertEqual(self.call(self.request(user="manager")).status_code, 403)

    def test_business_overview_monitors_visible_risks_without_claiming_all_tasks(self):
        ProjectNode.objects.create(
            project=self.other_project, node_key="device-install", name="设备安装", sequence=1,
            status="active", planned_end_at=timezone.now() - timedelta(days=1),
        )
        for role in ("service", "admin"):
            self.grant(role, role)
            response = self.call(self.request("/api/after-sales/dashboard", user=role))
            self.assertEqual(response.status_code, 200, response.content)
            data = json.loads(response.content)
            self.assertEqual(data["scope"], "business")
            self.assertEqual(data["metrics"]["projects"], ServiceProject.objects.filter(deleted_at__isnull=True).count())
            self.assertEqual(data["taskTotal"], 0)
            self.assertEqual(data["alertTotal"], 1)
            self.assertEqual(data["alerts"][0]["projectId"], self.other_project.id)
        self.other_project.created_by = "outsider"
        self.other_project.save()
        response = self.call(self.request("/api/after-sales/dashboard"))
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("metrics", json.loads(response.content))
