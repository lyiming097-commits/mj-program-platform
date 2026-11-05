import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from .files import DEFAULT_MAX_UPLOAD_BYTES, FileTooLargeError, save_upload


class UploadLimitTests(SimpleTestCase):
    def test_manifest_reserves_room_for_200_mb_files(self):
        manifest = json.loads(
            (Path(__file__).resolve().parents[2] / "app.manifest.yaml").read_text(encoding="utf-8")
        )
        route = next(route for route in manifest["routes"] if route["path"] == "/api/competitive/")
        backend = manifest["compose"]["services"]["competitive-backend"]["environment"]
        self.assertEqual(route["clientMaxBodySize"], "201m")
        self.assertEqual(int(backend["MAX_UPLOAD_BYTES"]), DEFAULT_MAX_UPLOAD_BYTES)

    def test_file_limit_is_inclusive_and_rejects_excess_without_leaving_temp_file(self):
        with TemporaryDirectory() as directory, patch.dict(
            os.environ, {"UPLOAD_DIR": directory, "MAX_UPLOAD_BYTES": "6"}
        ):
            stored = save_upload(SimpleUploadedFile("ok.pdf", b"123456", content_type="application/pdf"))
            self.assertEqual(stored.size, 6)
            with self.assertRaises(FileTooLargeError) as failure:
                save_upload(SimpleUploadedFile("large.pdf", b"1234567", content_type="application/pdf"))
            self.assertIn("6字节", str(failure.exception))
            self.assertEqual([path.name for path in Path(directory).iterdir()], [stored.storage_key])

    def test_default_limit_message_is_readable(self):
        self.assertEqual(str(FileTooLargeError(DEFAULT_MAX_UPLOAD_BYTES)), "单个附件不能超过200MB")
