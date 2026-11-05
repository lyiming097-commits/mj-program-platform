from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.utils.dateparse import parse_datetime


class CableSourceError(RuntimeError):
    pass


_LENGTH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:米|m|M)")


def decimal_or_zero(value):
    if value is None:
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def extract_length(*texts):
    for value in texts:
        matches = _LENGTH_RE.findall(str(value or ""))
        if not matches:
            continue
        try:
            return Decimal(matches[-1]).quantize(Decimal("0.01"))
        except InvalidOperation:
            continue
    return None


def _catalog_settings():
    return settings.PRODUCT_ARCHIVE_CATALOG


def catalog_url(path):
    base_url = str(_catalog_settings().get("BASE_URL") or "").strip().rstrip("/") + "/"
    if not base_url.strip("/"):
        raise CableSourceError("产品档案内部目录地址未配置")
    return urljoin(base_url, str(path or "").lstrip("/"))


def catalog_request_headers():
    service_name = str(getattr(settings, "SERVICE_NAME", "") or "cable-mall-backend").strip()
    secret = str(getattr(settings, "AUTH_SERVICE_INTROSPECTION_SECRET", "") or "").strip()
    if not service_name or not secret:
        raise CableSourceError("线缆商城内部服务凭据未配置")
    return {
        "Accept": "application/json",
        "X-Internal-Service": service_name,
        "X-Internal-Auth-Secret": secret,
        "X-Request-Id": uuid.uuid4().hex,
    }


def is_catalog_url(value):
    candidate = urlsplit(str(value or "").strip())
    base = urlsplit(catalog_url(""))
    return bool(candidate.scheme in {"http", "https"} and candidate.netloc == base.netloc)


def _timeout_seconds():
    try:
        return max(float(_catalog_settings().get("TIMEOUT_SECONDS", 8)), 0.5)
    except (TypeError, ValueError):
        return 8.0


def _decode_error(raw_body):
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("error") or payload.get("message") or "").strip()


def _request_json(path):
    request = urllib.request.Request(
        catalog_url(path),
        method="GET",
        headers=catalog_request_headers(),
    )
    try:
        with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        message = _decode_error(exc.read()) or "产品档案拒绝了线材目录请求"
        raise CableSourceError(f"产品档案目录读取失败：{message}") from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        raise CableSourceError("产品档案内部服务暂时不可用") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CableSourceError("产品档案目录返回了无效数据") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        message = str(payload.get("error") or "产品档案目录返回失败").strip() if isinstance(payload, dict) else ""
        raise CableSourceError(message or "产品档案目录返回失败")
    return payload


def request_product_image(product_archive_id, *, method="GET", variant="preview"):
    """Read a bounded image derivative from the product archive service."""
    normalized_variant = str(variant or "preview").strip().lower()
    if normalized_variant not in {"thumbnail", "preview"}:
        raise CableSourceError("产品图片规格不正确")
    path = f"products/{urllib.parse.quote(str(product_archive_id), safe='-')}/image/"
    path = f"{path}?{urllib.parse.urlencode({'variant': normalized_variant})}"
    request = urllib.request.Request(
        catalog_url(path),
        method=method,
        headers=catalog_request_headers(),
    )
    try:
        with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
            max_bytes = 500 * 1024 if normalized_variant == "thumbnail" else 1024 * 1024
            body = b"" if method == "HEAD" else response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise CableSourceError("产品图片超过大小限制")
            return {
                "body": body,
                "content_type": response.headers.get("Content-Type") or "image/jpeg",
                "content_length": response.headers.get("Content-Length"),
                "cache_control": response.headers.get("Cache-Control") or "private, max-age=300",
            }
    except urllib.error.HTTPError as exc:
        message = _decode_error(exc.read()) or "产品图片读取失败"
        raise CableSourceError(message) from exc
    except CableSourceError:
        raise
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        raise CableSourceError("产品档案内部服务暂时不可用") from exc


def normalize_row(row):
    if not isinstance(row, dict):
        raise CableSourceError("产品档案目录包含无效产品数据")
    try:
        product_archive_id = int(row.get("id"))
    except (TypeError, ValueError) as exc:
        raise CableSourceError("产品档案目录缺少稳定产品编号") from exc
    images = row.get("product_images") or []
    if isinstance(images, str):
        images = [images] if images else []
    archive_updated_at = row.get("archive_updated_at")
    if isinstance(archive_updated_at, str):
        archive_updated_at = parse_datetime(archive_updated_at)
    raw_salesperson_price = row.get("salesperson_price")
    if raw_salesperson_price is None or (
        isinstance(raw_salesperson_price, str) and not raw_salesperson_price.strip()
    ):
        raw_salesperson_price = row.get("unit_price")
    parameter_values = []
    parameter_rows = row.get("parameterPreviewRows")
    if isinstance(parameter_rows, list):
        for parameter in parameter_rows:
            if not isinstance(parameter, dict):
                continue
            value = str(
                parameter.get("scheme")
                or parameter.get("tender")
                or parameter.get("bid")
                or ""
            ).strip()
            if value and value not in parameter_values:
                parameter_values.append(value)
    plan_para = "\n".join(parameter_values) or str(row.get("plan_para") or "").strip()
    return {
        "product_archive_id": product_archive_id,
        "label": str(row.get("label") or "").strip(),
        "product_brand": str(row.get("product_brand") or "").strip(),
        "product_model": str(row.get("product_model") or "").strip(),
        "abbr": str(row.get("abbr") or "").strip(),
        "category_a": str(row.get("category_a") or "未分类").strip() or "未分类",
        "category_b": str(row.get("category_b") or "其他").strip() or "其他",
        "kingdee_code": str(row.get("kingdeeCode") or "").strip(),
        "product_images": [str(value).strip() for value in images if str(value or "").strip()],
        "plan_para": plan_para,
        "spec_text": str(row.get("spec_text") or "").strip(),
        "length_m": extract_length(row.get("abbr"), row.get("product_model"), row.get("label")),
        "quantity_unit": str(row.get("quantity_unit") or "").strip(),
        "unit_price": decimal_or_zero(row.get("unit_price")),
        "salesperson_price": decimal_or_zero(raw_salesperson_price),
        "distributor_price": decimal_or_zero(row.get("distributor_price")),
        "budget_price": decimal_or_zero(row.get("budget_price")),
        "market_reference_price": decimal_or_zero(row.get("market_reference_price")),
        "comments": str(row.get("comments") or "").strip(),
        "phase": int(row.get("phase") or (2 if row.get("is_active", True) else 5)),
        "archive_updated_at": archive_updated_at,
        "is_active": bool(row.get("is_active", True)),
    }


def source_cable_category_labels():
    return []


def fetch_online_cables():
    payload = _request_json(_catalog_settings().get("CABLES_PATH", "cables/"))
    items = payload.get("items")
    if not isinstance(items, list):
        raise CableSourceError("产品档案目录缺少线材列表")
    return [normalize_row(row) for row in items]


def source_health():
    try:
        payload = _request_json(_catalog_settings().get("HEALTH_PATH", "health/"))
    except CableSourceError as exc:
        return {"ok": False, "source": "product-archive", "message": str(exc)}
    return {
        "ok": True,
        "source": "product-archive",
        "product_count": int(payload.get("productCount") or 0),
        "service": str(payload.get("serviceName") or "").strip(),
    }
