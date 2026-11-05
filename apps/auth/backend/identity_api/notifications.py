"""Targeted in-platform notifications, readership snapshots, and permissions."""
import html
import hashlib
import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from html.parser import HTMLParser
from urllib.parse import quote

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import (
    DepartmentEmployee,
    NotificationAttachment,
    NotificationAcknowledgement,
    NotificationCategory,
    NotificationPermissionState,
    NotificationRecipient,
    PlatformNotification,
)
from .org.organization_access import (
    OrganizationAccessError,
    _OrganizationDirectory,
    _canonical_permission_rules,
    _error_response,
    _expected_revision,
    _parse_json_body,
    _permission_allows_user,
    can_manage_organization,
    lock_organization_state,
)
from .org.revision import get_organization_revision
from .robot_rich_text import MAX_IMAGE_BYTES, MAX_IMAGES, decode_image, parse_send_body

BASE = "/api/org/notices"
ROLE_ADMIN = "admin"
ROLE_PUBLISHER = "publisher"
ROLE_USER = "user"
VALID_ASSIGNMENT_ROLES = {ROLE_ADMIN, ROLE_PUBLISHER}
MAX_TITLE_LENGTH = 200
MAX_CATEGORY_LENGTH = 80
MAX_ATTACHMENT_COUNT = 10
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENT_TOTAL_BYTES = 30 * 1024 * 1024
MAX_HTML_LENGTH = 12 * 1024 * 1024
PREVIEW_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
}
ALLOWED_TAGS = {
    "p", "div", "br", "b", "strong", "i", "em", "u", "s", "span",
    "ul", "ol", "li", "h2", "h3", "blockquote", "pre", "code", "a", "img",
}
BLOCKED_TAGS = {"script", "style", "iframe", "object", "embed", "svg", "math", "template"}
VOID_TAGS = {"br", "img"}


class _SafeNotificationHtml(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.open_tags = []
        self.blocked_depth = 0
        self.nodes = 0
        self.image_count = 0
        self.image_bytes = 0

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        if self.nodes > 5000 or len(self.open_tags) > 40:
            raise OrganizationAccessError("富文本结构过于复杂，请简化内容")
        if tag in BLOCKED_TAGS:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in ALLOWED_TAGS:
            return
        if tag == "img":
            attributes = dict(attrs)
            source = attributes.get("src") or ""
            if self.image_count >= MAX_IMAGES:
                raise OrganizationAccessError(f"每条通知最多添加 {MAX_IMAGES} 张正文图片")
            data, _mime, _extension = decode_image(source)
            self.image_count += 1
            self.image_bytes += len(data)
            if self.image_bytes > MAX_IMAGE_BYTES:
                raise OrganizationAccessError("通知正文图片总大小不能超过 8 MB")
            alt = html.escape(str(attributes.get("alt") or "")[:200], quote=True)
            self.parts.append(f'<img src="{html.escape(source, quote=True)}" alt="{alt}">')
            return
        if tag == "a":
            attributes = dict(attrs)
            href = _safe_link(attributes.get("href", ""))
            if href:
                self.parts.append(f'<a href="{html.escape(href, quote=True)}" rel="noopener noreferrer">')
                self.open_tags.append(tag)
                return
        self.parts.append(f"<{tag}>")
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in BLOCKED_TAGS:
            self.blocked_depth = max(0, self.blocked_depth - 1)
            return
        if self.blocked_depth or tag not in self.open_tags:
            return
        while self.open_tags:
            current = self.open_tags.pop()
            self.parts.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data):
        if not self.blocked_depth:
            self.parts.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        if not self.blocked_depth:
            self.parts.append(html.escape(html.unescape(f"&{name};"), quote=False))

    def handle_charref(self, name):
        if not self.blocked_depth:
            self.parts.append(html.escape(html.unescape(f"&#{name};"), quote=False))

    def close(self):
        super().close()
        while self.open_tags:
            self.parts.append(f"</{self.open_tags.pop()}>")


def _safe_link(value):
    value = str(value or "").strip()
    if any(ord(character) < 32 for character in value):
        return ""
    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    return value if parsed.scheme.lower() in {"http", "https", "mailto", "tel"} else ""


def sanitize_notification_html(value):
    source = str(value or "")
    if len(source) > MAX_HTML_LENGTH:
        raise OrganizationAccessError("通知正文过长，请精简后重试")
    parser = _SafeNotificationHtml()
    try:
        parser.feed(source)
        parser.close()
    except OrganizationAccessError:
        raise
    except Exception as exc:
        raise OrganizationAccessError("富文本格式无效，请重新编辑正文") from exc
    result = "".join(parser.parts).strip()
    if len(re.sub(r"<img\b[^>]*>", "", result)) > 300_000:
        raise OrganizationAccessError("通知正文过长，请精简后重试")
    text = re.sub(r"<[^>]*>", "", result).replace("\xa0", " ").strip()
    if not text and not parser.image_count:
        raise OrganizationAccessError("请填写通知正文")
    return result


def _user_id(request):
    return str(getattr(request, "auth_user_id", "") or "").strip()


def _state():
    state, _ = NotificationPermissionState.objects.get_or_create(state_id=1)
    return state


def _role_ids(state, role):
    roles = state.roles if isinstance(state.roles, dict) else {}
    rules = roles.get(role, [])
    return rules if isinstance(rules, list) else []


def notification_role(request, state=None):
    state = state or _state()
    user_id = _user_id(request)
    if can_manage_organization(request) or _permission_allows_user(_role_ids(state, ROLE_ADMIN), user_id):
        return ROLE_ADMIN
    if _permission_allows_user(_role_ids(state, ROLE_PUBLISHER), user_id):
        return ROLE_PUBLISHER
    return ROLE_USER


def _can_manage(request, state=None):
    return notification_role(request, state) == ROLE_ADMIN


def _can_publish(request, state=None):
    return notification_role(request, state) in {ROLE_ADMIN, ROLE_PUBLISHER}


def _may_manage_notice(request, notice, state=None):
    role = notification_role(request, state)
    return role == ROLE_ADMIN or (role == ROLE_PUBLISHER and notice.created_by == _user_id(request))


def _parse_expiration(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise OrganizationAccessError("通知到期日期格式无效")
    value = value.strip()
    date_only = re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None
    try:
        if date_only:
            day = parse_date(value)
            parsed = datetime.combine(day + timedelta(days=1), time.min, tzinfo=ZoneInfo("Asia/Shanghai")) if day else None
        else:
            # Preserve the timestamp contract for existing clients and records.
            parsed = parse_datetime(value)
    except (ValueError, OverflowError) as exc:
        raise OrganizationAccessError("通知到期日期格式无效") from exc
    if parsed is None:
        raise OrganizationAccessError("通知到期日期格式无效")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    if parsed <= timezone.now():
        raise OrganizationAccessError("到期日期不能早于今天" if date_only else "通知失效时间必须晚于当前时间")
    return parsed


def _normalize_recipient_selection(value):
    if not isinstance(value, dict):
        raise OrganizationAccessError("请选择通知对象")
    departments = value.get("departments", [])
    people = value.get("people", [])
    if not isinstance(departments, list) or not isinstance(people, list):
        raise OrganizationAccessError("通知对象格式无效")
    normalized_departments = []
    seen_departments = set()
    for item in departments:
        if isinstance(item, (str, int)):
            raw_id, include_sub = item, False
        elif isinstance(item, dict):
            raw_id = item.get("deptId", item.get("id"))
            include_sub = item.get("includeSubDepartments", False) is True
        else:
            raise OrganizationAccessError("部门通知对象格式无效")
        try:
            dept_id = int(str(raw_id).strip())
        except (TypeError, ValueError, OverflowError) as exc:
            raise OrganizationAccessError("部门ID无效") from exc
        if dept_id <= 0:
            raise OrganizationAccessError("部门ID无效")
        if dept_id in seen_departments:
            continue
        seen_departments.add(dept_id)
        normalized_departments.append({"deptId": dept_id, "includeSubDepartments": include_sub})
    normalized_people = []
    seen_people = set()
    for item in people:
        raw_id = item.get("userId", item.get("id")) if isinstance(item, dict) else item
        user_id = str(raw_id or "").strip()
        if not user_id or len(user_id) > 64 or any(ord(character) < 32 for character in user_id):
            raise OrganizationAccessError("人员通知对象格式无效")
        if user_id not in seen_people:
            seen_people.add(user_id)
            normalized_people.append(user_id)
    if len(normalized_departments) > 200 or len(normalized_people) > 500:
        raise OrganizationAccessError("通知对象数量超出限制")
    return {"departments": normalized_departments, "people": normalized_people}


def _resolve_recipients(selection):
    directory = _OrganizationDirectory()
    membership_sources = defaultdict(set)
    for selected in selection.get("departments", []):
        dept_id = int(selected["deptId"])
        department = directory.departments.get(dept_id)
        if department is None:
            raise OrganizationAccessError(f"部门不存在或已停用：{dept_id}", code="INVALID_NOTIFICATION_AUDIENCE")
        user_ids = directory.department_member_ids(
            dept_id,
            include_sub_departments=bool(selected.get("includeSubDepartments")),
        )
        for user_id in user_ids:
            membership_sources[user_id].add(department.name)
    for user_id in selection.get("people", []):
        if user_id not in directory.employees:
            raise OrganizationAccessError(f"人员不存在、已离职或账号已停用：{user_id}", code="INVALID_NOTIFICATION_AUDIENCE")
        membership_sources[user_id].add("单独选择")
    if not membership_sources:
        raise OrganizationAccessError("请至少选择一个通知部门或人员")
    department_names_by_user = defaultdict(set)
    for department_id, user_ids in directory.members_by_department.items():
        name = directory.departments[department_id].name
        for user_id in user_ids:
            department_names_by_user[user_id].add(name)
    return [
        {
            "user_id": user_id,
            "name": directory.employees[user_id].name,
            "department_names": sorted(department_names_by_user.get(user_id, set())),
        }
        for user_id in sorted(membership_sources, key=lambda item: (directory.employees[item].name, item))
    ]


CONFIRMATION_STATEMENTS = {
    PlatformNotification.LEVEL_ORDINARY: "",
    PlatformNotification.LEVEL_CONFIRM: "本人已阅读并知晓本次通知的全部内容",
    PlatformNotification.LEVEL_ACCEPT: "本人已阅读并知晓本次通知的全部内容，并同意按通知要求执行相关规定",
}


def _parse_level(value):
    if not isinstance(value, str) or value not in CONFIRMATION_STATEMENTS:
        raise OrganizationAccessError("请选择有效的通知等级")
    return value


def _confirmation_version(notice):
    parts = [str(notice.publication_revision), notice.updated_at.isoformat(), notice.level]
    if CONFIRMATION_STATEMENTS[notice.level]:
        parts.append(CONFIRMATION_STATEMENTS[notice.level])
    parts.extend(sorted(str(item.id) for item in notice.attachments.all()))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _acknowledgement_data(record):
    if record is None:
        return None
    return {
        "userId": record.user_id, "name": record.name,
        "actorUserId": record.actor_user_id, "actorName": record.actor_name,
        "level": record.level, "statement": record.statement,
        "enteredStatement": record.entered_statement,
        "confirmedAt": record.confirmed_at.isoformat(),
        "publicationRevision": record.publication_revision,
        "contentSnapshot": record.content_snapshot,
    }


def _display_status(notice, now=None):
    if notice.status == PlatformNotification.STATUS_PUBLISHED and notice.expires_at and notice.expires_at <= (now or timezone.now()):
        return "expired"
    return notice.status


def _attachment_data(attachment):
    download_url = f"{BASE}/attachments/{attachment.id}/download"
    return {
        "id": str(attachment.id),
        "name": attachment.file_name,
        "size": attachment.byte_size,
        "url": download_url,
        "previewUrl": f"{download_url}?preview=1" if os.path.splitext(attachment.file_name)[1].lower() in PREVIEW_CONTENT_TYPES else "",
        "createdAt": attachment.created_at.isoformat(),
    }


def _notice_data(notice, *, include_content=False, include_stats=False, read_at=None):
    data = {
        "id": str(notice.id),
        "title": notice.title,
        "level": notice.level,
        "confirmationStatement": CONFIRMATION_STATEMENTS[notice.level],
        "confirmationVersion": _confirmation_version(notice),
        "category": {"id": notice.category_id, "name": notice.category.name},
        "status": _display_status(notice),
        "expiresAt": notice.expires_at.isoformat() if notice.expires_at else "",
        "expiresOn": timezone.localtime(notice.expires_at - timedelta(microseconds=1), ZoneInfo("Asia/Shanghai")).date().isoformat() if notice.expires_at else "",
        "createdAt": notice.created_at.isoformat(),
        "publishedAt": notice.published_at.isoformat() if notice.published_at else "",
        "updatedAt": notice.updated_at.isoformat(),
        "createdBy": {"userId": notice.created_by, "name": notice.created_by_name},
        "readAt": read_at.isoformat() if read_at else "",
        "attachments": [_attachment_data(item) for item in notice.attachments.all()],
    }
    if include_content:
        data["contentHtml"] = notice.content_html
    if include_stats:
        data["recipientCount"] = getattr(notice, "recipient_count", None)
        data["unreadCount"] = getattr(notice, "unread_count", None)
        if data["recipientCount"] is None:
            data["recipientCount"] = notice.recipients.count()
        if data["unreadCount"] is None:
            data["unreadCount"] = notice.recipients.filter(read_at__isnull=True).count()
        data["recipientSelection"] = notice.recipient_selection or {"departments": [], "people": []}
    return data


def _page_args(request, *, default_size=20, maximum=100):
    try:
        page = max(1, int(request.GET.get("page", "1")))
        page_size = min(maximum, max(1, int(request.GET.get("pageSize", str(default_size)))))
    except (TypeError, ValueError, OverflowError) as exc:
        raise OrganizationAccessError("页码或每页数量无效") from exc
    return page, page_size


def _read_date_param(request, key):
    raw = str(request.GET.get(key, "") or "").strip()
    if not raw:
        return None
    try:
        return timezone.datetime.fromisoformat(raw).date()
    except (ValueError, TypeError):
        raise OrganizationAccessError(f"{key}日期格式无效")


@require_GET
def capabilities(request):
    state = _state()
    role = notification_role(request, state)
    return JsonResponse({
        "role": role,
        "canManage": role == ROLE_ADMIN,
        "canPublish": role in {ROLE_ADMIN, ROLE_PUBLISHER},
        "canManageCategories": role == ROLE_ADMIN,
        "canManagePermissions": role == ROLE_ADMIN,
        "defaultExpirationDays": 30,
    })


@csrf_exempt
@require_http_methods(["GET", "PUT"])
def permissions(request, role):
    if role not in VALID_ASSIGNMENT_ROLES:
        return JsonResponse({"code": "INVALID_NOTIFICATION_ROLE", "error": "通知角色无效"}, status=404)
    if not _can_manage(request):
        return JsonResponse({"code": "NOTIFICATION_PERMISSIONS_FORBIDDEN", "error": "只有通知管理员可以设置通知权限"}, status=403)
    if request.method == "GET":
        state = _state()
        return JsonResponse({
            "rules": _role_ids(state, role),
            "revision": state.revision,
            "orgRevision": get_organization_revision(),
            "canManage": True,
        })
    try:
        payload = _parse_json_body(request)
        with transaction.atomic():
            org = lock_organization_state()
            state, _ = NotificationPermissionState.objects.select_for_update().get_or_create(state_id=1)
            if not _can_manage(request, state):
                return JsonResponse({"code": "NOTIFICATION_PERMISSIONS_FORBIDDEN", "error": "管理权限已失效"}, status=403)
            _expected_revision(payload.get("revision"), current=state.revision, field_name="revision",
                               required_code="REVISION_REQUIRED", conflict_code="REVISION_CONFLICT")
            _expected_revision(payload.get("orgRevision"), current=org.revision, field_name="orgRevision",
                               required_code="ORG_REVISION_REQUIRED", conflict_code="ORG_REVISION_CONFLICT")
            roles = dict(state.roles or {})
            roles[role] = _canonical_permission_rules(
                payload.get("rules"),
                previous_rules=_role_ids(state, role),
                directory=_OrganizationDirectory(),
            )
            state.roles = roles
            state.revision += 1
            state.save(update_fields=["roles", "revision", "updated_at"])
    except OrganizationAccessError as exc:
        return _error_response(exc)
    return JsonResponse({"rules": _role_ids(state, role), "revision": state.revision,
                         "orgRevision": get_organization_revision(), "canManage": True})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def categories(request):
    state = _state()
    if request.method == "GET":
        return JsonResponse({"items": [
            {"id": item.id, "name": item.name}
            for item in NotificationCategory.objects.all()
        ]})
    if not _can_manage(request, state):
        return JsonResponse({"code": "NOTIFICATION_CATEGORIES_FORBIDDEN", "error": "只有通知管理员可以管理分类"}, status=403)
    try:
        payload = _parse_json_body(request)
        name = str(payload.get("name", "") or "").strip()
        if not name or len(name) > MAX_CATEGORY_LENGTH or any(unicodedata.category(c).startswith("C") for c in name):
            raise OrganizationAccessError("请输入有效分类名称（最多80个字符）")
        if NotificationCategory.objects.filter(name__iexact=name).exists():
            raise OrganizationAccessError("分类名称已存在", code="DUPLICATE_NOTIFICATION_CATEGORY", status=409)
        category = NotificationCategory.objects.create(name=name, created_by=_user_id(request), updated_by=_user_id(request))
    except OrganizationAccessError as exc:
        return _error_response(exc)
    return JsonResponse({"id": category.id, "name": category.name}, status=201)


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def category_detail(request, category_id):
    state = _state()
    if not _can_manage(request, state):
        return JsonResponse({"code": "NOTIFICATION_CATEGORIES_FORBIDDEN", "error": "只有通知管理员可以管理分类"}, status=403)
    category = NotificationCategory.objects.filter(pk=category_id).first()
    if category is None:
        return JsonResponse({"code": "NOTIFICATION_CATEGORY_NOT_FOUND", "error": "分类不存在"}, status=404)
    if request.method == "DELETE":
        if category.notifications.exists():
            return JsonResponse({"code": "NOTIFICATION_CATEGORY_IN_USE", "error": "分类已被通知使用，不能删除"}, status=409)
        category.delete()
        return JsonResponse({"ok": True})
    try:
        payload = _parse_json_body(request)
        name = str(payload.get("name", "") or "").strip()
        if not name or len(name) > MAX_CATEGORY_LENGTH or any(unicodedata.category(c).startswith("C") for c in name):
            raise OrganizationAccessError("请输入有效分类名称（最多80个字符）")
        if NotificationCategory.objects.filter(name__iexact=name).exclude(pk=category.pk).exists():
            raise OrganizationAccessError("分类名称已存在", code="DUPLICATE_NOTIFICATION_CATEGORY", status=409)
        category.name = name
        category.updated_by = _user_id(request)
        category.save(update_fields=["name", "updated_by", "updated_at"])
    except OrganizationAccessError as exc:
        return _error_response(exc)
    return JsonResponse({"id": category.id, "name": category.name})


def _notice_payload(payload, *, existing=None):
    if not isinstance(payload, dict):
        raise OrganizationAccessError("请求格式无效")
    title = str(payload.get("title", existing.title if existing else "") or "").strip()
    level = _parse_level(payload.get("level", existing.level if existing else PlatformNotification.LEVEL_ORDINARY))
    if existing and existing.status != PlatformNotification.STATUS_DRAFT and level != existing.level:
        raise OrganizationAccessError("修改通知等级需要保存并重新发布", status=409)
    if not title or len(title) > MAX_TITLE_LENGTH or any(unicodedata.category(c).startswith("C") for c in title):
        raise OrganizationAccessError("请输入通知标题（最多200个字符）")
    html_value = payload.get("contentHtml", existing.content_html if existing else "")
    content_html = sanitize_notification_html(html_value)
    category_id = payload.get("categoryId", existing.category_id if existing else None)
    try:
        category_id = int(category_id)
    except (TypeError, ValueError, OverflowError) as exc:
        raise OrganizationAccessError("请选择通知分类") from exc
    category = NotificationCategory.objects.filter(pk=category_id).first()
    if category is None:
        raise OrganizationAccessError("所选通知分类不存在或已删除")
    expiration_raw = payload.get("expiresAt")
    if "expiresAt" not in payload and existing is not None:
        expiration = existing.expires_at
        if expiration and expiration <= timezone.now():
            raise OrganizationAccessError("已失效通知不能直接延长有效期，请重新发布")
    else:
        expiration = _parse_expiration(expiration_raw)
    if existing and existing.status != PlatformNotification.STATUS_DRAFT:
        selection = existing.recipient_selection or {"departments": [], "people": []}
    else:
        selection = _normalize_recipient_selection(
            payload.get("recipientSelection", existing.recipient_selection if existing else {})
        )
    return {"title": title, "level": level, "content_html": content_html, "category": category,
            "expires_at": expiration, "recipient_selection": selection}


@csrf_exempt
@require_http_methods(["GET", "POST"])
def notice_list(request):
    state = _state()
    if request.method == "GET":
        if not _can_publish(request, state):
            return JsonResponse({"code": "NOTIFICATION_MANAGEMENT_FORBIDDEN", "error": "当前账号没有通知发布权限"}, status=403)
        try:
            page, page_size = _page_args(request)
            keyword = str(request.GET.get("keyword", "") or "").strip()[:200]
            category_id = str(request.GET.get("categoryId", "") or "").strip()
            date_from = _read_date_param(request, "dateFrom")
            date_to = _read_date_param(request, "dateTo")
            if date_from and date_to and date_from > date_to:
                raise OrganizationAccessError("开始日期不能晚于结束日期")
            records = PlatformNotification.objects.select_related("category").prefetch_related("attachments")
            if notification_role(request, state) != ROLE_ADMIN:
                records = records.filter(created_by=_user_id(request))
            if keyword:
                records = records.filter(title__icontains=keyword)
            if category_id:
                try:
                    records = records.filter(category_id=int(category_id))
                except (TypeError, ValueError, OverflowError) as exc:
                    raise OrganizationAccessError("通知分类筛选条件无效") from exc
            if date_from:
                records = records.filter(created_at__date__gte=date_from)
            if date_to:
                records = records.filter(created_at__date__lte=date_to)
            status_filter = str(request.GET.get("status", "") or "").strip()
            now = timezone.now()
            if status_filter == "expired":
                records = records.filter(status=PlatformNotification.STATUS_PUBLISHED, expires_at__lte=now)
            elif status_filter == "published":
                records = records.filter(status=PlatformNotification.STATUS_PUBLISHED).filter(
                    Q(expires_at__isnull=True) | Q(expires_at__gt=now)
                )
            elif status_filter in {"draft", "withdrawn"}:
                records = records.filter(status=status_filter)
            elif status_filter not in {"", "all"}:
                raise OrganizationAccessError("通知状态筛选条件无效")
            recipient_user_id = str(request.GET.get("recipientUserId", "") or "").strip()
            unread_user_id = str(request.GET.get("unreadUserId", "") or "").strip()
            # Separate subqueries preserve the full recipient counts and allow
            # the recipient and unread filters to refer to different people.
            if recipient_user_id:
                records = records.filter(pk__in=NotificationRecipient.objects.filter(
                    user_id=recipient_user_id,
                ).values("notification_id"))
            if unread_user_id:
                records = records.filter(pk__in=NotificationRecipient.objects.filter(
                    user_id=unread_user_id, read_at__isnull=True,
                ).values("notification_id"))
            records = records.annotate(
                recipient_count=Count("recipients", distinct=True),
                unread_count=Count("recipients", filter=Q(recipients__read_at__isnull=True), distinct=True),
            )
            total = records.count()
            start = (page - 1) * page_size
            items = list(records.order_by("-created_at", "-id")[start:start + page_size])
            return JsonResponse({"items": [_notice_data(item, include_stats=True) for item in items],
                                 "page": page, "pageSize": page_size, "total": total})
        except OrganizationAccessError as exc:
            return _error_response(exc)
    if not _can_publish(request, state):
        return JsonResponse({"code": "NOTIFICATION_MANAGEMENT_FORBIDDEN", "error": "当前账号没有通知发布权限"}, status=403)
    try:
        payload = parse_send_body(request, max_bytes=MAX_HTML_LENGTH + 100_000)
        fields = _notice_payload(payload)
        notice = PlatformNotification.objects.create(
            **fields,
            created_by=_user_id(request),
            created_by_name=str(getattr(getattr(request, "auth_employee", None), "name", "") or ""),
            actor_user_id=str(getattr(request, "auth_actor_user_id", "") or _user_id(request)),
            actor_name=str(getattr(getattr(request, "auth_actor_employee", None), "name", "") or ""),
        )
    except OrganizationAccessError as exc:
        return _error_response(exc)
    return JsonResponse(_notice_data(notice, include_content=True, include_stats=True), status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
@transaction.atomic
def notice_detail(request, notice_id):
    records = PlatformNotification.objects.select_related("category").prefetch_related("attachments")
    if request.method != "GET":
        records = records.select_for_update(of=("self",))
    notice = records.filter(pk=notice_id).first()
    if notice is None:
        return JsonResponse({"code": "NOTIFICATION_NOT_FOUND", "error": "通知不存在"}, status=404)
    state = _state()
    role = notification_role(request, state)
    if request.method == "GET":
        recipient = NotificationRecipient.objects.filter(notification=notice, user_id=_user_id(request)).first()
        if not _may_manage_notice(request, notice, state) and recipient is None:
            return JsonResponse({"code": "NOTIFICATION_FORBIDDEN", "error": "当前账号不能查看此通知"}, status=403)
        data = _notice_data(
            notice,
            include_content=True,
            include_stats=_may_manage_notice(request, notice, state),
            read_at=recipient.read_at if recipient else None,
        )
        if recipient:
            data["confirmation"] = _acknowledgement_data(notice.acknowledgements.filter(
                user_id=recipient.user_id, publication_revision=notice.publication_revision,
            ).first())
        return JsonResponse(data)
    if not _may_manage_notice(request, notice, state):
        return JsonResponse({"code": "NOTIFICATION_MANAGEMENT_FORBIDDEN", "error": "当前账号不能管理此通知"}, status=403)
    if request.method == "DELETE":
        for attachment in notice.attachments.all():
            attachment.file.delete(save=False)
        notice.delete()
        return JsonResponse({"ok": True})
    try:
        payload = parse_send_body(request, max_bytes=MAX_HTML_LENGTH + 100_000)
        fields = _notice_payload(payload, existing=notice)
        for key, value in fields.items():
            setattr(notice, key, value)
        notice.save(update_fields=["title", "level", "content_html", "category", "expires_at", "recipient_selection", "updated_at"])
    except OrganizationAccessError as exc:
        return _error_response(exc)
    return JsonResponse(_notice_data(notice, include_content=True, include_stats=True))


@csrf_exempt
@require_POST
def publish(request, notice_id):
    state = _state()
    notice = PlatformNotification.objects.select_related("category").filter(pk=notice_id).first()
    if notice is None:
        return JsonResponse({"code": "NOTIFICATION_NOT_FOUND", "error": "通知不存在"}, status=404)
    if not _may_manage_notice(request, notice, state):
        return JsonResponse({"code": "NOTIFICATION_MANAGEMENT_FORBIDDEN", "error": "当前账号不能发布此通知"}, status=403)
    try:
        payload = _parse_json_body(request)
        reset_read = payload.get("resetRead", False)
        if not isinstance(reset_read, bool):
            raise OrganizationAccessError("resetRead 必须为布尔值")
        with transaction.atomic():
            locked = PlatformNotification.objects.select_for_update().select_related("category").get(pk=notice_id)
            level = _parse_level(payload.get("level", locked.level))
            if level != locked.level and locked.status != PlatformNotification.STATUS_DRAFT and not reset_read:
                raise OrganizationAccessError("修改通知等级需要重新发布并清空完成记录", status=409)
            if locked.status == PlatformNotification.STATUS_PUBLISHED and not reset_read:
                return JsonResponse(_notice_data(locked, include_content=True, include_stats=True))
            if locked.expires_at and locked.expires_at <= timezone.now():
                raise OrganizationAccessError("通知失效时间已到，请先修改失效时间")
            # Resolve the audience only once. Explicit republication resets reads
            # on that same snapshot; ordinary publication preserves existing reads.
            if locked.status == PlatformNotification.STATUS_DRAFT:
                recipients = _resolve_recipients(locked.recipient_selection or {})
                NotificationRecipient.objects.bulk_create([
                    NotificationRecipient(
                        notification=locked,
                        user_id=item["user_id"],
                        name=item["name"],
                        department_names=item["department_names"],
                    )
                    for item in recipients
                ], batch_size=500)
            elif not locked.recipients.exists():
                raise OrganizationAccessError("通知接收名单不存在，请重新创建通知", status=409)
            if reset_read:
                locked.recipients.filter(read_at__isnull=False).update(read_at=None)
                locked.publication_revision += 1
            locked.level = level
            locked.status = PlatformNotification.STATUS_PUBLISHED
            locked.published_at = timezone.now()
            locked.withdrawn_at = None
            locked.save(update_fields=["status", "level", "publication_revision", "published_at", "withdrawn_at", "updated_at"])
            notice = locked
    except PlatformNotification.DoesNotExist:
        return JsonResponse({"code": "NOTIFICATION_NOT_FOUND", "error": "通知不存在"}, status=404)
    except OrganizationAccessError as exc:
        return _error_response(exc)
    return JsonResponse(_notice_data(notice, include_content=True, include_stats=True))


@csrf_exempt
@require_POST
@transaction.atomic
def withdraw(request, notice_id):
    state = _state()
    notice = PlatformNotification.objects.select_for_update().filter(pk=notice_id).first()
    if notice is None:
        return JsonResponse({"code": "NOTIFICATION_NOT_FOUND", "error": "通知不存在"}, status=404)
    if not _may_manage_notice(request, notice, state):
        return JsonResponse({"code": "NOTIFICATION_MANAGEMENT_FORBIDDEN", "error": "当前账号不能撤回此通知"}, status=403)
    if notice.status != PlatformNotification.STATUS_PUBLISHED:
        return JsonResponse({"code": "NOTIFICATION_NOT_PUBLISHED", "error": "只有已发布通知可以撤回"}, status=409)
    notice.status = PlatformNotification.STATUS_WITHDRAWN
    notice.withdrawn_at = timezone.now()
    notice.save(update_fields=["status", "withdrawn_at", "updated_at"])
    return JsonResponse(_notice_data(notice, include_stats=True))


@require_GET
def recipients(request, notice_id):
    notice = PlatformNotification.objects.filter(pk=notice_id).first()
    state = _state()
    if notice is None:
        return JsonResponse({"code": "NOTIFICATION_NOT_FOUND", "error": "通知不存在"}, status=404)
    if not _may_manage_notice(request, notice, state):
        return JsonResponse({"code": "NOTIFICATION_MANAGEMENT_FORBIDDEN", "error": "当前账号不能查看阅读名单"}, status=403)
    try:
        page, page_size = _page_args(request)
    except OrganizationAccessError as exc:
        return _error_response(exc)
    status_filter = str(request.GET.get("status", "unread") or "unread").strip()
    rows = notice.recipients.all()
    if status_filter == "unread":
        rows = rows.filter(read_at__isnull=True)
    elif status_filter == "read":
        rows = rows.filter(read_at__isnull=False)
    elif status_filter != "all":
        return JsonResponse({"code": "INVALID_NOTIFICATION_READ_STATUS", "error": "阅读状态筛选条件无效"}, status=400)
    total = rows.count()
    start = (page - 1) * page_size
    items = list(rows.order_by("name", "user_id")[start:start + page_size])
    acknowledgements = {record.user_id: record for record in notice.acknowledgements.filter(
        publication_revision=notice.publication_revision, user_id__in=[item.user_id for item in items],
    )}
    return JsonResponse({"items": [{
        "userId": item.user_id,
        "name": item.name,
        "departmentNames": item.department_names or [],
        "readAt": item.read_at.isoformat() if item.read_at else "",
        "confirmation": _acknowledgement_data(acknowledgements.get(item.user_id)),
    } for item in items], "page": page, "pageSize": page_size, "total": total})


@require_GET
def unread(request):
    now = timezone.now()
    rows = NotificationRecipient.objects.filter(
        user_id=_user_id(request),
        read_at__isnull=True,
        notification__status=PlatformNotification.STATUS_PUBLISHED,
    ).filter(
        Q(notification__expires_at__isnull=True) | Q(notification__expires_at__gt=now)
    ).select_related("notification__category").prefetch_related("notification__attachments")
    total = rows.count()
    items = rows.order_by("notification__created_at", "notification_id")[:1]
    return JsonResponse({"items": [
        _notice_data(item.notification, include_content=True)
        for item in items
    ], "total": total})


@csrf_exempt
@require_POST
@transaction.atomic
def mark_read(request, notice_id):
    notice = PlatformNotification.objects.select_for_update().filter(pk=notice_id).first()
    recipient = NotificationRecipient.objects.filter(
        notification_id=notice_id,
        user_id=_user_id(request),
    ).first()
    if recipient is None:
        return JsonResponse({"code": "NOTIFICATION_FORBIDDEN", "error": "当前账号不是此通知的接收人"}, status=403)
    if _display_status(notice) != PlatformNotification.STATUS_PUBLISHED:
        return JsonResponse({"code": "NOTIFICATION_NOT_ACTIVE", "error": "通知已撤回、到期或尚未发布，请重新查看"}, status=409)
    try:
        payload = _parse_json_body(request)
        version = payload.get("confirmationVersion")
        if (notice.level != PlatformNotification.LEVEL_ORDINARY or version is not None) and version != _confirmation_version(notice):
            raise OrganizationAccessError("通知内容已更新，请重新阅读后确认", status=409, code="NOTIFICATION_CONFIRMATION_CHANGED")
        statement = CONFIRMATION_STATEMENTS[notice.level]
        entered = payload.get("statement", "")
        if not isinstance(entered, str) or (statement and entered != statement):
            raise OrganizationAccessError("确认内容需与提示声明完全一致")
    except OrganizationAccessError as exc:
        return _error_response(exc)
    if recipient.read_at is None:
        recipient.read_at = timezone.now()
        NotificationAcknowledgement.objects.create(
            notification=notice, publication_revision=notice.publication_revision,
            user_id=recipient.user_id, name=recipient.name,
            actor_user_id=str(getattr(request, "auth_actor_user_id", "") or _user_id(request)),
            actor_name=str(getattr(getattr(request, "auth_actor_employee", None), "name", "") or recipient.name),
            level=notice.level, statement=statement, entered_statement=entered if statement else "",
            confirmed_at=recipient.read_at,
            content_snapshot={"title": notice.title, "contentHtml": notice.content_html,
                              "attachments": [_attachment_data(item) for item in notice.attachments.all()]},
        )
        recipient.save(update_fields=["read_at"])
    return JsonResponse({"ok": True, "readAt": recipient.read_at.isoformat()})


@require_GET
def history(request):
    try:
        page, page_size = _page_args(request)
        keyword = str(request.GET.get("keyword", "") or "").strip()[:200]
        category_id = str(request.GET.get("categoryId", "") or "").strip()
        date_from = _read_date_param(request, "dateFrom")
        date_to = _read_date_param(request, "dateTo")
        if date_from and date_to and date_from > date_to:
            raise OrganizationAccessError("开始日期不能晚于结束日期")
        rows = NotificationRecipient.objects.filter(user_id=_user_id(request)).select_related(
            "notification__category",
        ).prefetch_related("notification__attachments")
        if keyword:
            rows = rows.filter(notification__title__icontains=keyword)
        if category_id:
            try:
                rows = rows.filter(notification__category_id=int(category_id))
            except (TypeError, ValueError, OverflowError) as exc:
                raise OrganizationAccessError("通知分类筛选条件无效") from exc
        if date_from:
            rows = rows.filter(notification__created_at__date__gte=date_from)
        if date_to:
            rows = rows.filter(notification__created_at__date__lte=date_to)
        total = rows.count()
        start = (page - 1) * page_size
        items = rows.order_by("-notification__created_at", "-notification_id")[start:start + page_size]
        return JsonResponse({"items": [
            _notice_data(item.notification, read_at=item.read_at)
            for item in items
        ], "page": page, "pageSize": page_size, "total": total})
    except OrganizationAccessError as exc:
        return _error_response(exc)


@csrf_exempt
@require_POST
@transaction.atomic
def upload_attachments(request, notice_id):
    state = _state()
    notice = PlatformNotification.objects.select_for_update().filter(pk=notice_id).first()
    if notice is None:
        return JsonResponse({"code": "NOTIFICATION_NOT_FOUND", "error": "通知不存在"}, status=404)
    if not _may_manage_notice(request, notice, state):
        return JsonResponse({"code": "NOTIFICATION_MANAGEMENT_FORBIDDEN", "error": "当前账号不能修改此通知附件"}, status=403)
    files = request.FILES.getlist("files")
    if not files:
        return JsonResponse({"code": "NOTIFICATION_ATTACHMENT_REQUIRED", "error": "请选择要上传的附件"}, status=400)
    if len(files) + notice.attachments.count() > MAX_ATTACHMENT_COUNT:
        return JsonResponse({"code": "NOTIFICATION_ATTACHMENT_LIMIT", "error": f"每条通知最多添加{MAX_ATTACHMENT_COUNT}个附件"}, status=400)
    if any(file.size <= 0 or file.size > MAX_ATTACHMENT_BYTES for file in files):
        return JsonResponse({"code": "NOTIFICATION_ATTACHMENT_SIZE", "error": "附件不能为空，单个附件不能超过20 MB"}, status=400)
    if sum(file.size for file in files) > MAX_ATTACHMENT_TOTAL_BYTES:
        return JsonResponse({"code": "NOTIFICATION_ATTACHMENT_TOTAL_SIZE", "error": "本次附件总大小不能超过30 MB"}, status=400)
    saved = []
    try:
        for uploaded in files:
            filename = os.path.basename(str(uploaded.name or "附件"))
            filename = "".join(character for character in filename if not unicodedata.category(character).startswith("C"))[:255].strip() or "附件"
            attachment = NotificationAttachment.objects.create(
                notification=notice,
                file=uploaded,
                file_name=filename,
                content_type=str(uploaded.content_type or "")[:128],
                byte_size=uploaded.size,
            )
            saved.append(attachment)
    except Exception as exc:
        for attachment in saved:
            attachment.file.delete(save=False)
            attachment.delete()
        return JsonResponse({"code": "NOTIFICATION_ATTACHMENT_SAVE_FAILED", "error": "附件保存失败，请重试"}, status=500)
    return JsonResponse({"items": [_attachment_data(item) for item in saved]})


@csrf_exempt
@require_http_methods(["DELETE"])
@transaction.atomic
def delete_attachment(request, attachment_id):
    attachment = NotificationAttachment.objects.select_related("notification").filter(pk=attachment_id).first()
    if attachment is None:
        return JsonResponse({"code": "NOTIFICATION_ATTACHMENT_NOT_FOUND", "error": "附件不存在"}, status=404)
    PlatformNotification.objects.select_for_update().get(pk=attachment.notification_id)
    if not _may_manage_notice(request, attachment.notification):
        return JsonResponse({"code": "NOTIFICATION_MANAGEMENT_FORBIDDEN", "error": "当前账号不能删除此附件"}, status=403)
    attachment.file.delete(save=False)
    attachment.delete()
    return JsonResponse({"ok": True})


@require_GET
def download_attachment(request, attachment_id):
    attachment = NotificationAttachment.objects.select_related("notification").filter(pk=attachment_id).first()
    if attachment is None:
        raise Http404
    state = _state()
    if not _may_manage_notice(request, attachment.notification, state) and not attachment.notification.recipients.filter(user_id=_user_id(request)).exists():
        return JsonResponse({"code": "NOTIFICATION_FORBIDDEN", "error": "当前账号不能下载此附件"}, status=403)
    preview = request.GET.get("preview") == "1"
    content_type = PREVIEW_CONTENT_TYPES.get(os.path.splitext(attachment.file_name)[1].lower())
    if preview and not content_type:
        return JsonResponse({"code": "NOTIFICATION_PREVIEW_UNSUPPORTED", "error": "此格式仅支持下载"}, status=415)
    try:
        response = FileResponse(attachment.file.open("rb"), as_attachment=not preview, filename=attachment.file_name)
    except (FileNotFoundError, OSError):
        raise Http404
    response["Content-Type"] = content_type if preview else "application/octet-stream"
    response["X-Content-Type-Options"] = "nosniff"
    return response
