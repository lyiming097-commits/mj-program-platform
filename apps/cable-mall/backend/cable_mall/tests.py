import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase, override_settings

from .models import CableProduct, OrderItem
from .source_catalog import CableSourceError, fetch_online_cables, normalize_row
from .views import (
    order_product_snapshot_changed,
    product_catalog_sync_due,
    product_snapshot_values,
    sync_product_catalog,
    upsert_cable_products,
)


CATALOG_SETTINGS = {
    "BASE_URL": "http://product-archive-backend:8000/api/internal/product-catalog/",
    "CABLES_PATH": "cables/",
    "HEALTH_PATH": "health/",
    "TIMEOUT_SECONDS": 3,
    "SYNC_INTERVAL_SECONDS": 300,
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def catalog_row(**overrides):
    row = {
        "id": 7,
        "label": "六类网线",
        "product_brand": "迈杰",
        "product_model": "305m",
        "abbr": "CAT6",
        "category_a": "综合布线",
        "category_b": "网线",
        "kingdeeCode": "KD-7",
        "product_images": [],
        "plan_para": "支持千兆网络传输",
        "spec_text": "CAT6",
        "length_m": None,
        "quantity_unit": "箱",
        "unit_price": "120.50",
        "salesperson_price": "135.50",
        "distributor_price": "110.00",
        "budget_price": "150.00",
        "market_reference_price": "180.00",
        "comments": "六类非屏蔽标准线缆",
        "phase": 2,
        "archive_updated_at": "2026-07-21T10:00:00+00:00",
        "is_active": True,
    }
    row.update(overrides)
    return row


@override_settings(
    PRODUCT_ARCHIVE_CATALOG=CATALOG_SETTINGS,
    SERVICE_NAME="cable-mall-backend",
    AUTH_SERVICE_INTROSPECTION_SECRET="catalog-secret",
)
class ProductArchiveCatalogClientTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.created_cable_product_table = CableProduct._meta.db_table not in connection.introspection.table_names()
        if cls.created_cable_product_table:
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(CableProduct)

    @classmethod
    def tearDownClass(cls):
        if cls.created_cable_product_table:
            with connection.schema_editor() as schema_editor:
                schema_editor.delete_model(CableProduct)
        super().tearDownClass()

    @patch("cable_mall.source_catalog.urllib.request.urlopen")
    def test_catalog_client_uses_internal_service_credentials(self, urlopen):
        urlopen.return_value = FakeResponse({"ok": True, "items": [catalog_row()]})

        rows = fetch_online_cables()

        self.assertEqual(rows[0]["product_archive_id"], 7)
        self.assertEqual(str(rows[0]["unit_price"]), "120.50")
        self.assertEqual(str(rows[0]["salesperson_price"]), "135.50")
        self.assertEqual(str(rows[0]["budget_price"]), "150.00")
        self.assertEqual(str(rows[0]["market_reference_price"]), "180.00")
        self.assertEqual(str(rows[0]["length_m"]), "305.00")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, CATALOG_SETTINGS["BASE_URL"] + "cables/")
        self.assertEqual(request.get_header("X-internal-service"), "cable-mall-backend")
        self.assertEqual(request.get_header("X-internal-auth-secret"), "catalog-secret")

    def test_missing_salesperson_price_falls_back_to_a1_but_zero_is_preserved(self):
        missing = normalize_row(catalog_row(salesperson_price=None))
        zero = normalize_row(catalog_row(salesperson_price=0))

        self.assertEqual(missing["salesperson_price"], Decimal("120.50"))
        self.assertEqual(zero["salesperson_price"], Decimal("0"))

    def test_catalog_uses_structured_parameter_rows_without_slash_ambiguity(self):
        row = normalize_row(catalog_row(
            plan_para="输入 / 输出 / 速度35mm/s",
            parameterPreviewRows=[
                {"scheme": "输入 / 输出", "tender": "", "bid": ""},
                {"scheme": "速度35mm/s", "tender": "", "bid": ""},
                {"scheme": "符合QB/T 2454", "tender": "", "bid": ""},
            ],
        ))

        self.assertEqual(
            row["plan_para"],
            "输入 / 输出\n速度35mm/s\n符合QB/T 2454",
        )

    def test_order_snapshots_use_salesperson_price_and_preserve_zero(self):
        product = CableProduct(
            product_archive_id=7,
            label="六类网线",
            product_brand="迈杰",
            product_model="305m",
            abbr="CAT6",
            category_a="综合布线",
            category_b="网线",
            spec_text="CAT6",
            quantity_unit="箱",
            unit_price=Decimal("120.50"),
            salesperson_price=Decimal("135.50"),
        )
        fallback = OrderItem(unit_price=Decimal("99.00"))

        values = product_snapshot_values(product, fallback)
        self.assertEqual(values["unit_price"], Decimal("135.50"))

        product.salesperson_price = Decimal("0")
        zero_values = product_snapshot_values(product, fallback)
        self.assertEqual(zero_values["unit_price"], Decimal("0"))

    def test_order_snapshot_change_compares_against_salesperson_price(self):
        product = CableProduct(
            product_archive_id=7,
            label="六类网线",
            product_brand="迈杰",
            product_model="305m",
            abbr="CAT6",
            category_a="综合布线",
            category_b="网线",
            spec_text="CAT6",
            length_m=Decimal("305.00"),
            quantity_unit="箱",
            unit_price=Decimal("120.50"),
            salesperson_price=Decimal("135.50"),
        )
        order_item = OrderItem(
            product_archive_id=7,
            product_label=product.label,
            product_brand=product.product_brand,
            product_model=product.product_model,
            product_abbr=product.abbr,
            category_a=product.category_a,
            category_b=product.category_b,
            spec_text=product.spec_text,
            length_m=product.length_m,
            source_unit=product.quantity_unit,
            unit_price=product.salesperson_price,
        )

        self.assertFalse(order_product_snapshot_changed(order_item, product))
        order_item.unit_price = product.unit_price
        self.assertTrue(order_product_snapshot_changed(order_item, product))

    def test_sync_migrates_matching_legacy_product_in_place(self):
        legacy = CableProduct.objects.create(
            product_archive_id=77,
            label="六类网线",
            product_brand="旧品牌",
            product_model="305m",
            abbr="CAT6",
            category_a="成品线",
            category_b="网线",
            kingdee_code="KD-7",
            phase=2,
            is_active=True,
        )

        result = upsert_cable_products([normalize_row(catalog_row())])

        legacy.refresh_from_db()
        self.assertEqual(legacy.salesperson_price, Decimal("135.50"))
        self.assertEqual(legacy.budget_price, Decimal("150.00"))
        self.assertEqual(legacy.market_reference_price, Decimal("180.00"))
        self.assertEqual(result["migrated"], 1)
        self.assertEqual(legacy.product_archive_id, 7)
        self.assertEqual(legacy.product_brand, "迈杰")
        self.assertEqual(CableProduct.objects.count(), 1)
        self.assertFalse(product_catalog_sync_due())

    def test_empty_product_archive_catalog_deactivates_legacy_products(self):
        product = CableProduct.objects.create(
            product_archive_id=88,
            label="旧线材",
            phase=2,
            is_active=True,
        )

        result = upsert_cable_products([])

        product.refresh_from_db()
        self.assertEqual(result["deactivated"], 1)
        self.assertFalse(product.is_active)

    @patch("cable_mall.views.fetch_online_cables", return_value=[])
    def test_catalog_sync_rejects_empty_snapshot_without_deactivating_products(self, _fetch):
        product = CableProduct.objects.create(
            product_archive_id=88,
            label="现有线材",
            phase=2,
            is_active=True,
        )

        with self.assertRaisesMessage(CableSourceError, "产品档案返回的线材目录为空"):
            sync_product_catalog(force=True)

        product.refresh_from_db()
        self.assertTrue(product.is_active)

    def test_public_media_route_serves_only_catalog_thumbnails_in_production(self):
        with TemporaryDirectory() as temporary_directory, override_settings(
            MEDIA_ROOT=Path(temporary_directory),
            DEBUG=False,
        ):
            thumbnail = Path(temporary_directory) / "cable_mall" / "product_thumbs" / "wire.jpg"
            thumbnail.parent.mkdir(parents=True)
            thumbnail.write_bytes(b"thumbnail-bytes")

            allowed = self.client.get("/cable-mall-media/cable_mall/product_thumbs/wire.jpg")
            denied = self.client.get("/cable-mall-media/private/file.jpg")

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(b"".join(allowed.streaming_content), b"thumbnail-bytes")
        self.assertEqual(denied.status_code, 404)
