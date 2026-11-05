import hashlib
import io
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from identity_api.models import PlatformCompanyEntity, PlatformCompanyEntityHistory


class ImportPlatformCompanyEntitiesTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "companies.json"
        self.row = {"id": 217, "company_name": "迁移测试主体", "category": "历史简称", "tax_number": "IMPORT-TAX-217",
                    "bank_name": "原银行", "bank_account": "原账号", "address": "原地址", "phone": "原电话",
                    "created_by": "original-user", "updated_by": "original-editor",
                    "created_at": "2026-01-02T03:04:05+00:00", "updated_at": "2026-02-03T04:05:06+00:00"}

    def export(self, records):
        fingerprint = hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.source.write_text(json.dumps({"format": "platform-company-entities/v1", "source": "crm-legacy",
                                          "count": len(records), "fingerprint": fingerprint, "records": records}), encoding="utf-8")
        return fingerprint

    def import_records(self, **options):
        output = io.StringIO()
        call_command("import_platform_company_entities", str(self.source), stdout=output, **options)
        return output.getvalue()

    def test_preview_import_preserves_ids_timestamps_and_is_idempotent(self):
        fingerprint = self.export([self.row])
        self.assertIn("new=1", self.import_records())
        self.assertEqual(PlatformCompanyEntity.objects.count(), 0)
        self.import_records(apply=True, expected_fingerprint=fingerprint)
        item = PlatformCompanyEntity.objects.get(pk=217)
        self.assertEqual(item.category, "历史简称")
        self.assertEqual(item.bank_account, "原账号")
        self.assertEqual(item.updated_by, "original-editor")
        self.assertEqual(item.created_at.isoformat(), self.row["created_at"])
        self.assertEqual(item.updated_at.isoformat(), self.row["updated_at"])
        self.assertIn("new=0", self.import_records(apply=True, expected_fingerprint=fingerprint))
        self.assertEqual(PlatformCompanyEntityHistory.objects.count(), 1)
        self.assertGreater(PlatformCompanyEntity.objects.create(company_name="新主体", tax_number="NEW-TAX").id, 217)

    def test_fingerprint_and_existing_id_or_tax_conflicts_block_all_writes(self):
        fingerprint = self.export([self.row])
        with self.assertRaises(CommandError):
            self.import_records(apply=True, expected_fingerprint="wrong")
        self.import_records(apply=True, expected_fingerprint=fingerprint)
        pending = {**self.row, "id": 218, "tax_number": "IMPORT-TAX-218"}
        changed = {**self.row, "company_name": "被覆盖的名称"}
        fingerprint = self.export([pending, changed])
        with self.assertRaises(CommandError):
            self.import_records(apply=True, expected_fingerprint=fingerprint)
        self.assertFalse(PlatformCompanyEntity.objects.filter(pk=218).exists())
        self.assertEqual(PlatformCompanyEntity.objects.get(pk=217).company_name, "迁移测试主体")
        fingerprint = self.export([{**self.row, "id": 999}])
        with self.assertRaises(CommandError):
            self.import_records(apply=True, expected_fingerprint=fingerprint)

    def test_corrupted_or_duplicate_export_is_rejected(self):
        self.export([self.row])
        payload = json.loads(self.source.read_text())
        payload["records"][0]["company_name"] = "损坏数据"
        self.source.write_text(json.dumps(payload))
        with self.assertRaises(CommandError):
            self.import_records()
        self.export([self.row, self.row])
        with self.assertRaises(CommandError):
            self.import_records()
        self.assertEqual(PlatformCompanyEntity.objects.count(), 0)
