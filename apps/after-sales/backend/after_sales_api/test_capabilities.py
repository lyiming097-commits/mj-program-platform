from __future__ import annotations

import json

from django.test import RequestFactory, TestCase

from . import capability_views
from .models import AppPermissionRule, ServiceCapabilityTag


class CapabilityCatalogTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, method: str, payload: dict | None = None, role="admin"):
        path = "/api/after-sales/capabilities"
        if method.lower() == "get":
            request = self.factory.get(path)
        else:
            request = self.factory.patch(
                path,
                data=json.dumps(payload or {}, ensure_ascii=False),
                content_type="application/json",
            )
        request.auth_user_id = f"capability-{role}"
        request.auth_user_name = "能力管理员"
        request.auth_actor_user_id = "capability-admin"
        request.auth_actor_name = "能力管理员"
        request.auth_is_proxy = False
        request.auth_can_use_system_admin = role == "admin"
        if role:
            AppPermissionRule.objects.get_or_create(permission=role, scope_type="employee", target_id=request.auth_user_id)
        return request

    @staticmethod
    def data(response) -> dict:
        return json.loads(response.content.decode("utf-8"))

    def test_catalog_contains_every_prototype_node_and_seeded_abilities(self):
        response = capability_views.capability_catalog(self.request("get"))

        self.assertEqual(response.status_code, 200)
        groups = self.data(response)["groups"]
        self.assertEqual([group["serviceType"] for group in groups], ["presales", "midsales", "aftersales"])
        self.assertEqual(sum(len(group["nodes"]) for group in groups), 30)
        device_debug = next(
            node
            for group in groups
            for node in group["nodes"]
            if group["serviceType"] == "midsales" and node["nodeKey"] == "device-debug"
        )
        self.assertEqual(device_debug["abilities"], ["中控联调", "录播联动", "平台接入"])

    def test_admin_can_replace_a_nodes_ordered_capability_list(self):
        response = capability_views.capability_catalog(self.request("patch", {
            "serviceType": "midsales",
            "nodeKey": "device-debug",
            "names": ["网络联调", "录播联动"],
        }))

        self.assertEqual(response.status_code, 200, self.data(response))
        rows = ServiceCapabilityTag.objects.filter(
            service_type="midsales",
            node_key="device-debug",
        )
        self.assertEqual(list(rows.values_list("name", flat=True)), ["网络联调", "录播联动"])
        self.assertTrue(all(row.created_by == "capability-admin" for row in rows))

    def test_sales_cannot_change_catalog(self):
        response = capability_views.capability_catalog(self.request("patch", {
            "serviceType": "midsales",
            "nodeKey": "device-debug",
            "names": ["网络联调"],
        }, role="sales"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.data(response)["code"], "SERVICE_PERMISSION_REQUIRED")

    def test_service_admin_can_change_catalog(self):
        response = capability_views.capability_catalog(self.request("patch", {
            "serviceType": "midsales", "nodeKey": "device-debug", "names": ["网络联调"],
        }, role="service"))
        self.assertEqual(response.status_code, 200, self.data(response))

    def test_empty_duplicate_and_unknown_node_updates_are_rejected(self):
        cases = [
            ({"serviceType": "midsales", "nodeKey": "device-debug", "names": []}, "CAPABILITY_REQUIRED"),
            ({"serviceType": "midsales", "nodeKey": "device-debug", "names": ["联调", "联调"]}, "DUPLICATE_CAPABILITY_NAME"),
            ({"serviceType": "midsales", "nodeKey": "missing", "names": ["联调"]}, "INVALID_NODE_KEY"),
        ]
        for payload, code in cases:
            with self.subTest(code=code):
                response = capability_views.capability_catalog(self.request("patch", payload))
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.data(response)["code"], code)
