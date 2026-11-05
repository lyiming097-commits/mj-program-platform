import inspect
import json
from pathlib import Path
import re

from django.db import connection, transaction
from django.http import JsonResponse
from pydantic import ValidationError

from . import handlers, schemas
from .category_supervisors import get_supervisors, save_supervisors
from .errors import HTTPException
from .models import AuditEvent, PermissionState
from .organization import department_tree, organization_snapshot, routing_users
from .permissions import capabilities, current_user, effective_members, rules_list, save_rules

ROUTES = json.loads(Path(__file__).with_name('route_specs.json').read_text(encoding='utf-8'))


def fail(error):
    message = error.detail
    code = ('ORG_REVISION_CONFLICT' if 'ORG_REVISION_CONFLICT' in str(message) else
            'REVISION_CONFLICT' if 'REVISION_CONFLICT' in str(message) else
            {401: 'UNAUTHORIZED', 403: 'FORBIDDEN', 503: 'AUTH_SERVICE_UNAVAILABLE'}.get(error.status_code, 'INVALID_REQUEST'))
    return JsonResponse({'ok': False, 'detail': message, 'error': message, 'code': code}, status=error.status_code)


def body(request):
    try:
        payload = json.loads(request.body or '{}')
        if not isinstance(payload, dict):
            raise ValueError()
        return payload
    except (ValueError, UnicodeError):
        raise HTTPException(400, '请求必须为 JSON 对象')


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        return JsonResponse({'ok': True, 'appId': 'form-designer'})
    except Exception:
        return JsonResponse({'ok': False}, status=503)


def canonicalize_ids(payload):
    """Only immutable Auth IDs are allowed in persisted personnel assignments."""
    users = {item['username'] for item in routing_users()}
    def walk(nodes):
        for node in nodes:
            if node.get('assigneeMode') == 'specified' or (node.get('type') in {'approval', 'executor'} and not node.get('assigneeMode')):
                if any(str(value) not in users for value in node.get('assignees', [])):
                    raise HTTPException(422, '处理人必须使用 Auth 目录中的有效 userId，请重新选择人员')
            for branch in node.get('branches', []):
                walk(branch.get('nodes', []))
    walk(payload.get('nodes', []))
    permissions = payload.get('permissions', {})
    for user_id in [*permissions.get('members', []), *payload.get('pageSettings', {}).get('consultants', [])]:
        if str(user_id) not in users:
            raise HTTPException(422, '成员必须使用有效的 Auth userId')


def endpoint(request, resource=''):
    resource = resource.rstrip('/')
    if resource in {'health', 'health/live', 'health/ready'}:
        return health(request)
    try:
        grants = capabilities(request)
        if resource == 'category-supervisors':
            if 'admin' not in grants:
                raise HTTPException(403, '只有应用管理员可以设置分类主管')
            if request.method == 'GET':
                return JsonResponse(get_supervisors())
            if request.method == 'POST':
                with transaction.atomic():
                    result = save_supervisors(body(request))
                    audit(request, 'category_supervisors.save')
                return JsonResponse(result)
            raise HTTPException(405, '请求方法不支持')
        if resource in {'permissions', 'permissions/directory'}:
            if 'admin' not in grants:
                raise HTTPException(403, '只有应用管理员可以配置权限')
            if resource.endswith('/directory') and request.method == 'GET':
                departments, employees, revision = organization_snapshot(refresh=True)
                return JsonResponse({'departments': department_tree(departments), 'employees': employees,
                                     'roles': [], 'directorySource': 'auth', 'orgRevision': revision})
            if resource == 'permissions' and request.method == 'GET':
                with transaction.atomic():
                    state, _created = PermissionState.objects.select_for_update().get_or_create(pk=1)
                    items = rules_list()
                    revision = str(state.revision)
                departments, employees, org_revision = organization_snapshot()
                effective = {p: sorted(effective_members(p, items, departments, employees)) for p in ['admin', 'designer', 'user']}
                return JsonResponse({'items': items, 'revision': revision, 'effectiveMembers': effective, 'orgRevision': org_revision})
            if resource == 'permissions' and request.method == 'POST':
                result = save_rules(body(request))
                audit(request, 'permissions.save')
                return JsonResponse(result)
            raise HTTPException(405, '请求方法不支持')
        if not grants:
            raise HTTPException(403, '尚未获得表单设计应用的使用权限，请联系应用管理员')
        user = current_user(request, grants)
        if resource in {'session', 'auth/me'} and request.method == 'GET':
            return JsonResponse({'user': user, 'canManageApp': 'admin' in grants,
                                 'canDesign': user['canDesign'], 'canUseSystemAdmin': request.auth_can_use_system_admin,
                                 'userId': request.auth_user_id, 'sessionId': getattr(request, 'auth_session_id', '')}) if resource == 'session' else JsonResponse(user)
        if resource == 'users/directory' and request.method == 'GET':
            return JsonResponse(routing_users(), safe=False)
        for method, route, name, admin, payload_type, status in ROUTES:
            pattern = '^' + re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', route) + '$'
            match = re.fullmatch(pattern, resource)
            if not match or request.method != method:
                continue
            if admin and not grants & {'admin', 'designer'}:
                raise HTTPException(403, '只有应用管理员或设计员可以执行此操作')
            if name in {'disable_workflow', 'enable_workflow', 'delete_workflow', 'restore_workflow'} and 'admin' not in grants:
                raise HTTPException(403, '只有应用管理员可以管理流程状态')
            # Full business-data administration is separate from design permission.
            if (name.endswith('form_record') or name == 'list_form_records' or name in {'list_all_workflow_runs', 'list_workflow_runs'}) and 'admin' not in grants:
                raise HTTPException(403, '只有应用管理员可以管理全部业务数据')
            if 'admin' not in grants:
                creates_definition = name in {'create_approval', 'create_workflow'}
                if name == 'put_form':
                    creates_definition = not handlers.FormRepository.get_schema(match.groupdict().get('form_id', ''))
                if name == 'put_workflow':
                    creates_definition = not handlers.WorkflowRepository.get_schema(match.groupdict().get('workflow_id', ''))
                if creates_definition:
                    raise HTTPException(403, '只有应用管理员可以新建审批')
            kwargs = match.groupdict()
            function = getattr(handlers, name)
            if 'current_user' in inspect.signature(function).parameters:
                kwargs['current_user'] = user
            if payload_type:
                payload = body(request)
                if payload_type in {'FormPayload', 'WorkflowPayload'}:
                    canonicalize_ids(payload)
                    if payload_type == 'WorkflowPayload':
                        for key in ['publishedSnapshot', 'publishedAt']:
                            payload[key] = None
                        payload['publishedVersion'] = 0
                kwargs['payload'] = getattr(schemas, payload_type).model_validate(payload)
            for key in ['permanent', 'recycle']:
                if key in inspect.signature(function).parameters:
                    kwargs[key] = request.GET.get(key, 'false').lower() == 'true'
            if name == 'list_approval_records':
                kwargs['scope'] = request.GET.get('scope', 'applications')
            if name in {'start_workflow_run', 'preview_workflow_run'}:
                workflow = handlers.load_workflow(kwargs['workflow_id'])
                form = (workflow.get('publishedSnapshot') or {}).get('formSchema') or {}
                permissions = form.get('permissions') or {}
                if permissions.get('canSubmit') is False or (permissions.get('accessMode') == 'members' and str(request.auth_user_id) not in permissions.get('members', [])):
                    raise HTTPException(403, '当前表单不允许你发起申请')
            if name == 'publish_workflow':
                canonicalize_ids(handlers.load_workflow(kwargs['workflow_id']))
            with transaction.atomic():
                if name in {'create_workflow', 'put_workflow', 'publish_workflow', 'start_workflow_run', 'preview_workflow_run', 'disable_workflow', 'enable_workflow', 'delete_workflow', 'restore_workflow'}:
                    workflow_id = kwargs.get('workflow_id') or kwargs['payload'].id
                    handlers.WorkflowRepository.lock_definition(workflow_id)
                result = function(**kwargs)
                if 'admin' not in grants and name in {'list_forms', 'get_form', 'list_workflows'}:
                    def can_access(form):
                        permissions = form.get('permissions') or {}
                        return permissions.get('accessMode') != 'members' or str(request.auth_user_id) in permissions.get('members', [])
                    if name == 'get_form' and not can_access(result):
                        raise HTTPException(403, '没有此表单的访问权限')
                    if name == 'list_forms':
                        result = [form for form in result if can_access(form)]
                    if name == 'list_workflows':
                        result = [workflow for workflow in result if can_access((workflow.get('publishedSnapshot') or {}).get('formSchema') or {})]
                if method not in {'GET', 'HEAD'} and name != 'preview_workflow_run':
                    audit(request, name)
            return JsonResponse(result, safe=isinstance(result, dict), status=status)
        raise HTTPException(404, '接口不存在')
    except HTTPException as error:
        return fail(error)
    except ValidationError:
        return fail(HTTPException(422, '请求字段格式不正确'))


def audit(request, action):
    AuditEvent.objects.create(actor_user_id=getattr(request, 'auth_actor_user_id', '') or request.auth_user_id,
                              effective_user_id=request.auth_user_id, action=action)
