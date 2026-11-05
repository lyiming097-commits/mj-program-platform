import uuid

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .models import SettingItem
from .serializers import serialize_setting, serialize_settings
from .setting_defaults import ensure_default_setting_items
from .view_helpers import error_response, json_body, request_access


OPTION_SETTING_GROUPS = frozenset(
    {"material_category", "validity", "reminder_owner"}
)
SETTING_GROUPS = frozenset({"collection_field", *OPTION_SETTING_GROUPS})
CORE_COLLECTION_FIELDS = frozenset(
    {"brand", "name", "product_id", "material_category", "region", "location"}
)


@require_http_methods(["GET"])
def settings_collection(request):
    _access, error = request_access(request, "can_manage")
    if error:
        return error
    ensure_default_setting_items()
    rows = SettingItem.objects.order_by("group", "position", "label")
    return JsonResponse(serialize_settings(rows), safe=False)


@csrf_exempt
@require_http_methods(["POST"])
def setting_items(request):
    _access, error = request_access(request, "can_manage")
    if error:
        return error
    payload, error = json_body(request)
    if error:
        return error
    group = str(payload.get("group") or "")
    label = str(payload.get("label") or "").strip()
    if group not in SETTING_GROUPS:
        return error_response("不支持的设置分组", 422)
    if not label or len(label) > 120:
        return error_response("设置项名称不能为空", 422)
    if SettingItem.objects.filter(group=group, label=label).exists():
        return error_response("该设置项已存在", 409)
    try:
        position = int(payload.get("position") or 0)
    except (TypeError, ValueError):
        return error_response("设置项顺序无效", 422)
    if position < 0:
        return error_response("设置项顺序无效", 422)
    item = SettingItem.objects.create(
        group=group,
        code=uuid.uuid4().hex,
        label=label,
        enabled=payload.get("enabled") is not False,
        required=payload.get("required") is True,
        position=position,
    )
    return JsonResponse(serialize_setting(item), status=201)


@csrf_exempt
@require_http_methods(["PATCH"])
def setting_item_detail(request, item_id):
    _access, error = request_access(request, "can_manage")
    if error:
        return error
    payload, error = json_body(request)
    if error:
        return error
    allowed_fields = {"label", "enabled", "required", "position"}
    if any(key not in allowed_fields for key in payload):
        return error_response("包含不支持的设置字段", 422)

    with transaction.atomic():
        try:
            item = SettingItem.objects.select_for_update().get(id=item_id)
        except SettingItem.DoesNotExist:
            return error_response("设置项不存在", 404)
        if item.group == "region":
            return error_response("省级行政区选项不可修改", 422)
        changes = {}
        if "label" in payload:
            label = str(payload["label"] or "").strip()
            if not label or len(label) > 120:
                return error_response("设置项名称不能为空", 422)
            if SettingItem.objects.filter(group=item.group, label=label).exclude(id=item.id).exists():
                return error_response("该设置项已存在", 409)
            changes["label"] = label
        for name in ("enabled", "required"):
            if name in payload:
                if not isinstance(payload[name], bool):
                    return error_response("启用和必填状态必须为布尔值", 422)
                changes[name] = payload[name]
        if "position" in payload:
            try:
                changes["position"] = int(payload["position"])
            except (TypeError, ValueError):
                return error_response("设置项顺序无效", 422)
            if changes["position"] < 0:
                return error_response("设置项顺序无效", 422)
        if item.group == "collection_field" and item.code in CORE_COLLECTION_FIELDS:
            if changes.get("enabled") is False:
                return error_response("核心采集字段不能停用", 409)
            if changes.get("required") is False:
                return error_response("核心采集字段必须保留为必填", 409)
        if item.group in OPTION_SETTING_GROUPS and changes.get("enabled") is False:
            if not SettingItem.objects.filter(group=item.group, enabled=True).exclude(id=item.id).exists():
                return error_response("每组选项至少保留一个启用项", 409)
        for name, value in changes.items():
            setattr(item, name, value)
        if changes:
            item.save(update_fields=[*changes, "updated_at"])
    return JsonResponse(serialize_setting(item))
