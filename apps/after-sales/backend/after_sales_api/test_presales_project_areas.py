from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from . import crm_source, services, views
from .models import AppPermissionRule, ServiceProvider
from .project_areas import PRESALES_PROJECT_LEVELS, PRESALES_PROJECT_URGENCIES
from .presales_statistics import presales_statistics
from .serializers import project_draft_version
from .tests import CleanDomainMixin, RequestMixin


class PresalesProjectAreasTests(RequestMixin, CleanDomainMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.clear_domain()
        cache.clear()
        self.addCleanup(cache.clear)
        self.project = services.create_project(self.request("post", "/"), {
            "code": "AREA-1", "name": "面积填写项目", "customer": "面积测试学校", "service_type": "presales",
            "business_data": {"projectInfo": {"name": "面积填写项目", "reason": "原说明"},
                              "projectInfoRecords": {"early-approval": {"name": "历史立项资料"}},
                              "other": {"keep": True}},
        })

    def save(self, areas, *, version=None, request=None):
        payload = {"presalesAreas": areas, "expectedDraftVersion": version or project_draft_version(self.project)}
        return views.project_item(request or self.request("patch", "/", payload), self.project.id)

    def save_info(self, info, *, version=None):
        payload = {"presalesProjectInfo": info, "expectedDraftVersion": version or project_draft_version(self.project)}
        return views.project_item(self.request("patch", "/", payload), self.project.id)

    def test_unchanged_optional_defaults_and_number_format_do_not_create_history(self):
        original_data = self.project.business_data.copy()
        stamp = self.project.updated_at
        version = project_draft_version(self.project)
        event_ids = list(self.project.events.values_list("id", flat=True))
        for info in ({"totalArea": None, "designArea": "", "projectLevel": ""},
                     {"totalArea": " ", "designArea": None, "projectLevel": None},
                     {"totalArea": None, "designArea": None, "projectLevel": "", "urgency": " ", "expectedBidAt": None},
                     {"totalArea": None, "designArea": None, "projectLevel": "", "expectedBidAt": " "}):
            response = self.save_info(info)
            self.assertEqual(response.status_code, 200, response.content)
            self.project.refresh_from_db()
            self.assertEqual(self.project.business_data, original_data)
            self.assertEqual(self.project.updated_at, stamp)
            self.assertEqual(project_draft_version(self.project), version)
            self.assertEqual(list(self.project.events.values_list("id", flat=True)), event_ids)

        self.assertEqual(self.save_info({"totalArea": "80", "designArea": "0", "projectLevel": "常规，金额小"}).status_code, 200)
        self.project.refresh_from_db()
        stamp = self.project.updated_at
        event_ids = list(self.project.events.values_list("id", flat=True))
        response = self.save_info({"totalArea": "080.00", "designArea": "0.00", "projectLevel": "常规，金额小"})
        self.assertEqual(response.status_code, 200, response.content)
        self.project.refresh_from_db()
        self.assertEqual(self.project.updated_at, stamp)
        self.assertEqual(list(self.project.events.values_list("id", flat=True)), event_ids)

        # Clearing a saved value is a real change, including a saved zero.
        response = self.save_info({"totalArea": None, "designArea": None, "projectLevel": ""})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.project.events.filter(event_type="project_updated").count(), 2)

    def test_save_preserves_project_and_historical_node_data_and_feeds_statistics(self):
        node = self.project.nodes.get(node_key="early-approval")
        node.status = "completed"
        node.save(update_fields=["status"])
        original_data = self.project.business_data.copy()
        response = self.save_info({"totalArea": "120.25", "designArea": "80", "projectLevel": "重要，金额大", "urgency": "紧急", "expectedBidAt": "2026-11-25"})
        self.assertEqual(response.status_code, 200, response.content)
        self.project.refresh_from_db()
        self.assertEqual(self.project.business_data["projectInfo"]["totalArea"], "120.25")
        self.assertEqual(self.project.business_data["projectInfo"]["designArea"], "80.00")
        self.assertEqual(self.project.business_data["projectInfo"]["projectLevel"], "重要，金额大")
        self.assertEqual(self.project.business_data["projectInfo"]["reason"], "原说明")
        self.assertEqual(self.project.business_data["projectInfoRecords"], original_data["projectInfoRecords"])
        self.assertEqual(self.project.business_data["other"], original_data["other"])
        node.refresh_from_db()
        self.assertEqual(node.status, "completed")
        reread = views.project_item(self.request("get", "/"), self.project.id)
        self.assertEqual(self.data(reread)["item"]["businessData"]["projectInfo"]["totalArea"], "120.25")
        request = self.request("get", "/api/after-sales/presales/statistics")
        crm_source._remember_scope(request, [], synced=True)
        with patch.object(views, "sync_crm_presales"):
            statistics = self.data(presales_statistics(request))
        item = next(row for row in statistics["items"] if row["id"] == self.project.id)
        self.assertEqual((item["totalArea"], item["designArea"]), ("120.25", "80.00"))
        self.assertEqual(item["projectLevel"], "重要，金额大")
        self.assertEqual(item["urgency"], "紧急")
        self.assertEqual(item["expectedBidAt"], "2026-11-25")
        self.assertTrue(self.project.events.filter(event_type="project_updated").exists())

    def test_expected_bid_date_is_optional_validated_and_preserved_by_older_clients(self):
        values = {"totalArea": "12", "designArea": "0", "projectLevel": "特殊，金额大", "urgency": "紧急"}
        for expected in ("2028-02-29", "2026-11-25"):
            response = self.save_info({**values, "expectedBidAt": f" {expected} "})
            self.assertEqual(response.status_code, 200, response.content)
            self.project.refresh_from_db()
            self.assertEqual(self.project.business_data["projectInfo"]["expectedBidAt"], expected)
        version = project_draft_version(self.project)
        events = self.project.events.count()
        self.assertEqual(self.save_info({**values, "expectedBidAt": "2026-11-25"}).status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(project_draft_version(self.project), version)
        self.assertEqual(self.project.events.count(), events)
        for invalid in ("2026-02-29", "2026-11-31", "2026-1-2", "20261125", "2026-W48-3", "2026-11-25T12:00:00Z", "0000-01-01", [], {}, True, 1):
            with self.subTest(invalid=invalid):
                response = self.save_info({**values, "totalArea": "999", "expectedBidAt": invalid})
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(self.data(response)["code"], "INVALID_EXPECTED_BID_DATE")
                self.project.refresh_from_db()
                self.assertEqual(self.project.business_data["projectInfo"]["totalArea"], "12.00")
                self.assertEqual(self.project.business_data["projectInfo"]["expectedBidAt"], "2026-11-25")
        self.assertEqual(self.save_info({**values, "totalArea": "25"}).status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.business_data["projectInfo"]["expectedBidAt"], "2026-11-25")
        self.assertEqual(self.save({"totalArea": "26", "designArea": None}).status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.business_data["projectInfo"]["expectedBidAt"], "2026-11-25")
        stale = self.save_info({**values, "expectedBidAt": "2026-12-01"}, version=version)
        self.assertEqual(stale.status_code, 409, stale.content)
        for empty in ("", None):
            self.assertEqual(self.save_info({**values, "expectedBidAt": empty}).status_code, 200)
            self.project.refresh_from_db()
            self.assertEqual(self.project.business_data["projectInfo"]["expectedBidAt"], "")

    def test_urgency_is_optional_validated_and_preserved_by_older_metadata_clients(self):
        self.assertEqual(PRESALES_PROJECT_URGENCIES, ("一般", "紧急", "非常紧急"))
        values = {"totalArea": "12", "designArea": "0", "projectLevel": "特殊，金额大"}
        for urgency in PRESALES_PROJECT_URGENCIES:
            response = self.save_info({**values, "urgency": f" {urgency} "})
            self.assertEqual(response.status_code, 200, response.content)
            self.project.refresh_from_db()
            self.assertEqual(self.project.business_data["projectInfo"]["urgency"], urgency)
        version = project_draft_version(self.project)
        events = self.project.events.count()
        self.assertEqual(self.save_info({**values, "urgency": "非常紧急"}).status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(project_draft_version(self.project), version)
        self.assertEqual(self.project.events.count(), events, "an unchanged urgency adds no audit record")
        for invalid in ("自定义紧急程度", [], {}, True, 1):
            response = self.save_info({**values, "totalArea": "999", "urgency": invalid})
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(self.data(response)["code"], "INVALID_PROJECT_URGENCY")
            self.project.refresh_from_db()
            self.assertEqual(self.project.business_data["projectInfo"]["totalArea"], "12.00")
            self.assertEqual(self.project.business_data["projectInfo"]["urgency"], "非常紧急")
        self.assertEqual(self.save_info({**values, "totalArea": "25"}).status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.business_data["projectInfo"]["urgency"], "非常紧急")
        self.assertEqual(self.save({"totalArea": "26", "designArea": None}).status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.business_data["projectInfo"]["urgency"], "非常紧急")
        stale = self.save_info({**values, "urgency": "一般"}, version=version)
        self.assertEqual(stale.status_code, 409, stale.content)
        for empty in ("", None):
            self.assertEqual(self.save_info({**values, "urgency": empty}).status_code, 200)
            self.project.refresh_from_db()
            self.assertEqual(self.project.business_data["projectInfo"]["urgency"], "")

    def test_exact_six_levels_are_optional_and_legacy_area_updates_preserve_the_level(self):
        self.assertEqual(len(set(PRESALES_PROJECT_LEVELS)), 6)
        for level in PRESALES_PROJECT_LEVELS:
            response = self.save_info({"totalArea": "12", "designArea": "0", "projectLevel": level})
            self.assertEqual(response.status_code, 200, response.content)
            self.project.refresh_from_db()
            self.assertEqual(self.project.business_data["projectInfo"]["projectLevel"], level)
        self.assertEqual(self.save({"totalArea": "25", "designArea": None}).status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.business_data["projectInfo"]["projectLevel"], "重要，金额大")
        for level in ("", None):
            response = self.save_info({"totalArea": None, "designArea": None, "projectLevel": level})
            self.assertEqual(response.status_code, 200, response.content)
            self.project.refresh_from_db()
            self.assertEqual(self.project.business_data["projectInfo"]["projectLevel"], "")

    def test_invalid_project_info_is_atomic_and_cannot_write_source_fees_or_other_fields(self):
        valid = {"totalArea": "120", "designArea": "80", "projectLevel": "常规，金额小"}
        self.assertEqual(self.save_info(valid).status_code, 200)
        self.project.refresh_from_db()
        original_data = self.project.business_data.copy()
        invalid = [{**valid, "projectLevel": level} for level in ("自定义等级", "重要,金额大", [], {}, True, 1)]
        invalid.extend([{**valid, "totalArea": "-1"}, {**valid, "actualFee": "99"},
                        {"projectLevel": "重要，金额小"}, []])
        for info in invalid:
            with self.subTest(info=info):
                response = self.save_info(info)
                self.assertEqual(response.status_code, 400, response.content)
                self.project.refresh_from_db()
                self.assertEqual(self.project.business_data, original_data)

    def test_empty_and_zero_are_distinct_and_invalid_values_leave_data_unchanged(self):
        response = self.save({"totalArea": None, "designArea": "0"})
        self.assertEqual(response.status_code, 200, response.content)
        self.project.refresh_from_db()
        self.assertIsNone(self.project.business_data["projectInfo"]["totalArea"])
        self.assertEqual(self.project.business_data["projectInfo"]["designArea"], "0.00")
        for invalid in (-1, "abc", "NaN", "Infinity", "1.234", "10000000000", True, {}, []):
            with self.subTest(invalid=invalid):
                response = self.save({"totalArea": invalid, "designArea": "80"})
                self.assertEqual(response.status_code, 400, response.content)
                self.project.refresh_from_db()
                self.assertIsNone(self.project.business_data["projectInfo"]["totalArea"])
                self.assertEqual(self.project.business_data["projectInfo"]["designArea"], "0.00")
        response = self.save({"totalArea": "", "designArea": " "})
        self.assertEqual(response.status_code, 200, response.content)
        self.project.refresh_from_db()
        self.assertIsNone(self.project.business_data["projectInfo"]["designArea"])

    def test_stale_or_missing_version_cannot_overwrite_project_data(self):
        version = project_draft_version(self.project)
        self.assertEqual(self.save_info({"totalArea": "200", "designArea": "100", "projectLevel": "特殊，金额大"}).status_code, 200)
        stale = self.save_info({"totalArea": "10", "designArea": "5", "projectLevel": "常规，金额小"}, version=version)
        self.assertEqual(stale.status_code, 409, stale.content)
        missing = views.project_item(self.request("patch", "/", {
            "presalesProjectInfo": {"totalArea": "10", "designArea": "5", "projectLevel": "常规，金额小"},
        }), self.project.id)
        self.assertEqual(missing.status_code, 409, missing.content)
        self.project.refresh_from_db()
        self.assertEqual(self.project.business_data["projectInfo"]["totalArea"], "200.00")
        self.assertEqual(self.project.business_data["projectInfo"]["projectLevel"], "特殊，金额大")

    def test_crm_source_fields_are_preserved_and_crm_visibility_is_checked(self):
        self.project.source_crm_id = "crm-area"
        self.project.crm_snapshot = {"stage": "方案渗透"}
        self.project.save()
        request = self.request("patch", "/", {"presalesProjectInfo": {"totalArea": "50", "designArea": "20", "projectLevel": "重要，金额小", "urgency": "紧急", "expectedBidAt": "2026-11-25"},
            "expectedDraftVersion": project_draft_version(self.project)})
        crm_source._remember_scope(request, ["crm-area"], synced=True)
        with patch.object(crm_source, "_request_payload", return_value={"item": {"id": "crm-area"}}):
            response = views.project_item(request, self.project.id)
        self.assertEqual(response.status_code, 200, response.content)
        self.project.refresh_from_db()
        info = self.project.business_data["projectInfo"]
        self.assertEqual((self.project.name, info["name"], info["totalArea"]), ("面积填写项目", "面积填写项目", "50.00"))
        self.assertEqual(info["projectLevel"], "重要，金额小")
        crm_source._sync_row(self.request("get", "/"), {"id": "crm-area", "stage": "方案渗透",
            "name": "CRM 更新后的项目", "customerName": "学校", "owner": "销售负责人", "purchaseNeed": "新需求", "bidTime": "2026-12-01"})
        self.project.refresh_from_db()
        self.assertEqual(self.project.business_data["projectInfo"]["urgency"], "紧急", "CRM refresh preserves the locally maintained urgency")
        self.assertEqual(self.project.business_data["projectInfo"]["expectedBidAt"], "2026-11-25", "CRM bidTime never overwrites the locally maintained expected date")
        request = self.request("patch", "/", {"presalesProjectInfo": {"totalArea": "90", "designArea": "40", "projectLevel": "常规，金额大"},
            "expectedDraftVersion": project_draft_version(self.project)})
        crm_source._remember_scope(request, [], synced=True)
        with patch.object(crm_source, "_request_payload", side_effect=crm_source.CrmSourceError(
            "没有 CRM 项目权限", status=403, code="CRM_PERMISSION_DENIED",
        )):
            response = views.project_item(request, self.project.id)
        self.assertIn(response.status_code, (403, 404), response.content)

    def test_sales_and_service_roles_can_maintain_project_areas(self):
        for role in ("sales", "service"):
            user = f"area-{role}"
            AppPermissionRule.objects.create(permission=role, scope_type="employee", target_id=user)
            request = self.request("patch", "/", {"presalesProjectInfo": {"totalArea": "30", "designArea": "10", "projectLevel": "特殊，金额小"},
                "expectedDraftVersion": project_draft_version(self.project)}, user_id=user, admin=False)
            response = views.project_item(request, self.project.id)
            self.assertEqual(response.status_code, 200, response.content)
            self.project.refresh_from_db()

    def test_unauthorized_users_mobile_users_and_other_service_types_cannot_write(self):
        for user, mobile in (("unassigned", False), ("wxmini:area", True)):
            if mobile:
                ServiceProvider.objects.create(auth_user_id=user, name="小程序测试人员", certification_status="certified")
            request = self.request("patch", "/", {"presalesProjectInfo": {"totalArea": "30", "designArea": "10", "projectLevel": "特殊，金额小"},
                "expectedDraftVersion": project_draft_version(self.project)}, user_id=user, admin=False)
            with patch("after_sales_api.permissions.get_auth_user_department_scope", return_value={"departmentIds": []}):
                response = views.project_item(request, self.project.id)
            self.assertEqual(response.status_code, 403, response.content)
        self.project.service_type = "midsales"
        self.project.save(update_fields=["service_type"])
        response = self.save_info({"totalArea": "30", "designArea": "10", "projectLevel": "特殊，金额小"})
        self.assertEqual(response.status_code, 400, response.content)
