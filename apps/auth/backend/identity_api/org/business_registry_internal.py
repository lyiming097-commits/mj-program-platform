"""Backend-only enterprise lookup; callers persist only companyName and creditNo."""
import json
import uuid

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..auth.session import AuthSessionError, validate_auth_token
from ..internal import internal_json_response, require_internal_auth
from ..models import BusinessRegistryCompany, BusinessRegistryQuery
from .business_registry import search_parameters, start_query


def caller_payload(request):
    denied = require_internal_auth(request, service_name="Business registry")
    if denied is not None:
        return None, None, denied
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError("请求必须是 JSON 对象")
        if "token" in payload and (not isinstance(payload["token"], str) or not payload["token"].strip()):
            raise ValueError("token 必须是有效的登录凭证，系统任务可省略此字段")
    except (ValueError, TypeError, UnicodeDecodeError):
        return None, None, internal_json_response(request, status=400, error="请求须为合法 JSON 对象，token 如提供则须为非空字符串", code="INVALID_REQUEST")
    # The service identity comes only from its registered credential. A human
    # identity is accepted only from a verified Auth token, never a posted user ID.
    identity = {
        "source_app_id": request.internal_service_app_id,
        "source_service": request.internal_caller,
        "actor_user_id": "", "effective_user_id": "",
        "actor_name": request.internal_caller, "effective_name": request.internal_caller,
    }
    if "token" in payload:
        try:
            session = validate_auth_token(payload["token"].strip())
        except AuthSessionError as error:
            return None, None, internal_json_response(request, status=error.status_code, error=str(error), code=error.code)
        identity.update(
            actor_user_id=session.actor_user_id, actor_name=session.actor_employee.name,
            effective_user_id=session.user_id, effective_name=session.employee.name,
        )
    return payload, identity, None


def query_response(request, record):
    has_more = (
        record.status == "succeeded" and record.result_count > 0 and record.page_num < 100
        and (record.result_count == record.page_size if record.total_records is None
             else record.page_num * record.page_size < record.total_records)
    )
    return internal_json_response(request, {
        "queryId": record.id, "queryRequestId": str(record.request_id),
        "keyword": record.keyword, "pageNum": record.page_num, "pageSize": record.page_size,
        "status": record.status, "message": record.message,
        "totalRecords": record.total_records, "resultCount": record.result_count,
        "hasMore": has_more, "nextPageNum": record.page_num + 1 if has_more else None,
        "companies": [{"companyName": company["companyName"], "creditNo": company["creditNo"]}
                      for company in record.companies],
    }, status=202 if record.status == "running" else 200)


@csrf_exempt
@require_POST
def search(request):
    payload, identity, error = caller_payload(request)
    if error is not None:
        return error
    try:
        parameters = search_parameters({**payload, "requestId": payload.get("queryRequestId")})
    except (ValueError, TypeError):
        return internal_json_response(request, status=400, code="INVALID_REQUEST",
            error="keyword 须为 1–200 字，pageNum 须为 1–100，pageSize 须为 1–20，queryRequestId 须为 UUID")
    record, error = start_query(**parameters, **identity)
    return error if error is not None else query_response(request, record)


@csrf_exempt
@require_POST
def query_detail(request):
    payload, identity, error = caller_payload(request)
    if error is not None:
        return error
    try:
        request_id = uuid.UUID(str(payload.get("queryRequestId", "")))
    except (ValueError, TypeError):
        return internal_json_response(request, status=400, error="queryRequestId 须为 UUID", code="INVALID_REQUEST")
    scope = {key: identity[key] for key in ("source_app_id", "source_service", "actor_user_id", "effective_user_id")}
    record = BusinessRegistryQuery.objects.filter(request_id=request_id, **scope).first()
    if record is None:
        return internal_json_response(request, status=404, error="查询记录不存在", code="NOT_FOUND")
    return query_response(request, record)


@csrf_exempt
@require_POST
def cached_companies(request):
    """Exact public enterprise identities already purchased; never calls the provider."""
    payload, identity, error = caller_payload(request)
    if error is not None:
        return error
    keys = payload.get("keywords")
    if (not isinstance(keys, list) or not 1 <= len(keys) <= 100
            or any(not isinstance(key, str) or not 1 <= len(key.strip()) <= 200 for key in keys)):
        return internal_json_response(request, status=400, code="INVALID_REQUEST", error="keywords 须为 1–100 个非空查询条件")
    results = []
    for key in dict.fromkeys(key.strip() for key in keys):
        from django.db.models import Q
        rows = list(BusinessRegistryCompany.objects.filter(Q(company_name=key) | Q(credit_no=key))
                    .select_related("last_query").order_by("-last_queried_at", "id")[:21])
        results.append({"keyword": key, "truncated": len(rows) > 20, "companies": [
            {"companyName": row.company_name, "creditNo": row.credit_no,
             "evidenceId": str(row.last_query.request_id), "queriedAt": row.last_queried_at.isoformat()}
            for row in rows[:20]
        ]})
    # Query histories, identities, provider responses and contact details are private.
    return internal_json_response(request, {"items": results, "paidQueries": 0})
