from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from django.urls import resolve

from . import product_catalog_client, views
from .product_search import matches_product
from .models import ProjectAssignment, ServiceProject, ServiceProvider
from .tests import RequestMixin


AFTERSALES_DATA_WITHOUT_PRODUCTS = {
    "managerContact": "13800000000",
    "expectedDuration": "1天",
    "feeAgreement": "客户承担",
    "feeRemark": "按实际服务结算",
}

CATALOG_PRODUCT = {
    "productId": 901,
    "kingdeeCode": "KD-901",
    "name": "智慧讲台",
    "brand": "迈杰",
    "model": "MJ-901",
    "abbr": "智慧讲台",
    "productDomain": "自制设备",
    "categoryA": "自制设备",
    "categoryB": "智慧教室",
    "categoryC": "讲台",
    "unit": "台",
    "lifecycle": "成熟产品",
    "isActive": True,
    "productThumb": "/api/after-sales/product-catalog/901/image?variant=thumbnail",
    "productPreview": "/api/after-sales/product-catalog/901/image?variant=preview",
    "manuals": [
        {"key": "productManual", "label": "产品说明书", "url": "/files/product_archive/manual.pdf?token=signed"},
    ],
}


class RelatedProductTests(RequestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def create_aftersales_project(self) -> ServiceProject:
        response = views.projects_collection(self.request(
            "post",
            "/api/after-sales/projects",
            {
                "serviceType": "aftersales",
                "name": "关联产品测试",
                "customer": "测试客户",
                "ownerName": "系统管理员",
                "address": "杭州测试地址",
                "summary": "现场任务说明",
                "businessData": AFTERSALES_DATA_WITHOUT_PRODUCTS,
                "disabledNodeKeys": ["mail-service", "school-inspection"],
            },
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        return ServiceProject.objects.get(pk=self.data(response)["item"]["id"])

    def create_midsales_project(self) -> ServiceProject:
        response = views.projects_collection(self.request(
            "post",
            "/api/after-sales/projects",
            {
                "serviceType": "midsales",
                "name": "售中关联产品测试",
                "customer": "测试客户",
                "ownerName": "系统管理员",
            },
        ))
        self.assertEqual(response.status_code, 201, self.data(response))
        return ServiceProject.objects.get(pk=self.data(response)["item"]["id"])

    def test_aftersales_can_be_created_without_product_details(self):
        project = self.create_aftersales_project()

        self.assertNotIn("products", project.business_data)
        self.assertEqual(project.business_data.get("relatedProducts", []), [])

    @patch("after_sales_api.views.fetch_product_catalog")
    def test_product_picker_catalog_exposes_manual_links_for_direct_viewing(self, fetch_catalog):
        fetch_catalog.return_value = {
            "items": [CATALOG_PRODUCT],
            "total": 1,
            "page": 1,
            "pageSize": 24,
            "categoriesA": ["自制设备"],
            "categoriesB": ["智慧教室"],
            "categoriesC": ["讲台"],
        }

        response = views.product_catalog(self.request(
            "get",
            "/api/after-sales/product-catalog",
            query={"q": "讲台", "page": 1, "pageSize": 24},
        ))

        self.assertEqual(response.status_code, 200, self.data(response))
        manual = self.data(response)["items"][0]["manuals"][0]
        self.assertEqual(manual, {
            "key": "productManual",
            "label": "产品说明书",
            "url": "/files/product_archive/manual.pdf?token=signed",
        })
        fetch_catalog.assert_called_once()

    @patch("after_sales_api.views.fetch_products_by_ids")
    def test_linked_product_detail_reads_full_catalog_record(self, fetch_products):
        fetch_products.return_value = {901: {
            **CATALOG_PRODUCT,
            "configInfo": "产品功能说明",
            "parameterRows": [{"id": "p1", "scheme": "方案参数", "tender": "", "bid": ""}],
        }}
        path = "/api/after-sales/product-catalog/901"
        self.assertEqual(resolve(path).func, views.product_catalog_item)

        response = views.product_catalog_item(self.request("get", path), 901)

        self.assertEqual(response.status_code, 200, self.data(response))
        product = self.data(response)["item"]
        self.assertEqual(product["configInfo"], "产品功能说明")
        self.assertEqual(product["parameterRows"][0]["scheme"], "方案参数")
        self.assertEqual(product["manuals"][0]["url"], CATALOG_PRODUCT["manuals"][0]["url"])
        fetch_products.assert_called_once_with([901])

    @patch("after_sales_api.views.fetch_products_by_ids", return_value={})
    def test_linked_product_detail_reports_missing_product(self, _fetch_products):
        response = views.product_catalog_item(self.request("get", "/api/after-sales/product-catalog/901"), 901)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.data(response)["code"], "PRODUCT_NOT_FOUND")

    @patch("after_sales_api.views.fetch_products_by_ids")
    def test_wechat_user_cannot_read_catalog_product_detail(self, fetch_products):
        request = self.request("get", "/api/after-sales/product-catalog/901", admin=False)
        request.auth_token_claims = {"chn": "wechat-mini", "aud": "after-sales-mobile"}

        response = views.product_catalog_item(request, 901)

        self.assertEqual(response.status_code, 403)
        fetch_products.assert_not_called()

    @patch("after_sales_api.product_catalog_client._request_json")
    def test_catalog_client_maps_three_level_category_path(self, request_json):
        request_json.return_value = {
            "items": [{
                "id": 901,
                "label": "智慧讲台",
                "product_domain": "自制设备",
                "category_a": "智慧教室",
                "category_b": "讲台",
            }],
            "total": 1,
            "page": 1,
            "pageSize": 24,
            "productDomains": ["自制设备"],
            "categoriesA": ["智慧教室"],
            "categoriesB": ["讲台"],
        }

        payload = product_catalog_client.fetch_product_catalog({
            "categoryA": "自制设备",
            "categoryB": "智慧教室",
            "categoryC": "讲台",
            "page": 1,
            "pageSize": 24,
        })

        self.assertEqual(payload["categoriesA"], ["自制设备"])
        self.assertEqual(payload["categoriesB"], ["智慧教室"])
        self.assertEqual(payload["categoriesC"], ["讲台"])
        self.assertEqual(
            [payload["items"][0][key] for key in ("categoryA", "categoryB", "categoryC")],
            ["自制设备", "智慧教室", "讲台"],
        )
        request_json.assert_called_once_with("products/", params={
            "page": 1,
            "pageSize": 24,
            "productDomain": "自制设备",
            "categoryA": "智慧教室",
            "categoryB": "讲台",
            "includeManuals": "1",
        })

    def test_catalog_search_matches_mall_fuzzy_rules(self):
        product = {
            "abbr": "乐享款讲台", "label": "智慧多功能讲台", "product_model": "ELCP-H22C",
            "product_brand": "迈杰", "kingdeeCode": "KD-901", "category_a": "智慧教室",
        }
        for query in ("乐享", "lxkjt", "LXK JT", "迈杰KD-901", "elcp-h2c", "智慧 教室", "KD901"):
            self.assertTrue(matches_product(query, product), query)
        self.assertTrue(matches_product("讲台子", product))
        self.assertFalse(matches_product("无关产品", product))
        self.assertFalse(matches_product("abc", product))

    def test_management_project_list_searches_pinyin_without_bypassing_visibility(self):
        project = self.create_aftersales_project()
        response = views.projects_collection(self.request(
            "get", "/api/after-sales/projects", query={"search": "glcpcs", "type": "aftersales"},
        ))
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertIn(project.id, [row["id"] for row in self.data(response)["items"]])
        no_match = views.projects_collection(self.request(
            "get", "/api/after-sales/projects", query={"search": "wqrrcc", "type": "aftersales"},
        ))
        self.assertEqual(self.data(no_match)["total"], 0)

    @patch("after_sales_api.product_catalog_client._request_json")
    def test_fuzzy_catalog_search_scans_before_pagination_and_fetches_only_selected_details(self, request_json):
        products = [{"id": index, "abbr": f"普通产品{index}"} for index in range(1, 200)]
        products += [{"id": 200, "abbr": "乐享款讲台", "product_model": "ELCP-H22C"}]
        products += [{"id": 201, "abbr": "智能演讲台"}]
        options = {"productDomains": ["自制设备"], "categoriesA": ["智慧教室"], "categoriesB": ["讲台"]}

        def response(_path, *, params):
            if params.get("productIds"):
                ids = {int(value) for value in params["productIds"].split(",")}
                return {"items": [{**row, "manuals": [{"key": "manual", "url": "/manual.pdf"}]} for row in products if row["id"] in ids]}
            number = params["page"]
            return {"items": products[(number - 1) * 200:number * 200], "total": len(products), **(options if number == 1 else {})}

        request_json.side_effect = response
        result = product_catalog_client.fetch_product_catalog({
            "q": "LXKJT", "categoryA": "自制设备", "page": 1, "pageSize": 1,
        })
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["productId"], 200)
        self.assertEqual(result["items"][0]["manuals"][0]["url"], "/manual.pdf")
        self.assertEqual(result["categoriesC"], ["讲台"])
        self.assertEqual([call.kwargs["params"]["page"] for call in request_json.call_args_list[:2]], [1, 2])
        self.assertEqual(request_json.call_args.kwargs["params"]["productIds"], "200")

        request_json.reset_mock()
        result = product_catalog_client.fetch_product_catalog({"q": "讲台", "page": 2, "pageSize": 1})
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["items"][0]["productId"], 201)

        request_json.reset_mock()
        result = product_catalog_client.fetch_product_catalog({"q": "不存在", "page": 1, "pageSize": 1})
        self.assertEqual(result["items"], [])
        self.assertEqual(result["total"], 0)
        request_json.assert_not_called()

    @patch("after_sales_api.product_catalog_client._request_json")
    def test_catalog_client_maps_ordered_gallery_to_local_image_proxy(self, request_json):
        source = "http://product-archive-backend:8000/api/internal/product-catalog/products/901/image/"
        request_json.return_value = {
            "items": [{
                "id": 901,
                "label": "智慧讲台",
                "has_image": True,
                "product_images": [
                    f"{source}?slot=cover&variant=thumbnail",
                    f"{source}?slot=detail-1&variant=thumbnail",
                    f"{source}?slot=other-2&variant=thumbnail",
                    "https://example.com/other?slot=cover&variant=thumbnail",
                    f"{source}?slot=detail-1&variant=thumbnail",
                ],
            }],
        }

        product = product_catalog_client.fetch_product_catalog()["items"][0]

        self.assertEqual([image["slot"] for image in product["productImages"]], ["cover", "detail-1", "other-2"])
        self.assertEqual(product["productImages"][1], {
            "slot": "detail-1",
            "thumbnail": "/api/after-sales/product-catalog/901/image?slot=detail-1&variant=thumbnail",
            "preview": "/api/after-sales/product-catalog/901/image?slot=detail-1&variant=preview",
        })
        self.assertEqual(product["productPreview"], "/api/after-sales/product-catalog/901/image?variant=preview")
        self.assertEqual(product_catalog_client._normalize_product({"id": 902})["productImages"], [])

    @patch("after_sales_api.product_catalog_client._request", return_value=(b"image", "image/jpeg"))
    def test_catalog_client_proxies_only_supported_image_slots(self, request_image):
        self.assertEqual(product_catalog_client.fetch_product_image(901, variant="preview", slot="detail-2"), (b"image", "image/jpeg"))
        request_image.assert_called_once_with(
            "products/901/image/", params={"variant": "preview", "slot": "detail-2"}, max_bytes=1024 * 1024,
        )
        with self.assertRaises(product_catalog_client.ProductCatalogError):
            product_catalog_client.fetch_product_image(901, slot="../../secret")
        self.assertEqual(request_image.call_count, 1)

    @patch("after_sales_api.views.fetch_products_by_ids", return_value={901: CATALOG_PRODUCT})
    def test_admin_links_validated_catalog_product_as_project_snapshot(self, fetch_products):
        project = self.create_aftersales_project()
        request = self.request(
            "patch",
            f"/api/after-sales/projects/{project.id}/related-products",
            {"productIds": [901]},
        )

        response = views.project_related_products(request, project.id)

        self.assertEqual(response.status_code, 200, self.data(response))
        project.refresh_from_db()
        snapshot = project.business_data["relatedProducts"][0]
        self.assertEqual(snapshot["productId"], 901)
        self.assertEqual(snapshot["name"], "智慧讲台")
        self.assertEqual(snapshot["productThumb"], "/api/after-sales/product-catalog/901/image?variant=thumbnail")
        self.assertEqual(snapshot["manuals"], [{"key": "productManual", "label": "产品说明书"}])
        self.assertNotIn("url", snapshot["manuals"][0])
        fetch_products.assert_called_once_with([901])

    @patch("after_sales_api.views.fetch_products_by_ids", return_value={901: CATALOG_PRODUCT})
    def test_admin_links_product_to_only_the_selected_midsales_node(self, fetch_products):
        project = self.create_midsales_project()

        response = views.project_node_related_products(
            self.request(
                "patch",
                f"/api/after-sales/projects/{project.id}/nodes/device-debug/related-products",
                {"productIds": [901]},
            ),
            project.id,
            "device-debug",
        )

        self.assertEqual(response.status_code, 200, self.data(response))
        debug_node = project.nodes.get(node_key="device-debug")
        install_node = project.nodes.get(node_key="device-install")
        self.assertEqual(debug_node.business_data["relatedProducts"][0]["productId"], 901)
        self.assertNotIn("relatedProducts", install_node.business_data)
        self.assertNotIn("relatedProducts", project.business_data)
        fetch_products.assert_called_once_with([901])

    @patch("after_sales_api.views.fetch_products_by_ids", return_value={901: CATALOG_PRODUCT})
    def test_midsales_provider_receives_only_assigned_node_product_manual(self, _fetch_products):
        project = self.create_midsales_project()
        debug_node = project.nodes.get(node_key="device-debug")
        debug_node.business_data = {
            "relatedProducts": [{
                "productId": 901,
                "name": "智慧讲台",
                "manuals": [{"key": "productManual", "label": "产品说明书"}],
            }],
        }
        debug_node.save(update_fields=["business_data"])
        provider = ServiceProvider.objects.create(
            auth_user_id="midsales-field-user",
            name="售中现场人员",
            phone="13800000003",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        ProjectAssignment.objects.create(
            project=project,
            node=debug_node,
            provider=provider,
            status=ProjectAssignment.STATUS_ASSIGNED,
        )

        home = views.mobile_home(self.request(
            "get",
            "/api/after-sales/mobile/home",
            user_id=provider.auth_user_id,
            name=provider.name,
            admin=False,
        ))

        self.assertEqual(home.status_code, 200, self.data(home))
        manuals = self.data(home)["productManuals"]
        self.assertEqual(len(manuals), 1)
        self.assertEqual(manuals[0]["nodeKey"], "device-debug")
        self.assertIn("nodeKey=device-debug", manuals[0]["externalUrl"])
        response = views.product_manual(
            self.request(
                "get",
                f"/api/after-sales/product-catalog/901/manual/productManual?projectId={project.id}&nodeKey=device-debug",
                user_id=provider.auth_user_id,
                name=provider.name,
                admin=False,
                query={"projectId": project.id, "nodeKey": "device-debug"},
            ),
            901,
            "productManual",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/files/product_archive/manual.pdf?token=signed")

    @patch("after_sales_api.views.fetch_product_image", return_value=(b"image-bytes", "image/jpeg"))
    def test_assigned_provider_can_open_related_product_image(self, fetch_image):
        project = self.create_aftersales_project()
        project.business_data = {
            **project.business_data,
            "relatedProducts": [{"productId": 901, "name": "智慧讲台", "manuals": []}],
        }
        project.save(update_fields=["business_data"])
        provider = ServiceProvider.objects.create(
            auth_user_id="image-field-user",
            name="图片查看人员",
            phone="13800000005",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        node = project.nodes.get(node_key="onsite-service")
        ProjectAssignment.objects.create(
            project=project,
            node=node,
            provider=provider,
            status=ProjectAssignment.STATUS_ASSIGNED,
        )

        response = views.product_catalog_image(
            self.request(
                "get",
                f"/api/after-sales/product-catalog/901/image?variant=thumbnail&projectId={project.id}&nodeKey=onsite-service",
                user_id=provider.auth_user_id,
                name=provider.name,
                admin=False,
                query={"variant": "thumbnail", "projectId": project.id, "nodeKey": "onsite-service"},
            ),
            901,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"image-bytes")
        self.assertEqual(response["Content-Type"], "image/jpeg")
        fetch_image.assert_called_once_with(901, variant="thumbnail")

    @patch("after_sales_api.views.fetch_product_image", return_value=(b"other-image", "image/jpeg"))
    def test_admin_can_open_additional_product_image(self, fetch_image):
        response = views.product_catalog_image(
            self.request(
                "get",
                "/api/after-sales/product-catalog/901/image?slot=other-1&variant=preview",
                query={"slot": "other-1", "variant": "preview"},
            ),
            901,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"other-image")
        fetch_image.assert_called_once_with(901, slot="other-1", variant="preview")

    @patch("after_sales_api.views.fetch_product_image")
    def test_unassigned_provider_cannot_open_related_product_image(self, fetch_image):
        project = self.create_aftersales_project()
        project.business_data = {
            **project.business_data,
            "relatedProducts": [{"productId": 901, "name": "智慧讲台", "manuals": []}],
        }
        project.save(update_fields=["business_data"])
        provider = ServiceProvider.objects.create(
            auth_user_id="image-outsider",
            name="未指派人员",
            phone="13800000006",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )

        response = views.product_catalog_image(
            self.request(
                "get",
                f"/api/after-sales/product-catalog/901/image?slot=detail-1&variant=thumbnail&projectId={project.id}",
                user_id=provider.auth_user_id,
                name=provider.name,
                admin=False,
                query={"slot": "detail-1", "variant": "thumbnail", "projectId": project.id},
            ),
            901,
        )

        self.assertEqual(response.status_code, 404)
        fetch_image.assert_not_called()

    @patch("after_sales_api.views.fetch_products_by_ids", return_value={901: CATALOG_PRODUCT})
    def test_assigned_provider_receives_and_can_open_related_product_manual(self, _fetch_products):
        project = self.create_aftersales_project()
        project.business_data = {
            **project.business_data,
            "relatedProducts": [{
                **{key: CATALOG_PRODUCT[key] for key in ("productId", "name", "brand", "model")},
                "abbr": "讲台简称",
                "manuals": [{"key": "productManual", "label": "产品说明书"}],
            }],
        }
        project.save(update_fields=["business_data"])
        provider = ServiceProvider.objects.create(
            auth_user_id="field-user",
            name="现场人员",
            phone="13800000001",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        node = project.nodes.get(node_key="onsite-service")
        ProjectAssignment.objects.create(
            project=project,
            node=node,
            provider=provider,
            status=ProjectAssignment.STATUS_ASSIGNED,
        )

        home = views.mobile_home(self.request(
            "get",
            "/api/after-sales/mobile/home",
            user_id=provider.auth_user_id,
            name=provider.name,
            admin=False,
        ))
        self.assertEqual(home.status_code, 200, self.data(home))
        manuals = self.data(home)["productManuals"]
        self.assertEqual(len(manuals), 1)
        self.assertEqual(manuals[0]["productId"], 901)
        self.assertEqual(manuals[0]["productName"], "智慧讲台")
        self.assertEqual(manuals[0]["productAbbr"], "讲台简称")
        self.assertEqual(manuals[0]["title"], "讲台简称 · 产品说明书")
        self.assertIn(f"projectId={project.id}", manuals[0]["externalUrl"])

        response = views.product_manual(
            self.request(
                "get",
                f"/api/after-sales/product-catalog/901/manual/productManual?projectId={project.id}",
                user_id=provider.auth_user_id,
                name=provider.name,
                admin=False,
                query={"projectId": project.id},
            ),
            901,
            "productManual",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/files/product_archive/manual.pdf?token=signed")

    @patch("after_sales_api.views.render_feishu_manual_pdf")
    @patch("after_sales_api.views.fetch_products_by_ids")
    def test_assigned_provider_receives_rendered_feishu_manual(self, fetch_products, render_manual):
        product = {
            **CATALOG_PRODUCT,
            "manuals": [{
                "key": "productManual",
                "label": "产品说明书",
                "url": "https://tenant.feishu.cn/wiki/document-token",
            }],
        }
        fetch_products.return_value = {901: product}
        project = self.create_aftersales_project()
        project.business_data = {
            **project.business_data,
            "relatedProducts": [{
                "productId": 901,
                "name": "智慧讲台",
                "manuals": [{"key": "productManual", "label": "产品说明书"}],
            }],
        }
        project.save(update_fields=["business_data"])
        provider = ServiceProvider.objects.create(
            auth_user_id="feishu-field-user",
            name="飞书资料现场人员",
            phone="13800000004",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )
        node = project.nodes.get(node_key="onsite-service")
        ProjectAssignment.objects.create(
            project=project,
            node=node,
            provider=provider,
            status=ProjectAssignment.STATUS_ASSIGNED,
        )
        with TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "manual.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nrendered manual")
            render_manual.return_value = pdf_path
            response = views.product_manual(
                self.request(
                    "get",
                    f"/api/after-sales/product-catalog/901/manual/productManual?projectId={project.id}",
                    user_id=provider.auth_user_id,
                    name=provider.name,
                    admin=False,
                    query={"projectId": project.id},
                ),
                901,
                "productManual",
            )
            body = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("product-901-productManual.pdf", response["Content-Disposition"])
        self.assertEqual(body, b"%PDF-1.4\nrendered manual")
        render_manual.assert_called_once_with("https://tenant.feishu.cn/wiki/document-token")

    @patch("after_sales_api.views.fetch_products_by_ids")
    def test_unassigned_provider_cannot_open_related_product_manual(self, fetch_products):
        project = self.create_aftersales_project()
        project.business_data = {
            **project.business_data,
            "relatedProducts": [{
                "productId": 901,
                "name": "智慧讲台",
                "manuals": [{"key": "productManual", "label": "产品说明书"}],
            }],
        }
        project.save(update_fields=["business_data"])
        provider = ServiceProvider.objects.create(
            auth_user_id="other-user",
            name="其他人员",
            phone="13800000002",
            certification_status=ServiceProvider.CERT_CERTIFIED,
        )

        response = views.product_manual(
            self.request(
                "get",
                f"/api/after-sales/product-catalog/901/manual/productManual?projectId={project.id}",
                user_id=provider.auth_user_id,
                name=provider.name,
                admin=False,
                query={"projectId": project.id},
            ),
            901,
            "productManual",
        )

        self.assertEqual(response.status_code, 404)
        fetch_products.assert_not_called()
