from datetime import date, timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import crm_source, services, views
from .models import AppPermissionRule, PresalesTaskSchedule, ServiceProject
from .presales_task_schedule import annotate_presales_task_deadline, pending_presales_task_schedules, sync_presales_task_schedules
from .serializers import serialize_project
from .tests import CleanDomainMixin, RequestMixin


class PresalesTaskScheduleTests(RequestMixin, CleanDomainMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        self.project = services.create_project(self.request("post", "/"), {
            "code": "round-time", "name": "轮次时间测试", "customer": "测试学校", "service_type": "presales",
            "owner_user_id": "system-admin",
        })
        self.node = self.project.nodes.get(node_key="early-plan")

    def save_rounds(self, rounds, **values):
        return views.project_node_autosave(self.request("patch", "/", {
            "businessData": {"schemeRounds": rounds}, **values,
        }), self.project.pk, self.node.node_key)

    def activate(self):
        self.project.nodes.update(status="pending")
        self.node.status = "active"
        self.node.save(update_fields=["status"])

    def dashboard(self, **identity):
        identity.setdefault("admin", identity.get("user_id", "system-admin") == "system-admin")
        return self.data(views.dashboard(self.request("get", "/", **identity)))

    def grant_business(self, *users):
        AppPermissionRule.objects.bulk_create([
            AppPermissionRule(permission="sales", scope_type="employee", target_id=user) for user in users
        ])

    def assign_executor(self, user_id, *, node=None):
        node = node or self.node
        response = views.project_node_autosave(self.request("patch", "/", {
            "businessData": {"managementAssignment": {"userId": user_id, "name": "同名员工"}},
        }), self.project.pk, node.node_key)
        self.assertEqual(response.status_code, 200, self.data(response))

    def assign_required_people(self):
        for node in self.project.nodes.all():
            node.business_data = {"managementAssignment": {"userId": "employee", "name": "测试人员"}}
            node.save(update_fields=["business_data"])

    def test_approval_requires_people_but_no_node_dates(self):
        self.assign_required_people()
        response = views.project_advance(self.request("post", "/", {
            "nodeKey": "early-approval", "outcome": "approved",
        }), self.project.pk)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        self.assertEqual(self.node.status, "active")
        self.assertIsNone(self.node.planned_start_at)
        self.assertIsNone(self.node.planned_end_at)
        self.assertIsNotNone(self.node.actual_start_at)

    def test_missing_people_still_block_approval(self):
        response = views.project_advance(self.request("post", "/", {
            "nodeKey": "early-approval", "outcome": "approved",
        }), self.project.pk)
        self.assertEqual(response.status_code, 409)
        self.assertIn("项目人员", self.data(response)["error"])

    def test_individual_personnel_notes_survive_round_changes_and_invalid_or_stale_updates(self):
        members = [{"userId": "designer-a", "name": "设计甲", "note": "负责方案设计"},
                   {"userId": "designer-b", "name": "设计乙", "note": "负责预算复核"}]
        stamp = self.node.updated_at.isoformat()
        def save(rows, version=None):
            self.node.refresh_from_db()
            return views.project_node_autosave(self.request("patch", "/", {
                "expectedUpdatedAt": version or self.node.updated_at.isoformat(),
                "businessData": {"managementAssignment": {"members": rows}},
            }), self.project.pk, self.node.node_key)
        response = save(members)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["managementAssignment"]["members"], members)
        self.assertEqual(self.save_rounds([{"note": "本轮工作内容"}]).status_code, 200)
        for invalid_note in (None, 3, [], {}):
            with self.subTest(note=invalid_note):
                response = save([{**members[0], "note": invalid_note}, members[1]])
                self.assertEqual(response.status_code, 400, self.data(response))
        response = save([{**members[0], "note": "旧版本覆盖"}, members[1]], stamp)
        self.assertEqual(response.status_code, 409, self.data(response))
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["managementAssignment"]["members"], members)
        # Reordering/removing people keeps the note attached to the stable ID.
        response = save([members[1], {**members[0], "note": ""}])
        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["managementAssignment"]["members"], [members[1], {**members[0], "note": ""}])
        self.assertEqual(save([members[1]]).status_code, 200)
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["managementAssignment"]["members"], [members[1]])

    def test_latest_round_dates_are_optional_and_history_is_read_only(self):
        rounds = [
            {"plannedStartDate": "2026-10-15", "plannedEndDate": "2026-10-18", "designDate": "2026-10-14",
             "note": "历史备注", "attachmentIds": ["88"], "submitDate": "2026-10-13", "result": "驳回"},
            {"plannedEndDate": "2026-10-20", "designDate": ""}, {},
        ]
        response = self.save_rounds(rounds)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        saved = self.node.business_data["schemeRounds"]
        self.assertEqual(saved[0]["note"], "历史备注")
        self.assertEqual(saved[0]["attachmentIds"], ["88"])
        self.assertEqual(saved[0]["designDate"], "2026-10-14")
        self.assertNotIn("result", saved[0])
        tasks = list(self.node.presales_tasks.all())
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0].actual_end_date, date(2026, 10, 14))
        self.assertEqual(tasks[1].planned_end_date, date(2026, 10, 20))
        self.assertIsNone(tasks[2].planned_end_date)
        # Earlier rounds are immutable after a newer round has been created.
        rounds[0]["plannedEndDate"] = "2026-10-19"
        response = self.save_rounds(rounds[:2])
        self.assertEqual(response.status_code, 409, self.data(response))
        self.assertEqual(self.node.presales_tasks.count(), 3)
        rounds[0]["plannedEndDate"] = "2026-10-18"
        rounds[-1]["plannedEndDate"] = "2026-10-21"
        self.assertEqual(self.save_rounds(rounds).status_code, 200)
        self.assertEqual(self.node.presales_tasks.get(round_number=3).planned_end_date, date(2026, 10, 21))
        self.assertEqual(self.save_rounds(rounds[:2]).status_code, 200)
        self.assertEqual(self.node.presales_tasks.count(), 2)
        self.assertEqual(self.node.presales_tasks.get(round_number=2).planned_end_date, date(2026, 10, 20))
        self.assertEqual(self.save_rounds([{}, {}]).status_code, 409)
        self.assertEqual(self.node.presales_tasks.get(round_number=1).planned_end_date, date(2026, 10, 18))

    def test_invalid_round_dates_are_rejected_atomically(self):
        self.assertEqual(self.save_rounds([{"plannedEndDate": "2026-10-14"}]).status_code, 200)
        cases = [
            ([{"plannedStartDate": "2026-10-15", "plannedEndDate": "2026-10-14"}], "INVALID_PRESALES_TASK_RANGE"),
            ([{"plannedEndDate": "2026-02-30"}], "INVALID_PRESALES_TASK_DATE"),
            ([{"plannedStartDate": 7}], "INVALID_PRESALES_TASK_DATE"),
            (["invalid"], "INVALID_PRESALES_TASKS"),
        ]
        for rounds, code in cases:
            with self.subTest(code=code):
                response = self.save_rounds(rounds)
                self.assertEqual(response.status_code, 400, self.data(response))
                self.assertEqual(self.data(response)["code"], code)
                self.node.refresh_from_db()
                self.assertEqual(self.node.business_data["schemeRounds"], [{"plannedEndDate": "2026-10-14"}])
                self.assertEqual(self.node.presales_tasks.get().planned_end_date, date(2026, 10, 14))

    def test_legacy_node_schedule_does_not_block_save_or_advance(self):
        self.assign_required_people()
        self.node.refresh_from_db()
        self.node.planned_start_at = timezone.now()
        self.node.planned_end_at = timezone.now() - timedelta(days=1)
        self.node.save()
        original = (self.node.planned_start_at, self.node.planned_end_at)
        self.assertEqual(self.save_rounds([{}], plannedStartAt="2026-10-19", plannedEndAt="2026-10-10").status_code, 200)
        response = views.project_advance(self.request("post", "/", {"nodeKey": "early-approval", "outcome": "approved"}), self.project.pk)
        self.assertEqual(response.status_code, 200, self.data(response))
        response = views.project_advance(self.request("post", "/", {"nodeKey": "early-plan", "businessData": {"schemeRounds": [{}]}}), self.project.pk)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        self.assertEqual((self.node.planned_start_at, self.node.planned_end_at), original)
        self.assertEqual(self.node.presales_tasks.get().actual_end_date, None)

    def test_midsales_still_validates_node_schedule(self):
        project = services.create_project(self.request("post", "/"), {
            "code": "mid-time", "name": "售中排期", "customer": "学校", "service_type": "midsales",
        })
        response = views.project_node_autosave(self.request("patch", "/", {
            "plannedStartAt": "2026-10-15T09:00:00+08:00", "plannedEndAt": "2026-10-14T09:00:00+08:00",
        }), project.pk, "midsales-project")
        self.assertEqual(response.status_code, 400, self.data(response))
        self.assertEqual(self.data(response)["code"], "INVALID_PLANNED_TIME_RANGE")

    def test_dashboard_deadlines_and_visibility_are_per_task(self):
        self.activate()
        self.assign_executor("system-admin")
        today = timezone.localdate()
        past, future = (today - timedelta(days=2)).isoformat(), (today + timedelta(days=1)).isoformat()
        self.save_rounds([{"plannedEndDate": past}, {"plannedEndDate": today.isoformat()},
                          {"plannedEndDate": past, "designDate": today.isoformat()}, {"plannedEndDate": future}, {}])
        self.node.planned_end_at = timezone.now() - timedelta(days=90)
        self.node.save(update_fields=["planned_end_at"])
        data = self.dashboard()
        self.assertEqual(data["taskTotal"], 5)
        self.assertEqual(data["alertTotal"], 4)
        self.assertEqual(data["alerts"][0]["type"], "overdue_presales_task")
        self.assertEqual(data["alerts"][0]["roundNumber"], 1)
        self.assertEqual(data["alerts"][0]["dueText"], "已超时 2 天")
        self.assertEqual(data["tasks"][0]["roundNumber"], 1)
        self.assertIn(3, [task["roundNumber"] for task in data["tasks"]], "historical dates no longer mark a round as finished")
        deadline = serialize_project(annotate_presales_task_deadline(ServiceProject.objects.filter(pk=self.project.pk)).get())
        self.assertEqual(deadline["plannedEndDate"], past)
        self.assertEqual(deadline["plannedStartDate"], "")
        # A logged-in user without any application role cannot use the module.
        outsider = self.dashboard(user_id="other-user")
        self.assertEqual(outsider["code"], "APP_ACCESS_DENIED")
        self.assertNotIn("tasks", outsider)
        # Set up the single-round deadline case directly; completed history may
        # no longer be replaced by a draft request from a newer client.
        self.node.business_data = {**self.node.business_data, "schemeRounds": [{"plannedEndDate": past, "designDate": today.isoformat()}]}
        self.node.save(update_fields=["business_data"])
        sync_presales_task_schedules(self.node)
        self.assertEqual(self.dashboard()["alertTotal"], 1)
        self.node.status = "completed"
        self.node.completed_at = timezone.now()
        self.node.save(update_fields=["status", "completed_at"])
        self.assertEqual(self.dashboard()["alertTotal"], 0)
        self.assertEqual(self.dashboard()["taskTotal"], 0, "passing the node completes its tasks without a manual round date")

    def test_inactive_completed_deleted_or_cancelled_tasks_never_alert(self):
        self.activate()
        self.save_rounds([{"plannedEndDate": "2000-01-01"}])
        for state in ("pending", "completed", "skipped"):
            self.node.status = state
            self.node.save(update_fields=["status"])
            self.assertEqual(pending_presales_task_schedules().count(), 0)
        self.node.status = "active"
        self.node.enabled = False
        self.node.save()
        self.assertEqual(pending_presales_task_schedules().count(), 0)
        self.node.enabled = True
        self.node.save()
        for status in ("completed", "cancelled"):
            self.project.status = status
            self.project.save()
            self.assertEqual(pending_presales_task_schedules().count(), 0)
        self.project.status = "in_progress"
        self.project.deleted_at = timezone.now()
        self.project.save()
        self.assertEqual(pending_presales_task_schedules().count(), 0)

    def test_business_executor_sees_own_rounds_and_overall_three_day_risks(self):
        self.grant_business("executor-a")
        self.activate()
        today = timezone.localdate()
        rounds = [{"plannedEndDate": (today + timedelta(days=days)).isoformat()}
                  for days in (-1, 0, 1, 3, 4)] + [{}]
        self.save_rounds(rounds)
        self.assign_executor("executor-a")
        sibling = self.project.nodes.get(node_key="budget-match")
        sibling.status = "active"
        sibling.business_data = {
            "managementAssignment": {"userId": "executor-b", "name": "同名员工"},
            "schemeRounds": [{"plannedEndDate": "2000-01-01"}],
        }
        sibling.save()
        sync_presales_task_schedules(sibling)
        # Business permission grants admission but not settings access. Personal
        # tasks still match the effective ID, even when display names coincide.
        data = self.dashboard(user_id="executor-a", name="同名员工", admin=False)
        outsider = self.dashboard(user_id="unassigned", name="同名员工", admin=False)
        self.assertEqual(data["taskTotal"], 6)
        self.assertEqual(data["alertTotal"], 5)
        self.assertEqual({item["nodeId"] for item in data["tasks"]}, {self.node.pk})
        self.assertEqual({item["nodeId"] for item in data["alerts"]}, {self.node.pk, sibling.pk})
        self.assertEqual(data["metrics"]["projects"], 1)
        self.assertEqual(data["tasks"][0]["dueText"], "已超时 1 天")
        self.assertEqual(data["alerts"][0]["type"], "overdue_presales_task")
        due = [item for item in data["alerts"] if item["type"] == "due_presales_task"]
        self.assertEqual({item["roundNumber"] for item in due}, {2, 3, 4})
        self.assertEqual([item["dueText"] for item in due], ["今天到期", "还有 1 天到期", "还有 3 天到期"])
        self.assertTrue(all(item["level"] == "medium" for item in due))
        self.assertEqual(data["tasks"][4]["dueText"], f"{today + timedelta(days=4):%Y-%m-%d} 到期")
        self.assertEqual(data["tasks"][5]["dueText"], "未设置预计完成时间")
        self.assertEqual(outsider["code"], "APP_ACCESS_DENIED")
        self.assertNotIn("taskTotal", outsider)

    def test_authorized_owner_monitors_risks_but_audit_creator_has_no_module_access(self):
        self.grant_business("project-owner")
        self.activate()
        self.project.owner_user_id = "project-owner"
        self.project.created_by = "project-creator"
        self.project.save(update_fields=["owner_user_id", "created_by"])
        self.save_rounds([{"plannedEndDate": "2000-01-01"},
                          {"plannedEndDate": timezone.localdate().isoformat()}, {}])
        for executor in ("", "other-executor"):
            self.assign_executor(executor)
            for user_id in ("project-owner", "project-creator"):
                with self.subTest(executor=executor, user_id=user_id):
                    data = self.dashboard(user_id=user_id)
                    if user_id == "project-creator":
                        self.assertEqual(data["code"], "APP_ACCESS_DENIED")
                        self.assertNotIn("metrics", data)
                        continue
                    self.assertEqual(data["metrics"]["projects"], 1)
                    self.assertEqual(data["taskTotal"], 0)
                    self.assertEqual(data["alertTotal"], 2)
                    self.assertEqual(data["tasks"], [])
                    self.assertEqual({item["type"] for item in data["alerts"]},
                                     {"overdue_presales_task", "due_presales_task"})
        # Explicit assignment still works when the executor is also the owner.
        self.assign_executor("project-owner")
        assigned = self.dashboard(user_id="project-owner")
        self.assertEqual((assigned["taskTotal"], assigned["alertTotal"]), (3, 2))
        self.assertEqual(self.dashboard(user_id="project-creator")["code"], "APP_ACCESS_DENIED")
        self.assign_executor("")
        cleared = self.dashboard(user_id="project-owner")
        self.assertEqual((cleared["taskTotal"], cleared["alertTotal"]), (0, 2))
        self.node.refresh_from_db()
        self.node.status = "completed"
        self.node.save(update_fields=["status"])
        completed = self.dashboard(user_id="project-owner")
        self.assertEqual((completed["taskTotal"], completed["alertTotal"]), (0, 0))

    def test_owner_risk_scope_does_not_inherit_proxy_actor_or_bypass_crm_visibility(self):
        self.grant_business("actor-admin")
        self.activate()
        self.project.owner_user_id = "actor-admin"
        self.project.created_by = "actor-admin"
        self.project.source_crm_id = "private-crm"
        self.project.crm_snapshot = {"stage": "方案渗透"}
        self.project.save(update_fields=["owner_user_id", "created_by", "source_crm_id", "crm_snapshot"])
        self.node.business_data = {"schemeRounds": [{"plannedEndDate": "2000-01-01"}]}
        self.node.save(update_fields=["business_data"])
        sync_presales_task_schedules(self.node)
        for user_id, proxy, allowed, risk_count in [
            ("actor-admin", False, [], 0),
            ("actor-admin", False, ["private-crm"], 1),
            ("proxy-target", True, ["private-crm"], 0),
        ]:
            with self.subTest(user_id=user_id, proxy=proxy, allowed=allowed):
                request = self.request("get", "/", user_id=user_id, proxy=proxy, admin=False)
                request._after_sales_crm_ids = allowed
                with patch.object(views, "sync_crm_presales"), patch.object(views, "crm_sync_status", return_value={"crmScopeReady": True}):
                    data = self.data(views.dashboard(request))
                if proxy:
                    self.assertEqual(data["code"], "APP_ACCESS_DENIED")
                    self.assertNotIn("taskTotal", data)
                    continue
                self.assertEqual(data["taskTotal"], 0)
                self.assertEqual(data["alertTotal"], risk_count)

    def test_unassigned_nodes_without_rounds_are_not_pending_tasks(self):
        # This is the first CRM/local node, before any personnel are selected.
        self.assertEqual(self.dashboard()["metrics"]["projects"], 1)
        self.assertEqual(self.dashboard()["taskTotal"], 0)
        self.assertEqual(self.dashboard()["tasks"], [])
        self.assign_executor("system-admin", node=self.project.nodes.get(node_key="early-approval"))
        assigned = self.dashboard()
        self.assertEqual(assigned["taskTotal"], 1)
        self.assertEqual(assigned["tasks"][0]["nodeKey"], "early-approval")

    def test_reassignment_and_removal_move_pending_tasks_and_reminders(self):
        self.grant_business("executor-a", "executor-b")
        self.activate()
        self.save_rounds([{"plannedEndDate": timezone.localdate().isoformat()}, {}])
        self.assign_executor("executor-a")
        task_ids = list(self.node.presales_tasks.values_list("id", flat=True))
        self.assertEqual(self.dashboard(user_id="executor-a")["taskTotal"], 2)
        self.assign_executor("executor-b")
        before = self.dashboard(user_id="executor-a")
        after = self.dashboard(user_id="executor-b")
        self.assertEqual((before["taskTotal"], before["alertTotal"]), (0, 1))
        self.assertEqual((after["taskTotal"], after["alertTotal"]), (2, 1))
        self.assertEqual(list(self.node.presales_tasks.values_list("id", flat=True)), task_ids)
        self.assign_executor("")
        cleared = self.dashboard(user_id="executor-b")
        self.assertEqual((cleared["taskTotal"], cleared["alertTotal"]), (0, 1))

    def test_all_selected_executors_get_tasks_and_removal_updates_every_consumer(self):
        from . import access
        from .project_personnel import management_member_q
        from .settlement_finance import related_projects

        self.grant_business("executor-a", "executor-b", "executor", "unselected")
        self.activate()
        self.save_rounds([{"plannedEndDate": "2000-01-01"},
                          {"plannedEndDate": timezone.localdate().isoformat()}])
        members = [{"userId": user, "name": "同名员工"} for user in ("executor-a", "executor-b")]
        def save_members(rows):
            response = views.project_node_autosave(self.request("patch", "/", {
                "businessData": {"managementAssignment": {"members": rows,
                                 "userIds": ["unselected"], "note": "共同处理"}},
            }), self.project.pk, self.node.node_key)
            self.assertEqual(response.status_code, 200, self.data(response))
        save_members([*members, members[0]])
        selection = self.project.nodes.get(pk=self.node.pk).business_data["managementAssignment"]
        self.assertEqual(selection["userIds"], ["executor-a", "executor-b"])
        self.assertEqual(selection["members"], members)
        for user in ("executor-a", "executor-b"):
            data = self.dashboard(user_id=user)
            self.assertEqual((data["taskTotal"], data["alertTotal"]), (2, 2))
            self.assertTrue(related_projects(user).filter(pk=self.project.pk).exists())
        for user in ("executor", "unselected"):
            self.assertEqual(self.dashboard(user_id=user)["taskTotal"], 0)
            self.assertFalse(self.project.nodes.filter(management_member_q(user)).exists())
        node = self.project.nodes.get(pk=self.node.pk)
        with patch.object(access, "can_manage_project", return_value=False), patch.object(access, "can_use_management", return_value=True):
            self.assertTrue(access.can_edit_node(self.request("post", "/", user_id="executor-b"), node))
            self.assertFalse(access.can_edit_node(self.request("post", "/", user_id="executor"), node))
        save_members(members[1:])
        self.assertEqual(self.dashboard(user_id="executor-a")["taskTotal"], 0)
        self.assertEqual(self.dashboard(user_id="executor-b")["taskTotal"], 2)
        self.assertFalse(related_projects("executor-a").filter(pk=self.project.pk).exists())
        save_members([])
        self.assertEqual(self.dashboard(user_id="executor-b")["taskTotal"], 0)

    def test_proxy_uses_effective_executor_and_does_not_inherit_actor_tasks(self):
        self.grant_business("executor", "actor-admin")
        self.activate()
        self.save_rounds([{"plannedEndDate": timezone.localdate().isoformat()}])
        self.assign_executor("actor-admin")
        self.assertEqual(self.dashboard(user_id="executor", proxy=True)["taskTotal"], 0)
        self.assign_executor("executor")
        data = self.dashboard(user_id="executor", proxy=True)
        self.assertEqual((data["taskTotal"], data["alertTotal"]), (1, 1))
        self.assertEqual(self.dashboard(user_id="actor-admin")["taskTotal"], 0)

    def test_assignment_never_overrides_crm_scope_and_source_failure_keeps_local_tasks(self):
        self.grant_business("executor")
        self.activate()
        self.save_rounds([{"plannedEndDate": timezone.localdate().isoformat()}])
        self.assign_executor("executor")
        local = services.create_project(self.request("post", "/"), {
            "code": "local-executor", "name": "独立本地任务", "customer": "学校", "service_type": "presales",
        })
        local_node = local.nodes.get(node_key="early-plan")
        local.nodes.update(status="pending")
        local_node.status = "active"
        local_node.business_data = {
            "managementAssignment": {"userId": "executor", "name": "员工"},
            "schemeRounds": [{"plannedEndDate": timezone.localdate().isoformat()}],
        }
        local_node.save()
        sync_presales_task_schedules(local_node)
        self.project.source_crm_id = "crm-assigned"
        self.project.crm_snapshot = {"stage": "方案渗透"}
        self.project.save(update_fields=["source_crm_id", "crm_snapshot"])
        for allowed in ([], ["crm-assigned"]):
            request = self.request("get", "/", user_id="executor")
            request._after_sales_crm_ids = allowed
            with patch.object(views, "sync_crm_presales"), patch.object(views, "crm_sync_status", return_value={"crmScopeReady": True}):
                data = self.data(views.dashboard(request))
            self.assertEqual(data["taskTotal"], 2 if allowed else 1)
            self.assertEqual(data["alertTotal"], 2 if allowed else 1)
            expected = {local.pk, self.project.pk} if allowed else {local.pk}
            self.assertEqual({item["projectId"] for item in data["tasks"]}, expected)
        for failure in [crm_source.CrmSourceError(), crm_source.CrmSourceError("CRM 无权限", status=403, code="CRM_PERMISSION_DENIED")]:
            request = self.request("get", "/", user_id="executor")
            with patch.object(views, "sync_crm_presales", side_effect=failure):
                data = self.data(views.dashboard(request))
            self.assertFalse(data["crmScopeReady"])
            self.assertEqual(data["crmSyncError"], str(failure))
            self.assertEqual((data["taskTotal"], data["alertTotal"]), (1, 1))
            self.assertEqual(data["tasks"][0]["projectId"], local.pk)

    def test_executor_tasks_disappear_when_node_or_project_stops(self):
        self.grant_business("executor")
        self.activate()
        self.save_rounds([{"plannedEndDate": timezone.localdate().isoformat()}])
        self.assign_executor("executor")
        for status in ("pending", "completed", "skipped"):
            self.project.nodes.filter(pk=self.node.pk).update(status=status)
            data = self.dashboard(user_id="executor")
            self.assertEqual((data["taskTotal"], data["alertTotal"]), (0, 0))
        self.project.nodes.filter(pk=self.node.pk).update(status="active", enabled=False)
        data = self.dashboard(user_id="executor")
        self.assertEqual((data["taskTotal"], data["alertTotal"]), (0, 0))
        self.project.nodes.filter(pk=self.node.pk).update(enabled=True)
        for status in ("completed", "cancelled"):
            ServiceProject.objects.filter(pk=self.project.pk).update(status=status)
            data = self.dashboard(user_id="executor")
            self.assertEqual((data["taskTotal"], data["alertTotal"]), (0, 0))
        ServiceProject.objects.filter(pk=self.project.pk).update(status="in_progress", deleted_at=timezone.now())
        data = self.dashboard(user_id="executor")
        self.assertEqual((data["taskTotal"], data["alertTotal"]), (0, 0))

    def test_large_task_summary_is_bounded_without_reading_round_json(self):
        self.grant_business("executor")
        self.activate()
        self.assign_executor("executor")
        PresalesTaskSchedule.objects.bulk_create([
            PresalesTaskSchedule(node=self.node, round_number=number, planned_end_date=date(2000, 1, 1))
            for number in range(1, 1001)
        ])
        request = self.request("get", "/", user_id="executor", admin=False)
        with CaptureQueriesContext(connection) as queries:
            data = self.data(views.dashboard(request))
        self.assertEqual(data["taskTotal"], 1000)
        self.assertEqual(data["alertTotal"], 1000)
        self.assertEqual(len(data["tasks"]), 8)
        self.assertEqual(len(data["alerts"]), 8)
        self.assertLessEqual(len(queries), 25)
        # JSON predicates identify the executor in SQL; the round JSON is never
        # selected or materialized in Python, even for thousands of tasks.
        self.assertFalse(any('"business_data"' in query["sql"].split(" FROM ", 1)[0] for query in queries))

    def test_backfill_is_idempotent_and_preserves_original_data(self):
        self.node.business_data = {"schemeRounds": [{"designDate": "2026-10-10", "note": "原备注", "attachmentIds": ["7"]},
                                                   {"plannedEndDate": "2026-10-18"}, {"plannedEndDate": "bad"}]}
        self.node.planned_end_at = timezone.now()
        self.node.save()
        original = (self.node.business_data, self.node.planned_end_at)
        migration = import_module("after_sales_api.migrations.0024_presales_task_schedules")
        for _ in range(2):
            migration.backfill_round_schedules(apps, SimpleNamespace(connection=connection))
        self.assertEqual(self.node.presales_tasks.count(), 3)
        self.assertEqual(self.node.presales_tasks.get(round_number=1).actual_end_date, date(2026, 10, 10))
        self.assertIsNone(self.node.presales_tasks.get(round_number=1).planned_end_date)
        self.node.refresh_from_db()
        self.assertEqual((self.node.business_data, self.node.planned_end_at), original)
        sync_presales_task_schedules(self.node)
        self.assertEqual(self.node.presales_tasks.count(), 3)
