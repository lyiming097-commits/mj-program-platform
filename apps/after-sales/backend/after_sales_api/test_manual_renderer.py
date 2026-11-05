from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .manual_renderer import is_feishu_document_url, render_feishu_manual_pdf


class ManualRendererTests(SimpleTestCase):
    def test_accepts_only_https_feishu_hosts(self):
        self.assertTrue(is_feishu_document_url("https://tenant.feishu.cn/wiki/document-token"))
        self.assertTrue(is_feishu_document_url("https://feishu.cn/docx/document-token"))
        self.assertFalse(is_feishu_document_url("http://tenant.feishu.cn/wiki/document-token"))
        self.assertFalse(is_feishu_document_url("https://feishu.cn.example.com/wiki/document-token"))
        self.assertFalse(is_feishu_document_url("https://user@tenant.feishu.cn/wiki/document-token"))

    @patch("after_sales_api.manual_renderer._request_renderer_pdf", return_value=b"%PDF-1.4\ntest")
    def test_rendered_pdf_is_cached(self, request_renderer_pdf):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=Path(directory)):
            first = render_feishu_manual_pdf("https://tenant.feishu.cn/wiki/document-token")
            second = render_feishu_manual_pdf("https://tenant.feishu.cn/wiki/document-token")
            cached_pdf = first.read_bytes()

        self.assertEqual(first, second)
        self.assertEqual(cached_pdf, b"%PDF-1.4\ntest")
        request_renderer_pdf.assert_called_once()
