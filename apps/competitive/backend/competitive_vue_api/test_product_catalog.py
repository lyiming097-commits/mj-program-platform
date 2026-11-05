import json
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from . import product_catalog
from .product_catalog import _normalize_product, get_product_detail
from .product_views import product_options, products_collection


class ProductCatalogNormalizationTests(TestCase):
    def test_short_name_is_primary_and_three_level_hierarchy_is_explicit(self):
        product = _normalize_product({
            "id": 160,
            "kingdeeCode": "9.1.12.0160",
            "abbr": "尊享款讲桌",
            "label": "多功能电子讲台",
            "product_domain": "自制设备",
            "level_two": "智能讲台系列",
            "category": "讲台产品",
            "unit_price": "8000.00",
            "salesperson_price": "9000.00",
            "distributor_price": "10000.00",
            "budget_price": "12000.00",
            "market_reference_price": "15000.00",
            "is_active": True,
            "has_image": True,
        })

        self.assertEqual(product["name"], "尊享款讲桌")
        self.assertEqual(product["shortName"], "尊享款讲桌")
        self.assertEqual(product["fullName"], "多功能电子讲台")
        self.assertEqual(product["productDomain"], "自制设备")
        self.assertEqual(product["levelTwo"], "智能讲台系列")
        self.assertEqual(product["category"], "讲台产品")
        self.assertEqual(product["unitPrice"], "8000.00")
        self.assertEqual(product["salespersonPrice"], "9000.00")
        self.assertEqual(product["distributorPrice"], "10000.00")
        self.assertEqual(product["budgetPrice"], "12000.00")
        self.assertEqual(product["marketReferencePrice"], "15000.00")
        self.assertEqual(product["id"], "160")
        self.assertEqual(
            product["image"],
            "/api/competitive/products/160/image?variant=thumbnail",
        )
        self.assertEqual(
            product["imagePreview"],
            "/api/competitive/products/160/image?variant=preview",
        )

    def test_legacy_category_aliases_remain_supported(self):
        product = _normalize_product({
            "id": 161,
            "label": "旧目录产品",
            "product_domain": "合作设备",
            "category_a": "显示设备",
            "category_b": "智慧黑板",
        })

        self.assertEqual(product["name"], "旧目录产品")
        self.assertEqual(product["levelTwo"], "显示设备")
        self.assertEqual(product["category"], "智慧黑板")

    def test_zero_prices_are_not_treated_as_missing(self):
        product = _normalize_product({
            "id": 163,
            "label": "零价样品",
            "unit_price": 0,
            "salesperson_price": 0,
            "distributor_price": 0,
            "budget_price": 0,
            "market_reference_price": 0,
        })

        self.assertEqual(product["unitPrice"], "0")
        self.assertEqual(product["salespersonPrice"], "0")
        self.assertEqual(product["distributorPrice"], "0")
        self.assertEqual(product["budgetPrice"], "0")
        self.assertEqual(product["marketReferencePrice"], "0")

    def test_category_names_are_preserved_and_only_trimmed(self):
        product = _normalize_product({
            "id": 162,
            "label": "编号分类产品",
            "product_domain": " 自制设备 ",
            "level_two": " 2教室板书系列 ",
            "category": " 3单板产品 ",
            "product_domain_sort_order": 10,
            "category_a_sort_order": 20,
            "category_b_sort_order": 30,
        })

        self.assertEqual(product["productDomain"], "自制设备")
        self.assertEqual(product["levelTwo"], "2教室板书系列")
        self.assertEqual(product["category"], "3单板产品")
        self.assertEqual(product["productDomainSortOrder"], 10)
        self.assertEqual(product["levelTwoSortOrder"], 20)
        self.assertEqual(product["categorySortOrder"], 30)

    @patch.dict(os.environ, {
        "AUTH_SERVICE_INTROSPECTION_SECRET": "catalog-secret",
        "SERVICE_NAME": "competitive-backend",
        "PRODUCT_ARCHIVE_CATALOG_URL": "http://product-archive-backend:8000/api/internal/product-catalog/",
    })
    @patch("competitive_vue_api.product_catalog.httpx.get")
    def test_product_detail_collects_all_three_parameter_types(self, http_get):
        http_get.return_value.status_code = 200
        http_get.return_value.json.return_value = {
            "ok": True,
            "item": {
                "parameterRows": [
                    {"bid": "投标参数一", "tender": "招标参数一", "scheme": "方案参数一"},
                    {"bid": "投标参数二", "tender": "招标参数二", "scheme": "方案参数二"},
                    {"bid": "投标参数一", "tender": "", "scheme": ""},
                ],
            },
        }
        product = get_product_detail({"id": "160", "kingdeeCode": "P-160", "planPara": "旧方案"})

        self.assertEqual(product["bidPara"], "投标参数一\n投标参数二")
        self.assertEqual(product["tenderPara"], "招标参数一\n招标参数二")
        self.assertEqual(product["planPara"], "方案参数一\n方案参数二")
        self.assertEqual(
            http_get.call_args.args[0],
            "http://product-archive-backend:8000/api/internal/product-catalog/products/160/detail/",
        )
        request_headers = http_get.call_args.kwargs["headers"]
        self.assertEqual(request_headers["X-Internal-Service"], "competitive-backend")
        self.assertEqual(request_headers["X-Internal-Auth-Secret"], "catalog-secret")
        self.assertNotIn("Cookie", request_headers)
        self.assertNotIn("Authorization", request_headers)

    @patch.dict(os.environ, {"AUTH_SERVICE_INTROSPECTION_SECRET": "catalog-secret"})
    @patch("competitive_vue_api.product_catalog.cache")
    @patch("competitive_vue_api.product_catalog.httpx.get")
    def test_product_detail_falls_back_when_internal_detail_is_unavailable(self, http_get, product_cache):
        product_cache.get.return_value = None
        http_get.return_value.status_code = 503
        http_get.return_value.json.return_value = {"ok": False}

        product = get_product_detail({"id": "160", "kingdeeCode": "P-160", "planPara": "目录方案"})

        self.assertEqual(product["planPara"], "目录方案")
        self.assertNotIn("bidPara", product)

    @patch("competitive_vue_api.product_catalog.cache")
    @patch("competitive_vue_api.product_catalog.httpx.get")
    def test_product_detail_uses_shared_cache(self, http_get, product_cache):
        product_cache.get.return_value = {
            "bidPara": "缓存投标参数",
            "tenderPara": "缓存招标参数",
            "planPara": "缓存方案参数",
        }

        product = get_product_detail({"id": "160", "archiveUpdatedAt": "2026-09-09T10:00:00Z"})

        self.assertEqual(product["bidPara"], "缓存投标参数")
        self.assertEqual(product["planPara"], "缓存方案参数")
        http_get.assert_not_called()


class ProductCatalogStaleWhileRefreshTests(TestCase):
    def setUp(self):
        product_catalog._cached_at = 0.0
        product_catalog._cached_source_at = 0.0
        product_catalog._cached_products = []

    def tearDown(self):
        product_catalog._cached_at = 0.0
        product_catalog._cached_source_at = 0.0
        product_catalog._cached_products = []

    @patch("competitive_vue_api.product_catalog._schedule_background_refresh")
    @patch("competitive_vue_api.product_catalog._fetch_products_from_source")
    @patch("competitive_vue_api.product_catalog._shared_product_snapshot")
    def test_stale_snapshot_returns_without_waiting_for_source(
        self,
        shared_snapshot,
        fetch_source,
        schedule_refresh,
    ):
        shared_snapshot.return_value = ([{"id": "160", "name": "缓存产品"}], time.time() - 600)

        result = product_catalog.get_products()

        self.assertEqual(result[0]["name"], "缓存产品")
        fetch_source.assert_not_called()
        schedule_refresh.assert_called_once_with()

    @patch("competitive_vue_api.product_catalog._schedule_background_refresh")
    @patch("competitive_vue_api.product_catalog._shared_product_snapshot")
    def test_fresh_snapshot_does_not_schedule_refresh(self, shared_snapshot, schedule_refresh):
        shared_snapshot.return_value = ([{"id": "160", "name": "最新产品"}], time.time())

        result = product_catalog.get_products()

        self.assertEqual(result[0]["name"], "最新产品")
        schedule_refresh.assert_not_called()

    @patch("competitive_vue_api.product_catalog._schedule_background_refresh")
    @patch("competitive_vue_api.product_catalog._shared_product_snapshot")
    def test_empty_snapshot_is_a_valid_cached_catalog(self, shared_snapshot, schedule_refresh):
        shared_snapshot.return_value = ([], time.time())

        first = product_catalog.get_products()
        second = product_catalog.get_products()

        self.assertEqual(first, [])
        self.assertEqual(second, [])
        shared_snapshot.assert_called_once_with()
        schedule_refresh.assert_not_called()

    @patch("competitive_vue_api.product_catalog.httpx.Client")
    @patch("competitive_vue_api.product_catalog._request_page")
    def test_remaining_catalog_pages_are_fetched_in_parallel(self, request_page, http_client):
        barrier = threading.Barrier(2)
        worker_names = []

        def page_result(_client, page):
            if page == 1:
                return {"items": [{"id": 1}], "total": 3, "pageSize": 1}
            worker_names.append(threading.current_thread().name)
            barrier.wait(timeout=2)
            return {"items": [{"id": page}], "total": 3, "pageSize": 1}

        request_page.side_effect = page_result
        http_client.return_value.__enter__.return_value = object()

        result = product_catalog._fetch_products_from_source()

        self.assertEqual({item["id"] for item in result}, {"1", "2", "3"})
        self.assertEqual(len(set(worker_names)), 2)


class ProductCatalogViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.products = [
            {
                "id": "160", "name": "尊享款讲桌", "shortName": "尊享款讲桌",
                "fullName": "多功能电子讲台", "model": "MJ-160",
                "brand": "迈杰", "kingdeeCode": "9.1.12.0160", "productDomain": "自制设备",
                "levelTwo": "智能讲台系列", "category": "讲台产品", "categoryA": "智能讲台系列",
                "categoryB": "讲台产品", "coverage": "无竞品", "productDomainSortOrder": 10,
                "levelTwoSortOrder": 10, "categorySortOrder": 20,
                "planPara": "不应包含在列表响应中的大段方案参数",
                "specText": "不应包含在列表响应中的规格描述",
                "comments": "不应包含在列表响应中的备注",
            },
            {
                "id": "200", "name": "录播主机", "shortName": "录播主机",
                "fullName": "精品录播主机", "model": "MJ-200",
                "brand": "迈杰", "kingdeeCode": "P-200", "productDomain": "自制设备",
                "levelTwo": "录播系列", "category": "录播主机", "categoryA": "录播系列",
                "categoryB": "录播主机", "coverage": "无竞品", "productDomainSortOrder": 10,
                "levelTwoSortOrder": 20, "categorySortOrder": 10,
            },
            {
                "id": "300", "name": "合作产品", "shortName": "合作产品",
                "fullName": "合作产品", "model": "MJ-300",
                "brand": "合作品牌", "kingdeeCode": "P-300", "productDomain": "合作设备",
                "levelTwo": "显示设备", "category": "智慧黑板", "categoryA": "显示设备",
                "categoryB": "智慧黑板", "coverage": "无竞品", "productDomainSortOrder": 50,
                "levelTwoSortOrder": 10, "categorySortOrder": 10,
            },
        ]

    @patch("competitive_vue_api.product_views.request_access", return_value=(SimpleNamespace(), None))
    @patch("competitive_vue_api.product_views._products_with_coverage")
    def test_products_filter_all_three_levels_and_search_full_name(self, products, _access):
        products.return_value = self.products
        request = self.factory.get("/products", {
            "q": "多功能电子讲台",
            "productDomain": "自制设备",
            "levelTwo": "智能讲台系列",
            "category": "讲台产品",
        })

        payload = json.loads(products_collection(request).content)

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["name"], "尊享款讲桌")
        self.assertNotIn("planPara", payload["items"][0])
        self.assertNotIn("specText", payload["items"][0])
        self.assertNotIn("comments", payload["items"][0])
        self.assertEqual(payload["items"][0]["productDomain"], "自制设备")

    @patch("competitive_vue_api.product_views.request_access", return_value=(SimpleNamespace(), None))
    @patch("competitive_vue_api.product_views._products_with_coverage")
    def test_product_options_expose_three_level_cascade(self, products, _access):
        products.return_value = self.products

        payload = json.loads(product_options(self.factory.get("/products/options")).content)

        self.assertEqual(payload["domains"], ["自制设备", "合作设备"])
        self.assertEqual(payload["levelTwosByDomain"]["自制设备"], ["智能讲台系列", "录播系列"])
        self.assertEqual(
            payload["categoriesByPath"]["自制设备\u0000智能讲台系列"],
            ["讲台产品"],
        )

    @patch("competitive_vue_api.product_views.request_access", return_value=(SimpleNamespace(), None))
    @patch("competitive_vue_api.product_views._products_with_coverage")
    def test_product_page_can_include_filter_options(self, products, _access):
        products.return_value = self.products

        payload = json.loads(products_collection(self.factory.get("/products", {
            "productDomain": "自制设备",
            "includeOptions": "true",
            "pageSize": 20,
        })).content)

        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["options"]["domains"], ["自制设备", "合作设备"])
        self.assertEqual(
            payload["options"]["categoriesByPath"]["自制设备\u0000智能讲台系列"],
            ["讲台产品"],
        )
