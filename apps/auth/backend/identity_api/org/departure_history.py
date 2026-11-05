"""Read-only departure snapshots for CRM's existing historical members."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..models import Employee
from .internal_views import _internal_payload, _json_error, _parse_user_ids
from .queries import pinyin_initials, pinyin_text


@csrf_exempt
@require_POST
def internal_users_departure_history(request):
    payload, error = _internal_payload(request)
    if error is not None:
        return error
    if getattr(request, "internal_service_app_id", "") != "crm":
        return _json_error("Departure history is restricted to CRM", status=403, code="FORBIDDEN")
    user_ids, error = _parse_user_ids(payload)
    if error is not None:
        return error
    # Departed employees no longer have current department memberships. This
    # explicit-ID history lookup must not use the active directory's scope join.
    employees = {
        employee.user_id: employee
        for employee in Employee.objects.filter(
            user_id__in=user_ids, identity_source=Employee.IDENTITY_DINGTALK,
        ).only("user_id", "name", "status", "former_dingtalk_departments", "former_organization_recorded_at")
    }
    items = []
    for user_id in dict.fromkeys(user_ids):
        employee = employees.get(user_id)
        item = {"userId": user_id, "found": employee is not None}
        if employee is not None:
            item.update(name=employee.name, status=employee.status,
                        pinyin=pinyin_text(employee.name), pinyinInitials=pinyin_initials(employee.name))
            if employee.status == Employee.STATUS_INACTIVE:
                item["formerDingTalkDepartments"] = [
                    {key: row.get(key) for key in ("deptId", "name", "pathText")}
                    for row in (employee.former_dingtalk_departments or [])
                    if isinstance(row, dict)
                ]
                recorded_at = employee.former_organization_recorded_at
                item["formerOrganizationRecordedAt"] = recorded_at.isoformat() if recorded_at else ""
        items.append(item)
    return JsonResponse({"ok": True, "items": items})
