import json
import uuid
from io import StringIO
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import RequestFactory, TestCase

from .action_views import (
    _normalize_merge_result,
    create_competitor,
    merge_submission,
    soft_delete_competitor,
    update_competitor,
)
from .domain import normalize_competitor_parameter_text, split_competitor_parameter_text
from .models import (
    Competitor,
    CompetitorParameter,
    CompetitorRelease,
    CompetitorStatus,
    Submission,
    SubmissionStatus,
)
from .serializers import serialize_submission
from .releases import ensure_current_release


class ActionViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, method, path, payload=None):
        request = getattr(self.factory, method)(
            path,
            data=json.dumps(payload or {}),
            content_type="application/json",
        )
        request.auth_user_id = "user-1"
        request.auth_user_name = "测试用户"
        request.auth_actor_name = ""
        return request

    def create_submission(self, **overrides):
        values = {
            "product_id": "product-1",
            "owner": "采集人员",
            "owner_user_id": "collector-1",
            "brand": "测试品牌",
            "name": "测试竞品",
            "model": "A1",
            "region": "华东",
            "location": "杭州市",
            "validity": "一年",
            "expires_on": date.today() + timedelta(days=365),
            "reminder_owner": "本人",
            "submitted_on": date.today(),
            "status": SubmissionStatus.PENDING,
        }
        values.update(overrides)
        return Submission.objects.create(**values)

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_create_competitor_accepts_empty_parameters_and_attachments(self, _access):
        submission = self.create_submission(competitor_parameters="")
        request = self.request(
            "post",
            f"/submissions/{submission.id}/create-competitor",
            {"submission": {}},
        )

        response = create_competitor(request, submission.id)

        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(submission.status, SubmissionStatus.ADOPTED)
        self.assertIsNotNone(submission.competitor_id)
        self.assertIsNotNone(submission.competitor_release_id)
        self.assertEqual(submission.competitor.parameters.count(), 0)
        self.assertEqual(submission.attachments.count(), 0)
        release = submission.competitor.releases.get()
        self.assertEqual(release.number, 1)
        self.assertTrue(release.is_current)

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_submission_can_merge_into_a_selected_existing_version(self, _access):
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="原品牌",
            name="原竞品",
            model="A1",
            updated_on=date.today(),
            expires_on=date.today() + timedelta(days=30),
        )
        release = ensure_current_release(competitor)
        submission = self.create_submission(name="新采集名称")
        request = self.request(
            "post",
            f"/submissions/{submission.id}/merge",
            {
                "competitorId": str(competitor.id),
                "versionId": str(release.id),
                "mode": "mergeExisting",
                "submission": {},
                "result": {
                    "brand": "原品牌",
                    "name": "归并后名称",
                    "model": "A1",
                    "expires": (date.today() + timedelta(days=60)).isoformat(),
                    "parameters": ["功率：30W"],
                },
            },
        )

        response = merge_submission(request, submission.id)

        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        release.refresh_from_db()
        competitor.refresh_from_db()
        self.assertEqual(competitor.releases.count(), 1)
        self.assertEqual(submission.competitor_release_id, release.id)
        self.assertEqual(release.name, "归并后名称")
        self.assertEqual(competitor.name, "归并后名称")
        self.assertEqual(release.parameters[0]["text"], "功率：30W")

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_invalid_merge_target_does_not_commit_submission_patch(self, _access):
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="原品牌",
            name="原竞品",
            model="A1",
            updated_on=date.today(),
            expires_on=date.today() + timedelta(days=30),
        )
        submission = self.create_submission(name="原采集名称")
        request = self.request(
            "post",
            f"/submissions/{submission.id}/merge",
            {
                "competitorId": str(competitor.id),
                "versionId": str(uuid.uuid4()),
                "mode": "mergeExisting",
                "submission": {"name": "不应保存的修改"},
                "result": {
                    "brand": "原品牌",
                    "name": "归并名称",
                    "model": "A1",
                    "expires": (date.today() + timedelta(days=60)).isoformat(),
                    "parameters": [],
                },
            },
        )

        response = merge_submission(request, submission.id)

        self.assertEqual(response.status_code, 404)
        submission.refresh_from_db()
        self.assertEqual(submission.name, "原采集名称")
        self.assertEqual(submission.status, SubmissionStatus.PENDING)

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_submission_can_create_an_independent_parallel_version(self, _access):
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="原品牌",
            name="第一版",
            model="A1",
            regions=["华东"],
            price="旧价格",
            advantage="旧优势",
            updated_on=date.today(),
            expires_on=date.today() + timedelta(days=30),
        )
        CompetitorParameter.objects.create(
            competitor=competitor,
            name="",
            competitor_value="旧参数：仅属于 V1",
        )
        first_release = ensure_current_release(competitor)
        self.create_submission(
            competitor=competitor,
            competitor_release=first_release,
            status=SubmissionStatus.ADOPTED,
        )
        competitor.sources = 1
        competitor.save(update_fields=["sources", "updated_at"])
        submission = self.create_submission(name="第二版采集", region="华南")
        request = self.request(
            "post",
            f"/submissions/{submission.id}/merge",
            {
                "competitorId": str(competitor.id),
                "mode": "newVersion",
                "submission": {},
                "result": {
                    "brand": "原品牌",
                    "name": "第二版",
                    "model": "B2",
                    "price": "新价格",
                    "advantage": "新优势",
                    "expires": (date.today() + timedelta(days=90)).isoformat(),
                    "parameters": ["亮度：500nit"],
                },
            },
        )

        response = merge_submission(request, submission.id)

        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        first_release.refresh_from_db()
        competitor.refresh_from_db()
        second_release = CompetitorRelease.objects.get(competitor=competitor, number=2)
        self.assertFalse(first_release.is_current)
        self.assertTrue(second_release.is_current)
        self.assertEqual(submission.competitor_release_id, second_release.id)
        self.assertEqual(second_release.name, "第二版")
        self.assertEqual(second_release.regions, [submission.region])
        self.assertEqual(second_release.price, "新价格")
        self.assertEqual(second_release.advantage, "新优势")
        self.assertEqual(first_release.parameters[0]["text"], "旧参数：仅属于 V1")
        self.assertEqual(second_release.parameters[0]["text"], "亮度：500nit")
        self.assertNotIn("华东", second_release.regions)
        self.assertEqual(competitor.name, "第二版")
        self.assertEqual(competitor.sources, 2)
        self.assertEqual(first_release.submissions.count(), 1)
        self.assertEqual(second_release.submissions.count(), 1)

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_merging_into_an_older_version_keeps_current_projection(self, _access):
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="品牌",
            name="第一版",
            model="A1",
            sources=1,
            updated_on=date.today(),
            expires_on=date.today() + timedelta(days=30),
        )
        first_release = ensure_current_release(competitor)
        first_source = self.create_submission(
            competitor=competitor,
            competitor_release=first_release,
            status=SubmissionStatus.ADOPTED,
        )
        first_release.is_current = False
        first_release.save(update_fields=["is_current", "updated_at"])
        second_release = CompetitorRelease.objects.create(
            competitor=competitor,
            number=2,
            brand="品牌",
            name="当前第二版",
            model="B2",
            regions=["华南"],
            parameters=[],
            changed_on=date.today(),
            expires_on=date.today() + timedelta(days=60),
            status=CompetitorStatus.NORMAL,
            is_current=True,
        )
        competitor.name = second_release.name
        competitor.model = second_release.model
        competitor.regions = second_release.regions
        competitor.expires_on = second_release.expires_on
        competitor.save()
        submission = self.create_submission(region="华北")
        request = self.request(
            "post",
            f"/submissions/{submission.id}/merge",
            {
                "competitorId": str(competitor.id),
                "versionId": str(first_release.id),
                "mode": "mergeExisting",
                "submission": {},
                "result": {
                    "brand": "品牌",
                    "name": "修订后的第一版",
                    "model": "A1",
                    "expires": (date.today() + timedelta(days=45)).isoformat(),
                    "parameters": [],
                },
            },
        )

        response = merge_submission(request, submission.id)

        self.assertEqual(response.status_code, 200)
        competitor.refresh_from_db()
        first_release.refresh_from_db()
        second_release.refresh_from_db()
        submission.refresh_from_db()
        self.assertEqual(first_source.competitor_release_id, first_release.id)
        self.assertEqual(submission.competitor_release_id, first_release.id)
        self.assertEqual(first_release.name, "修订后的第一版")
        self.assertEqual(competitor.name, "当前第二版")
        self.assertTrue(second_release.is_current)
        self.assertEqual(competitor.sources, 2)

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_create_competitor_splits_raw_parameter_text_into_full_items(self, _access):
        submission = self.create_submission(
            competitor_parameters="额定功率：30W / 工作电压：220V\n安装方式：壁挂"
        )
        request = self.request(
            "post",
            f"/submissions/{submission.id}/create-competitor",
            {"submission": {}},
        )

        response = create_competitor(request, submission.id)

        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(
            list(submission.competitor.parameters.values_list("competitor_value", flat=True)),
            ["额定功率：30W / 工作电压：220V", "安装方式：壁挂"],
        )

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_parameter_number_prefixes_are_removed(self, _access):
        submission = self.create_submission(
            competitor_parameters="1：规格：1100×780×1020 / 2：材料：桌面板 / 3、主体采用钢板"
        )
        request = self.request(
            "post",
            f"/submissions/{submission.id}/create-competitor",
            {"submission": {}},
        )

        response = create_competitor(request, submission.id)

        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(
            list(submission.competitor.parameters.values_list("competitor_value", flat=True)),
            ["规格：1100×780×1020", "材料：桌面板", "主体采用钢板"],
        )

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_parameter_number_prefixes_without_slashes_are_split(self, _access):
        submission = self.create_submission(
            competitor_parameters="1. 规格：1100×780×1020  2. 材料：桌面板  3. 主体采用钢板"
        )
        request = self.request(
            "post",
            f"/submissions/{submission.id}/create-competitor",
            {"submission": {}},
        )

        response = create_competitor(request, submission.id)

        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(
            list(submission.competitor.parameters.values_list("competitor_value", flat=True)),
            ["规格：1100×780×1020", "材料：桌面板", "主体采用钢板"],
        )

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_parameter_number_prefixes_match_collection_preview_formats(self, _access):
        submission = self.create_submission(
            competitor_parameters="参数如下：1.亮度；2.对比度；（3）色温；4：1.35W；5：2024-09-01"
        )
        request = self.request(
            "post",
            f"/submissions/{submission.id}/create-competitor",
            {"submission": {}},
        )

        response = create_competitor(request, submission.id)

        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(
            list(submission.competitor.parameters.values_list("competitor_value", flat=True)),
            ["亮度", "对比度", "色温", "1.35W", "2024-09-01"],
        )

    def test_parameter_parser_preserves_quantities_and_unit_slashes(self):
        text = (
            "1、标配 19 寸国标机架；\n"
            "2、下层右侧板预留不少于 1 个 86 盒安装位置；\n"
            "3、升降速度35mm/s，材料密度720kg/立方米，符合QB/T 2454-2013。"
        )

        self.assertEqual(
            split_competitor_parameter_text(text),
            [
                "标配 19 寸国标机架",
                "下层右侧板预留不少于 1 个 86 盒安装位置",
                "升降速度35mm/s，材料密度720kg/立方米，符合QB/T 2454-2013。",
            ],
        )

    def test_parameter_parser_treats_every_line_as_an_item_and_keeps_marker(self):
        text = (
            "一、外形尺寸\n"
            "1.桌面强\n"
            "度符合要求；\n"
            "▲2、升降速\n"
            "度35mm/s；\n"
            "二、音箱"
        )

        self.assertEqual(
            split_competitor_parameter_text(text),
            ["一、外形尺寸", "桌面强", "度符合要求", "▲升降速", "度35mm/s", "二、音箱"],
        )

    def test_parameter_parser_never_splits_on_slashes(self):
        self.assertEqual(
            split_competitor_parameter_text(
                "椅背：炭灰/灰/红 / 椅轮：60/25 / 协议：TCP/IP"
            ),
            ["椅背：炭灰/灰/红 / 椅轮：60/25 / 协议：TCP/IP"],
        )
        self.assertEqual(split_competitor_parameter_text("保留结尾斜杠/"), ["保留结尾斜杠/"])

    def test_parameter_parser_does_not_treat_decimals_as_number_prefixes(self):
        self.assertEqual(
            split_competitor_parameter_text(
                "参数如下：1.额定功率：1.35W 2.无线频段：2.4GHz\n3.日期：2024-09-01"
            ),
            ["额定功率：1.35W", "无线频段：2.4GHz", "日期：2024-09-01"],
        )
        self.assertEqual(split_competitor_parameter_text("15英寸\n1.35W"), ["15英寸", "1.35W"])

    def test_parameter_parser_splits_explicit_parameter_labels(self):
        self.assertEqual(
            split_competitor_parameter_text(
                "参数 1：1.规格：2400mm×1200mm / 参数2：2.接口：TCP/IP / 参数 3：3.速度：60/25mm/s"
            ),
            ["规格：2400mm×1200mm", "接口：TCP/IP", "速度：60/25mm/s"],
        )
        self.assertEqual(
            split_competitor_parameter_text("基础参数 1：保持为正文 / 参数补充说明"),
            ["基础参数 1：保持为正文 / 参数补充说明"],
        )

    def test_parameter_repair_command_only_changes_exact_legacy_output(self):
        raw = (
            "1、标配 19 寸国标机架；\n"
            "2、预留不少于 1 个 86 盒安装位置；\n"
            "3、安装完成。"
        )
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="品牌",
            name="名称",
            model="A1",
            updated_on=date.today(),
            expires_on=date.today() + timedelta(days=30),
        )
        self.create_submission(
            competitor=competitor,
            competitor_parameters=raw,
            status=SubmissionStatus.ADOPTED,
        )
        legacy_items = ["标配", "寸国标机架", "预留不少于", "个", "盒安装位置", "安装完成。"]
        CompetitorParameter.objects.bulk_create([
            CompetitorParameter(
                competitor=competitor,
                name=f"__text__:legacy-{index}",
                competitor_value=value,
                position=index,
            )
            for index, value in enumerate(legacy_items)
        ])

        call_command("repair_competitor_parameters", stdout=StringIO())
        self.assertEqual(
            list(competitor.parameters.values_list("competitor_value", flat=True)),
            legacy_items,
        )

        call_command("repair_competitor_parameters", apply=True, stdout=StringIO())
        self.assertEqual(
            list(competitor.parameters.values_list("competitor_value", flat=True)),
            [
                "标配 19 寸国标机架",
                "预留不少于 1 个 86 盒安装位置",
                "安装完成。",
            ],
        )
        self.assertEqual(competitor.versions.get().action, "系统修复")

    def test_legacy_parameter_rows_are_exposed_as_raw_text(self):
        submission = self.create_submission(
            competitor_parameters=[
                {"name": "额定功率", "value": "30W"},
                {"name": "安装方式", "value": "壁挂"},
            ]
        )

        self.assertEqual(
            normalize_competitor_parameter_text(submission.competitor_parameters),
            "额定功率：30W\n安装方式：壁挂",
        )
        self.assertEqual(
            serialize_submission(submission)["competitorParameterText"],
            "额定功率：30W\n安装方式：壁挂",
        )

    def test_merge_parameters_accept_full_text_items_and_remove_duplicates(self):
        result = _normalize_merge_result(
            {
                "brand": "测试品牌",
                "name": "测试竞品",
                "model": "A1",
                "expires": (date.today() + timedelta(days=365)).isoformat(),
                "parameters": ["额定功率：30W", "额定功率：30W", "安装方式：壁挂"],
            }
        )

        self.assertEqual(result["parameters"], ["额定功率：30W", "安装方式：壁挂"])
        self.assertEqual(
            split_competitor_parameter_text("额定功率：30W／安装方式：壁挂"),
            ["额定功率：30W／安装方式：壁挂"],
        )

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_manage=True), None),
    )
    def test_admin_soft_delete_hides_competitor_and_related_submissions(self, _access):
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="测试品牌",
            name="测试竞品",
            model="A1",
            updated_on=date.today(),
            expires_on=date.today() + timedelta(days=365),
        )
        submission = self.create_submission(
            competitor=competitor,
            status=SubmissionStatus.ADOPTED,
        )
        request = self.request("delete", f"/competitors/{competitor.id}")

        response = soft_delete_competitor(request, competitor.id)

        self.assertEqual(response.status_code, 200)
        competitor.refresh_from_db()
        submission.refresh_from_db()
        self.assertIsNotNone(competitor.deleted_at)
        self.assertEqual(submission.deleted_at, competitor.deleted_at)

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_reviewer_can_update_formal_competitor_and_parameters(self, request_access):
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="旧品牌",
            name="旧名称",
            model="A1",
            price="1000",
            dealer="旧经销商",
            advantage="旧优势",
            weakness="旧劣势",
            tactic="旧策略",
            updated_on=date.today() - timedelta(days=5),
            expires_on=date.today() + timedelta(days=30),
        )
        request = self.request(
            "patch",
            f"/competitors/{competitor.id}",
            {
                "brand": "新品牌",
                "name": "新名称",
                "model": "B2",
                "price": "2000",
                "dealer": "新经销商",
                "advantage": "新优势",
                "weakness": "新劣势",
                "tactic": "新策略",
                "expires": (date.today() + timedelta(days=365)).isoformat(),
                "competitorParameterText": "1. 功率：30W / 2. 安装方式：壁挂",
            },
        )

        response = update_competitor(request, competitor.id)

        self.assertEqual(response.status_code, 200)
        request_access.assert_called_once_with(request, "can_review")
        competitor.refresh_from_db()
        self.assertEqual(competitor.brand, "新品牌")
        self.assertEqual(competitor.name, "新名称")
        self.assertEqual(competitor.model, "B2")
        self.assertEqual(competitor.updated_on, date.today())
        self.assertEqual(competitor.status, CompetitorStatus.NORMAL)
        self.assertEqual(
            list(competitor.parameters.values_list("competitor_value", flat=True)),
            ["功率：30W", "安装方式：壁挂"],
        )
        version = competitor.versions.get()
        self.assertEqual(version.version, "V1")
        self.assertEqual(version.action, "人工编辑")
        self.assertEqual(version.changed_by, "测试用户")
        self.assertIn("品牌", version.note)
        self.assertIn("参数对照", version.note)
        payload = json.loads(response.content)
        self.assertEqual(payload["competitor"]["brand"], "新品牌")
        self.assertEqual([item["text"] for item in payload["parameters"]], ["功率：30W", "安装方式：壁挂"])
        self.assertEqual(payload["version"]["action"], "人工编辑")

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_formal_competitor_update_preserves_manually_split_parameters(self, _access):
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="品牌",
            name="名称",
            model="A1",
            updated_on=date.today(),
            expires_on=date.today() + timedelta(days=30),
        )
        parameters = ["功率：30W / 备用接口", "协议：QB/T 2454"]
        request = self.request(
            "patch",
            f"/competitors/{competitor.id}",
            {
                "brand": competitor.brand,
                "name": competitor.name,
                "model": competitor.model,
                "expires": competitor.expires_on.isoformat(),
                "parameters": parameters,
            },
        )

        response = update_competitor(request, competitor.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(competitor.parameters.values_list("competitor_value", flat=True)),
            parameters,
        )

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_formal_competitor_update_only_changes_selected_older_version(self, _access):
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="品牌",
            name="当前第二版",
            model="B2",
            updated_on=date.today(),
            expires_on=date.today() + timedelta(days=60),
        )
        first_release = CompetitorRelease.objects.create(
            competitor=competitor,
            number=1,
            brand="品牌",
            name="第一版",
            model="A1",
            regions=["华东"],
            parameters=[],
            changed_on=date.today() - timedelta(days=30),
            expires_on=date.today() + timedelta(days=30),
            status=CompetitorStatus.NORMAL,
            is_current=False,
        )
        second_release = CompetitorRelease.objects.create(
            competitor=competitor,
            number=2,
            brand=competitor.brand,
            name=competitor.name,
            model=competitor.model,
            regions=[],
            parameters=[],
            changed_on=competitor.updated_on,
            expires_on=competitor.expires_on,
            status=competitor.status,
            is_current=True,
        )
        request = self.request(
            "patch",
            f"/competitors/{competitor.id}",
            {
                "versionId": str(first_release.id),
                "brand": "品牌",
                "name": "修订后的第一版",
                "model": "A1",
                "expires": first_release.expires_on.isoformat(),
                "parameters": ["功率：10W"],
            },
        )

        response = update_competitor(request, competitor.id)

        self.assertEqual(response.status_code, 200)
        competitor.refresh_from_db()
        first_release.refresh_from_db()
        second_release.refresh_from_db()
        self.assertEqual(first_release.name, "修订后的第一版")
        self.assertEqual(first_release.parameters[0]["text"], "功率：10W")
        self.assertEqual(competitor.name, "当前第二版")
        self.assertEqual(second_release.name, "当前第二版")
        self.assertTrue(second_release.is_current)
        self.assertEqual(competitor.versions.count(), 1)

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_formal_competitor_update_rejects_invalid_payload(self, _access):
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="原品牌",
            name="原名称",
            model="A1",
            updated_on=date.today(),
            expires_on=date.today() + timedelta(days=30),
        )
        request = self.request(
            "patch",
            f"/competitors/{competitor.id}",
            {
                "brand": "",
                "name": "原名称",
                "expires": competitor.expires_on.isoformat(),
            },
        )

        response = update_competitor(request, competitor.id)

        self.assertEqual(response.status_code, 422)
        competitor.refresh_from_db()
        self.assertEqual(competitor.brand, "原品牌")
        self.assertFalse(competitor.versions.exists())

    @patch(
        "competitive_vue_api.action_views.request_access",
        return_value=(SimpleNamespace(can_review=True), None),
    )
    def test_formal_competitor_noop_update_does_not_create_version(self, _access):
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="品牌",
            name="名称",
            model="A1",
            price="1000",
            dealer="经销商",
            advantage="优势",
            weakness="劣势",
            tactic="策略",
            updated_on=date.today(),
            expires_on=date.today() + timedelta(days=30),
        )
        request = self.request(
            "patch",
            f"/competitors/{competitor.id}",
            {
                "brand": competitor.brand,
                "name": competitor.name,
                "model": competitor.model,
                "price": competitor.price,
                "dealer": competitor.dealer,
                "advantage": competitor.advantage,
                "weakness": competitor.weakness,
                "tactic": competitor.tactic,
                "expires": competitor.expires_on.isoformat(),
                "competitorParameterText": "",
            },
        )

        response = update_competitor(request, competitor.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["changedFields"], [])
        self.assertFalse(competitor.versions.exists())
