import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from .board_cache import get_competitor_board_summary, invalidate_competitor_board_summary
from .competitor_views import competitor_board_summary, competitor_detail, competitors_collection
from .models import (
    Competitor,
    CompetitorRelease,
    Submission,
    SubmissionAttachment,
    SubmissionStatus,
)
from .releases import ensure_current_release


class BoardSummaryTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.today = date.today()

    def tearDown(self):
        invalidate_competitor_board_summary()

    def create_competitor(self, product_id, regions, updated_on):
        return Competitor.objects.create(
            product_id=product_id,
            brand="品牌",
            name=f"竞品-{product_id}",
            model="型号",
            regions=regions,
            updated_on=updated_on,
            expires_on=self.today + timedelta(days=30),
        )

    def create_submission(self, competitor, *, submitted_on=None):
        return Submission.objects.create(
            competitor=competitor,
            product_id=competitor.product_id,
            owner="业务员",
            brand=competitor.brand,
            name=competitor.name,
            model=competitor.model,
            region="浙江省",
            validity="一年",
            expires_on=self.today + timedelta(days=365),
            reminder_owner="本人",
            status=SubmissionStatus.ADOPTED,
            submitted_on=submitted_on or self.today,
        )

    @patch(
        "competitive_vue_api.competitor_views.request_access",
        return_value=(SimpleNamespace(), None),
    )
    def test_board_summary_aggregates_count_regions_and_latest_update(self, _access):
        self.create_competitor("product-1", ["杭州", "宁波"], self.today - timedelta(days=2))
        self.create_competitor("product-1", ["杭州"], self.today)
        self.create_competitor("product-2", [], self.today - timedelta(days=1))

        response = competitor_board_summary(self.factory.get("/competitors/board-summary"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.content),
            {
                "items": [
                    {
                        "productId": "product-1",
                        "count": 2,
                        "regionCount": 2,
                        "latestUpdate": self.today.isoformat(),
                    },
                    {
                        "productId": "product-2",
                        "count": 1,
                        "regionCount": 0,
                        "latestUpdate": (self.today - timedelta(days=1)).isoformat(),
                    },
                ],
            },
        )
        self.assertEqual(response["Cache-Control"], "private, max-age=15")

    def test_summary_cache_reuses_result_until_invalidated(self):
        self.create_competitor("product-1", ["杭州"], self.today)

        first = get_competitor_board_summary()
        Competitor.objects.filter(product_id="product-1").update(name="更新后的竞品")
        second = get_competitor_board_summary()

        self.assertEqual(first, second)
        invalidate_competitor_board_summary()
        self.assertEqual(get_competitor_board_summary()[0]["count"], 1)

    @patch(
        "competitive_vue_api.competitor_views.request_access",
        return_value=(SimpleNamespace(), None),
    )
    @patch("competitive_vue_api.competitor_views.sync_expiry_statuses")
    @patch(
        "competitive_vue_api.competitor_views.get_products",
        return_value=[{
            "id": "product-2",
            "name": "关联产品",
            "fullName": "关联产品全称",
            "hasImage": True,
        }],
    )
    def test_competitor_list_paginates_before_serializing(self, _products, _sync, _access):
        self.create_competitor("product-1", [], self.today)
        self.create_competitor("product-2", [], self.today - timedelta(days=1))
        self.create_competitor("product-3", [], self.today - timedelta(days=2))

        response = competitors_collection(
            self.factory.get("/competitors", {"page": 2, "pageSize": 1})
        )
        payload = json.loads(response.content)

        self.assertEqual(payload["total"], 3)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["productId"], "product-2")
        self.assertEqual(payload["items"][0]["product"]["name"], "关联产品")
        self.assertTrue(payload["items"][0]["product"]["hasImage"])
        self.assertIsNone(payload["items"][0]["coverSubmission"])
        self.assertEqual(response["Cache-Control"], "private, max-age=5")

    @patch(
        "competitive_vue_api.competitor_views.request_access",
        return_value=(SimpleNamespace(), None),
    )
    @patch("competitive_vue_api.competitor_views.sync_expiry_statuses")
    @patch("competitive_vue_api.competitor_views.get_products", return_value=[])
    def test_competitor_list_cover_prefers_product_image_then_first_image(
        self, _products, _sync, _access
    ):
        preferred = self.create_competitor("product-1", [], self.today)
        preferred_source = self.create_submission(preferred)
        SubmissionAttachment.objects.create(
            submission=preferred_source,
            filename="普通图片.png",
            byte_size=100,
            media_type="image/png",
            category="技术参数",
        )
        product_image = SubmissionAttachment.objects.create(
            submission=preferred_source,
            filename="产品图片.jpg",
            byte_size=100,
            media_type="image/jpeg",
            category="产品图片",
        )

        fallback = self.create_competitor("product-2", [], self.today - timedelta(days=1))
        fallback_source = self.create_submission(fallback)
        SubmissionAttachment.objects.create(
            submission=fallback_source,
            filename="不是图片.pdf",
            byte_size=100,
            media_type="application/pdf",
            category="产品图片",
        )
        first_image = SubmissionAttachment.objects.create(
            submission=fallback_source,
            filename="现场图片.webp",
            byte_size=100,
            media_type=" IMAGE/WEBP ",
            category="渠道信息",
        )

        response = competitors_collection(
            self.factory.get("/competitors", {"page": 1, "pageSize": 20})
        )
        items = {item["productId"]: item for item in json.loads(response.content)["items"]}

        self.assertEqual(
            items["product-1"]["coverSubmission"],
            {
                "id": str(preferred_source.id),
                "attachments": [
                    {
                        "id": str(product_image.id),
                        "name": "产品图片.jpg",
                        "type": "image/jpeg",
                        "category": "产品图片",
                    }
                ],
            },
        )
        self.assertEqual(
            items["product-2"]["coverSubmission"]["attachments"][0]["id"],
            str(first_image.id),
        )

    @patch(
        "competitive_vue_api.competitor_views.request_access",
        return_value=(SimpleNamespace(), None),
    )
    @patch("competitive_vue_api.competitor_views.sync_expiry_statuses")
    @patch("competitive_vue_api.competitor_views.get_product", return_value=None)
    def test_detail_keeps_history_when_catalog_product_is_missing(
        self, _get_product, _sync, _access
    ):
        competitor = self.create_competitor("486", ["杭州"], self.today)

        response = competitor_detail(
            self.factory.get(f"/competitors/{competitor.id}/detail"), competitor.id
        )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["product"]["id"], "486")
        self.assertEqual(payload["product"]["name"], "历史产品（ID: 486）")
        self.assertTrue(payload["product"]["archiveUnavailable"])

    @patch(
        "competitive_vue_api.competitor_views.request_access",
        return_value=(SimpleNamespace(), None),
    )
    @patch("competitive_vue_api.competitor_views.sync_expiry_statuses")
    @patch("competitive_vue_api.competitor_views.get_product_detail")
    @patch("competitive_vue_api.competitor_views.get_product")
    def test_detail_loads_current_catalog_product(
        self, get_product, get_product_detail, _sync, _access
    ):
        competitor = self.create_competitor("486", ["杭州"], self.today)
        catalog_product = {"id": "486", "name": "自制产品"}
        product_detail = {**catalog_product, "bidPara": "投标参数"}
        get_product.return_value = catalog_product
        get_product_detail.return_value = product_detail

        response = competitor_detail(
            self.factory.get(f"/competitors/{competitor.id}/detail"), competitor.id
        )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["product"], product_detail)
        get_product_detail.assert_called_once_with(catalog_product)

    @patch(
        "competitive_vue_api.competitor_views.request_access",
        return_value=(SimpleNamespace(), None),
    )
    @patch("competitive_vue_api.competitor_views.sync_expiry_statuses")
    @patch("competitive_vue_api.competitor_views.get_product", return_value=None)
    def test_detail_includes_source_location_for_map(self, _product, _sync, _access):
        competitor = self.create_competitor("486", ["杭州"], self.today)
        located_at = datetime(2026, 9, 8, 8, 30, tzinfo=timezone.utc)
        submission = Submission.objects.create(
            competitor=competitor,
            product_id="486",
            owner="业务员",
            brand="品牌",
            name="竞品",
            model="A1",
            competitor_parameters="参数一 / 参数二 / 协议：QB/T 2454",
            region="浙江省",
            city="杭州市",
            location="浙江省杭州市西湖区文三路",
            located=True,
            latitude=30.2741,
            longitude=120.1551,
            location_accuracy=18,
            located_at=located_at,
            location_source="device",
            validity="一年",
            expires_on=self.today + timedelta(days=365),
            reminder_owner="本人",
            status=SubmissionStatus.ADOPTED,
            submitted_on=self.today,
        )

        response = competitor_detail(
            self.factory.get(f"/competitors/{competitor.id}/detail"), competitor.id
        )
        source = json.loads(response.content)["regionSources"][0]

        self.assertEqual(source["id"], str(submission.id))
        self.assertEqual(source["location"], "浙江省杭州市西湖区文三路")
        self.assertTrue(source["located"])
        self.assertEqual(source["latitude"], 30.2741)
        self.assertEqual(source["longitude"], 120.1551)
        self.assertEqual(source["locationAccuracy"], 18)
        self.assertEqual(source["locatedAt"], located_at.isoformat())
        self.assertEqual(source["locationSource"], "device")
        self.assertEqual(
            json.loads(response.content)["parameterSource"],
            {
                "submissionId": str(submission.id),
                "owner": "业务员",
                "date": self.today.isoformat(),
                "text": "参数一 / 参数二 / 协议：QB/T 2454",
            },
        )

    @patch(
        "competitive_vue_api.competitor_views.request_access",
        return_value=(SimpleNamespace(), None),
    )
    @patch("competitive_vue_api.competitor_views.sync_expiry_statuses")
    @patch("competitive_vue_api.competitor_views.get_product", return_value=None)
    def test_detail_switches_fields_and_sources_by_formal_version(
        self, _product, _sync, _access
    ):
        competitor = self.create_competitor("486", ["华东"], self.today)
        competitor.name = "第一版"
        competitor.save(update_fields=["name", "updated_at"])
        first = ensure_current_release(competitor)
        first_source = Submission.objects.create(
            competitor=competitor,
            competitor_release=first,
            product_id="486",
            owner="第一位业务员",
            brand="品牌",
            name="第一版",
            model="A1",
            region="华东",
            validity="一年",
            expires_on=self.today + timedelta(days=30),
            reminder_owner="本人",
            status=SubmissionStatus.ADOPTED,
            submitted_on=self.today,
        )
        first.is_current = False
        first.save(update_fields=["is_current", "updated_at"])
        second = CompetitorRelease.objects.create(
            competitor=competitor,
            number=2,
            brand="品牌",
            name="第二版",
            model="B2",
            regions=["华南"],
            parameters=[{"text": "亮度：500nit"}],
            changed_on=self.today,
            expires_on=self.today + timedelta(days=60),
            status="正常",
            note="第二版",
            created_by="审核员",
            is_current=True,
        )
        Submission.objects.create(
            competitor=competitor,
            competitor_release=second,
            product_id="486",
            owner="第二位业务员",
            brand="品牌",
            name="第二版",
            model="B2",
            region="华南",
            validity="一年",
            expires_on=self.today + timedelta(days=60),
            reminder_owner="本人",
            status=SubmissionStatus.ADOPTED,
            submitted_on=self.today,
        )

        response = competitor_detail(
            self.factory.get(
                f"/competitors/{competitor.id}/detail",
                {"versionId": str(first.id)},
            ),
            competitor.id,
        )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["competitor"]["name"], "第一版")
        self.assertEqual(payload["selectedVersion"]["id"], str(first.id))
        self.assertEqual(len(payload["versions"]), 2)
        self.assertEqual(
            [item["id"] for item in payload["regionSources"]],
            [str(first_source.id)],
        )
