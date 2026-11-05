import threading
import time

from .models import Competitor


BOARD_SUMMARY_CACHE_TTL_SECONDS = 15

_summary_lock = threading.Lock()
_summary_cached_at = 0.0
_summary_cache: list[dict] | None = None


def get_competitor_board_summary(*, force_refresh: bool = False) -> list[dict]:
    global _summary_cached_at, _summary_cache
    now = time.monotonic()
    if (
        not force_refresh
        and _summary_cache is not None
        and now - _summary_cached_at < BOARD_SUMMARY_CACHE_TTL_SECONDS
    ):
        return [dict(item) for item in _summary_cache]

    with _summary_lock:
        now = time.monotonic()
        if (
            not force_refresh
            and _summary_cache is not None
            and now - _summary_cached_at < BOARD_SUMMARY_CACHE_TTL_SECONDS
        ):
            return [dict(item) for item in _summary_cache]

        grouped: dict[str, dict] = {}
        rows = Competitor.objects.filter(deleted_at__isnull=True).values(
            "product_id",
            "regions",
            "updated_on",
        )
        for row in rows:
            product_id = str(row.get("product_id") or "").strip()
            if not product_id:
                continue
            item = grouped.setdefault(
                product_id,
                {
                    "productId": product_id,
                    "count": 0,
                    "regionIds": set(),
                    "latestUpdate": "",
                },
            )
            item["count"] += 1
            item["regionIds"].update(
                str(region).strip()
                for region in (row.get("regions") or [])
                if str(region).strip()
            )
            updated = row.get("updated_on")
            updated_text = updated.isoformat() if updated else ""
            if updated_text > item["latestUpdate"]:
                item["latestUpdate"] = updated_text

        result = [
            {
                "productId": item["productId"],
                "count": item["count"],
                "regionCount": len(item["regionIds"]),
                "latestUpdate": item["latestUpdate"],
            }
            for item in grouped.values()
        ]
        result.sort(key=lambda item: item["productId"])
        _summary_cache = result
        _summary_cached_at = time.monotonic()
        return [dict(item) for item in result]


def invalidate_competitor_board_summary() -> None:
    global _summary_cached_at, _summary_cache
    with _summary_lock:
        _summary_cached_at = 0.0
        _summary_cache = None
