from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.request
import uuid
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit

from django.core.cache import cache

from .product_search import matches_product


class ProductCatalogError(RuntimeError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


PRODUCT_IMAGE_MAX_BYTES = {
    "thumbnail": 500 * 1024,
    "preview": 1024 * 1024,
}
MANUAL_KEYS = {"productManual", "installManual", "manual"}
PRODUCT_IMAGE_SLOT_PATTERN = re.compile(r"(?:cover|size|detail-[1-4]|other-[1-9][0-9]*)\Z")


def _base_url() -> str:
    return os.getenv(
        "PRODUCT_ARCHIVE_CATALOG_URL",
        "http://product-archive-backend:8000/api/internal/product-catalog/",
    ).strip().rstrip("/") + "/"


def _timeout_seconds() -> float:
    try:
        return max(float(os.getenv("PRODUCT_ARCHIVE_CATALOG_TIMEOUT_SECONDS", "8")), 0.5)
    except ValueError:
        return 8.0


def _headers() -> dict[str, str]:
    secret = os.getenv("AUTH_SERVICE_INTROSPECTION_SECRET", "").strip()
    if not secret:
        raise ProductCatalogError("产品档案内部服务凭据未配置")
    return {
        "Accept": "application/json",
        "X-Internal-Service": os.getenv("SERVICE_NAME", "after-sales-backend").strip() or "after-sales-backend",
        "X-Internal-Auth-Secret": secret,
        "X-Request-Id": uuid.uuid4().hex,
    }


def _error_message(raw_body: bytes) -> str:
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    return str(payload.get("error") or payload.get("message") or "").strip() if isinstance(payload, dict) else ""


def _request(path: str, *, params: dict | None = None, max_bytes: int | None = None) -> tuple[bytes, str]:
    url = urljoin(_base_url(), str(path or "").lstrip("/"))
    if params:
        query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
        if query:
            url = f"{url}?{query}"
    request = urllib.request.Request(url, method="GET", headers=_headers())
    try:
        with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
            if max_bytes is None:
                body = response.read()
            else:
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) > max_bytes:
                    raise ProductCatalogError("产品图片超过大小限制")
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise ProductCatalogError("产品图片超过大小限制")
            return body, str(response.headers.get("Content-Type") or "application/octet-stream")
    except urllib.error.HTTPError as exc:
        message = _error_message(exc.read()) or "产品档案拒绝了读取请求"
        status_code = exc.code if exc.code in {400, 403, 404} else 503
        raise ProductCatalogError(message, status_code) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, ValueError) as exc:
        raise ProductCatalogError("产品档案暂时不可用") from exc


def _request_json(path: str, *, params: dict | None = None) -> dict:
    raw_body, _content_type = _request(path, params=params)
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductCatalogError("产品档案返回了无效数据") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ProductCatalogError("产品档案读取失败")
    return payload


def _normalize_manuals(value) -> list[dict]:
    result = []
    for row in value if isinstance(value, list) else []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        url = str(row.get("url") or "").strip()
        if key not in MANUAL_KEYS or not url:
            continue
        result.append({
            "key": key,
            "label": str(row.get("label") or "产品说明书").strip() or "产品说明书",
            "url": url,
        })
    return result


def _product_image_slots(row: dict, product_id: int) -> list[str]:
    urls = row.get("product_images")
    if not isinstance(urls, list):
        return ["cover"] if row.get("has_image") else []
    slots = []
    expected_path = f"/api/internal/product-catalog/products/{product_id}/image/"
    for url in urls:
        try:
            parsed = urlsplit(str(url))
        except ValueError:
            continue
        slot = parse_qs(parsed.query).get("slot", [""])[0]
        if parsed.path == expected_path and PRODUCT_IMAGE_SLOT_PATTERN.fullmatch(slot) and slot not in slots:
            slots.append(slot)
    return slots or (["cover"] if row.get("has_image") else [])


def _normalize_product(row: dict) -> dict:
    try:
        product_id = int(row.get("id"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProductCatalogError("产品档案包含无效产品编号") from exc
    if product_id <= 0:
        raise ProductCatalogError("产品档案包含无效产品编号")
    has_image = bool(row.get("has_image") or row.get("product_images"))
    image_base = f"/api/after-sales/product-catalog/{quote(str(product_id), safe='')}/image"
    product_images = [
        {
            "slot": slot,
            "thumbnail": f"{image_base}?slot={slot}&variant=thumbnail",
            "preview": f"{image_base}?slot={slot}&variant=preview",
        }
        for slot in _product_image_slots(row, product_id)
    ]
    parameter_rows = []
    for index, parameter in enumerate(row.get("parameterPreviewRows") if isinstance(row.get("parameterPreviewRows"), list) else []):
        if not isinstance(parameter, dict):
            continue
        parameter_rows.append({
            "id": str(parameter.get("id") or f"parameter-{index + 1}"),
            "scheme": str(parameter.get("scheme") or "").strip(),
            "tender": str(parameter.get("tender") or "").strip(),
            "bid": str(parameter.get("bid") or "").strip(),
        })
    return {
        "productId": product_id,
        "kingdeeCode": str(row.get("kingdeeCode") or "").strip(),
        "name": str(row.get("label") or "").strip(),
        "brand": str(row.get("product_brand") or "").strip(),
        "model": str(row.get("product_model") or "").strip(),
        "abbr": str(row.get("abbr") or "").strip(),
        "productDomain": str(row.get("product_domain") or "").strip(),
        "categoryA": str(row.get("product_domain") or "").strip(),
        "categoryB": str(row.get("category_a") or "").strip(),
        "categoryC": str(row.get("category_b") or "").strip(),
        "unit": str(row.get("quantity_unit") or "").strip(),
        "lifecycle": str(row.get("lifecycle") or "").strip(),
        "configInfo": str(row.get("config_info") or "").strip(),
        "packageInfo": str(row.get("package_info") or "").strip(),
        "parameterText": str(row.get("plan_para") or "").strip(),
        "parameterRows": parameter_rows,
        "isActive": bool(row.get("is_active", True)),
        "productThumb": f"{image_base}?variant=thumbnail" if has_image else "",
        "productPreview": f"{image_base}?variant=preview" if has_image else "",
        "productImages": product_images,
        "manuals": _normalize_manuals(row.get("manuals")),
    }


def fetch_product_catalog(params: dict | None = None) -> dict:
    source_params = dict(params or {})
    query = str(source_params.get("q") or "").strip()
    page = int(source_params.get("page") or 1)
    page_size = int(source_params.get("pageSize") or 20)
    product_domain = source_params.pop("categoryA", "")
    category_a = source_params.pop("categoryB", "")
    category_b = source_params.pop("categoryC", "")
    source_params.update({
        "productDomain": product_domain,
        "categoryA": category_a,
        "categoryB": category_b,
        "includeManuals": "1",
    })
    if query:
        source_params.pop("q", None)
        source_params.pop("page", None)
        source_params.pop("pageSize", None)
        cache_key = "after-sales:catalog-scan:v1:" + hashlib.sha256(
            json.dumps(source_params, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        snapshot = cache.get(cache_key)
        if snapshot is None:
            candidates = []
            scan_page = 1
            while True:
                payload = _request_json("products/", params={
                    **source_params, "page": scan_page, "pageSize": 200,
                    "profile": "competitive",
                    "includeManuals": "0", "includeOptions": "true" if scan_page == 1 else "false",
                })
                batch = payload.get("items") if isinstance(payload.get("items"), list) else []
                if scan_page == 1:
                    categories = (
                        payload.get("productDomains", []), payload.get("categoriesA", []), payload.get("categoriesB", []),
                    )
                candidates.extend(row for row in batch if isinstance(row, dict))
                if not batch or scan_page * 200 >= int(payload.get("total") or 0):
                    break
                scan_page += 1
            snapshot = (candidates, categories)
            cache.set(cache_key, snapshot, timeout=5)
        candidates, categories = snapshot
        matches = [row for row in candidates if matches_product(query, row)]
        total = len(matches)
        ids = [str(row["id"]) for row in matches[(page - 1) * page_size:page * page_size]]
        if ids:
            detail = _request_json("products/", params={
                "productIds": ",".join(ids), "page": 1, "pageSize": len(ids),
                "includeManuals": "1", "includeOptions": "false",
            })
            details_by_id = {str(row.get("id")): row for row in detail.get("items", [])}
            rows = [details_by_id[item_id] for item_id in ids if item_id in details_by_id]
        else:
            rows = []
        return {
            "items": [_normalize_product(row) for row in rows],
            "total": total, "page": page, "pageSize": page_size,
            "categoriesA": [str(value) for value in categories[0] if str(value or "").strip()],
            "categoriesB": [str(value) for value in categories[1] if str(value or "").strip()],
            "categoriesC": [str(value) for value in categories[2] if str(value or "").strip()],
        }
    payload = _request_json("products/", params=source_params)
    rows = payload.get("items") if isinstance(payload.get("items"), list) else []
    return {
        "items": [_normalize_product(row) for row in rows],
        "total": int(payload.get("total") or 0),
        "page": int(payload.get("page") or 1),
        "pageSize": int(payload.get("pageSize") or 20),
        "categoriesA": [str(value) for value in payload.get("productDomains", []) if str(value or "").strip()],
        "categoriesB": [str(value) for value in payload.get("categoriesA", []) if str(value or "").strip()],
        "categoriesC": [str(value) for value in payload.get("categoriesB", []) if str(value or "").strip()],
    }


def fetch_products_by_ids(product_ids) -> dict[int, dict]:
    normalized = []
    for value in product_ids or []:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and product_id not in normalized:
            normalized.append(product_id)
    if not normalized:
        return {}
    payload = fetch_product_catalog({
        "productIds": ",".join(str(value) for value in normalized),
        "page": 1,
        "pageSize": min(len(normalized), 200),
    })
    return {int(item["productId"]): item for item in payload["items"]}


def fetch_product_image(product_id: int, *, variant: str = "thumbnail", slot: str = "cover") -> tuple[bytes, str]:
    normalized_variant = str(variant or "thumbnail").strip().lower()
    normalized_slot = str(slot or "cover").strip().lower()
    max_bytes = PRODUCT_IMAGE_MAX_BYTES.get(normalized_variant)
    if max_bytes is None or not PRODUCT_IMAGE_SLOT_PATTERN.fullmatch(normalized_slot):
        raise ProductCatalogError("产品图片规格无效", 400)
    params = {"variant": normalized_variant}
    if normalized_slot != "cover":
        params["slot"] = normalized_slot
    return _request(
        f"products/{quote(str(int(product_id)), safe='')}/image/",
        params=params,
        max_bytes=max_bytes,
    )
