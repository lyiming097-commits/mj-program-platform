"""CRM owns project basics; service workflows keep their own IDs and history."""
from __future__ import annotations

import json
import hashlib
import logging
import socket
import threading
import uuid
from datetime import timedelta, timezone as datetime_timezone
from types import SimpleNamespace
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import ServiceProject
from .services import DomainValidationError, create_project, generated_code, text


logger = logging.getLogger(__name__)
SOURCE_KEYS = ("id", "name", "customerName", "ownerUserId", "owner", "customerProvince",
               "overview", "purchaseNeed", "stage", "status", "orderType", "deleted", "createdAt",
               "amount", "integrationWorkTypes", "integrationEngineeringArea", "bidTime")
SYNC_LEASE_SECONDS = 90
# CRM's sales funnel order: service starts at solution penetration. System
# procurement pools, blank stages and unknown stages are not sales milestones.
CRM_PRESALES_STAGES = ("方案渗透", "标前准备", "挂网投标", "中标待签", "待审合同", "已签合同")


def _cache_key(request):
    # Like Mall, reuse the verified snapshot across logins of the same user.
    # Auth still validates each request; actors and capabilities cannot share it.
    identity = [getattr(request, key, "") for key in
                ("auth_user_id", "auth_actor_user_id", "auth_can_use_system_admin", "auth_is_proxy")]
    identity.append((getattr(request, "auth_token_claims", {}) or {}).get("chn", ""))
    if not identity[0]:
        # Tests/anonymous callers must not create a shared authenticated scope.
        cookie = request.COOKIES.get(getattr(settings, "AUTH_COOKIE_NAME", "mj_auth_token"), "")
        identity.append([cookie, request.META.get("HTTP_AUTHORIZATION", "")])
    digest = hashlib.sha256(json.dumps(identity, default=str).encode()).hexdigest()
    # Refresh older snapshots once to include the read-only statistics fields.
    return "after-sales:crm:v6:" + digest


def _source_row(row):
    result = {key: row[key] for key in SOURCE_KEYS if key in row}
    # Only CRM's actual creation timestamp defines a new CRM project. Invalid
    # or missing timestamps must never fall back to today's local import time.
    try:
        created_at = parse_datetime(text(row.get("createdAt")))
    except (TypeError, ValueError, OverflowError):
        created_at = None
    if created_at is not None:
        if timezone.is_naive(created_at):
            created_at = timezone.make_aware(created_at, timezone.get_default_timezone())
        result["createdAt"] = created_at.astimezone(datetime_timezone.utc).isoformat()
    else:
        result.pop("createdAt", None)
    return result


def _sync_interval():
    return max(30, int(settings.CRM_PROJECT_SOURCE.get("SYNC_INTERVAL_SECONDS", 300)))


def _snapshot(request):
    failure = cache.get(_cache_key(request) + ":error")
    if failure and failure["code"] == "CRM_PERMISSION_DENIED":
        raise CrmSourceError(failure["message"], status=403, code=failure["code"])
    return cache.get(_cache_key(request))


def _remember_scope(request, ids, *, synced=False, verified_at=None):
    interval = _sync_interval()
    key = _cache_key(request)
    now = timezone.now()
    # Keep the last verified scope through one refresh window, as Mall does.
    # Importing workflows does not require users to wait to read existing rows.
    verified_at = verified_at or now
    expires_at = verified_at + timedelta(seconds=max(interval * 2, interval + 60))
    timeout = (expires_at - now).total_seconds()
    revoked_at = parse_datetime(cache.get(key + ":revokedAt") or "")
    if revoked_at and verified_at <= revoked_at:
        raise CrmSourceError("当前账号无权读取 CRM 项目，请重新核对权限", status=403, code="CRM_PERMISSION_DENIED")
    previous = _snapshot(request)  # A concurrent permission denial wins.
    if timeout <= 0:
        return
    cache.set(key, {"ids": ids, "verifiedAt": verified_at.isoformat(),
                    "syncedAt": now.isoformat() if synced else (previous or {}).get("syncedAt", ""),
                    "expiresAt": expires_at.isoformat()}, timeout=timeout)
    if synced:
        fresh_timeout = (verified_at + timedelta(seconds=interval) - now).total_seconds()
        if fresh_timeout > 0:
            cache.set(key + ":fresh", True, timeout=fresh_timeout)
        else:
            cache.delete(key + ":fresh")
    else:
        cache.delete(key + ":fresh")
    cache.delete(key + ":error")


def _remember_error(request, exc):
    if exc.code == "CRM_SESSION_EXPIRED":
        # An old worker's revoked login must not revoke the same user's new
        # authenticated login or poison its shared visibility snapshot.
        return
    key = _cache_key(request)
    previous = cache.get(key + ":error")
    if previous and previous["code"] == "CRM_PERMISSION_DENIED" and exc.code != "CRM_PERMISSION_DENIED":
        return
    cache.set(key + ":error", {"message": str(exc), "code": exc.code}, timeout=30)
    if exc.code == "CRM_PERMISSION_DENIED":
        interval = _sync_interval()
        # Outlive the short retry error so a slow old import cannot restore a
        # scope after the denial message expires. A newer CRM check can recover.
        cache.set(key + ":revokedAt", timezone.now().isoformat(), timeout=max(interval * 2, interval + 60))
        cache.delete_many([key, key + ":fresh"])


class CrmSourceError(DomainValidationError):
    def __init__(self, message="CRM 项目暂时无法读取，请稍后重试", *, status=503, code="CRM_SOURCE_UNAVAILABLE"):
        super().__init__(message, status=status, code=code)


def _request_payload(request, path):
    config = settings.CRM_PROJECT_SOURCE
    headers = {"Accept": "application/json"}
    cookie_name = getattr(settings, "AUTH_COOKIE_NAME", "mj_auth_token")
    token = request.COOKIES.get(cookie_name)
    if token:
        headers["Cookie"] = f"{cookie_name}={token}"
    authorization = request.META.get("HTTP_AUTHORIZATION")
    if authorization:
        headers["Authorization"] = authorization
    url = config["BASE_URL"].rstrip("/") + "/" + path
    started = monotonic()
    # Only GET transport failures are retried. Permission denials, malformed
    # JSON must still fail closed immediately.
    for attempt in range(3):
        _renew_sync_lease(request)
        try:
            with urlopen(Request(url, headers=headers), timeout=config["TIMEOUT_SECONDS"]) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as exc:
            if exc.code == 401:
                raise CrmSourceError("登录状态已失效，请重新登录", status=401, code="CRM_SESSION_EXPIRED") from exc
            if exc.code == 403:
                denied = CrmSourceError(
                    "当前账号无权读取 CRM 项目，请在 CRM 分配商机只读权限或对应项目访问权限",
                    status=403, code="CRM_PERMISSION_DENIED",
                )
                # A concurrently fetched page must revoke the old scope even
                # if another page's transport error is observed first.
                _remember_error(request, denied)
                raise denied from exc
            if exc.code == 404:
                raise CrmSourceError("CRM 项目不存在或无权访问", status=404, code="CRM_PROJECT_NOT_FOUND") from exc
            if exc.code not in {429, 502, 503, 504} or attempt == 2:
                logger.warning("CRM source request failed endpoint=%s http=%s elapsed=%.2fs",
                               path.split("?", 1)[0], exc.code, monotonic() - started)
                raise CrmSourceError() from exc
        except (URLError, socket.timeout, TimeoutError, OSError) as exc:
            if attempt == 2:
                logger.warning("CRM source request failed endpoint=%s error=%s elapsed=%.2fs",
                               path.split("?", 1)[0], type(exc).__name__, monotonic() - started)
                raise CrmSourceError() from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise CrmSourceError("CRM 返回的项目数据无效") from exc
        sleep((0.25, 0.75)[attempt])
    if not isinstance(payload, dict) or payload.get("ok") is False:
        raise CrmSourceError("CRM 返回的项目数据无效")
    return payload


def crm_opportunities(request):
    """Use the same permission-aware cached complete CRM endpoint as Mall."""
    if hasattr(request, "_after_sales_crm_rows"):
        return request._after_sales_crm_rows
    started = monotonic()
    payload = _request_payload(request, "opportunities")
    batch = payload.get("items")
    # This endpoint is unpaginated. Never grant access/import from a partial
    # result if an upstream version accidentally starts truncating it.
    if (not isinstance(batch, list)
            or any(key in payload for key in ("page", "pageSize", "totalPages"))
            or payload.get("hasNext")
            or ("total" in payload and (type(payload["total"]) is not int or payload["total"] != len(batch)))):
        raise CrmSourceError("CRM 项目列表不完整，请重试")
    rows = []
    seen = set()
    for row in batch:
        source_id = text(row.get("id")) if isinstance(row, dict) else ""
        if not source_id or len(source_id) > 64:
            raise CrmSourceError("CRM 项目编号无效")
        if source_id in seen:
            raise CrmSourceError("CRM 项目列表存在重复，请重试")
        seen.add(source_id)
        if not row.get("deleted"):
            rows.append(_source_row(row))
    request._after_sales_crm_rows = rows
    logger.info("CRM presales snapshot fetched rows=%d cache_hit=%s elapsed=%.2fs",
                len(rows), bool(payload.get("cacheHit")), monotonic() - started)
    return request._after_sales_crm_rows


def crm_visible_ids(request):
    if hasattr(request, "_after_sales_crm_ids"):
        return request._after_sales_crm_ids
    snapshot = _snapshot(request)
    if snapshot is not None:
        ids = snapshot["ids"]
    else:
        ids = [text(row["id"]) for row in crm_opportunities(request)]
        _remember_scope(request, ids)
    request._after_sales_crm_ids = ids
    return ids


def scope_crm_queryset(request, queryset, prefix=""):
    field = prefix + "source_crm_id"
    local = Q(**{field: ""}) | Q(**{field + "__isnull": True})
    if hasattr(request, "_after_sales_crm_ids") or queryset.exclude(local).exists():
        # Apply the admission rule before pagination and dashboard aggregation,
        # including legacy imports. Keep CRM authorization separate, and leave
        # independent local projects and other service types unchanged.
        admitted = ~Q(**{prefix + "service_type": ServiceProject.TYPE_PRESALES}) | Q(**{
            prefix + "crm_snapshot__stage__in": CRM_PRESALES_STAGES,
        })
        queryset = queryset.filter(local | (Q(**{field + "__in": crm_visible_ids(request)}) & admitted))
    return queryset


def assert_crm_project_access(request, project, *, write=False):
    """A service admin never bypasses CRM's effective-user object permission."""
    if not project.source_crm_id:
        return
    details = getattr(request, "_after_sales_crm_details", None)
    if details is None:
        details = request._after_sales_crm_details = {}
    source_id = project.source_crm_id
    if source_id not in details:
        try:
            payload = _request_payload(request, "opportunities/" + quote(source_id, safe=""))
        except CrmSourceError as exc:
            if exc.code == "CRM_PERMISSION_DENIED":
                _remember_error(request, exc)
            raise
        item = payload.get("item")
        if not isinstance(item, dict) or text(item.get("id")) != source_id:
            raise CrmSourceError("CRM 返回的项目详情无效")
        details[source_id] = item
    if details[source_id].get("deleted"):
        raise CrmSourceError("CRM 项目已删除，售前记录已保留", status=409 if write else 404, code="CRM_PROJECT_DELETED")


def refresh_crm_project(request, project):
    if project.source_crm_id:
        assert_crm_project_access(request, project)
        return _sync_row(request, request._after_sales_crm_details[project.source_crm_id])
    return project


def _source_fields(row):
    overview = text(row.get("overview"))
    need = text(row.get("purchaseNeed"))
    info = "\n".join(value for value in [overview, need if need != overview else ""] if value)
    return {
        "name": text(row.get("name"))[:255] or "未命名 CRM 项目",
        "customer": text(row.get("customerName"))[:255] or "未填写客户",
        "owner_user_id": text(row.get("ownerUserId"))[:64],
        "owner_name": (text(row.get("owner")) or text(row.get("ownerUserId")))[:128],
        "province": text(row.get("customerProvince"))[:64],
        "summary": info,
    }


def crm_project_info(project):
    return {"customer": project.customer, "name": project.name, "owner": project.owner_name, "info": project.summary}


def protect_crm_project_fields(project, fields):
    """Protect source basics while allowing local reasons, attachments and workflow data."""
    if not project.source_crm_id:
        return
    for key in _source_fields(project.crm_snapshot):
        if key in fields and fields[key] != getattr(project, key):
            raise DomainValidationError("CRM 来源项目的基础资料请在 CRM 中修改", status=409, code="CRM_FIELDS_READ_ONLY")
    data = fields.get("business_data")
    if data is not None:
        data = dict(data)
        data.pop("managerContact", None)
        data.pop("manager_contact", None)
        info = dict(data.get("projectInfo") or {})
        info.update(crm_project_info(project))
        data["projectInfo"] = info
        fields["business_data"] = data


@transaction.atomic
def _sync_row(request, row):
    row = _source_row(row)
    source_id = text(row["id"])
    fields = _source_fields(row)
    project = ServiceProject.objects.select_for_update().filter(
        service_type=ServiceProject.TYPE_PRESALES, source_crm_id=source_id,
    ).first()
    if project is None:
        if row.get("stage") not in CRM_PRESALES_STAGES:
            return None
        try:
            # A savepoint lets another request win the unique-source race safely.
            with transaction.atomic():
                return create_project(request, {
                    **fields,
                    "code": generated_code("PS"),
                    "service_type": ServiceProject.TYPE_PRESALES,
                    "status": ServiceProject.STATUS_IN_PROGRESS,
                    "source_crm_id": source_id,
                    "crm_snapshot": row,
                    "crm_synced_at": timezone.now(),
                    "business_data": {"projectInfo": {
                        "customer": fields["customer"], "name": fields["name"],
                        "owner": fields["owner_name"], "info": fields["summary"], "reason": "",
                    }},
                })
        except IntegrityError:
            project = ServiceProject.objects.select_for_update().get(
                service_type=ServiceProject.TYPE_PRESALES, source_crm_id=source_id,
            )
    # Never restore, activate, complete, or reset an existing service workflow here.
    source_changed = any(getattr(project, key) != value for key, value in fields.items())
    for key, value in fields.items():
        setattr(project, key, value)
    data = dict(project.business_data or {})
    data["projectInfo"] = {**(data.get("projectInfo") or {}), **crm_project_info(project)}
    data.pop("managerContact", None)
    data.pop("manager_contact", None)
    if project.crm_snapshot == row and project.business_data == data and not source_changed:
        return project
    project.business_data = data
    project.crm_snapshot = row
    project.crm_synced_at = timezone.now()
    # Synchronization is not a local service edit; preserve audit and sort timestamps.
    project.save(update_fields=[*fields, "business_data", "crm_snapshot", "crm_synced_at"])
    return project


def _sync_rows(request, rows):
    """Read existing basics once; lock only changed rows in bounded batches."""
    rows_by_id = {text(row["id"]): _source_row(row) for row in rows}
    existing = {item.source_crm_id: item for item in ServiceProject.objects.filter(
        service_type=ServiceProject.TYPE_PRESALES, source_crm_id__in=rows_by_id,
    ).only("id", "source_crm_id", "crm_snapshot", *_source_fields({}).keys())}
    changed_ids = [source_id for source_id, row in rows_by_id.items()
                   if source_id in existing and (
                       existing[source_id].crm_snapshot != row or any(
                           getattr(existing[source_id], key) != value
                           for key, value in _source_fields(row).items()
                       )
                   )]
    for start in range(0, len(changed_ids), 100):
        _renew_sync_lease(request)
        with transaction.atomic():
            updates = list(ServiceProject.objects.select_for_update().filter(
                pk__in=[existing[source_id].pk for source_id in changed_ids[start:start + 100]],
            ))
            for item in updates:
                row = rows_by_id[item.source_crm_id]
                for key, value in _source_fields(row).items():
                    setattr(item, key, value)
                data = dict(item.business_data or {})
                data["projectInfo"] = {**(data.get("projectInfo") or {}), **crm_project_info(item)}
                data.pop("managerContact", None)
                data.pop("manager_contact", None)
                item.business_data = data
                item.crm_snapshot = row
                item.crm_synced_at = timezone.now()
            ServiceProject.objects.bulk_update(updates, [
                *_source_fields({}).keys(), "business_data", "crm_snapshot", "crm_synced_at",
            ], batch_size=100)
    for source_id in rows_by_id:
        if source_id in existing or rows_by_id[source_id].get("stage") not in CRM_PRESALES_STAGES:
            continue
        # Reuse the established workflow initializer and unique-source race
        # handling. This runs outside the HTTP request in production.
        _renew_sync_lease(request)
        _sync_row(request, rows_by_id[source_id])
    return list(rows_by_id)


def _background_request(request):
    values = {key: value for key, value in vars(request).items() if key.startswith("auth_")}
    return SimpleNamespace(**values, COOKIES=dict(request.COOKIES), META={
        "HTTP_AUTHORIZATION": request.META.get("HTTP_AUTHORIZATION", ""),
    })


def _renew_sync_lease(request):
    token = getattr(request, "_after_sales_crm_lock_token", "")
    if token:
        lock_key = _cache_key(request) + ":lock"
        if cache.get(lock_key) != token:
            raise CrmSourceError("CRM 项目同步已重试，请稍候", code="CRM_SYNC_REPLACED")
        cache.touch(lock_key, timeout=SYNC_LEASE_SECONDS)


def _start_background_sync(request):
    key = _cache_key(request)
    lock_key = key + ":lock"
    lock_token = uuid.uuid4().hex
    if not cache.add(lock_key, lock_token, timeout=SYNC_LEASE_SECONDS):
        return
    copied = _background_request(request)
    copied._after_sales_crm_lock_token = lock_token

    def run():
        close_old_connections()
        try:
            sync_crm_presales(copied, force=True)
        except CrmSourceError as exc:
            if cache.get(lock_key) == lock_token:
                _remember_error(copied, exc)
        except Exception:
            logger.exception("CRM presales background sync failed")
            if cache.get(lock_key) == lock_token:
                _remember_error(copied, CrmSourceError("CRM 项目同步失败，请稍后重试"))
        finally:
            connection.close()
            if cache.get(lock_key) == lock_token:
                cache.delete(lock_key)

    try:
        threading.Thread(target=run, name="after-sales-crm-sync", daemon=True).start()
    except Exception:
        cache.delete(lock_key)
        raise


def _in_memory_database():
    return connection.vendor == "sqlite" and (
        connection.settings_dict["NAME"] == ":memory:"
        or "mode=memory" in str(connection.settings_dict["NAME"])
    )


def sync_crm_presales(request, *, background=False, force=False):
    key = _cache_key(request)
    if force:
        cache.delete(key + ":error")
    snapshot = _snapshot(request)
    if background:
        # SQLite's in-memory test database cannot be shared with a new thread.
        if _in_memory_database():
            return sync_crm_presales(request, force=force)
        if force or not cache.get(key + ":fresh"):
            if not cache.get(key + ":error"):
                _start_background_sync(request)
        request._after_sales_crm_ids = snapshot["ids"] if snapshot else []
        # Status must describe the scope used by this response, even if the
        # background worker publishes a new snapshot before serialization.
        request._after_sales_crm_scope_ready = bool(snapshot and snapshot.get("verifiedAt"))
        request._after_sales_crm_scope_snapshot = snapshot
        return request._after_sales_crm_ids
    if snapshot is not None and cache.get(key + ":fresh") and not force:
        request._after_sales_crm_ids = snapshot["ids"]
        return snapshot["ids"]
    try:
        rows = crm_opportunities(request)
        verified_at = timezone.now()
        _renew_sync_lease(request)
        _remember_scope(request, [text(row["id"]) for row in rows], verified_at=verified_at)
        # Serialize only the local import, not all network reads. A slow CRM
        # fetch for one user must not starve another user's visibility refresh.
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(7193048212)")
            _renew_sync_lease(request)
            ids = _sync_rows(request, rows)
    except CrmSourceError as exc:
        if not getattr(request, "_after_sales_crm_lock_token", "") or cache.get(key + ":lock") == request._after_sales_crm_lock_token:
            _remember_error(request, exc)
        raise

    def finish():
        _renew_sync_lease(request)
        _remember_scope(request, ids, synced=True, verified_at=verified_at)

    transaction.on_commit(finish)
    request._after_sales_crm_ids = ids
    request._after_sales_crm_scope_ready = True
    return ids


def crm_sync_status(request):
    key = _cache_key(request)
    failure = cache.get(key + ":error")
    if failure and failure["code"] == "CRM_PERMISSION_DENIED":
        raise CrmSourceError(failure["message"], status=403, code=failure["code"])
    snapshot = request._after_sales_crm_scope_snapshot if hasattr(request, "_after_sales_crm_scope_snapshot") else cache.get(key)
    return {
        "crmSyncing": bool(cache.get(key + ":lock")),
        "crmSyncedAt": snapshot["syncedAt"] if snapshot else "",
        "crmSyncError": failure["message"] if failure else "",
        "crmScopeReady": getattr(request, "_after_sales_crm_scope_ready", bool(snapshot and snapshot.get("verifiedAt"))),
        "crmScopeExpiresAt": snapshot.get("expiresAt", "") if snapshot else "",
    }
