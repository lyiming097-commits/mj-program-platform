import json

from django.test import RequestFactory, TestCase

from .models import AppPermissionRule, RewardPrize, ServiceProvider
from .reward_prize_views import reward_prize_item, reward_prizes
from .views import reward_prize_options


class RewardPrizeCatalogTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, method, path, payload=None, *, user_id="settings-admin", admin=True, channel="dingtalk"):
        factory_method = getattr(self.factory, method)
        if method == "get":
            request = factory_method(path)
        else:
            request = factory_method(path, json.dumps(payload or {}, ensure_ascii=False), content_type="application/json")
        request.auth_user_id = user_id
        request.auth_user_name = user_id
        request.auth_actor_user_id = user_id
        request.auth_actor_name = user_id
        request.auth_is_proxy = False
        request.auth_can_use_system_admin = admin
        request.auth_token_claims = {"chn": channel, "aud": "after-sales-mobile" if channel == "wechat-mini" else "platform"}
        return request

    @staticmethod
    def data(response):
        return json.loads(response.content.decode("utf-8"))

    def test_catalog_add_rename_disable_enable_and_available_options(self):
        path = "/api/after-sales/reward-prizes"
        self.assertEqual(self.data(reward_prizes(self.request("get", path)))["items"], [])
        created = reward_prizes(self.request("post", path, {"name": "  工具包  "}))
        self.assertEqual(created.status_code, 201, self.data(created))
        prize_id = self.data(created)["item"]["id"]
        self.assertEqual(self.data(created)["item"]["name"], "工具包")
        duplicate = reward_prizes(self.request("post", path, {"name": "工具包"}))
        self.assertEqual(self.data(duplicate)["code"], "DUPLICATE_REWARD_PRIZE")

        renamed = reward_prize_item(self.request("patch", f"{path}/{prize_id}", {"name": "维修箱"}), prize_id)
        self.assertEqual(self.data(renamed)["item"]["name"], "维修箱")
        disabled = reward_prize_item(self.request("patch", f"{path}/{prize_id}", {"enabled": False}), prize_id)
        self.assertFalse(self.data(disabled)["item"]["enabled"])
        self.assertEqual(self.data(reward_prize_options(self.request("get", f"{path}/options")))["items"], [])
        self.assertEqual(len(self.data(reward_prizes(self.request("get", path)))["items"]), 1)
        reward_prize_item(self.request("patch", f"{path}/{prize_id}", {"enabled": True}), prize_id)
        self.assertEqual(self.data(reward_prize_options(self.request("get", f"{path}/options")))["items"], [
            {"id": prize_id, "name": "维修箱"},
        ])

    def test_catalog_requires_settings_permission_and_options_require_management(self):
        path = "/api/after-sales/reward-prizes"
        prize = RewardPrize.objects.create(name="工具包")
        for method, route, payload in (
            ("get", path, None),
            ("post", path, {"name": "维修箱"}),
            ("patch", f"{path}/{prize.id}", {"enabled": False}),
        ):
            with self.subTest(method=method):
                request = self.request(method, route, payload, user_id="ordinary-user", admin=False)
                response = reward_prize_item(request, prize.id) if method == "patch" else reward_prizes(request)
                self.assertEqual(response.status_code, 403)
        self.assertEqual(RewardPrize.objects.count(), 1)
        self.assertTrue(RewardPrize.objects.get(pk=prize.id).enabled)

        ServiceProvider.objects.create(auth_user_id="provider-a", name="服务人员")
        for user_id, channel in (("provider-a", "wechat-mini"), ("provider-a", "dingtalk")):
            request = self.request("get", f"{path}/options", user_id=user_id, admin=False, channel=channel)
            self.assertEqual(reward_prize_options(request).status_code, 403)
        AppPermissionRule.objects.create(permission="service", scope_type="employee", target_id="manager")
        manager = self.request("get", f"{path}/options", user_id="manager", admin=False)
        self.assertEqual(reward_prize_options(manager).status_code, 200)

    def test_bad_name_and_state_are_rejected(self):
        path = "/api/after-sales/reward-prizes"
        for name in ("  ", "奖" * 256):
            self.assertEqual(reward_prizes(self.request("post", path, {"name": name})).status_code, 400)
        prize = RewardPrize.objects.create(name="工具包")
        changed = reward_prize_item(self.request("patch", f"{path}/{prize.id}", {"enabled": "false"}), prize.id)
        self.assertEqual(changed.status_code, 400)
        self.assertTrue(RewardPrize.objects.get(pk=prize.id).enabled)
