import inspect
import json
from pathlib import Path
import re

from django.db import connection, transaction
from django.http import JsonResponse
from pydantic import ValidationError

from . import handlers, schemas
from .category_supervisors import (can_edit_category_form, category_settings, change_category_status, effective_category,
                                   get_supervisors, list_categories, recycled_categories, save_category, save_supervisors,
                                   workflow_categories, workflow_form_ids)
from .errors import HTTPException
from .models import AuditEvent, PermissionState
from .organization import department_tree, organization_snapshot, routing_users
from .permissions import capabilities, current_user, effective_members, rules_list, save_rules
from .workflow_personnel import personnel_impact, replace_current_person, replace_template_person
from .uploads import create_upload, read_upload

ROUTES = json.loads(Path(__file__).with_name('route_specs.json').read_text(encoding='utf-8'))
SCOPED_DESIGN_ACTIONS = {'get_workflow', 'put_workflow', 'publish_workflow', 'put_form',
                         'create_approval', 'disable_workflow', 'enable_workflow', 'delete_workflow'}


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
        if resource == 'workflow-categories':
            if request.method == 'GET':
                return JsonResponse(list_categories(include_deleted=True), safe=False)
            raise HTTPException(405, '请求方法不支持')
        if resource == 'workflow-category-settings/lifecycle':
            if 'admin' not in grants:
                raise HTTPException(403, '只有应用管理员可以管理流程分组')
            if request.method != 'POST':
                raise HTTPException(405, '请求方法不支持')
            payload = body(request)
            with transaction.atomic():
                result = change_category_status(payload)
                audit(request, 'workflow_category.' + payload['action'])
            return JsonResponse(result)
        if resource == 'workflow-category-settings':
            if 'admin' not in grants:
                raise HTTPException(403, '只有应用管理员可以设置流程分类')
            if request.method == 'GET':
                return JsonResponse(category_settings())
            if request.method == 'POST':
                with transaction.atomic():
                    result = save_category(body(request))
                    audit(request, 'workflow_category.save')
                return JsonResponse(result)
            raise HTTPException(405, '请求方法不支持')
        if resource in {'workflow-personnel', 'workflow-personnel/assignees'}:
            if 'admin' not in grants:
                raise HTTPException(403, '只有应用管理员可以跨流程排查人员')
            if resource == 'workflow-personnel' and request.method == 'GET':
                return JsonResponse(personnel_impact(request.GET.get('userId', '').strip()))
            if request.method == 'POST':
                with transaction.atomic():
                    if resource.endswith('/assignees'):
                        result = replace_current_person(body(request))
                        audit(request, 'workflow_personnel.update')
                    else:
                        result = replace_template_person(body(request))
                        audit(request, 'workflow_personnel.replace')
                return JsonResponse(result)
            raise HTTPException(405, '请求方法不支持')
        if resource == 'workflow-audit' and request.method == 'GET':
            if 'admin' not in grants:
                raise HTTPException(403, '只有应用管理员可以查看流程操作记录')
            actions = ('create_approval', 'create_workflow', 'put_workflow', 'publish_workflow',
                       'disable_workflow', 'enable_workflow', 'delete_workflow', 'restore_workflow', 'category_supervisors.save',
                       'workflow_category.save', 'workflow_category.delete', 'workflow_category.restore',
                       'rename_workflow', 'workflow_personnel.replace', 'workflow_personnel.update')
            events = AuditEvent.objects.filter(action__in=actions).order_by('-created_at', '-pk')[:50]
            return JsonResponse([
                {'id': event.pk, 'action': event.action, 'actorId': event.actor_user_id,
                 'effectiveUserId': event.effective_user_id, 'createdAt': event.created_at}
                for event in events
            ], safe=False)
        user = current_user(request, grants)
        if resource == 'uploads':
            if request.method != 'POST':
                raise HTTPException(405, '请求方法不支持')
            with transaction.atomic():
                result = create_upload(request, user)
                audit(request, 'upload_file')
            return JsonResponse(result, status=201)
        upload_route = re.fullmatch(r'uploads/([0-9a-f]{32})(/content)?', resource)
        if upload_route:
            if request.method != 'GET':
                raise HTTPException(405, '请求方法不支持')
            result = read_upload(upload_route[1], user, request.GET.get('runId', ''), request.GET.get('recordId', ''),
                                 bool(upload_route[2]), request.GET.get('inline') == 'true')
            return result if upload_route[2] else JsonResponse(result)
        categories = set(user.get('managedCategories') or [])
        scoped_user = bool(categories) and not grants & {'admin', 'designer'}
        rename_route = re.fullmatch(r'workflows/([^/]+)/name', resource)
        if rename_route and request.method == 'PATCH':
            workflow_id = rename_route[1]
            with transaction.atomic():
                handlers.WorkflowRepository.lock_definition(workflow_id)
                workflow = handlers.load_workflow(workflow_id)
                if 'admin' not in grants and not workflow_categories(workflow) <= categories:
                    raise HTTPException(403, '没有此流程分组的管理权限')
                if effective_category(workflow) in recycled_categories():
                    raise HTTPException(409, '请先恢复此流程所属的分组')
                result = handlers.rename_workflow(workflow, body(request), user)
                audit(request, 'rename_workflow')
            return JsonResponse(result)
        draft_route = re.fullmatch(r'approval-drafts/(flow-([0-9a-f]{32}))', resource)
        if draft_route and request.method == 'PUT':
            draft = schemas.ApprovalDraftPayload.model_validate(body(request))
            workflow_id, suffix = draft_route.groups()
            form_id = 'form-' + suffix
            form = draft.form.model_dump(exclude={'updatedAt'})
            workflow = draft.workflow.model_dump(exclude={'updatedAt', 'publishedAt', 'publishedVersion', 'publishedSnapshot'})
            if (draft.workflow.id != workflow_id or draft.form.id != form_id or workflow_form_ids(workflow) != {form_id}
                    or sum(node.get('type') == 'start' for node in workflow['nodes']) != 1
                    or not form['name'].strip() or not workflow['name'].strip()):
                raise HTTPException(422, '审批草稿必须关联本次创建的表单，并填写名称')
            if 'admin' not in grants and workflow['category'] not in categories:
                raise HTTPException(403, '没有此流程分类的管理权限')
            if workflow['category'] not in {item['key'] for item in list_categories()}:
                raise HTTPException(422, '请先创建流程分类')
            canonicalize_ids(form)
            canonicalize_ids(workflow)
            workflow = handlers.normalize_workflow_schema(workflow)
            with transaction.atomic():
                handlers.WorkflowRepository.lock_definition(workflow_id)
                existing_workflow = handlers.WorkflowRepository.get_schema(workflow_id)
                existing_form = handlers.FormRepository.get_schema(form_id)
                if existing_workflow and existing_form:
                    saved_workflow, saved_form = json.loads(existing_workflow[0]), json.loads(existing_form[0])
                    if (all(saved_workflow.get(key) == value for key, value in workflow.items())
                            and all(saved_form.get(key) == value for key, value in form.items())):
                        return JsonResponse({'workflow': saved_workflow, 'form': saved_form})
                if existing_workflow or existing_form:
                    raise HTTPException(409, '审批草稿已存在或已被修改，请重新打开后编辑')
                now = handlers.utc_now()
                form['updatedAt'] = now
                workflow['updatedAt'] = now
                workflow['draftSavedAt'] = now
                handlers.FormRepository.save_schema(form_id, form)
                handlers.WorkflowRepository.create_schema(workflow)
                audit(request, 'create_approval')
            return JsonResponse({'workflow': workflow, 'form': form}, status=201)
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
            if admin and not grants & {'admin', 'designer'} and not (scoped_user and name in SCOPED_DESIGN_ACTIONS):
                raise HTTPException(403, '只有应用管理员或设计员可以执行此操作')
            if name == 'restore_workflow' and 'admin' not in grants:
                raise HTTPException(403, '只有应用管理员可以管理流程状态')
            # Full business-data administration is separate from design permission.
            if (name.endswith('form_record') or name == 'list_form_records' or name in {'list_all_workflow_runs', 'list_workflow_runs'}) and 'admin' not in grants:
                raise HTTPException(403, '只有应用管理员可以管理全部业务数据')
            if 'admin' not in grants:
                creates_definition = name == 'create_workflow'
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
                if name in {'start_workflow_run', 'preview_workflow_run', 'publish_workflow'}:
                    stored = handlers.load_workflow(kwargs['workflow_id'])
                    archived = recycled_categories()
                    required_categories = workflow_categories(stored) if name == 'publish_workflow' else {effective_category(stored)}
                    if required_categories & archived.keys():
                        raise HTTPException(409, '此流程所属分组已移入回收站')
                if name == 'put_workflow' and request.headers.get('X-Workflow-Updated-At'):
                    row = handlers.WorkflowRepository.get_schema(kwargs['workflow_id'])
                    if row:
                        stored = json.loads(row[0])
                        if not stored.get('deletedAt') and stored.get('updatedAt') != request.headers['X-Workflow-Updated-At']:
                            raise HTTPException(409, '审批草稿已被更新，请重新打开流程后再保存')
                if name == 'put_form' and request.headers.get('X-Form-Updated-At'):
                    stored_form = handlers.Form.objects.select_for_update().filter(pk=kwargs['form_id']).first()
                    if stored_form and stored_form.updated_at != request.headers['X-Form-Updated-At']:
                        raise HTTPException(409, '表单已被更新，请重新打开后再保存')
                if scoped_user and name in {'get_workflow', 'put_workflow', 'publish_workflow'}:
                    stored = handlers.load_workflow(kwargs['workflow_id'])
                    if not workflow_categories(stored) <= categories:
                        raise HTTPException(403, '没有此流程分类的管理权限')
                    target = kwargs['payload'].model_dump() if name == 'put_workflow' else stored
                    if not workflow_categories(target) <= categories or not workflow_form_ids(target) <= workflow_form_ids(stored):
                        raise HTTPException(403, '不能将审批移出所管理的分类或关联其他表单')
                if scoped_user and name in {'get_form', 'put_form'}:
                    if not can_edit_category_form(kwargs['form_id'], categories):
                        if name == 'put_form':
                            raise HTTPException(403, '没有此表单的编辑权限')
                        kwargs['current_user'] = {**user, 'role': 'employee'}
                result = function(**kwargs)
                if 'admin' not in grants and name in {'list_forms', 'get_form', 'list_workflows'}:
                    def can_access(form):
                        permissions = form.get('permissions') or {}
                        return permissions.get('accessMode') != 'members' or str(request.auth_user_id) in permissions.get('members', [])
                    if name == 'get_form' and not (scoped_user and kwargs['current_user']['role'] == 'admin') and not can_access(result):
                        raise HTTPException(403, '没有此表单的访问权限')
                    if name == 'list_forms':
                        result = [form for form in result if scoped_user or can_access(form)]
                    if name == 'list_workflows':
                        result = [workflow for workflow in result if (scoped_user and workflow_categories(workflow) <= categories)
                                  or can_access((workflow.get('publishedSnapshot') or {}).get('formSchema') or {})]
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
