import hashlib
import logging
import math
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from django.core.cache import cache


class ProductCatalogError(RuntimeError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


_cache_lock = threading.Lock()
_refresh_state_lock = threading.Lock()
_cached_at = 0.0
_cached_source_at = 0.0
_cached_products: list[dict[str, Any]] = []
_refresh_thread: threading.Thread | None = None
logger = logging.getLogger(__name__)

PRODUCT_CATALOG_CACHE_KEY = "competitive:product-catalog:v3"
PRODUCT_CATALOG_LEGACY_CACHE_KEY = "competitive:product-catalog:v2"
PRODUCT_CATALOG_REFRESH_LOCK_KEY = "competitive:product-catalog:refresh-lock:v1"
PRODUCT_CATALOG_CACHE_TTL_SECONDS = 300
PRODUCT_CATALOG_STALE_CACHE_TTL_SECONDS = 86_400
PRODUCT_CATALOG_LOCAL_CACHE_TTL_SECONDS = 60
PRODUCT_IMAGE_VARIANT_MAX_BYTES = {
    "thumbnail": 500 * 1024,
    "preview": 1024 * 1024,
}


def _cache_ttl_seconds() -> int:
    try:
        configured = int(
            os.getenv(
                "PRODUCT_ARCHIVE_CATALOG_CACHE_TTL_SECONDS",
                str(PRODUCT_CATALOG_CACHE_TTL_SECONDS),
            )
        )
    except (TypeError, ValueError):
        configured = PRODUCT_CATALOG_CACHE_TTL_SECONDS
    return max(configured, 60)


def _stale_cache_ttl_seconds() -> int:
    try:
        configured = int(
            os.getenv(
                "PRODUCT_ARCHIVE_CATALOG_STALE_TTL_SECONDS",
                str(PRODUCT_CATALOG_STALE_CACHE_TTL_SECONDS),
            )
        )
    except (TypeError, ValueError):
        configured = PRODUCT_CATALOG_STALE_CACHE_TTL_SECONDS
    return max(configured, _cache_ttl_seconds() * 2)


def _cache_get(key: str) -> Any:
    try:
        return cache.get(key)
    except Exception:
        return None


def _cache_set(key: str, value: Any, *, timeout: int | None = None) -> None:
    try:
        cache.set(key, value, timeout=timeout or _cache_ttl_seconds())
    except Exception:
        pass


def _cache_delete(key: str) -> None:
    try:
        cache.delete(key)
    except Exception:
        pass


def _cached_product_list(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    if not all(isinstance(item, dict) and item.get("id") for item in value):
        return None
    return [dict(item) for item in value]


def _cached_product_snapshot(value: Any) -> tuple[list[dict[str, Any]], float] | None:
    if not isinstance(value, dict):
        return None
    products = _cached_product_list(value.get("products"))
    if products is None:
        return None
    try:
        fetched_at = float(value.get("fetchedAt") or 0)
    except (TypeError, ValueError):
        fetched_at = 0.0
    return products, fetched_at


def _set_local_products(products: list[dict[str, Any]], fetched_at: float) -> None:
    global _cached_at, _cached_source_at, _cached_products
    _cached_products = [dict(item) for item in products]
    _cached_at = time.monotonic()
    _cached_source_at = fetched_at


def _store_product_snapshot(products: list[dict[str, Any]], fetched_at: float) -> None:
    _cache_set(
        PRODUCT_CATALOG_CACHE_KEY,
        {
            "fetchedAt": fetched_at,
            "products": [dict(item) for item in products],
        },
        timeout=_stale_cache_ttl_seconds(),
    )


def _shared_product_snapshot() -> tuple[list[dict[str, Any]], float] | None:
    snapshot = _cached_product_snapshot(_cache_get(PRODUCT_CATALOG_CACHE_KEY))
    if snapshot is not None:
        return snapshot
    legacy_products = _cached_product_list(_cache_get(PRODUCT_CATALOG_LEGACY_CACHE_KEY))
    if legacy_products is None:
        return None
    # Preserve the existing cache during rollout, but refresh it in the background.
    snapshot = legacy_products, 0.0
    _store_product_snapshot(*snapshot)
    return snapshot


def _snapshot_is_fresh(fetched_at: float) -> bool:
    return fetched_at > 0 and time.time() - fetched_at < _cache_ttl_seconds()


def _normalize_category_name(value: Any, fallback: str) -> str:
    """Preserve product archive taxonomy names and normalize whitespace only."""
    return str(value or "").strip() or fallback


def _normalize_sort_order(value: Any) -> int:
    try:
        return min(max(int(value), 0), 1_000_000)
    except (TypeError, ValueError):
        return 1_000_000


def _price_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _product_sort_key(product: dict[str, Any]) -> tuple[Any, ...]:
    return (
        product.get("productDomainSortOrder", 1_000_000),
        product.get("levelTwoSortOrder", 1_000_000),
        product.get("categorySortOrder", 1_000_000),
        str(product.get("productDomain") or "").casefold(),
        str(product.get("levelTwo") or "").casefold(),
        str(product.get("category") or "").casefold(),
        str(product.get("name") or "").casefold(),
        str(product.get("id") or ""),
    )


def _headers() -> dict[str, str]:
    secret = os.getenv("AUTH_SERVICE_INTROSPECTION_SECRET", "").strip()
    if not secret:
        raise ProductCatalogError("产品档案内部服务凭据未配置")
    return {
        "Accept": "application/json",
        "X-Internal-Service": os.getenv(
            "SERVICE_NAME", "competitive-backend"
        ).strip(),
        "X-Internal-Auth-Secret": secret,
        "X-Request-Id": uuid.uuid4().hex,
    }


def _base_url() -> str:
    return os.getenv(
        "PRODUCT_ARCHIVE_CATALOG_URL",
        "http://product-archive-backend:8000/api/internal/product-catalog/",
    ).strip().rstrip("/") + "/"


def _normalize_product(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ProductCatalogError("产品档案返回了无效产品数据")
    try:
        product_id = int(row.get("id"))
    except (TypeError, ValueError) as exc:
        raise ProductCatalogError("产品档案缺少稳定产品编号") from exc
    if product_id <= 0:
        raise ProductCatalogError("产品档案包含无效产品编号")
    product_id_text = str(product_id)
    has_image = bool(row.get("has_image") or row.get("product_images"))
    product_domain = str(row.get("product_domain") or "").strip() or "未分类"
    level_two = _normalize_category_name(
        row.get("level_two") or row.get("category_a"),
        "未分类",
    )
    category = _normalize_category_name(
        row.get("category") or row.get("category_b"),
        "其他",
    )
    short_name = str(row.get("abbr") or "").strip()
    full_name = str(row.get("label") or "").strip()
    return {
        "id": product_id_text,
        "name": short_name or full_name or product_id_text,
        "shortName": short_name,
        "fullName": full_name,
        "model": str(
            row.get("product_model") or row.get("kingdeeCode") or product_id_text
        ).strip(),
        "brand": str(row.get("product_brand") or "").strip(),
        "productDomain": product_domain,
        "levelTwo": level_two,
        "category": category,
        "categoryA": level_two,
        "categoryB": category,
        "productDomainSortOrder": _normalize_sort_order(
            row.get("product_domain_sort_order")
        ),
        "levelTwoSortOrder": _normalize_sort_order(
            row.get("category_a_sort_order")
        ),
        "categorySortOrder": _normalize_sort_order(
            row.get("category_b_sort_order")
        ),
        "kingdeeCode": str(row.get("kingdeeCode") or "").strip(),
        "unit": str(row.get("quantity_unit") or "").strip(),
        "unitPrice": _price_text(row.get("unit_price")),
        "salespersonPrice": _price_text(row.get("salesperson_price")),
        "distributorPrice": _price_text(row.get("distributor_price")),
        "budgetPrice": _price_text(row.get("budget_price")),
        "marketReferencePrice": _price_text(row.get("market_reference_price")),
        "planPara": str(row.get("plan_para") or "").strip(),
        "specText": str(row.get("spec_text") or "").strip(),
        "comments": str(row.get("comments") or "").strip(),
        "phase": int(row.get("phase") or 0),
        "archiveUpdatedAt": str(row.get("archive_updated_at") or "").strip(),
        "isActive": bool(row.get("is_active")),
        "hasImage": has_image,
        "line": product_domain,
        "segment": category,
        "image": (
            f"/api/competitive/products/{quote(product_id_text, safe='')}/image?variant=thumbnail"
            if has_image
            else ""
        ),
        "imagePreview": (
            f"/api/competitive/products/{quote(product_id_text, safe='')}/image?variant=preview"
            if has_image
            else ""
        ),
        "coverage": "无竞品",
    }


def _request_page(client: httpx.Client, page: int) -> dict[str, Any]:
    try:
        response = client.get(
            f"{_base_url()}products/",
            headers=_headers(),
            params={
                "page": page,
                "pageSize": 200,
                "excludeEliminated": "true",
                "profile": "competitive",
                "includeOptions": "false",
            },
        )
    except httpx.HTTPError as exc:
        raise ProductCatalogError("产品档案暂时不可用") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProductCatalogError("产品档案返回了无效响应") from exc
    if response.status_code != 200 or not isinstance(payload, dict) or payload.get("ok") is not True:
        message = (
            str(payload.get("error") or payload.get("message") or "").strip()
            if isinstance(payload, dict)
            else ""
        )
        status_code = response.status_code if response.status_code in {400, 403, 404} else 503
        raise ProductCatalogError(message or "产品档案读取失败", status_code)
    return payload


def _fetch_products_from_source() -> list[dict[str, Any]]:
    timeout = float(os.getenv("PRODUCT_ARCHIVE_CATALOG_TIMEOUT_SECONDS", "8"))
    with httpx.Client(timeout=timeout) as client:
        first_payload = _request_page(client, 1)
        first_rows = first_payload.get("items")
        if not isinstance(first_rows, list):
            raise ProductCatalogError("产品档案返回的产品列表格式不正确")
        products = [_normalize_product(row) for row in first_rows]
        total = int(first_payload.get("total") or 0)
        page_size = max(int(first_payload.get("pageSize") or 200), 1)
        total_pages = math.ceil(total / page_size)
        if total_pages > 1:
            with ThreadPoolExecutor(
                max_workers=min(total_pages - 1, 6),
                thread_name_prefix="competitive-product-page",
            ) as executor:
                remaining = list(executor.map(
                    lambda page: _request_page(client, page),
                    range(2, total_pages + 1),
                ))
            for payload in remaining:
                rows = payload.get("items")
                if not isinstance(rows, list):
                    raise ProductCatalogError("产品档案返回的产品列表格式不正确")
                products.extend(_normalize_product(row) for row in rows)
    products.sort(key=_product_sort_key)
    return products


def _refresh_products() -> list[dict[str, Any]]:
    products = _fetch_products_from_source()
    fetched_at = time.time()
    _set_local_products(products, fetched_at)
    _store_product_snapshot(products, fetched_at)
    return [dict(item) for item in products]


def _acquire_refresh_lock(token: str) -> bool:
    try:
        return bool(cache.add(PRODUCT_CATALOG_REFRESH_LOCK_KEY, token, timeout=120))
    except Exception:
        return True


def _release_refresh_lock(token: str) -> None:
    try:
        if cache.get(PRODUCT_CATALOG_REFRESH_LOCK_KEY) == token:
            cache.delete(PRODUCT_CATALOG_REFRESH_LOCK_KEY)
    except Exception:
        pass


def _background_refresh(token: str) -> None:
    global _refresh_thread
    try:
        with _cache_lock:
            snapshot = _shared_product_snapshot()
            if snapshot is not None and _snapshot_is_fresh(snapshot[1]):
                _set_local_products(*snapshot)
                return
            _refresh_products()
    except Exception as exc:
        logger.warning("Product catalog background refresh failed: %s", exc)
    finally:
        _release_refresh_lock(token)
        with _refresh_state_lock:
            _refresh_thread = None


def _schedule_background_refresh() -> None:
    global _refresh_thread
    with _refresh_state_lock:
        if _refresh_thread is not None and _refresh_thread.is_alive():
            return
        token = uuid.uuid4().hex
        if not _acquire_refresh_lock(token):
            return
        _refresh_thread = threading.Thread(
            target=_background_refresh,
            args=(token,),
            name="competitive-product-catalog-refresh",
            daemon=True,
        )
        _refresh_thread.start()


def get_products(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    cache_ttl = _cache_ttl_seconds()
    local_cache_ttl = min(cache_ttl, PRODUCT_CATALOG_LOCAL_CACHE_TTL_SECONDS)
    if not force_refresh and _cached_at and time.monotonic() - _cached_at < local_cache_ttl:
        if not _snapshot_is_fresh(_cached_source_at):
            _schedule_background_refresh()
        return [dict(item) for item in _cached_products]
    if not force_refresh:
        snapshot = _shared_product_snapshot()
        if snapshot is not None:
            _set_local_products(*snapshot)
            if not _snapshot_is_fresh(snapshot[1]):
                _schedule_background_refresh()
            return [dict(item) for item in snapshot[0]]
    with _cache_lock:
        if not force_refresh:
            if _cached_at and time.monotonic() - _cached_at < local_cache_ttl:
                return [dict(item) for item in _cached_products]
            snapshot = _shared_product_snapshot()
            if snapshot is not None:
                _set_local_products(*snapshot)
                if not _snapshot_is_fresh(snapshot[1]):
                    _schedule_background_refresh()
                return [dict(item) for item in snapshot[0]]
        return _refresh_products()


def get_product(product_id: str) -> dict[str, Any] | None:
    normalized_id = str(product_id or "").strip()
    return next((item for item in get_products() if item["id"] == normalized_id), None)


def get_product_detail(product: dict[str, Any]) -> dict[str, Any]:
    product_id = str(product.get("id") or "").strip()
    if not product_id:
        return dict(product)
    cache_version = str(product.get("archiveUpdatedAt") or "current")
    version_digest = hashlib.sha1(cache_version.encode("utf-8")).hexdigest()[:16]
    detail_cache_key = f"competitive:product-detail:v2:{product_id}:{version_digest}"
    cached_detail = _cache_get(detail_cache_key)
    if isinstance(cached_detail, dict):
        return {**product, **cached_detail}
    detail_url = f"{_base_url()}products/{quote(product_id, safe='')}/detail/"
    timeout = float(os.getenv("PRODUCT_ARCHIVE_CATALOG_TIMEOUT_SECONDS", "8"))
    try:
        response = httpx.get(detail_url, headers=_headers(), timeout=timeout)
        payload = response.json()
    except (ProductCatalogError, httpx.HTTPError, ValueError):
        return dict(product)
    item = payload.get("item") if isinstance(payload, dict) else None
    if response.status_code != 200 or not isinstance(item, dict):
        return dict(product)
    parameter_rows = item.get("parameterRows")
    if not isinstance(parameter_rows, list):
        return dict(product)

    parameter_values = {"bid": [], "tender": [], "scheme": []}
    for row in parameter_rows:
        if not isinstance(row, dict):
            continue
        for key in parameter_values:
            value = str(row.get(key) or "").strip()
            if value and value not in parameter_values[key]:
                parameter_values[key].append(value)
    detail = {
        "bidPara": "\n".join(parameter_values["bid"]),
        "tenderPara": "\n".join(parameter_values["tender"]),
        "planPara": "\n".join(parameter_values["scheme"]) or product.get("planPara", ""),
    }
    _cache_set(detail_cache_key, detail)
    return {**product, **detail}


def get_product_image(product_id: str, *, variant: str = "thumbnail") -> tuple[bytes, str]:
    try:
        normalized_id = int(str(product_id).strip())
    except ValueError as exc:
        raise ProductCatalogError("产品编号不正确", 400) from exc
    normalized_variant = str(variant or "thumbnail").strip().lower()
    max_bytes = PRODUCT_IMAGE_VARIANT_MAX_BYTES.get(normalized_variant)
    if max_bytes is None:
        raise ProductCatalogError("产品图片规格不正确", 400)
    timeout = float(os.getenv("PRODUCT_ARCHIVE_CATALOG_TIMEOUT_SECONDS", "8"))
    try:
        response = httpx.get(
            f"{_base_url()}products/{quote(str(normalized_id), safe='')}/image/"
            f"?{urlencode({'variant': normalized_variant})}",
            headers=_headers(),
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise ProductCatalogError("产品图片暂时不可用") from exc
    if response.status_code != 200:
        status_code = response.status_code if response.status_code in {400, 403, 404} else 503
        raise ProductCatalogError("产品图片不存在", status_code)
    try:
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) > max_bytes:
            raise ProductCatalogError("产品图片超过大小限制")
    except (TypeError, ValueError):
        pass
    if len(response.content) > max_bytes:
        raise ProductCatalogError("产品图片超过大小限制")
    return response.content, response.headers.get("Content-Type", "application/octet-stream")
