from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

from django.conf import settings


class ManualRenderError(RuntimeError):
    pass


def is_feishu_document_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and not parsed.username
        and not parsed.password
        and port in (None, 443)
        and (hostname == "feishu.cn" or hostname.endswith(".feishu.cn"))
    )


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _cache_ttl_seconds() -> int:
    return _positive_int_env("MANUAL_RENDER_CACHE_TTL_SECONDS", 6 * 60 * 60)


def _max_pdf_bytes() -> int:
    return _positive_int_env("MANUAL_RENDERER_MAX_PDF_BYTES", 30 * 1024 * 1024)


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return Path(settings.MEDIA_ROOT) / "product_manual_cache" / f"{digest}.pdf"


def _cache_is_fresh(path: Path) -> bool:
    try:
        return path.is_file() and time.time() - path.stat().st_mtime <= _cache_ttl_seconds()
    except OSError:
        return False


def _renderer_error_message(raw_body: bytes) -> str:
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    return str(payload.get("error") or "").strip() if isinstance(payload, dict) else ""


def _request_renderer_pdf(url: str) -> bytes:
    endpoint = os.getenv(
        "MANUAL_RENDERER_URL",
        "http://after-sales-manual-renderer:3000/render",
    ).strip()
    token = os.getenv("MANUAL_RENDERER_TOKEN", "").strip()
    if not endpoint or not token:
        raise ManualRenderError("说明书渲染服务尚未配置")
    request = urllib.request.Request(
        endpoint,
        method="POST",
        data=json.dumps({"url": url}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/pdf",
            "Content-Type": "application/json; charset=utf-8",
            "X-Renderer-Token": token,
        },
    )
    max_bytes = _max_pdf_bytes()
    try:
        with urllib.request.urlopen(
            request,
            timeout=_positive_int_env("MANUAL_RENDERER_TIMEOUT_SECONDS", 90),
        ) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > max_bytes:
                raise ManualRenderError("生成的说明书文件过大")
            body = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        message = _renderer_error_message(exc.read()) or "飞书说明书暂时无法生成，请稍后重试"
        raise ManualRenderError(message) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, ValueError) as exc:
        raise ManualRenderError("飞书说明书暂时无法生成，请稍后重试") from exc
    if len(body) > max_bytes:
        raise ManualRenderError("生成的说明书文件过大")
    if not body.startswith(b"%PDF-"):
        raise ManualRenderError("说明书渲染服务返回了无效文件")
    return body


def render_feishu_manual_pdf(url: str) -> Path:
    if not is_feishu_document_url(url):
        raise ManualRenderError("该地址不是可渲染的飞书说明书")
    cache_path = _cache_path(url)
    if _cache_is_fresh(cache_path):
        return cache_path
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = cache_path.with_suffix(".lock")
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if _cache_is_fresh(cache_path):
            return cache_path
        try:
            pdf = _request_renderer_pdf(url)
        except ManualRenderError:
            if cache_path.is_file():
                return cache_path
            raise
        temporary_path = cache_path.with_name(f".{cache_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            temporary_path.write_bytes(pdf)
            os.replace(temporary_path, cache_path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return cache_path
