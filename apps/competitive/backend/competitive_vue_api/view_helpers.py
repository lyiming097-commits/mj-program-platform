import json
from math import ceil

from django.db.models import Q
from django.http import JsonResponse

from .models import Submission
from .org_client import OrganizationServiceError
from .permissions import resolve_permission_access


def error_response(detail, status: int) -> JsonResponse:
    return JsonResponse({"detail": detail}, status=status)


def request_access(request, capability: str = "can_access"):
    try:
        access = resolve_permission_access(request)
    except OrganizationServiceError as exc:
        return None, error_response(str(exc), exc.status_code)
    if not getattr(access, capability):
        messages = {
            "can_access": "暂无竞品情报系统权限",
            "can_collect": "缺少采集权限",
            "can_review": "缺少审核权限",
            "can_manage": "缺少权限管理权限",
        }
        return access, error_response(messages[capability], 403)
    return access, None


def json_body(request):
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return None, error_response("请求 JSON 无效", 400)
    if not isinstance(payload, dict):
        return None, error_response("请求 JSON 必须为对象", 400)
    return payload, None


def pagination(request) -> tuple[int, int] | JsonResponse:
    try:
        page = int(request.GET.get("page", "1"))
        page_size = int(request.GET.get("pageSize", "20"))
    except ValueError:
        return error_response("分页参数无效", 422)
    if page < 1 or page_size < 1 or page_size > 100:
        return error_response("分页参数无效", 422)
    return page, page_size


def page_result(items: list, total: int, page: int, page_size: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "pages": ceil(total / page_size) if total else 0,
    }


def submission_owner_filter(request) -> Q:
    operator_name = request.auth_actor_name or request.auth_user_name
    return Q(owner_user_id=request.auth_user_id) | Q(
        owner_user_id__isnull=True,
        owner=operator_name,
    )


def can_view_submission(request, access, submission: Submission) -> bool:
    if access.can_review:
        return True
    return bool(
        submission.owner_user_id == request.auth_user_id
        or (
            not submission.owner_user_id
            and submission.owner == (request.auth_actor_name or request.auth_user_name)
        )
    )
