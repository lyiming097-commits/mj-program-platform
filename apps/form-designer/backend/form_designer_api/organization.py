from contextvars import ContextVar
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from .errors import HTTPException

_snapshot = ContextVar('form_designer_organization', default=None)


class SnapshotMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _snapshot.set({})
        try:
            return self.get_response(request)
        finally:
            _snapshot.reset(token)


def post_internal(path, payload):
    secret_file = os.getenv('AUTH_SERVICE_INTROSPECTION_SECRET_FILE')
    secret = Path(secret_file).read_text(encoding='utf-8').strip() if secret_file else os.getenv('AUTH_SERVICE_INTROSPECTION_SECRET', '')
    if not secret:
        raise HTTPException(503, 'Auth 内部服务凭据尚未配置')
    base = os.getenv('AUTH_ORG_INTERNAL_URL', 'http://auth-backend:8000/api/internal/org').rstrip('/')
    request = urllib.request.Request(f'{base}/{path}', data=json.dumps(payload).encode(), method='POST', headers={
        'Content-Type': 'application/json',
        'X-Internal-Service': os.getenv('SERVICE_NAME', 'form-designer-backend'),
        'X-Internal-Auth-Secret': secret,
    })
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.load(response)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise HTTPException(503, 'Auth 组织架构服务暂不可用') from exc
    if not isinstance(data, dict) or data.get('ok') is not True:
        raise HTTPException(503, 'Auth 组织架构响应无效')
    return data


def organization_snapshot(*, refresh=False):
    cache = _snapshot.get()
    if cache is not None and cache.get('value') and not refresh:
        return cache['value']
    for _attempt in range(3):
        revision = None
        all_items = []
        consistent = True
        for endpoint in ['departments/search', 'users/search']:
            items, offset = [], 0
            while True:
                data = post_internal(endpoint, {
                    'keyword': '', 'offset': offset, 'limit': 100,
                    'status': 'active', 'accountStatus': 'enabled',
                    'includeDepartments': True, 'includeDepartmentPath': True,
                })
                current = data.get('orgRevision')
                if isinstance(current, bool) or not isinstance(current, int) or current < 0:
                    raise HTTPException(503, 'Auth 未返回有效组织版本')
                if revision is not None and revision != current:
                    consistent = False
                    break
                revision = current
                page = data.get('items')
                if not isinstance(page, list):
                    raise HTTPException(503, 'Auth 组织目录格式错误')
                items.extend(page)
                offset += len(page)
                total = data.get('total')
                if total is not None:
                    if offset >= int(total):
                        break
                    if not page:
                        raise HTTPException(503, 'Auth 组织目录分页不完整')
                elif len(page) < 100:
                    break
                if offset > 100000:
                    raise HTTPException(503, 'Auth 组织目录超出读取范围')
            if not consistent:
                break
            all_items.append(items)
        if consistent:
            value = (*all_items, revision)
            if cache is not None:
                cache['value'] = value
            return value
    raise HTTPException(503, '组织架构持续变化，请稍后重试')


def department_id(item):
    return str(item.get('deptId', item.get('id', '')))


def manager_ids(department):
    return [str(value) for value in (department.get('managerUserIds') or [department.get('managerUserId')]) if value]


def routing_users():
    departments, employees, _revision = organization_snapshot()
    department_map = {department_id(item): item for item in departments}
    users = []
    for employee in employees:
        user_id = str(employee.get('userId', employee.get('id', '')))
        memberships = [department_id(item) for item in employee.get('departments', [])]
        managers = list(dict.fromkeys(manager for dept in memberships for manager in manager_ids(department_map.get(dept, {})) if manager != user_id))
        is_manager = any(user_id in manager_ids(dept) for dept in departments)
        users.append({
            'username': user_id, 'userId': user_id,
            'displayName': employee.get('name') or user_id,
            'role': 'manager' if is_manager else 'employee',
            'department': '、'.join(department_map.get(dept, {}).get('name', dept) for dept in memberships),
            'departmentIds': memberships,
            'managerUsername': str(employee.get('managerUserId') or (managers[0] if managers else '')) or None,
            'managerUserIds': managers,
        })
    return users


def department_tree(departments):
    nodes = {department_id(item): {'id': department_id(item), 'name': item.get('name', ''), 'children': []} for item in departments}
    roots = []
    for item in departments:
        node = nodes[department_id(item)]
        parent = str(item.get('parentDeptId') or '')
        if parent in nodes and parent != node['id']:
            nodes[parent]['children'].append(node)
        else:
            roots.append(node)
    return roots
