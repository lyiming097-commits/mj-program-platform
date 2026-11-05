from __future__ import annotations

import json
import uuid
from typing import Any

from django.http import HttpResponse, JsonResponse


INTERNAL_SECRET_HEADER = "X-Internal-Auth-Secret"
INTERNAL_SERVICE_HEADER = "X-Internal-Service"
REQUEST_ID_HEADER = "X-Request-Id"
API_PATH_PREFIX = "/api/"
INTERNAL_PATH_PREFIX = "/api/internal/"
INTERNAL_ORG_PATH_PREFIX = "/api/internal/org/"
PUBLIC_ORG_PATH_PREFIX = "/api/org/"


def parse_json_body(request) -> dict[str, Any]:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def is_internal_api_request(request) -> bool:
    return str(getattr(request, "path", "") or "").startswith(INTERNAL_PATH_PREFIX)


def is_api_request(request) -> bool:
    return str(getattr(request, "path", "") or "").startswith(API_PATH_PREFIX)


def get_internal_request_id(request) -> str:
    request_id = str(getattr(request, "internal_request_id", "") or "").strip()
    if request_id:
        return request_id

    raw_request_id = str(request.headers.get(REQUEST_ID_HEADER) or "").strip()
    request_id = raw_request_id[:64] or uuid.uuid4().hex
    request.internal_request_id = request_id
    return request_id


def get_internal_caller(request) -> str:
    caller = str(getattr(request, "internal_caller", "") or "").strip()
    if caller:
        return caller

    caller = str(request.headers.get(INTERNAL_SERVICE_HEADER) or "unknown").strip()
    caller = caller[:128] or "unknown"
    request.internal_caller = caller
    return caller


def prepare_internal_request(request) -> None:
    get_internal_request_id(request)
    get_internal_caller(request)


def infer_error_code(status_code: int, error: object = "") -> str:
    message = str(error or "").strip().lower()
    if "internal auth secret" in message:
        return "INVALID_INTERNAL_SECRET"
    if "not configured" in message:
        return "INTERNAL_AUTH_NOT_CONFIGURED"
    if "missing auth token" in message:
        return "MISSING_AUTH_TOKEN"
    if status_code == 400:
        return "INVALID_REQUEST"
    if status_code == 401:
        return "UNAUTHORIZED"
    if status_code == 403:
        return "FORBIDDEN"
    if status_code == 404:
        return "NOT_FOUND"
    if status_code == 405:
        return "METHOD_NOT_ALLOWED"
    if status_code >= 500:
        return "INTERNAL_SERVER_ERROR"
    return "REQUEST_FAILED"


def internal_json_response(
    request,
    payload: dict[str, Any] | None = None,
    *,
    status: int = 200,
    code: str | None = None,
    error: str | None = None,
) -> JsonResponse:
    prepare_internal_request(request)
    response_payload = dict(payload or {})
    request_id = get_internal_request_id(request)

    if status >= 400 or response_payload.get("ok") is False:
        response_payload["ok"] = False
        if error is not None:
            response_payload.setdefault("error", error)
        response_payload.setdefault("error", error or "Request failed")
        response_payload.setdefault("code", code or infer_error_code(status, response_payload.get("error")))
    else:
        response_payload.setdefault("ok", True)

    response_payload.setdefault("requestId", request_id)
    response = JsonResponse(response_payload, status=status)
    response[REQUEST_ID_HEADER] = request_id
    return response


def require_internal_auth(request, *, service_name: str = "Internal API") -> JsonResponse | None:
    prepare_internal_request(request)
    provided_secret = str(request.headers.get(INTERNAL_SECRET_HEADER) or "").strip()
    caller = get_internal_caller(request)
    if caller == "unknown":
        return internal_json_response(
            request,
            {"ok": False, "error": "Missing internal service name"},
            status=403,
            code="MISSING_INTERNAL_SERVICE",
        )

    from .models import InternalServiceCredential

    credential = InternalServiceCredential.objects.filter(service_name=caller).first()
    if credential is None:
        return internal_json_response(
            request,
            {"ok": False, "error": "Unknown internal service"},
            status=403,
            code="UNKNOWN_INTERNAL_SERVICE",
        )
    if not credential.enabled:
        return internal_json_response(
            request,
            {"ok": False, "error": "Internal service is disabled"},
            status=403,
            code="INTERNAL_SERVICE_DISABLED",
        )
    if not credential.matches_secret(provided_secret):
        return internal_json_response(
            request,
            {"ok": False, "error": "Invalid internal auth secret"},
            status=403,
            code="INVALID_INTERNAL_SECRET",
        )

    request.internal_auth_ok = True
    request.internal_service_app_id = credential.app_id
    return None


def response_json_payload(response: HttpResponse) -> dict[str, Any] | None:
    if getattr(response, "streaming", False):
        return None
    content_type = str(response.headers.get("Content-Type", "") or "")
    if "application/json" not in content_type.lower():
        return None
    try:
        payload = json.loads(response.content.decode(getattr(response, "charset", "utf-8") or "utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def apply_organization_revision(request, response: HttpResponse, payload: dict[str, Any]) -> None:
    path = str(getattr(request, "path", "") or "")
    if not (path.startswith(INTERNAL_ORG_PATH_PREFIX) or path.startswith(PUBLIC_ORG_PATH_PREFIX)):
        return
    revision = getattr(request, "organization_revision", None)
    if revision is None:
        from .org.revision import get_organization_revision

        revision = get_organization_revision()
    payload.setdefault("orgRevision", revision)
    response["X-Organization-Revision"] = str(revision)


def apply_internal_response_contract(request, response: HttpResponse) -> HttpResponse:
    request_id = get_internal_request_id(request)
    payload = response_json_payload(response)

    if payload is None:
        if response.status_code < 400:
            response[REQUEST_ID_HEADER] = request_id
            return response
        payload = {
            "ok": False,
            "code": infer_error_code(response.status_code),
            "error": getattr(response, "reason_phrase", "") or "Request failed",
            "requestId": request_id,
        }
        replacement = JsonResponse(payload, status=response.status_code)
        if response.has_header("Allow"):
            replacement["Allow"] = response["Allow"]
        replacement[REQUEST_ID_HEADER] = request_id
        return replacement

    payload.setdefault("requestId", request_id)
    apply_organization_revision(request, response, payload)
    if response.status_code >= 400 or payload.get("ok") is False:
        payload["ok"] = False
        payload.setdefault("error", getattr(response, "reason_phrase", "") or "Request failed")
        payload.setdefault("code", infer_error_code(response.status_code, payload.get("error")))

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        getattr(response, "charset", "utf-8") or "utf-8"
    )
    response.content = body
    response["Content-Length"] = str(len(body))
    response[REQUEST_ID_HEADER] = request_id
    return response


def apply_api_response_contract(request, response: HttpResponse) -> HttpResponse:
    if is_internal_api_request(request):
        return response

    request_id = get_internal_request_id(request)
    payload = response_json_payload(response)

    if payload is None:
        if response.status_code < 400:
            response[REQUEST_ID_HEADER] = request_id
            return response
        payload = {
            "ok": False,
            "code": infer_error_code(response.status_code),
            "error": getattr(response, "reason_phrase", "") or "Request failed",
            "requestId": request_id,
        }
        replacement = JsonResponse(payload, status=response.status_code)
        if response.has_header("Allow"):
            replacement["Allow"] = response["Allow"]
        replacement[REQUEST_ID_HEADER] = request_id
        return replacement

    payload.setdefault("requestId", request_id)
    apply_organization_revision(request, response, payload)
    if response.status_code >= 400 or payload.get("ok") is False:
        payload["ok"] = False
        payload.setdefault("error", getattr(response, "reason_phrase", "") or "Request failed")
        payload.setdefault("code", infer_error_code(response.status_code, payload.get("error")))
    else:
        payload.setdefault("ok", True)

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        getattr(response, "charset", "utf-8") or "utf-8"
    )
    response.content = body
    response["Content-Length"] = str(len(body))
    response[REQUEST_ID_HEADER] = request_id
    return response


class InternalApiGovernanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not is_internal_api_request(request):
            return self.get_response(request)

        prepare_internal_request(request)
        response = self.get_response(request)
        return apply_internal_response_contract(request, response)


class ApiResponseContractMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not is_api_request(request):
            return self.get_response(request)

        get_internal_request_id(request)
        response = self.get_response(request)
        return apply_api_response_contract(request, response)
