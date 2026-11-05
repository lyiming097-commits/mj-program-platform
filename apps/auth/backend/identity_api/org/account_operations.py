"""Account change previews and durable records, restricted to organization administrators."""
import hashlib
import json

from django.core import signing
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from ..models import Employee, OrganizationAccountOperation
from .organization_access import can_manage_organization

SALT = "auth.organization.account-preview.v1"


def changed_accounts(account_status, user_id=""):
    queryset = Employee.objects.all()
    if user_id:
        queryset = queryset.filter(user_id=user_id)
    else:
        queryset = queryset.filter(identity_source=Employee.IDENTITY_DINGTALK, status=Employee.STATUS_ACTIVE)
    return queryset.exclude(account_status=account_status).order_by("user_id")


def preview_signature(request, account_status, user_id, employees):
    snapshot = [(item.user_id, item.name, item.status, item.account_status, item.auth_version) for item in employees]
    return {
        "userId": user_id,
        "accountStatus": account_status,
        "operator": str(getattr(request, "auth_user_id", "")),
        "actor": str(getattr(request, "auth_actor_user_id", "")),
        "snapshot": hashlib.sha256(json.dumps(snapshot, ensure_ascii=False).encode()).hexdigest(),
    }


def validate_preview(request, payload, account_status, user_id, employees):
    # Older mobile clients remain compatible; desktop always sends the signed preview.
    if "confirmationToken" not in payload:
        return None
    try:
        actual = signing.loads(payload["confirmationToken"], salt=SALT, max_age=300)
        if actual == preview_signature(request, account_status, user_id, employees):
            return None
    except (signing.BadSignature, TypeError, ValueError):
        pass
    return JsonResponse({"code": "ACCOUNT_PREVIEW_CHANGED", "error": "账号范围或状态已变化，请重新核对影响人数后确认"}, status=409)


def record_account_operation(request, account_status, user_id, employees):
    if not employees:
        return
    effective_id = str(getattr(request, "auth_user_id", ""))
    actor_id = str(getattr(request, "auth_actor_user_id", "") or effective_id)
    names = dict(Employee.objects.filter(user_id__in=[effective_id, actor_id]).values_list("user_id", "name"))
    OrganizationAccountOperation.objects.create(
        actor_user_id=actor_id, actor_name=names.get(actor_id, actor_id),
        effective_user_id=effective_id, effective_name=names.get(effective_id, effective_id),
        account_status=account_status, scope="employee" if user_id else "all",
        changes=[{"userId": item.user_id, "name": item.name, "before": item.account_status, "after": account_status} for item in employees],
    )


@require_GET
def account_status_preview(request):
    if not can_manage_organization(request):
        return JsonResponse({"error": "只有组织架构管理员可以查看账号操作范围"}, status=403)
    account_status = request.GET.get("accountStatus", "")
    user_id = request.GET.get("userId", "").strip()
    if account_status not in {Employee.ACCOUNT_ENABLED, Employee.ACCOUNT_DISABLED}:
        return JsonResponse({"error": "账号状态无效"}, status=400)
    if user_id:
        employee = Employee.objects.filter(user_id=user_id).first()
        if employee is None:
            return JsonResponse({"error": "员工不存在"}, status=404)
        if employee.status == Employee.STATUS_INACTIVE and account_status == Employee.ACCOUNT_ENABLED:
            return JsonResponse({"error": "离职员工账号不能启用"}, status=400)
    employees = list(changed_accounts(account_status, user_id))
    ids = {item.user_id for item in employees}
    return JsonResponse({
        "count": len(employees), "scope": "employee" if user_id else "all",
        "affectsCurrentAccount": bool(ids & {getattr(request, "auth_user_id", ""), getattr(request, "auth_actor_user_id", "")}),
        "confirmationToken": signing.dumps(preview_signature(request, account_status, user_id, employees), salt=SALT),
    })


@require_GET
def account_operation_list(request):
    if not can_manage_organization(request):
        return JsonResponse({"error": "只有组织架构管理员可以查看账号操作记录"}, status=403)
    try:
        offset = max(0, int(request.GET.get("offset", "0")))
    except (ValueError, TypeError):
        return JsonResponse({"error": "分页参数无效"}, status=400)
    queryset = OrganizationAccountOperation.objects.all()
    return JsonResponse({"total": queryset.count(), "items": [{
        "id": item.id, "actorName": item.actor_name, "actorUserId": item.actor_user_id,
        "effectiveName": item.effective_name, "effectiveUserId": item.effective_user_id,
        "accountStatus": item.account_status, "scope": item.scope,
        "count": len(item.changes), "changes": item.changes,
        "createdAt": item.created_at.isoformat(),
    } for item in queryset[offset:offset + 20]]})
