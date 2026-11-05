import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone

from .maintenance import (
    process_pending_file_deletions,
    purge_expired_soft_deletions,
)
from .models import (
    Competitor,
    PendingFileDeletion,
    Submission,
    SubmissionAttachment,
)


class MaintenanceTests(TestCase):
    def setUp(self):
        self.uploads = tempfile.TemporaryDirectory()
        self.addCleanup(self.uploads.cleanup)
        self.upload_patch = patch.dict(os.environ, {"UPLOAD_DIR": self.uploads.name})
        self.upload_patch.start()
        self.addCleanup(self.upload_patch.stop)

    def create_deleted_competitor(self, deleted_at):
        competitor = Competitor.objects.create(
            product_id="product-1",
            brand="测试品牌",
            name="测试竞品",
            model="A1",
            updated_on=date.today(),
            expires_on=date.today() + timedelta(days=30),
            deleted_at=deleted_at,
        )
        submission = Submission.objects.create(
            competitor=competitor,
            product_id="product-1",
            owner="测试人员",
            owner_user_id="user-1",
            brand="测试品牌",
            name="测试竞品",
            model="A1",
            region="华东",
            location="杭州市",
            validity="一年",
            expires_on=date.today() + timedelta(days=30),
            reminder_owner="本人",
            submitted_on=date.today(),
            deleted_at=deleted_at,
            status="已采纳",
        )
        storage_key = f"{uuid4().hex}.jpg"
        Path(self.uploads.name, storage_key).write_bytes(b"test-image")
        SubmissionAttachment.objects.create(
            submission=submission,
            filename="test.jpg",
            byte_size=10,
            media_type="image/jpeg",
            category="产品图片",
            storage_key=storage_key,
        )
        return competitor, submission, storage_key

    def test_soft_deleted_data_is_retained_until_thirty_days(self):
        now = timezone.now()
        competitor, submission, storage_key = self.create_deleted_competitor(
            now - timedelta(days=29)
        )

        purged = purge_expired_soft_deletions(now=now)

        self.assertEqual(purged, 0)
        self.assertTrue(Competitor.objects.filter(id=competitor.id).exists())
        self.assertTrue(Submission.objects.filter(id=submission.id).exists())
        self.assertTrue(Path(self.uploads.name, storage_key).is_file())

    def test_expired_soft_deleted_data_and_attachments_are_purged(self):
        now = timezone.now()
        competitor, submission, storage_key = self.create_deleted_competitor(
            now - timedelta(days=31)
        )

        purged = purge_expired_soft_deletions(now=now)

        self.assertEqual(purged, 1)
        self.assertFalse(Competitor.objects.filter(id=competitor.id).exists())
        self.assertFalse(Submission.objects.filter(id=submission.id).exists())
        self.assertTrue(
            PendingFileDeletion.objects.filter(storage_key=storage_key).exists()
        )
        self.assertEqual(process_pending_file_deletions(), 1)
        self.assertFalse(Path(self.uploads.name, storage_key).exists())
        self.assertFalse(PendingFileDeletion.objects.exists())

    def test_failed_file_cleanup_is_kept_for_retry(self):
        pending = PendingFileDeletion.objects.create(storage_key="invalid-key")

        self.assertEqual(process_pending_file_deletions(), 0)

        pending.refresh_from_db()
        self.assertEqual(pending.attempts, 1)
        self.assertTrue(pending.last_error)
