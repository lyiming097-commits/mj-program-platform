import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from . import mobile_task_views, provider_self_views, views
from .models import AppPermissionRule, ProjectAssignment, ProjectNode, ServiceProject, ServiceProvider


class AuthChannelIsolationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def authenticate(request, user_id: str, channel: str):
        request.auth_user_id = user_id
        request.auth_user_name = user_id
        request.auth_actor_user_id = user_id
        request.auth_actor_name = user_id
        request.auth_is_proxy = False
        request.auth_can_use_system_admin = False
        request.auth_token_claims = {
            "chn": channel,
            "aud": "after-sales-mobile" if channel == "wechat-mini" else "platform",
        }
        return request

    @staticmethod
    def data(response):
        return json.loads(response.content.decode("utf-8"))

    @patch("after_sales_api.views.get_request_app_permission")
    def test_unregistered_wechat_user_is_never_treated_as_management(self, permission):
        request = self.authenticate(
            self.factory.get("/api/after-sales/dashboard"),
            "wxmini:unregistered",
            "wechat-mini",
        )
        denied = views._ensure_app_admin(request)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.data(denied)["code"], "APP_ADMIN_REQUIRED")
        permission.assert_not_called()

    def test_dingtalk_user_cannot_use_provider_self_or_mobile_scope(self):
        provider = ServiceProvider.objects.create(
            auth_user_id="ding-user",
            name="错误绑定人员",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        self_request = self.authenticate(
            self.factory.get("/api/after-sales/providers/me"),
            provider.auth_user_id,
            "dingtalk",
        )
        response = provider_self_views.provider_me(self_request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.data(response)["code"], "WECHAT_ACCOUNT_REQUIRED")

        _provider, denied = views._provider_required(self_request)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.data(denied)["code"], "WECHAT_PROVIDER_REQUIRED")
        _assignment, denied = mobile_task_views._assigned_task(self_request, 1)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.data(denied)["code"], "WECHAT_PROVIDER_REQUIRED")

    def test_wechat_registration_creates_pending_provider(self):
        request = self.authenticate(
            self.factory.post(
                "/api/after-sales/providers/apply",
                data=json.dumps({
                    "name": "新微信服务人员",
                    "phone": "13800000000",
                    "city": "杭州",
                    "role": "installer",
                    "regions": ["杭州"],
                    "skills": ["设备安装"],
                    "bio": "现场服务",
                }),
                content_type="application/json",
            ),
            "wxmini:new-provider",
            "wechat-mini",
        )
        response = provider_self_views.provider_apply(request)
        self.assertEqual(response.status_code, 201, response.content)
        provider = ServiceProvider.objects.get(auth_user_id="wxmini:new-provider")
        self.assertEqual(provider.certification_status, ServiceProvider.CERT_PENDING)
        self.assertEqual(provider.identity_source, ServiceProvider.IDENTITY_WECHAT_MINI)

    @patch("after_sales_api.views.get_request_app_permission", return_value="admin")
    def test_dingtalk_provider_archive_cannot_receive_new_field_assignment(self, _permission):
        provider = ServiceProvider.objects.create(
            auth_user_id="ding-service-user",
            identity_source=ServiceProvider.IDENTITY_DINGTALK,
            name="钉钉历史服务人员",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        project = ServiceProject.objects.create(
            code="DING-SOURCE-001",
            service_type=ServiceProject.TYPE_MIDSALES,
            name="来源隔离项目",
            customer="测试客户",
        )
        node = ProjectNode.objects.create(
            project=project,
            node_key="device-install",
            name="设备安装",
            sequence=1,
        )
        request = self.authenticate(
            self.factory.post(
                f"/api/after-sales/projects/{project.id}/assignments",
                data=json.dumps({"nodeKey": node.node_key, "providerId": provider.id}),
                content_type="application/json",
            ),
            "admin-user",
            "dingtalk",
        )

        request.auth_can_use_system_admin = True
        response = views.project_assignments(request, project.id)

        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(self.data(response)["code"], "PROVIDER_SOURCE_NOT_WECHAT")
        self.assertFalse(ProjectAssignment.objects.filter(project=project, provider=provider).exists())

    @patch("after_sales_api.views.get_request_app_permission", return_value="admin")
    def test_service_team_candidates_only_include_wechat_registrants(self, _permission):
        AppPermissionRule.objects.create(permission="service", scope_type="employee", target_id="admin-user")
        wechat_provider = ServiceProvider.objects.create(
            auth_user_id="wxmini:candidate",
            identity_source=ServiceProvider.IDENTITY_WECHAT_MINI,
            name="微信服务人员",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        ServiceProvider.objects.create(
            auth_user_id="ding-history",
            identity_source=ServiceProvider.IDENTITY_DINGTALK,
            name="钉钉历史人员",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        request = self.authenticate(
            self.factory.get("/api/after-sales/providers?status=certified"),
            "admin-user",
            "dingtalk",
        )

        response = views.providers_collection(request)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            [item["id"] for item in self.data(response)["items"]],
            [wechat_provider.id],
        )

    def test_provider_deactivation_scrubs_profile_and_retains_assignment_history(self):
        provider = ServiceProvider.objects.create(
            auth_user_id="wxmini:delete-provider",
            name="待注销人员",
            phone="13800000000",
            city="杭州",
            regions=["杭州"],
            skills=["设备安装"],
            bio="个人简介",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        project = ServiceProject.objects.create(
            code="DELETE-PROVIDER-001",
            service_type=ServiceProject.TYPE_MIDSALES,
            name="历史任务",
            customer="测试客户",
        )
        node = ProjectNode.objects.create(
            project=project,
            node_key="device-install",
            name="设备安装",
            sequence=1,
        )
        assignment = ProjectAssignment.objects.create(
            project=project,
            node=node,
            provider=provider,
        )
        request = self.authenticate(
            self.factory.delete("/api/after-sales/providers/me"),
            provider.auth_user_id,
            "wechat-mini",
        )

        response = provider_self_views.provider_me(request)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.data(response)["activeAssignmentCount"], 1)
        provider.refresh_from_db()
        self.assertEqual(provider.certification_status, ServiceProvider.CERT_PAUSED)
        self.assertEqual(provider.name, "已注销服务人员")
        self.assertEqual(provider.phone, "")
        self.assertEqual(provider.regions, [])
        self.assertEqual(provider.skills, [])
        self.assertTrue(ProjectAssignment.objects.filter(pk=assignment.pk, provider=provider).exists())
