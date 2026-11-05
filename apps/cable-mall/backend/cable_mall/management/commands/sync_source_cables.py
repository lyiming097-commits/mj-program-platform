from django.core.management.base import BaseCommand, CommandError

from cable_mall.source_catalog import CableSourceError, fetch_online_cables, source_cable_category_labels
from cable_mall.views import sync_product_thumbnails, upsert_cable_products


class Command(BaseCommand):
    help = "从产品档案同步线材到线缆商城销售产品镜像"

    def handle(self, *args, **options):
        try:
            rows = fetch_online_cables()
        except CableSourceError as exc:
            raise CommandError(str(exc)) from exc

        result = upsert_cable_products(rows, category_a_labels=source_cable_category_labels())
        result["thumbnails"] = sync_product_thumbnails()
        self.stdout.write(
            self.style.SUCCESS(
                f"同步完成：新增 {result['created']}，更新 {result['updated']}，"
                f"当前在线 {result['active_count']}，缩略图新增 {result['thumbnails']['created']}，"
                f"已有 {result['thumbnails']['existing']}，失败 {result['thumbnails']['failed']}"
            )
        )
