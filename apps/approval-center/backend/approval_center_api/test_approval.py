from __future__ import annotations

import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from . import approval_views, views
from .models import (
    ApprovalApplication,
    ApprovalCategory,
    ApprovalCategoryPermission,
    ApprovalDraft,
    ApprovalEvent,
    ApprovalTask,
    ApprovalTemplate,
    ApprovalTemplateVersion,
)
from .org_client import AuthOrgClientError


class ApprovalApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.permission_patcher = patch.object(
            approval_views,
            "get_request_app_permission",
            side_effect=lambda request: "admin" if request.auth_user_id == "admin" else "",
        )
        self.permission_patcher.start()
        self.addCleanup(self.permission_patcher.stop)
        self.directory_patcher = patch.object(
            approval_views,
            "get_auth_organization_snapshot",
            return_value=([], [
                {"userId": "admin", "name": "系统管理员"},
                {"userId": "initiator", "name": "申请人"},
                {"userId": "approver-1", "name": "审批人甲"},
                {"userId": "approver-2", "name": "审批人乙"},
                {"userId": "approver-3", "name": "审批人丙"},
                {"userId": "cc-user", "name": "抄送人"},
                {"userId": "other", "name": "其他员工"},
            ], 1),
        )
        self.directory_patcher.start()
        self.addCleanup(self.directory_patcher.stop)

    def request(
        self,
        method,
        path,
        payload=None,
        *,
        user="initiator",
        query=None,
        actor=None,
        proxy=False,
    ):
        kwargs = {}
        if payload is not None:
            kwargs.update(
                data=json.dumps(payload, ensure_ascii=False),
                content_type="application/json",
            )
        if method.lower() == "get":
            request = self.factory.get(path, data=query or {})
        else:
            request = getattr(self.factory, method.lower())(path, **kwargs)
        names = {
            "admin": "系统管理员",
            "initiator": "申请人",
            "approver-1": "审批人甲",
            "approver-2": "审批人乙",
            "approver-3": "审批人丙",
            "cc-user": "抄送人",
            "other": "其他员工",
        }
        request.auth_user_id = user
        request.auth_user_name = names.get(user, user)
        actor = actor or user
        request.auth_actor_user_id = actor
        request.auth_actor_name = names.get(actor, actor)
        request.auth_is_proxy = proxy
        request.auth_can_use_system_admin = user == "admin"
        return request

    @staticmethod
    def data(response):
        return json.loads(response.content.decode("utf-8"))

    @staticmethod
    def template_payload(*, nodes=None, fields=None, name="付款申请"):
        return {
            "name": name,
            "description": "供应商付款审批",
            "category": "财务",
            "icon": "WalletCards",
            "color": "#1677ff",
            "formSchema": {
                "fields": fields or [
                    {"key": "reason", "type": "textarea", "label": "付款事由", "required": True},
                    {"key": "amount", "type": "amount", "label": "付款金额", "required": True},
                ],
            },
            "flowSchema": {
                "nodes": nodes or [
                    {
                        "key": "manager",
                        "type": "approver",
                        "name": "部门主管",
                        "assigneeIds": ["approver-1"],
                        "assigneeNames": {"approver-1": "审批人甲"},
                        "approvalMode": "all",
                    },
                    {
                        "key": "finance",
                        "type": "approver",
                        "name": "财务审核",
                        "assigneeIds": ["approver-2"],
                        "assigneeNames": {"approver-2": "审批人乙"},
                        "approvalMode": "all",
                    },
                    {
                        "key": "notify",
                        "type": "cc",
                        "name": "结果抄送",
                        "assigneeIds": ["cc-user"],
                        "assigneeNames": {"cc-user": "抄送人"},
                    },
                ],
            },
            "settings": {"allowWithdraw": True},
        }

    def create_template(self, *, nodes=None, fields=None, name="付款申请", publish=True):
        response = approval_views.templates_collection(self.request(
            "post",
            "/api/approval-center/templates",
            self.template_payload(nodes=nodes, fields=fields, name=name),
            user="admin",
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        template = ApprovalTemplate.objects.get(pk=self.data(response)["item"]["id"])
        if publish:
            response = approval_views.template_publish(
                self.request(
                    "post",
                    f"/api/approval-center/templates/{template.pk}/publish",
                    {"revision": str(template.revision), "releaseNote": "首版"},
                    user="admin",
                ),
                template.pk,
            )
            self.assertEqual(response.status_code, 200, self.data(response))
            template.refresh_from_db()
        return template

    def create_application(self, template, *, user="initiator", values=None):
        response = approval_views.applications_collection(self.request(
            "post",
            "/api/approval-center/applications",
            {
                "templateId": template.pk,
                "title": "9 月供应商付款",
                "values": values or {"reason": "采购款", "amount": "18000.50"},
                "departmentId": "12",
                "departmentName": "采购部",
            },
            user=user,
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        return ApprovalApplication.objects.get(pk=self.data(response)["item"]["id"])

    def action(
        self,
        application,
        action,
        *,
        user,
        comment="",
        revision=None,
        task_id=None,
        actor=None,
        proxy=False,
    ):
        payload = {
            "comment": comment,
            "revision": str(revision if revision is not None else application.revision),
        }
        if task_id is not None:
            payload["taskId"] = task_id
        return approval_views.application_action(
            self.request(
                "post",
                f"/api/approval-center/applications/{application.pk}/{action}",
                payload,
                user=user,
                actor=actor,
                proxy=proxy,
            ),
            application.pk,
            action,
        )

    def test_only_admin_can_create_publish_and_manage_templates(self):
        denied = approval_views.templates_collection(self.request(
            "post",
            "/api/approval-center/templates",
            self.template_payload(),
        ))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.data(denied)["code"], "APP_ADMIN_REQUIRED")

        template = self.create_template(publish=False)
        self.assertEqual(template.status, ApprovalTemplate.STATUS_DRAFT)
        published = approval_views.template_publish(
            self.request(
                "post",
                f"/api/approval-center/templates/{template.pk}/publish",
                {"revision": "1"},
                user="admin",
            ),
            template.pk,
        )
        self.assertEqual(published.status_code, 200, self.data(published))
        template.refresh_from_db()
        self.assertEqual(template.status, ApprovalTemplate.STATUS_PUBLISHED)
        self.assertEqual(template.versions.count(), 1)

    def test_publish_rejects_invalid_form_and_flow(self):
        template = self.create_template(publish=False)
        template.form_schema = {
            "fields": [{"key": "reason", "type": "textarea", "label": "付款事由", "required": True}],
        }
        template.flow_schema = {"nodes": []}
        template.save(update_fields=["form_schema", "flow_schema"])
        response = approval_views.template_publish(
            self.request("post", f"/templates/{template.pk}/publish", {}, user="admin"),
            template.pk,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.data(response)["code"], "INVALID_FLOW_SCHEMA")
        self.assertEqual(ApprovalTemplateVersion.objects.count(), 0)

    def test_publish_rejects_invalid_choice_fields_and_unknown_assignees(self):
        empty_choice = self.create_template(
            publish=False,
            fields=[{
                "key": "payment_type",
                "type": "radio",
                "label": "付款类型",
                "required": True,
                "options": [],
            }],
        )
        response = approval_views.template_publish(
            self.request("post", f"/templates/{empty_choice.pk}/publish", {}, user="admin"),
            empty_choice.pk,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.data(response)["code"], "INVALID_FORM_SCHEMA")

        unknown_assignee = self.create_template(
            publish=False,
            nodes=[{
                "key": "ghost",
                "type": "approver",
                "name": "审批节点",
                "assigneeIds": ["ghost-user"],
            }],
        )
        response = approval_views.template_publish(
            self.request("post", f"/templates/{unknown_assignee.pk}/publish", {}, user="admin"),
            unknown_assignee.pk,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.data(response)["code"], "INVALID_FLOW_ASSIGNEE")
        self.assertEqual(ApprovalTemplateVersion.objects.count(), 0)

    def test_publish_fails_closed_and_uses_canonical_assignee_names(self):
        template = self.create_template(publish=False)
        with patch.object(
            approval_views,
            "get_auth_organization_snapshot",
            side_effect=AuthOrgClientError("组织服务不可用", 503),
        ):
            unavailable = approval_views.template_publish(
                self.request("post", f"/templates/{template.pk}/publish", {}, user="admin"),
                template.pk,
            )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(self.data(unavailable)["code"], "AUTH_ORG_UNAVAILABLE")
        self.assertEqual(template.versions.count(), 0)

        canonical_employees = [
            {"userId": "approver-1", "name": "审批人甲（组织架构）"},
            {"userId": "approver-2", "name": "审批人乙"},
            {"userId": "cc-user", "name": "抄送人"},
        ]
        with patch.object(
            approval_views,
            "get_auth_organization_snapshot",
            return_value=([], canonical_employees, 2),
        ):
            published = approval_views.template_publish(
                self.request("post", f"/templates/{template.pk}/publish", {}, user="admin"),
                template.pk,
            )
        self.assertEqual(published.status_code, 200, self.data(published))
        template.refresh_from_db()
        first_node = template.published_version.flow_schema["nodes"][0]
        self.assertEqual(first_node["assigneeNames"]["approver-1"], "审批人甲（组织架构）")

    def test_published_version_is_immutable_for_existing_applications(self):
        template = self.create_template()
        first_version = template.published_version
        application = self.create_application(template)

        response = approval_views.template_item(
            self.request(
                "patch",
                f"/templates/{template.pk}",
                {
                    "revision": str(template.revision),
                    "name": "供应商付款申请",
                    "formSchema": {
                        "fields": [
                            {"key": "reason", "type": "textarea", "label": "用途", "required": True},
                            {"key": "amount", "type": "amount", "label": "金额", "required": True},
                        ],
                    },
                },
                user="admin",
            ),
            template.pk,
        )
        self.assertEqual(response.status_code, 200, self.data(response))
        template.refresh_from_db()
        self.assertTrue(self.data(response)["item"]["hasUnpublishedChanges"])

        response = approval_views.template_publish(
            self.request(
                "post",
                f"/templates/{template.pk}/publish",
                {"revision": str(template.revision), "releaseNote": "字段改名"},
                user="admin",
            ),
            template.pk,
        )
        self.assertEqual(response.status_code, 200, self.data(response))
        application.refresh_from_db()
        self.assertEqual(application.template_version_id, first_version.pk)
        self.assertEqual(application.template_version.form_schema["fields"][0]["label"], "付款事由")
        self.assertEqual(template.versions.count(), 2)

        public_response = approval_views.template_item(
            self.request("get", f"/templates/{template.pk}"),
            template.pk,
        )
        self.assertEqual(self.data(public_response)["item"]["formSchema"]["fields"][0]["label"], "用途")
        template.form_schema["fields"][0]["label"] = "尚未发布的新字段名"
        template.revision += 1
        template.save(update_fields=["form_schema", "revision", "updated_at"])
        public_response = approval_views.template_item(
            self.request("get", f"/templates/{template.pk}"),
            template.pk,
        )
        self.assertEqual(self.data(public_response)["item"]["formSchema"]["fields"][0]["label"], "用途")
        manage_response = approval_views.template_item(
            self.request("get", f"/templates/{template.pk}", user="admin", query={"scope": "manage"}),
            template.pk,
        )
        self.assertEqual(
            self.data(manage_response)["item"]["formSchema"]["fields"][0]["label"],
            "尚未发布的新字段名",
        )

    def test_application_validates_required_fields_and_uses_session_identity(self):
        template = self.create_template()
        invalid = approval_views.applications_collection(self.request(
            "post",
            "/applications",
            {"templateId": template.pk, "values": {"amount": "not-a-number"}},
        ))
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.data(invalid)["code"], "INVALID_APPLICATION_VALUES")

        application = self.create_application(template)
        self.assertEqual(application.initiator_user_id, "initiator")
        self.assertEqual(application.initiator_name, "申请人")
        self.assertEqual(application.template_version.version, 1)
        self.assertEqual(application.events.first().action, ApprovalEvent.ACTION_SUBMITTED)

    def test_application_rejects_values_outside_configured_choices(self):
        template = self.create_template(fields=[{
            "key": "payment_type",
            "type": "radio",
            "label": "付款类型",
            "required": True,
            "options": ["对公付款", "费用报销"],
        }])
        response = approval_views.applications_collection(self.request(
            "post",
            "/applications",
            {"templateId": template.pk, "values": {"payment_type": "任意伪造值"}},
        ))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.data(response)["code"], "INVALID_APPLICATION_VALUES")

    def test_application_rejects_malformed_unknown_and_directory_values(self):
        template = self.create_template(fields=[
            {"key": "summary", "type": "text", "label": "摘要"},
            {
                "key": "payment_type",
                "type": "radio",
                "label": "付款类型",
                "options": ["对公付款", "费用报销"],
            },
            {
                "key": "labels",
                "type": "multiselect",
                "label": "标签",
                "options": ["紧急", "普通"],
            },
            {"key": "period", "type": "dateRange", "label": "付款周期"},
            {"key": "amount", "type": "amount", "label": "付款金额"},
            {"key": "owner", "type": "user", "label": "经办人"},
            {"key": "department", "type": "department", "label": "所属部门"},
            {"key": "hint", "type": "description", "label": "填写说明"},
        ])
        cases = [
            ("文本对象", {"summary": {"text": "伪造"}}),
            ("单选数组", {"payment_type": ["对公付款"]}),
            ("多选非字符串项", {"labels": ["紧急", 1]}),
            ("多选重复项", {"labels": ["紧急", "紧急"]}),
            ("倒序日期区间", {"period": ["2026-09-18", "2026-09-17"]}),
            ("NaN 金额", {"amount": float("nan")}),
            ("无限金额", {"amount": float("inf")}),
            ("未知字段", {"unconfigured": "伪造值"}),
            ("展示字段被赋值", {"hint": "伪造值"}),
            ("不存在的人员", {"owner": "missing-user"}),
            ("不存在的部门", {"department": "missing-department"}),
        ]

        for label, values in cases:
            with self.subTest(label=label):
                response = approval_views.applications_collection(self.request(
                    "post",
                    "/applications",
                    {"templateId": template.pk, "values": values},
                ))
                self.assertEqual(response.status_code, 400, self.data(response))
                self.assertEqual(
                    self.data(response)["code"],
                    "INVALID_APPLICATION_VALUES",
                )
                self.assertEqual(ApprovalApplication.objects.count(), 0)
                self.assertEqual(ApprovalTask.objects.count(), 0)

    def test_submission_fails_atomically_when_published_assignee_is_inactive(self):
        template = self.create_template()
        current_employees = [
            {"userId": "initiator", "name": "申请人", "status": "在职", "accountStatus": "启用"},
            {"userId": "approver-1", "name": "审批人甲", "status": "离职", "accountStatus": "停用"},
            {"userId": "approver-2", "name": "审批人乙", "status": "在职", "accountStatus": "启用"},
            {"userId": "cc-user", "name": "抄送人", "status": "在职", "accountStatus": "启用"},
        ]
        with patch.object(
            approval_views,
            "get_auth_organization_snapshot",
            return_value=([], current_employees, 2),
        ):
            response = approval_views.applications_collection(self.request(
                "post",
                "/applications",
                {
                    "templateId": template.pk,
                    "values": {"reason": "采购款", "amount": "10"},
                },
            ))

        self.assertEqual(response.status_code, 409, self.data(response))
        self.assertEqual(self.data(response)["code"], "FLOW_PARTICIPANT_UNAVAILABLE")
        self.assertIn("approver-1", self.data(response)["error"])
        self.assertEqual(ApprovalApplication.objects.count(), 0)
        self.assertEqual(ApprovalTask.objects.count(), 0)
        self.assertEqual(ApprovalEvent.objects.count(), 0)

    def test_submission_uses_current_directory_names_and_initiator_department(self):
        template = self.create_template(name="超长审批模板" * 20)
        published_version = template.published_version
        original_flow_schema = json.loads(json.dumps(published_version.flow_schema))
        long_initiator_name = "申请人新名称" * 30
        long_approver_name = "审批人甲新名称" * 30
        departments = [{"deptId": "12", "name": "采购部"}]
        employees = [
            {
                "userId": "initiator",
                "name": long_initiator_name,
                "status": "在职",
                "accountStatus": "启用",
                "departments": [{"deptId": "12", "name": "被忽略的旧部门名"}],
            },
            {
                "userId": "approver-1",
                "name": long_approver_name,
                "status": "在职",
                "accountStatus": "启用",
            },
            {"userId": "approver-2", "name": "审批人乙", "status": "在职", "accountStatus": "启用"},
            {"userId": "cc-user", "name": "抄送人", "status": "在职", "accountStatus": "启用"},
        ]
        with patch.object(
            approval_views,
            "get_auth_organization_snapshot",
            return_value=(departments, employees, 2),
        ):
            response = approval_views.applications_collection(self.request(
                "post",
                "/applications",
                {
                    "templateId": template.pk,
                    "values": {"reason": "采购款", "amount": "10"},
                    "departmentId": "forged-department",
                    "departmentName": "伪造部门",
                },
            ))

        self.assertEqual(response.status_code, 201, self.data(response))
        application = ApprovalApplication.objects.get(pk=self.data(response)["item"]["id"])
        self.assertEqual(application.initiator_name, long_initiator_name[:128])
        self.assertEqual(len(application.title), 200)
        self.assertEqual(application.initiator_department_id, "12")
        self.assertEqual(application.initiator_department_name, "采购部")
        self.assertEqual(
            application.tasks.get(node_key="manager").assignee_name,
            long_approver_name[:128],
        )
        self.assertEqual(len(application.initiator_name), 128)
        self.assertEqual(len(application.tasks.get(node_key="manager").assignee_name), 128)
        published_version.refresh_from_db()
        self.assertEqual(published_version.flow_schema, original_flow_schema)
        self.assertEqual(
            published_version.flow_schema["nodes"][0]["assigneeNames"]["approver-1"],
            "审批人甲",
        )

    def test_auth_failure_does_not_consume_submission_draft(self):
        template = self.create_template()
        draft_response = approval_views.drafts_collection(self.request(
            "post",
            "/drafts",
            {
                "templateId": template.pk,
                "title": "待提交草稿",
                "values": {"reason": "采购款", "amount": "10"},
            },
        ))
        draft_id = self.data(draft_response)["item"]["id"]

        with patch.object(
            approval_views,
            "get_auth_organization_snapshot",
            side_effect=AuthOrgClientError("组织服务不可用", 503),
        ):
            response = approval_views.applications_collection(self.request(
                "post",
                "/applications",
                {
                    "templateId": template.pk,
                    "draftId": draft_id,
                    "values": {"reason": "采购款", "amount": "10"},
                },
            ))

        self.assertEqual(response.status_code, 503, self.data(response))
        self.assertEqual(self.data(response)["code"], "AUTH_ORG_UNAVAILABLE")
        self.assertTrue(ApprovalDraft.objects.filter(pk=draft_id).exists())
        self.assertEqual(ApprovalApplication.objects.count(), 0)
        self.assertEqual(ApprovalTask.objects.count(), 0)

    def test_proxy_actions_preserve_effective_identity_and_audit_real_actor(self):
        template = self.create_template()
        submitted = approval_views.applications_collection(self.request(
            "post",
            "/applications",
            {
                "templateId": template.pk,
                "title": "代理发起申请",
                "values": {"reason": "采购款", "amount": "10"},
            },
            user="initiator",
            actor="admin",
            proxy=True,
        ))
        self.assertEqual(submitted.status_code, 201, self.data(submitted))
        application = ApprovalApplication.objects.get(pk=self.data(submitted)["item"]["id"])
        submitted_event = application.events.get(action=ApprovalEvent.ACTION_SUBMITTED)
        self.assertEqual(application.initiator_user_id, "initiator")
        self.assertEqual(submitted_event.actor_user_id, "admin")
        self.assertEqual(submitted_event.data["effectiveUserId"], "initiator")
        self.assertTrue(submitted_event.data["isProxying"])

        acted = self.action(
            application,
            "approve",
            user="approver-1",
            actor="admin",
            proxy=True,
            comment="代审批确认",
        )
        self.assertEqual(acted.status_code, 200, self.data(acted))
        task = application.tasks.get(node_key="manager")
        event = application.events.get(action=ApprovalEvent.ACTION_APPROVED)
        self.assertEqual(task.acted_by_user_id, "admin")
        self.assertEqual(event.actor_user_id, "admin")
        self.assertEqual(event.data["effectiveUserId"], "approver-1")
        self.assertTrue(event.data["isProxying"])

    def test_sequential_approval_advances_nodes_then_copies_and_completes(self):
        template = self.create_template()
        application = self.create_application(template)
        first = application.tasks.get(node_key="manager")
        second = application.tasks.get(node_key="finance")
        copied = application.tasks.get(node_key="notify")
        self.assertEqual(first.status, ApprovalTask.STATUS_PENDING)
        self.assertEqual(second.status, ApprovalTask.STATUS_WAITING)
        self.assertEqual(copied.status, ApprovalTask.STATUS_WAITING)

        response = self.action(application, "approve", user="approver-1", comment="同意")
        self.assertEqual(response.status_code, 200, self.data(response))
        application.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(application.current_node_key, "finance")
        self.assertEqual(second.status, ApprovalTask.STATUS_PENDING)

        response = self.action(application, "approve", user="approver-2", comment="财务确认")
        self.assertEqual(response.status_code, 200, self.data(response))
        application.refresh_from_db()
        copied.refresh_from_db()
        self.assertEqual(application.status, ApprovalApplication.STATUS_APPROVED)
        self.assertEqual(copied.status, ApprovalTask.STATUS_COPIED)
        self.assertIsNotNone(application.completed_at)
        self.assertTrue(application.events.filter(action=ApprovalEvent.ACTION_COMPLETED).exists())

    def test_all_mode_waits_for_every_assignee(self):
        template = self.create_template(nodes=[{
            "key": "joint",
            "type": "approver",
            "name": "联合审批",
            "assigneeIds": ["approver-1", "approver-2"],
            "approvalMode": "all",
        }])
        application = self.create_application(template)
        response = self.action(application, "approve", user="approver-1")
        self.assertEqual(response.status_code, 200, self.data(response))
        application.refresh_from_db()
        self.assertEqual(application.status, ApprovalApplication.STATUS_PENDING)
        self.assertEqual(
            application.tasks.get(assignee_user_id="approver-2").status,
            ApprovalTask.STATUS_PENDING,
        )
        response = self.action(application, "approve", user="approver-2")
        self.assertEqual(response.status_code, 200, self.data(response))
        application.refresh_from_db()
        self.assertEqual(application.status, ApprovalApplication.STATUS_APPROVED)

    def test_any_mode_cancels_siblings_after_first_approval(self):
        template = self.create_template(nodes=[{
            "key": "either",
            "type": "approver",
            "name": "任一审批",
            "assigneeIds": ["approver-1", "approver-2"],
            "approvalMode": "any",
        }])
        application = self.create_application(template)
        response = self.action(application, "approve", user="approver-1")
        self.assertEqual(response.status_code, 200, self.data(response))
        application.refresh_from_db()
        self.assertEqual(application.status, ApprovalApplication.STATUS_APPROVED)
        self.assertEqual(
            application.tasks.get(assignee_user_id="approver-2").status,
            ApprovalTask.STATUS_CANCELLED,
        )

    def test_reject_return_and_withdraw_are_terminal_and_authorized(self):
        template = self.create_template()
        application = self.create_application(template)
        missing_comment = self.action(application, "reject", user="approver-1")
        self.assertEqual(missing_comment.status_code, 400)
        self.assertEqual(self.data(missing_comment)["code"], "COMMENT_REQUIRED")

        forbidden = self.action(application, "withdraw", user="other")
        self.assertEqual(forbidden.status_code, 403)
        withdrawn = self.action(application, "withdraw", user="initiator", comment="信息需调整")
        self.assertEqual(withdrawn.status_code, 200, self.data(withdrawn))
        application.refresh_from_db()
        self.assertEqual(application.status, ApprovalApplication.STATUS_WITHDRAWN)
        repeat = self.action(application, "withdraw", user="initiator")
        self.assertEqual(repeat.status_code, 409)

        returned_application = self.create_application(template)
        missing_return_comment = self.action(
            returned_application,
            "return",
            user="approver-1",
        )
        self.assertEqual(missing_return_comment.status_code, 400)
        self.assertEqual(self.data(missing_return_comment)["code"], "COMMENT_REQUIRED")
        response = self.action(
            returned_application,
            "return",
            user="approver-1",
            comment="请补充发票",
        )
        self.assertEqual(response.status_code, 200, self.data(response))
        returned_application.refresh_from_db()
        self.assertEqual(returned_application.status, ApprovalApplication.STATUS_RETURNED)

        rejected_application = self.create_application(template)
        response = self.action(
            rejected_application,
            "reject",
            user="approver-1",
            comment="不符合付款政策",
        )
        self.assertEqual(response.status_code, 200, self.data(response))
        rejected_application.refresh_from_db()
        self.assertEqual(rejected_application.status, ApprovalApplication.STATUS_REJECTED)

    def test_template_action_settings_are_enforced_by_backend(self):
        template = self.create_template()
        version = template.published_version
        version.settings = {
            "allowWithdraw": False,
            "requireApprovalComment": True,
            "requireRejectComment": False,
            "requireReturnComment": False,
        }
        version.save(update_fields=["settings"])
        application = self.create_application(template)
        denied_withdraw = self.action(application, "withdraw", user="initiator")
        self.assertEqual(denied_withdraw.status_code, 409)
        missing_approval_comment = self.action(application, "approve", user="approver-1")
        self.assertEqual(missing_approval_comment.status_code, 400)
        self.assertEqual(self.data(missing_approval_comment)["code"], "COMMENT_REQUIRED")

        rejected = self.action(application, "reject", user="approver-1")
        self.assertEqual(rejected.status_code, 200, self.data(rejected))
        application.refresh_from_db()
        self.assertEqual(application.status, ApprovalApplication.STATUS_REJECTED)

        returned_application = self.create_application(template)
        returned = self.action(returned_application, "return", user="approver-1")
        self.assertEqual(returned.status_code, 200, self.data(returned))
        returned_application.refresh_from_db()
        self.assertEqual(returned_application.status, ApprovalApplication.STATUS_RETURNED)

    def test_revision_conflict_and_unrelated_user_are_rejected(self):
        template = self.create_template()
        application = self.create_application(template)
        conflict = self.action(
            application,
            "approve",
            user="approver-1",
            revision=application.revision + 1,
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.data(conflict)["code"], "REVISION_CONFLICT")

        forbidden = approval_views.application_item(
            self.request("get", f"/applications/{application.pk}", user="other"),
            application.pk,
        )
        self.assertEqual(forbidden.status_code, 403)
        allowed = approval_views.application_item(
            self.request("get", f"/applications/{application.pk}", user="admin"),
            application.pk,
        )
        self.assertEqual(allowed.status_code, 200)

    def test_future_approvers_and_cc_users_cannot_view_before_activation(self):
        template = self.create_template()
        application = self.create_application(template)

        future_approver = approval_views.application_item(
            self.request("get", f"/applications/{application.pk}", user="approver-2"),
            application.pk,
        )
        future_cc = approval_views.application_item(
            self.request("get", f"/applications/{application.pk}", user="cc-user"),
            application.pk,
        )
        self.assertEqual(future_approver.status_code, 403)
        self.assertEqual(future_cc.status_code, 403)

        first = self.action(application, "approve", user="approver-1")
        self.assertEqual(first.status_code, 200, self.data(first))
        application.refresh_from_db()
        active_approver = approval_views.application_item(
            self.request("get", f"/applications/{application.pk}", user="approver-2"),
            application.pk,
        )
        still_future_cc = approval_views.application_item(
            self.request("get", f"/applications/{application.pk}", user="cc-user"),
            application.pk,
        )
        self.assertEqual(active_approver.status_code, 200)
        self.assertEqual(still_future_cc.status_code, 403)

        second = self.action(application, "approve", user="approver-2")
        self.assertEqual(second.status_code, 200, self.data(second))
        visible_cc = approval_views.application_item(
            self.request("get", f"/applications/{application.pk}", user="cc-user"),
            application.pk,
        )
        self.assertEqual(visible_cc.status_code, 200)

    def test_task_list_embeds_application_summary(self):
        template = self.create_template()
        application = self.create_application(template)
        response = approval_views.tasks_collection(self.request(
            "get",
            "/tasks",
            user="approver-1",
            query={"view": "pending"},
        ))
        self.assertEqual(response.status_code, 200)
        data = self.data(response)
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertTrue(item["canAct"])
        self.assertEqual(item["application"]["id"], application.pk)
        self.assertEqual(item["application"]["title"], "9 月供应商付款")
        self.assertEqual(item["application"]["serialNo"], application.serial_no)
        self.assertEqual(item["application"]["initiatorName"], "申请人")
        self.assertEqual(item["application"]["currentNodeName"], "部门主管")

    def test_application_lists_are_scoped_to_current_user(self):
        template = self.create_template()
        application = self.create_application(template)
        initiated = approval_views.applications_collection(self.request(
            "get", "/applications", query={"view": "initiated"},
        ))
        self.assertEqual(self.data(initiated)["total"], 1)
        self.assertEqual(self.data(initiated)["items"][0]["id"], application.pk)

        unrelated = approval_views.applications_collection(self.request(
            "get", "/applications", user="other", query={"view": "initiated"},
        ))
        self.assertEqual(self.data(unrelated)["total"], 0)
        pending = approval_views.applications_collection(self.request(
            "get", "/applications", user="approver-1", query={"view": "pending"},
        ))
        self.assertEqual(self.data(pending)["total"], 1)
        denied_all = approval_views.applications_collection(self.request(
            "get", "/applications", user="other", query={"view": "all"},
        ))
        self.assertEqual(denied_all.status_code, 403)

    def test_exception_list_is_admin_only(self):
        template = self.create_template()
        application = self.create_application(template)
        application.status = ApprovalApplication.STATUS_EXCEPTION
        application.exception_message = "审批人解析失败"
        application.save(update_fields=["status", "exception_message", "updated_at"])
        denied = approval_views.exceptions_collection(self.request(
            "get", "/exceptions", user="other",
        ))
        self.assertEqual(denied.status_code, 403)
        allowed = approval_views.exceptions_collection(self.request(
            "get", "/exceptions", user="admin",
        ))
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(self.data(allowed)["total"], 1)
        self.assertEqual(
            self.data(allowed)["items"][0]["exceptionMessage"],
            "审批人解析失败",
        )

    def test_drafts_are_private_to_owner(self):
        template = self.create_template()
        response = approval_views.drafts_collection(self.request(
            "post",
            "/drafts",
            {"templateId": template.pk, "title": "未完成付款", "values": {"amount": 10}},
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        draft_id = self.data(response)["item"]["id"]
        self.assertEqual(ApprovalDraft.objects.count(), 1)
        owner_detail = approval_views.draft_item(
            self.request("get", f"/drafts/{draft_id}"),
            draft_id,
        )
        self.assertEqual(owner_detail.status_code, 200)
        self.assertEqual(self.data(owner_detail)["item"]["id"], draft_id)
        other_list = approval_views.drafts_collection(self.request(
            "get", "/drafts", user="other",
        ))
        self.assertEqual(self.data(other_list)["total"], 0)
        forbidden = approval_views.draft_item(
            self.request("delete", f"/drafts/{draft_id}", user="other"),
            draft_id,
        )
        self.assertEqual(forbidden.status_code, 404)

    def test_submitting_a_draft_consumes_it_atomically(self):
        template = self.create_template()
        draft_response = approval_views.drafts_collection(self.request(
            "post",
            "/drafts",
            {
                "templateId": template.pk,
                "title": "未完成付款",
                "values": {"reason": "采购款", "amount": "10"},
            },
        ))
        draft_id = self.data(draft_response)["item"]["id"]
        payload = {
            "templateId": template.pk,
            "draftId": draft_id,
            "title": "未完成付款",
            "values": {"reason": "采购款", "amount": "10"},
        }
        submitted = approval_views.applications_collection(self.request(
            "post", "/applications", payload,
        ))
        self.assertEqual(submitted.status_code, 201, self.data(submitted))
        self.assertFalse(ApprovalDraft.objects.filter(pk=draft_id).exists())

        duplicate = approval_views.applications_collection(self.request(
            "post", "/applications", payload,
        ))
        self.assertEqual(duplicate.status_code, 404)
        self.assertEqual(self.data(duplicate)["code"], "DRAFT_NOT_FOUND")
        self.assertEqual(ApprovalApplication.objects.count(), 1)

    def test_draft_is_not_consumed_when_submission_fails_or_does_not_match(self):
        template = self.create_template()
        second_template = self.create_template()
        draft_response = approval_views.drafts_collection(self.request(
            "post",
            "/drafts",
            {
                "templateId": template.pk,
                "title": "待提交草稿",
                "values": {"reason": "采购款", "amount": "10"},
            },
        ))
        draft_id = self.data(draft_response)["item"]["id"]

        invalid = approval_views.applications_collection(self.request(
            "post",
            "/applications",
            {
                "templateId": template.pk,
                "draftId": draft_id,
                "values": {"reason": "", "amount": "bad"},
            },
        ))
        self.assertEqual(invalid.status_code, 400)
        self.assertTrue(ApprovalDraft.objects.filter(pk=draft_id).exists())

        mismatch = approval_views.applications_collection(self.request(
            "post",
            "/applications",
            {
                "templateId": second_template.pk,
                "draftId": draft_id,
                "values": {"reason": "采购款", "amount": "10"},
            },
        ))
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(self.data(mismatch)["code"], "DRAFT_TEMPLATE_MISMATCH")
        self.assertTrue(ApprovalDraft.objects.filter(pk=draft_id).exists())

        foreign = approval_views.applications_collection(self.request(
            "post",
            "/applications",
            {
                "templateId": template.pk,
                "draftId": draft_id,
                "values": {"reason": "采购款", "amount": "10"},
            },
            user="other",
        ))
        self.assertEqual(foreign.status_code, 404)
        self.assertTrue(ApprovalDraft.objects.filter(pk=draft_id).exists())

    def test_draft_search_and_task_application_status_filter_are_applied(self):
        template = self.create_template()
        approval_views.drafts_collection(self.request(
            "post",
            "/drafts",
            {"templateId": template.pk, "title": "九月付款", "values": {}},
        ))
        approval_views.drafts_collection(self.request(
            "post",
            "/drafts",
            {"templateId": template.pk, "title": "差旅申请", "values": {}},
        ))
        drafts = approval_views.drafts_collection(self.request(
            "get", "/drafts", query={"q": "九月"},
        ))
        self.assertEqual(self.data(drafts)["total"], 1)

        application = self.create_application(template)
        pending = approval_views.tasks_collection(self.request(
            "get",
            "/tasks",
            user="approver-1",
            query={"view": "pending", "status": "pending"},
        ))
        hidden = approval_views.tasks_collection(self.request(
            "get",
            "/tasks",
            user="approver-1",
            query={"view": "pending", "status": "approved"},
        ))
        self.assertEqual(self.data(pending)["total"], 1)
        self.assertEqual(self.data(hidden)["total"], 0)
        self.assertEqual(self.data(pending)["items"][0]["applicationId"], application.pk)

    def test_workspace_counts_current_users_work(self):
        template = self.create_template()
        self.create_application(template)
        response = approval_views.workspace(self.request(
            "get", "/workspace", user="approver-1",
        ))
        self.assertEqual(response.status_code, 200)
        data = self.data(response)
        self.assertEqual(data["counts"]["pending"], 1)
        self.assertEqual(data["counts"]["initiated"], 0)
        self.assertEqual(data["recentTemplates"][0]["name"], "付款申请")

    def test_runtime_form_directory_is_scoped_to_published_field_needs(self):
        plain_template = self.create_template()
        with patch.object(views, "get_auth_organization_snapshot") as get_snapshot:
            response = views.form_option_directory(self.request(
                "get",
                "/directory/form-options",
                query={"templateId": plain_template.pk},
            ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.data(response)["directorySource"], "not-required")
        get_snapshot.assert_not_called()

        directory_template = self.create_template(fields=[
            {"key": "owner", "type": "user", "label": "经办人", "required": True},
            {"key": "department", "type": "department", "label": "所属部门", "required": True},
        ])
        departments = [{
            "deptId": 12,
            "name": "采购部",
            "parentDeptId": 1,
            "managerUserIds": ["secret-manager"],
            "updatedAt": "secret",
        }]
        employees = [{
            "userId": "approver-1",
            "name": "审批人甲",
            "rawName": "审批人甲",
            "status": "在职",
            "accountStatus": "启用",
            "isSystemAdmin": True,
            "departments": [{"deptId": 12, "name": "采购部", "departmentPathText": "总部/采购部"}],
        }]
        with patch.object(
            views,
            "get_auth_organization_snapshot",
            return_value=(departments, employees, 9),
        ):
            response = views.form_option_directory(self.request(
                "get",
                "/directory/form-options",
                query={"templateId": directory_template.pk},
            ))
        self.assertEqual(response.status_code, 200)
        data = self.data(response)
        self.assertEqual(data["orgRevision"], 9)
        self.assertEqual(data["employees"], [{
            "userId": "approver-1",
            "name": "审批人甲",
            "departments": [{"deptId": 12, "name": "采购部"}],
        }])
        self.assertEqual(data["departments"], [{
            "deptId": 12,
            "name": "采购部",
            "parentDeptId": 1,
        }])
        self.assertNotIn("isSystemAdmin", data["employees"][0])


class ApprovalCategoryApiTests(ApprovalApiTests):
    """Regression coverage for category-scoped management and ordering APIs."""

    def create_category(self, name="人事"):
        response = approval_views.categories_collection(self.request(
            "post",
            "/categories",
            {"name": name, "description": "人事流程"},
            user="admin",
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        return ApprovalCategory.objects.get(pk=self.data(response)["item"]["id"])

    def test_category_crud_and_template_ordering(self):
        category = self.create_category()
        template = self.create_template(name="入职申请")
        response = approval_views.template_item(
            self.request(
                "patch",
                f"/templates/{template.pk}",
                {"categoryId": category.pk, "categoryOrder": 4, "revision": str(template.revision)},
                user="admin",
            ),
            template.pk,
        )
        self.assertEqual(response.status_code, 200, self.data(response))
        template.refresh_from_db()
        self.assertEqual(template.category_ref_id, category.pk)
        self.assertEqual(template.category_order, 4)

        response = approval_views.templates_reorder(self.request(
            "post",
            "/templates/reorder",
            {"categoryId": category.pk, "items": [{"id": template.pk, "sortOrder": 1}]},
            user="admin",
        ))
        self.assertEqual(response.status_code, 200, self.data(response))
        template.refresh_from_db()
        self.assertEqual(template.category_order, 1)
        self.assertEqual(self.data(response)["items"][0]["categoryId"], category.pk)

        response = approval_views.categories_reorder(self.request(
            "post",
            "/categories/reorder",
            {"items": [{"id": category.pk, "sortOrder": 0}]},
            user="admin",
        ))
        self.assertEqual(response.status_code, 200, self.data(response))

        response = approval_views.category_item(self.request(
            "patch",
            f"/categories/{category.pk}",
            {"name": "人事与行政", "description": "更新"},
            user="admin",
        ), category.pk)
        self.assertEqual(response.status_code, 200, self.data(response))
        template.refresh_from_db()
        self.assertEqual(template.category, "人事与行政")

    def test_atomic_template_move_crosses_page_boundary(self):
        category = self.create_category("跨页排序")
        templates = [
            ApprovalTemplate.objects.create(
                name=f"表单 {index + 1}",
                category=category.name,
                category_ref=category,
                category_order=index,
                created_by="admin",
            )
            for index in range(21)
        ]

        response = approval_views.templates_reorder(self.request(
            "post",
            "/templates/reorder",
            {
                "categoryId": category.pk,
                "templateId": templates[19].pk,
                "direction": "down",
            },
            user="admin",
        ))

        self.assertEqual(response.status_code, 200, self.data(response))
        ordered_ids = list(
            ApprovalTemplate.objects.filter(category_ref=category)
            .order_by("category_order")
            .values_list("id", flat=True)
        )
        self.assertEqual(ordered_ids[19:21], [templates[20].pk, templates[19].pk])
        templates[19].refresh_from_db()
        templates[20].refresh_from_db()
        self.assertEqual(templates[19].category_order, 20)
        self.assertEqual(templates[20].category_order, 19)

    def test_atomic_template_move_rejects_invalid_direction(self):
        category = self.create_category("排序校验")
        template = ApprovalTemplate.objects.create(
            name="待排序表单",
            category=category.name,
            category_ref=category,
            created_by="admin",
        )

        response = approval_views.templates_reorder(self.request(
            "post",
            "/templates/reorder",
            {
                "categoryId": category.pk,
                "templateId": template.pk,
                "direction": "sideways",
            },
            user="admin",
        ))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.data(response)["code"], "INVALID_SORT_DIRECTION")

    def test_global_admin_management_list_includes_drafts(self):
        draft = self.create_template(name="待发布表单", publish=False)

        response = approval_views.templates_collection(self.request(
            "get",
            "/templates",
            user="admin",
            query={"scope": "manage"},
        ))

        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertIn(draft.pk, [item["id"] for item in self.data(response)["items"]])
        self.assertEqual(
            next(item for item in self.data(response)["items"] if item["id"] == draft.pk)["status"],
            ApprovalTemplate.STATUS_DRAFT,
        )

    def test_category_manager_can_manage_only_assigned_category(self):
        category = self.create_category("分类管理员可见")
        with patch.object(
            approval_views,
            "get_auth_organization_snapshot",
            return_value=([], [{
                "userId": "category-manager",
                "name": "分类管理员",
                "status": "在职",
                "accountStatus": "启用",
            }], 8),
        ):
            response = approval_views.category_permissions(self.request(
                "post",
                f"/categories/{category.pk}/permissions",
                {"rules": [{
                    "scopeType": "employee",
                    "targetId": "category-manager",
                    "targetName": "分类管理员",
                }]},
                user="admin",
            ), category.pk)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertEqual(ApprovalCategoryPermission.objects.filter(category=category).count(), 1)

        response = approval_views.templates_collection(self.request(
            "post",
            "/templates",
            {
                **self.template_payload(name="分类表单"),
                "categoryId": category.pk,
            },
            user="category-manager",
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        template_id = self.data(response)["item"]["id"]
        response = approval_views.templates_collection(self.request(
            "get",
            "/templates",
            user="category-manager",
            query={"scope": "manage", "categoryId": category.pk},
        ))
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertEqual([item["id"] for item in self.data(response)["items"]], [template_id])

        other = self.create_category("其他分类")
        denied = approval_views.templates_reorder(self.request(
            "post",
            "/templates/reorder",
            {"categoryId": other.pk, "items": []},
            user="category-manager",
        ))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.data(denied)["code"], "CATEGORY_ADMIN_REQUIRED")
