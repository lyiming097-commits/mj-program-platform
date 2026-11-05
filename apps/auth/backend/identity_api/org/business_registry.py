"""Saved enterprise queries shared by the administrator UI and authenticated internal services."""
import json
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ..models import BusinessRegistryCompany, BusinessRegistryQuery, BusinessRegistryQueryCompany, Employee
from .business_registry_client import RegistryResponseError, identity_key, normalize_companies, query_company_service
from .organization_access import can_manage_organization

FIELD_MAP = {
    "companyName": "company_name", "creditNo": "credit_no", "companyCode": "company_code",
    "legalPerson": "legal_person", "companyStatus": "company_status", "establishDate": "establish_date",
}


def forbidden(request):
    if not can_manage_organization(request):
        return JsonResponse({"error": "只有后台管理员可以使用工商信息"}, status=403)
    return None


def integer(value, minimum, maximum):
    if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit():
        raise ValueError("分页参数必须是整数")
    number = int(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"分页参数须在 {minimum}–{maximum} 之间")
    return number


def filter_day(value):
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("日期须为有效的 YYYY-MM-DD") from error
    if value != parsed.isoformat():
        raise ValueError("日期须为有效的 YYYY-MM-DD")
    return parsed


def filter_local_day(records, field, value):
    # Use explicit Beijing-day boundaries, including records stored in UTC.
    day = filter_day(value)
    if day.year < 2 or day == date.max:
        raise ValueError("查询日期超出支持范围")
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo("Asia/Shanghai"))
    return records.filter(**{f"{field}__gte": start, f"{field}__lt": start + timedelta(days=1)})


def query_data(record, *, detail=False):
    result = {
        "id": record.id, "requestId": str(record.request_id), "keyword": record.keyword,
        "pageNum": record.page_num, "pageSize": record.page_size, "status": record.status,
        "message": record.message, "totalRecords": record.total_records, "resultCount": record.result_count,
        "actorName": record.actor_name, "actorUserId": record.actor_user_id,
        "effectiveName": record.effective_name, "effectiveUserId": record.effective_user_id,
        "createdAt": record.created_at.isoformat(), "orderNo": record.order_no,
        "httpStatus": record.http_status, "businessCode": record.business_code,
        "gatewayRequestId": record.gateway_request_id,
        "sourceAppId": record.source_app_id or "auth", "sourceService": record.source_service or "auth-backend",
    }
    if detail:
        result["companies"] = record.companies
    return result


@require_GET
def companies(request):
    denied = forbidden(request)
    if denied is not None:
        return denied
    try:
        page = integer(request.GET.get("page", "1"), 1, 1_000_000)
        records = BusinessRegistryCompany.objects.annotate(query_count=Count("query_links")).order_by("-last_queried_at", "-id")
        for key in ("companyName", "creditNo", "companyCode", "legalPerson"):
            value = request.GET.get(key, "").strip()[:200]
            if value:
                records = records.filter(**{f"{FIELD_MAP[key]}__icontains": value})
        status = request.GET.get("companyStatus", "").strip()[:128]
        if status:
            records = records.filter(company_status=status)
        established = request.GET.get("establishDate", "").strip()
        if established:
            day = filter_day(established)
            records = records.filter(Q(establish_date=day.isoformat().replace("-", "")) | Q(establish_date__startswith=day.isoformat()))
        queried = request.GET.get("lastQueriedOn", "").strip()
        if queried:
            records = filter_local_day(records, "last_queried_at", queried)
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
    keyword = request.GET.get("keyword", "").strip()[:200]
    if keyword:
        records = records.filter(Q(company_name__icontains=keyword) | Q(credit_no__icontains=keyword) | Q(company_code__icontains=keyword))
    return JsonResponse({
        "configured": bool(settings.BUSINESS_REGISTRY_APPCODE), "total": records.count(), "page": page,
        "filterOptions": {"companyStatuses": list(BusinessRegistryCompany.objects.exclude(company_status="").order_by("company_status").values_list("company_status", flat=True).distinct())},
        "items": [{
            "id": row.id, **{key: getattr(row, field) for key, field in FIELD_MAP.items()},
            "firstQueriedAt": row.first_queried_at.isoformat(), "lastQueriedAt": row.last_queried_at.isoformat(),
            "lastQueryId": row.last_query_id, "queryCount": row.query_count,
        } for row in records[(page - 1) * 20:page * 20]],
    })


@require_GET
def company_queries(request, company_id):
    denied = forbidden(request)
    if denied is not None:
        return denied
    company = BusinessRegistryCompany.objects.filter(pk=company_id).first()
    if company is None:
        return JsonResponse({"error": "企业记录不存在"}, status=404)
    try:
        page = integer(request.GET.get("page", "1"), 1, 1_000_000)
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
    records = BusinessRegistryQuery.objects.filter(company_links__company=company).defer("companies", "response_payload")
    return JsonResponse({
        "company": {"id": company.id, "companyName": company.company_name, "creditNo": company.credit_no},
        "total": records.count(), "page": page,
        "items": [query_data(row) for row in records[(page - 1) * 20:page * 20]],
    })


@require_GET
def queries(request):
    denied = forbidden(request)
    if denied is not None:
        return denied
    try:
        page = integer(request.GET.get("page", "1"), 1, 1_000_000)
        records = BusinessRegistryQuery.objects.defer("companies", "response_payload")
        for key, field, minimum, maximum in (("pageNum", "page_num", 1, 100), ("resultCount", "result_count", 0, 20)):
            value = request.GET.get(key, "").strip()
            if value:
                records = records.filter(**{field: integer(value, minimum, maximum)})
        status = request.GET.get("status", "").strip()
        if status:
            if status not in ("running", "succeeded", "empty", "failed"):
                raise ValueError("无效的查询状态")
            records = records.filter(status=status)
        actor = request.GET.get("actor", "").strip()[:200]
        if actor:
            records = records.filter(Q(actor_name__icontains=actor) | Q(actor_user_id__icontains=actor) | Q(effective_name__icontains=actor) | Q(effective_user_id__icontains=actor))
        created = request.GET.get("createdOn", "").strip()
        if created:
            records = filter_local_day(records, "created_at", created)
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
    keyword = request.GET.get("keyword", "").strip()[:200]
    if keyword:
        records = records.filter(keyword__icontains=keyword)
    return JsonResponse({"configured": bool(settings.BUSINESS_REGISTRY_APPCODE), "total": records.count(), "page": page, "items": [query_data(row) for row in records[(page - 1) * 20:page * 20]]})


@require_GET
def query_detail(request, query_id):
    denied = forbidden(request)
    if denied is not None:
        return denied
    record = BusinessRegistryQuery.objects.filter(pk=query_id).first()
    if record is None:
        return JsonResponse({"error": "查询记录不存在"}, status=404)
    return JsonResponse(query_data(record, detail=True))


def complete_query(record):
    try:
        http_status, payload, gateway_id = query_company_service(
            settings.BUSINESS_REGISTRY_APPCODE, record.keyword, record.page_num, record.page_size,
        )
        record.http_status = http_status
        record.response_payload = payload
        record.gateway_request_id = gateway_id
        record.business_code = str(payload.get("code", ""))[:32]
        if not 200 <= http_status < 300:
            raise RegistryResponseError(f"工商服务请求失败（HTTP {http_status}），请检查服务认证或额度")
        if payload.get("success") is not True or record.business_code != "200":
            if record.business_code == "400" and str(payload.get("msg", "")).strip() == "查无数据":
                record.status, record.message, record.total_records = "empty", "查无数据", 0
            else:
                raise RegistryResponseError("工商服务未完成查询，请检查查询条件或服务状态")
        else:
            record.companies = normalize_companies(payload, record.page_size)
            data = payload["data"]
            record.order_no = str(data.get("orderNo") or "")[:128]
            page_info = data.get("pageInfo") or {}
            if not isinstance(page_info, dict):
                raise RegistryResponseError("工商服务返回的分页信息异常")
            if "pageIndex" in page_info:
                try:
                    actual_page = integer(page_info["pageIndex"], 1, 100)
                except ValueError as error:
                    raise RegistryResponseError("工商服务返回的页码异常") from error
                if actual_page != record.page_num:
                    raise RegistryResponseError("工商服务返回的页码与请求不一致")
            try:
                record.total_records = integer(page_info["totalRecords"], 0, 9_223_372_036_854_775_807)
            except (KeyError, ValueError):
                record.total_records = None
            record.result_count = len(record.companies)
            record.status = "succeeded" if record.result_count else "empty"
            record.message = f"已保存本页 {record.result_count} 条企业信息" if record.result_count else "查无数据"
    except requests.Timeout:
        record.status, record.message = "failed", "工商服务请求超时，未自动重试；可稍后重新查询"
    except requests.RequestException:
        record.status, record.message = "failed", "工商服务连接失败，未自动重试；请稍后重新查询"
    except RegistryResponseError as error:
        record.status, record.message = "failed", str(error)
    record.completed_at = timezone.now()
    if record.status == "failed":
        record.companies, record.result_count = [], 0
    # All companies and the successful query snapshot are committed together.
    with transaction.atomic():
        if record.status == "succeeded":
            for company in record.companies:
                row, _ = BusinessRegistryCompany.objects.get_or_create(
                    identity_key=identity_key(company),
                    defaults={**{field: company[key] for key, field in FIELD_MAP.items()},
                              "last_queried_at": record.created_at, "last_query": record},
                )
                # A slower earlier request must not overwrite a newer snapshot.
                BusinessRegistryCompany.objects.filter(pk=row.pk, last_queried_at__lte=record.created_at).update(
                    **{field: company[key] for key, field in FIELD_MAP.items()},
                    last_queried_at=record.created_at, last_query=record,
                )
                BusinessRegistryQueryCompany.objects.get_or_create(company=row, query=record)
        record.save()


def search_parameters(payload):
    if not isinstance(payload, dict):
        raise ValueError("请求必须是 JSON 对象")
    keyword = payload.get("keyword")
    if not isinstance(keyword, str) or not 1 <= len(keyword.strip()) <= 200:
        raise ValueError("请输入 1–200 字的企业名称、信用代码或注册号")
    return {
        "keyword": keyword.strip(),
        "page_num": integer(payload.get("pageNum", 1), 1, 100),
        "page_size": integer(payload.get("pageSize", 20), 1, 20),
        "request_id": uuid.UUID(str(payload.get("requestId", ""))),
    }


def start_query(*, keyword, page_num, page_size, request_id, actor_user_id, actor_name,
                effective_user_id, effective_name, source_app_id="", source_service=""):
    """One paid request per UUID, bound to both its caller and query parameters."""
    existing = BusinessRegistryQuery.objects.filter(request_id=request_id).first()
    if existing is None and not settings.BUSINESS_REGISTRY_APPCODE:
        return None, JsonResponse({"error": "工商查询服务尚未配置，请联系管理员配置服务凭证", "code": "REGISTRY_NOT_CONFIGURED"}, status=503)
    binding = {
        "keyword": keyword, "page_num": page_num, "page_size": page_size,
        "actor_user_id": actor_user_id, "effective_user_id": effective_user_id,
        "source_app_id": source_app_id, "source_service": source_service,
    }
    record, created = BusinessRegistryQuery.objects.get_or_create(request_id=request_id, defaults={
        **binding, "actor_name": actor_name, "effective_name": effective_name,
    })
    if any(getattr(record, key) != value for key, value in binding.items()):
        return None, JsonResponse({"error": "请求编号已使用，请重新发起查询", "code": "REGISTRY_REQUEST_CONFLICT"}, status=409)
    if created:
        complete_query(record)
    return record, None


@csrf_exempt
@require_POST
def search(request):
    denied = forbidden(request)
    if denied is not None:
        return denied
    try:
        parameters = search_parameters(json.loads(request.body))
    except (ValueError, TypeError, UnicodeDecodeError) as error:
        return JsonResponse({"error": str(error) if not isinstance(error, json.JSONDecodeError) else "请求 JSON 格式错误"}, status=400)
    effective_id = str(request.auth_user_id)
    actor_id = str(request.auth_actor_user_id or effective_id)
    names = dict(Employee.objects.filter(user_id__in=[effective_id, actor_id]).values_list("user_id", "name"))
    record, error = start_query(**parameters,
        actor_user_id=actor_id, actor_name=names.get(actor_id, actor_id),
        effective_user_id=effective_id, effective_name=names.get(effective_id, effective_id))
    if error is not None:
        return error
    return JsonResponse(query_data(record, detail=True), status=202 if record.status == "running" else 200)
