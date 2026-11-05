import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from .dashboard_views import bootstrap
from .models import SettingItem
from .setting_defaults import PROVINCE_NAMES
from .settings_views import setting_item_detail, setting_items, settings_collection


class ProvinceOptionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("competitive_vue_api.dashboard_views.request_access", return_value=(None, None))
    @patch("competitive_vue_api.settings_views.request_access", return_value=(None, None))
    def test_bootstrap_and_settings_use_same_fixed_provinces_without_changing_legacy_rows(
        self, _settings_access, _dashboard_access,
    ):
        legacy = SettingItem.objects.create(
            group="region", code="region_5", label="华中 / 武汉", enabled=True,
        )
        settings = json.loads(settings_collection(self.factory.get("/settings")).content)
        bootstrap_settings = json.loads(bootstrap(self.factory.get("/bootstrap")).content)["settings"]

        for rows in (settings, bootstrap_settings):
            provinces = [item["label"] for item in rows if item["group"] == "region"]
            self.assertEqual(provinces, list(PROVINCE_NAMES))
            self.assertEqual(len(provinces), 34)
            self.assertNotIn("华中 / 武汉", provinces)
        legacy.refresh_from_db()
        self.assertEqual(legacy.label, "华中 / 武汉")

    @patch("competitive_vue_api.settings_views.request_access", return_value=(None, None))
    def test_region_settings_are_read_only(self, _access):
        create_request = self.factory.post(
            "/settings", data=json.dumps({"group": "region", "label": "华中 / 武汉"}),
            content_type="application/json",
        )
        self.assertEqual(setting_items(create_request).status_code, 422)

        legacy = SettingItem.objects.create(
            group="region", code="region_5", label="华中 / 武汉", enabled=True,
        )
        update_request = self.factory.patch(
            "/settings", data=json.dumps({"label": "华东 / 杭州"}),
            content_type="application/json",
        )
        self.assertEqual(setting_item_detail(update_request, legacy.id).status_code, 422)
        legacy.refresh_from_db()
        self.assertEqual(legacy.label, "华中 / 武汉")
