import json
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from identity_api.auth.session import create_auth_session_token
from identity_api.auth.tokens import AUTH_COOKIE_NAME
from identity_api.models import AdministrativeRegion, AdministrativeRegionDirectory, Employee, InternalServiceCredential
from identity_api.org.administrative_regions import load_administrative_region_directory


class AdministrativeRegionDirectoryTests(TestCase):
    base_path = "/api/internal/directory/administrative-regions"
    secret = "test-region-directory-secret-0123456789"

    def setUp(self):
        self.credential = InternalServiceCredential(service_name="directory-consumer", app_id="consumer")
        self.credential.set_secret(self.secret)
        self.credential.save()

    def post(self, suffix="", payload=None, **headers):
        return self.client.post(
            self.base_path + suffix,
            data=json.dumps({} if payload is None else payload),
            content_type="application/json",
            HTTP_X_INTERNAL_SERVICE="directory-consumer",
            HTTP_X_INTERNAL_AUTH_SECRET=headers.pop("secret", self.secret),
            **headers,
        )

    def test_complete_tree_matches_management_directory(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        directory = response.json()
        self.assertEqual(directory["stats"], {"provinces": 34, "cities": 369, "districts": 3478})
        self.assertEqual(len(directory["items"]), 34)
        zhejiang = next(item for item in directory["items"] if item["code"] == "330000")
        hangzhou = next(item for item in zhejiang["cities"] if item["code"] == "330100")
        self.assertEqual(hangzhou["name"], "杭州市")
        self.assertIn("临平区", [item["name"] for item in hangzhou["districts"]])
        self.assertNotIn("江干区", [item["name"] for item in hangzhou["districts"]])
        self.assertTrue(all(item["pinyin"] and item["pinyinInitials"] for item in hangzhou["districts"]))

        admin = Employee.objects.create(user_id="directory-admin", name="目录管理员")
        self.client.cookies[AUTH_COOKIE_NAME] = create_auth_session_token(admin)["token"]
        management = self.client.get("/api/directory/administrative-regions").json()
        for field in ("revision", "stats", "items"):
            self.assertEqual(directory[field], management[field])
        self.assertNotIn("orgRevision", directory)

    def test_browse_and_search_by_level_parent_and_keyword(self):
        response = self.post("/search", {"level": "province", "limit": 10, "offset": 10})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 34)
        self.assertEqual(response.json()["count"], 10)
        self.assertTrue(all(item["level"] == "province" for item in response.json()["items"]))

        response = self.post("/search", {"parentCode": "340000"})
        self.assertEqual(response.json()["total"], 16)
        self.assertTrue(all(item["level"] == "city" for item in response.json()["items"]))
        response = self.post("/search", {"parentCode": "340100"})
        self.assertEqual(response.json()["total"], 14)
        self.assertTrue(all(item["parentCode"] == "340100" for item in response.json()["items"]))
        response = self.post("/search", {"parentCode": "", "limit": 100})
        self.assertEqual(response.json()["total"], 34)

        for keyword in ("余杭区", "330110", "Yu-Hang Qu", "YHQ"):
            with self.subTest(keyword=keyword):
                response = self.post("/search", {"keyword": keyword, "level": "district", "parentCode": "330100"})
                self.assertEqual(response.json()["total"], 1)
                self.assertEqual(response.json()["items"][0]["code"], "330110")
        response = self.post("/search", {"keyword": "余杭区", "parentCode": "340100"})
        self.assertEqual(response.json()["total"], 0)

    def test_exact_code_lookup_and_leaf_children(self):
        response = self.post("/get", {"code": "330110"})
        self.assertEqual(response.status_code, 200)
        item = response.json()["item"]
        self.assertEqual(item["name"], "余杭区")
        self.assertEqual(item["parentCode"], "330100")
        self.assertEqual(item["path"], "浙江省 / 杭州市 / 余杭区")
        self.assertEqual(self.post("/search", {"parentCode": "330110"}).json()["items"], [])
        for suffix, payload in (("/get", {"code": "999999"}), ("/search", {"parentCode": "999999"})):
            response = self.post(suffix, payload)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["code"], "REGION_NOT_FOUND")

    def test_snapshot_conditional_read_and_named_parent_search(self):
        revision = self.post().json()["revision"]
        response = self.post(payload={"ifRevision": revision})
        self.assertTrue(response.json()["notModified"])
        self.assertEqual(response.json()["revision"], revision)
        self.assertNotIn("items", response.json())
        self.assertEqual(self.post(payload={"ifRevision": 123}).status_code, 400)
        cities = self.post("/search", {"province": "浙江省", "keyword": "hzs"}).json()["items"]
        self.assertEqual([row["code"] for row in cities], ["330100", "330500"])
        districts = self.post("/search", {"province": "浙江省", "city": "杭州市", "keyword": "yhq"}).json()["items"]
        self.assertEqual([row["code"] for row in districts], ["330110"])
        self.assertEqual(self.post("/search", {"province": "浙江省", "city": "南京市"}).status_code, 404)
        self.assertEqual(self.post("/search", {"province": "浙江省", "parentCode": "320000"}).status_code, 400)
        self.assertEqual(self.post("/search", {"city": "杭州市"}).status_code, 400)
        self.assertEqual(self.post("/search", {"revision": "obsolete"}).status_code, 409)

    def test_all_endpoints_require_enabled_service_credentials(self):
        for suffix in ("", "/search", "/get"):
            with self.subTest(suffix=suffix):
                response = self.client.post(self.base_path + suffix, data="{}", content_type="application/json")
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.post(suffix, secret="incorrect").status_code, 403)
                self.assertNotIn("items", response.json())
        self.credential.enabled = False
        self.credential.save(update_fields=["enabled"])
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "INTERNAL_SERVICE_DISABLED")

    def test_rejects_invalid_requests_and_does_not_accept_writes(self):
        for suffix in ("", "/search", "/get"):
            self.assertEqual(self.post(suffix, []).status_code, 400)
            self.assertEqual(self.client.get(self.base_path + suffix).status_code, 405)
            self.assertEqual(self.client.put(self.base_path + suffix, data="{}").status_code, 405)
            response = self.client.post(
                self.base_path + suffix, data="{", content_type="application/json",
                HTTP_X_INTERNAL_SERVICE="directory-consumer", HTTP_X_INTERNAL_AUTH_SECRET=self.secret,
            )
            self.assertEqual(response.status_code, 400)
        for payload in (
            {"level": "county"}, {"level": []}, {"parentCode": 330100},
            {"parentCode": "3301"}, {"limit": 0}, {"limit": 101},
            {"limit": True}, {"limit": 1.5}, {"offset": 2.5},
            {"offset": -1}, {"keyword": "x" * 101},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.post("/search", payload).status_code, 400)
        for code in (None, True, 330110, "3301", "abcdef"):
            self.assertEqual(self.post("/get", {"code": code}).status_code, 400)

    def authenticate_management(self):
        admin = Employee.objects.create(user_id="directory-admin", name="目录管理员")
        self.client.cookies[AUTH_COOKIE_NAME] = create_auth_session_token(admin)["token"]

    def test_all_reads_use_persisted_fields_without_seed_file_or_transliteration(self):
        self.authenticate_management()
        AdministrativeRegion.objects.filter(code="330110").update(
            name="余杭测试区", pinyin="canonicalregion", pinyin_initials="cqr",
        )
        with (
            patch("pathlib.Path.read_text", side_effect=AssertionError("Runtime must not read seed files")),
            patch("pathlib.Path.read_bytes", side_effect=AssertionError("Runtime must not read seed files")),
            patch("identity_api.org.queries.pinyin_text", side_effect=AssertionError("Use persisted pinyin")),
        ):
            with CaptureQueriesContext(connection) as queries:
                directory = load_administrative_region_directory()
            self.assertEqual(len(queries), 2)
            self.assertTrue(all("platform_administrative_region" in query["sql"] for query in queries))
            self.assertEqual(directory.by_code["330110"]["name"], "余杭测试区")
            exact = self.post("/get", {"code": "330110"}).json()["item"]
            self.assertEqual(exact["pinyin"], "canonicalregion")
            for endpoint in ("/api/directory/administrative-regions/search", self.base_path + "/search"):
                if endpoint.startswith(self.base_path):
                    response = self.post("/search", {"keyword": "cqr"})
                else:
                    response = self.client.get(endpoint, {"keyword": "cqr"})
                self.assertEqual(response.json()["items"][0]["code"], "330110")
            internal = self.post().json()
            management = self.client.get("/api/directory/administrative-regions").json()
            self.assertEqual(internal["items"], management["items"])
            self.assertIn("余杭测试区", json.dumps(management["items"], ensure_ascii=False))

    def test_publication_uses_database_revision_without_process_cache(self):
        self.authenticate_management()
        original = AdministrativeRegionDirectory.objects.get(is_current=True)
        original.is_current = False
        original.save(update_fields=["is_current"])
        published = AdministrativeRegionDirectory.objects.create(
            revision="test-region-release", source="test-fixture", source_fingerprint="a" * 64,
            region_count=3, is_current=True,
        )
        for index, (code, name, level, parent) in enumerate((
            ("330000", "浙江省", "province", ""), ("330100", "杭州市", "city", "330000"),
            ("330110", "余杭新目录区", "district", "330100"),
        )):
            AdministrativeRegion.objects.create(
                directory=published, code=code, name=name, level=level, parent_code=parent,
                pinyin="fixture", pinyin_initials="fx", sort_order=index,
            )
        responses = [self.post(), self.post("/search", {"keyword": "新目录"}), self.post("/get", {"code": "330110"}),
                     self.client.get("/api/directory/administrative-regions"),
                     self.client.get("/api/directory/administrative-regions/search", {"keyword": "新目录"})]
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertTrue(all(response.json()["revision"] == published.revision for response in responses))
        self.assertEqual(responses[0].json()["stats"], {"provinces": 1, "cities": 1, "districts": 1})
        self.assertEqual(responses[2].json()["item"]["path"], "浙江省 / 杭州市 / 余杭新目录区")
        published.is_current = False
        published.save(update_fields=["is_current"])
        original.is_current = True
        original.save(update_fields=["is_current"])
        self.assertEqual(self.post().json()["revision"], original.revision)
        self.assertEqual(self.post("/get", {"code": "330110"}).json()["item"]["name"], "余杭区")

    def test_missing_or_incomplete_database_directory_fails_without_file_fallback(self):
        self.authenticate_management()
        directory = AdministrativeRegionDirectory.objects.get(is_current=True)
        for unavailable_state in ("unpublished", "incomplete", "invalid-parent"):
            with self.subTest(state=unavailable_state):
                if unavailable_state == "unpublished":
                    directory.is_current = False
                    directory.save(update_fields=["is_current"])
                elif unavailable_state == "incomplete":
                    directory.is_current = True
                    directory.region_count += 1
                    directory.save(update_fields=["is_current", "region_count"])
                else:
                    directory.region_count -= 1
                    directory.save(update_fields=["region_count"])
                    AdministrativeRegion.objects.filter(directory=directory, code="330110").update(parent_code="999999")
                responses = [self.post(), self.post("/search"), self.post("/get", {"code": "330110"}),
                             self.client.get("/api/directory/administrative-regions"),
                             self.client.get("/api/directory/administrative-regions/search", {"q": "余杭"})]
                for response in responses:
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json()["code"], "REGION_DIRECTORY_UNAVAILABLE")
                    self.assertNotIn("items", response.json())

    def test_database_enforces_unique_current_revision_and_region_codes(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AdministrativeRegionDirectory.objects.create(
                revision="duplicate-current", source="test", source_fingerprint="a" * 64,
                region_count=1, is_current=True,
            )
        row = AdministrativeRegion.objects.filter(code="330110").get()
        row.pk = None
        with self.assertRaises(IntegrityError), transaction.atomic():
            row.save(force_insert=True)


class AdministrativeRegionDatabaseMigrationTests(TransactionTestCase):
    def test_migration_seeds_complete_directory_and_keeps_platform_company_data(self):
        before = [("identity_api", "0021_platform_company_entities")]
        after = [("identity_api", "0022_administrative_region_database")]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        old_apps.get_model("identity_api", "PlatformCompanyEntity").objects.create(
            id=217, company_name="平台主体保留测试", tax_number="REGION-MIGRATION-COMPANY",
        )
        try:
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            apps = executor.loader.project_state(after).apps
            Directory = apps.get_model("identity_api", "AdministrativeRegionDirectory")
            Region = apps.get_model("identity_api", "AdministrativeRegion")
            directory = Directory.objects.get(is_current=True)
            self.assertEqual(directory.revision, "vant-area-data-2.2.0")
            self.assertEqual(directory.region_count, 3881)
            self.assertEqual(Region.objects.count(), 3881)
            self.assertEqual(Region.objects.filter(level="province").count(), 34)
            self.assertEqual(Region.objects.filter(level="city").count(), 369)
            self.assertEqual(Region.objects.filter(level="district").count(), 3478)
            row = Region.objects.get(code="330110")
            self.assertEqual((row.name, row.parent_code, row.pinyin, row.pinyin_initials),
                             ("余杭区", "330100", "yuhangqu", "yhq"))
            self.assertEqual(apps.get_model("identity_api", "PlatformCompanyEntity").objects.get(pk=217).company_name,
                             "平台主体保留测试")
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
