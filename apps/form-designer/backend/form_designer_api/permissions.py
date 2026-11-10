from django.db import transaction
from .category_supervisors import managed_categories
from .errors import HTTPException
from .models import PermissionRule, PermissionState
from .organization import department_id, organization_snapshot, routing_users

PERMISSIONS = {'admin', 'designer', 'user'}
SCOPES = {'department', 'departmentSub', 'employee', 'excludedEmployee'}


def effective_members(permission, rules, departments, employees):
    parents = {department_id(item): str(item.get('parentDeptId') or '') for item in departments}
    result = set()
    relevant = [item for item in rules if item['permission'] == permission]
    excluded = {item['targetId'] for item in relevant if item['scopeType'] == 'excludedEmployee'}
    for employee in employees:
        user_id = str(employee.get('userId', employee.get('id', '')))
        direct = {department_id(item) for item in employee.get('departments', [])}
        ancestors = set(direct)
        for initial in direct:
            cursor = initial
            while parents.get(cursor) and parents[cursor] not in ancestors:
                cursor = parents[cursor]
                ancestors.add(cursor)
        included = any(
            (item['scopeType'] == 'employee' and item['targetId'] == user_id)
            or (item['scopeType'] == 'department' and item['targetId'] in direct)
            or (item['scopeType'] == 'departmentSub' and item['targetId'] in ancestors)
            for item in relevant
        )
        if included and user_id not in excluded:
            result.add(user_id)
    return result


def rules_list():
    return [{'permission': item.permission, 'scopeType': item.scope_type, 'targetId': item.target_id,
             'targetName': item.target_name, 'sortOrder': item.sort_order}
            for item in PermissionRule.objects.order_by('sort_order', 'id')]


def capabilities(request):
    if getattr(request, 'auth_can_use_system_admin', False) is True:
        return {'admin', 'designer', 'user'}
    user_id = str(getattr(request, 'auth_user_id', ''))
    if not user_id:
        raise HTTPException(401, '请先通过统一身份中心登录')
    rules = rules_list()
    categories = managed_categories(user_id)
    if not rules and not categories:
        return set()
    departments, employees, _revision = organization_snapshot()
    granted = {permission for permission in PERMISSIONS if user_id in effective_members(permission, rules, departments, employees)}
    if categories and any(str(item.get('userId', item.get('id', ''))) == user_id for item in employees):
        granted.add('user')
    if 'admin' in granted:
        granted.update(PERMISSIONS)
    if 'designer' in granted:
        granted.add('user')
    return granted


def current_user(request, grants):
    user_id = str(request.auth_user_id)
    user = next((item for item in routing_users() if item['username'] == user_id), None)
    categories = managed_categories(user_id) if user else []
    if user is None:
        user = {'username': user_id, 'displayName': getattr(request, 'auth_user_name', '') or user_id,
                'department': '', 'departmentIds': [], 'managerUsername': None, 'role': 'employee'}
    return {**user, 'role': 'admin' if grants & {'admin', 'designer'} or categories else user['role'],
            'actorUserId': getattr(request, 'auth_actor_user_id', '') or user_id,
            'actorName': getattr(request, 'auth_actor_name', '') or user['displayName'],
            'canManagePermissions': 'admin' in grants, 'canDesignGlobally': bool(grants & {'admin', 'designer'}),
            'canDesign': bool(grants & {'admin', 'designer'} or categories), 'managedCategories': categories}


def save_rules(payload):
    departments, employees, revision = organization_snapshot(refresh=True)
    if str(payload.get('orgRevision', '')) != str(revision):
        raise HTTPException(409, '组织架构已变化，请刷新后重新确认（ORG_REVISION_CONFLICT）')
    items = payload.get('items')
    if not isinstance(items, list) or len(items) > 1000:
        raise HTTPException(400, '权限规则必须为数组，且不能超过 1000 条')
    depts = {department_id(item): item.get('name', '') for item in departments}
    users = {str(item.get('userId', item.get('id', ''))): item.get('name', '') for item in employees}
    normalized, seen = [], set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise HTTPException(400, '权限规则格式错误')
        permission, scope, target = item.get('permission'), item.get('scopeType'), str(item.get('targetId', ''))
        if permission not in PERMISSIONS or scope not in SCOPES:
            raise HTTPException(400, '不支持的权限或授权范围')
        targets = depts if scope in {'department', 'departmentSub'} else users
        if not target or target not in targets:
            raise HTTPException(400, '所选部门或人员已不存在，请刷新目录')
        key = (permission, scope, target)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(PermissionRule(permission=permission, scope_type=scope, target_id=target,
                                         target_name=targets[target], sort_order=index))
    with transaction.atomic():
        state, _created = PermissionState.objects.select_for_update().get_or_create(pk=1)
        if str(payload.get('revision', '')) != str(state.revision):
            raise HTTPException(409, '权限已被其他人修改，请刷新后重新确认（REVISION_CONFLICT）')
        PermissionRule.objects.all().delete()
        PermissionRule.objects.bulk_create(normalized)
        state.revision += 1
        state.save(update_fields=['revision'])
    return {'ok': True, 'items': rules_list(), 'revision': str(state.revision), 'orgRevision': revision}
