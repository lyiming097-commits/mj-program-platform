import json

from django.test import RequestFactory, TestCase

from .provider_tag_views import provider_tags


class ProviderTagApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, method, path, payload=None, *, user_id="tag-admin", admin=True):
        if method == "get":
            request = self.factory.get(path)
        else:
            request = self.factory.patch(
                path,
                data=json.dumps(payload or {}, ensure_ascii=False),
                content_type="application/json",
            )
        request.auth_user_id = user_id
        request.auth_user_name = "标签管理员"
        request.auth_actor_user_id = user_id
        request.auth_actor_name = "标签管理员"
        request.auth_is_proxy = False
        request.auth_can_use_system_admin = admin
        return request

    @staticmethod
    def data(response):
        return json.loads(response.content.decode("utf-8"))

    def test_public_catalog_is_available_to_registration_clients(self):
        response = provider_tags(self.factory.get("/api/after-sales/public/provider-tags"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("讲台安装", self.data(response)["items"])

    def test_only_system_admin_can_replace_catalog(self):
        denied = provider_tags(self.request(
            "patch",
            "/api/after-sales/provider-tags",
            {"names": ["新标签"]},
            user_id="ordinary-user",
            admin=False,
        ))
        self.assertEqual(denied.status_code, 403)

        saved = provider_tags(self.request(
            "patch",
            "/api/after-sales/provider-tags",
            {"names": ["讲台安装", "平台接入", "新标签"]},
        ))
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.data(saved)["items"], ["讲台安装", "平台接入", "新标签"])
