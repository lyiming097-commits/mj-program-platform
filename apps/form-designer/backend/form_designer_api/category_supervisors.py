import json

from django.db import transaction

from .errors import HTTPException
from .models import CategorySupervisorState
from .organization import organization_snapshot
from .repositories import WorkflowRepository, utc_now


DEFAULT_CATEGORIES = ('销售流程', '商务流程', '售前流程', '采购流程', '行政流程', '人事流程', '财务流程', '产品流程', '常用流程')


def category_key(value):
    return str(value or '').strip() or '常用流程'


def workflow_categories(workflow):
    categories = {category_key(workflow.get('category'))}
    if workflow.get('publishedSnapshot'):
        categories.add(category_key(workflow['publishedSnapshot'].get('category')))
    return categories


def effective_category(workflow):
    return category_key((workflow.get('publishedSnapshot') or workflow).get('category'))


def recycled_categories():
    state = CategorySupervisorState.objects.filter(pk=1).first()
    return state.deleted_categories if state else {}


def workflow_form_ids(workflow):
    return {form_id for form_id in [
        (workflow.get('publishedSnapshot') or {}).get('formId'),
        *(node.get('formId') for node in workflow.get('nodes', []) if node.get('type') == 'start'),
    ] if form_id}


def can_edit_category_form(form_id, categories):
    linked = [workflow for row in WorkflowRepository.list_schemas()
              if form_id in workflow_form_ids(workflow := json.loads(row[0]))]
    return bool(linked) and all(workflow_categories(workflow) <= categories for workflow in linked)


def managed_categories(user_id):
    state = CategorySupervisorState.objects.filter(pk=1).first()
    return [key for key, ids in state.administrators.items() if key not in state.deleted_categories and user_id in ids] if state else []


def category_keys(state):
    return list(dict.fromkeys([
        *DEFAULT_CATEGORIES,
        *(state.names if state else {}),
        *(state.assignments if state else {}),
        *(category for row in WorkflowRepository.list_schemas() for category in sorted(workflow_categories(json.loads(row[0])))),
    ]))


def list_categories(state=None, include_deleted=False):
    if state is None:
        state = CategorySupervisorState.objects.filter(pk=1).first()
    archived = state.deleted_categories if state else {}
    return [
        {'key': key, 'name': state.names.get(key, key) if state else key,
         **({'deletedAt': archived[key]} if key in archived else {})}
        for key in category_keys(state) if include_deleted or key not in archived
    ]


def serialize_state(state):
    return {'items': [{'category': category, 'supervisorUserIds': list(ids)}
                      for category, ids in sorted(state.assignments.items())],
            'revision': str(state.revision)}


def category_settings():
    state = CategorySupervisorState.objects.filter(pk=1).first()
    return {
        'items': [
            {**item,
             'administratorUserIds': state.administrators.get(item['key'], []) if state else [],
             'supervisorUserIds': state.assignments.get(item['key'], []) if state else []}
            for item in list_categories(state)
        ],
        'revision': str(state.revision) if state else '1',
    }


def save_category(payload):
    name = payload.get('name')
    key = payload.get('key')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40 or name.strip() in {'全部流程', '独立表单'}:
        raise HTTPException(422, '请填写有效的流程名称，最多40个字')
    name = name.strip()
    _departments, employees, org_revision = organization_snapshot(refresh=True)
    if str(payload.get('orgRevision', '')) != str(org_revision):
        raise HTTPException(409, '组织架构已变化，请刷新后重新确认（ORG_REVISION_CONFLICT）')
    users = {str(item.get('userId', item.get('id', ''))) for item in employees}
    with transaction.atomic():
        state, _created = CategorySupervisorState.objects.select_for_update().get_or_create(pk=1)
        if str(payload.get('revision', '')) != str(state.revision):
            raise HTTPException(409, '流程设置已变化，请刷新后重新确认（REVISION_CONFLICT）')
        keys = category_keys(state)
        if key is not None and (not isinstance(key, str) or key not in keys):
            raise HTTPException(404, '该流程分类不存在')
        if key in state.deleted_categories:
            raise HTTPException(409, '请先恢复该分组再修改设置')
        if any(existing != key and name.casefold() in {existing.casefold(), state.names.get(existing, existing).casefold()} for existing in keys):
            raise HTTPException(422, '该流程名称已存在')
        key = key or name
        for field, config in [('administratorUserIds', state.administrators), ('supervisorUserIds', state.assignments)]:
            ids = payload.get(field)
            if not isinstance(ids, list) or len(ids) > 50 or any(not isinstance(user, str) or not user or user not in users | set(config.get(key, [])) for user in ids):
                raise HTTPException(422, '请选择有效的人员，最多50人')
            config[key] = list(dict.fromkeys(ids))
        state.names[key] = name
        state.revision += 1
        state.save(update_fields=['names', 'administrators', 'assignments', 'revision'])
    return {'key': key, 'name': name}


def change_category_status(payload):
    key, action = payload.get('key'), payload.get('action')
    if not isinstance(key, str) or not key or action not in ('delete', 'restore'):
        raise HTTPException(422, '请选择有效的分组操作')
    state, _created = CategorySupervisorState.objects.select_for_update().get_or_create(pk=1)
    if key not in category_keys(state):
        raise HTTPException(404, '该流程分组不存在')
    archived = state.deleted_categories
    if action == 'delete' and key not in archived:
        if str(payload.get('revision', '')) != str(state.revision):
            raise HTTPException(409, '分组设置已变化，请重新打开后再删除')
        archived[key] = utc_now()
    elif action == 'restore' and key in archived:
        del archived[key]
    else:
        return {'key': key, 'name': state.names.get(key, key), 'deletedAt': archived.get(key)}
    state.revision += 1
    state.save(update_fields=['deleted_categories', 'revision'])
    return {'key': key, 'name': state.names.get(key, key), 'deletedAt': archived.get(key)}


def get_supervisors():
    state = CategorySupervisorState.objects.filter(pk=1).first()
    return serialize_state(state) if state else {'items': [], 'revision': '1'}


def save_supervisors(payload):
    _departments, employees, org_revision = organization_snapshot(refresh=True)
    if str(payload.get('orgRevision', '')) != str(org_revision):
        raise HTTPException(409, '组织架构已变化，请刷新后重新确认（ORG_REVISION_CONFLICT）')
    category = payload.get('category')
    if not isinstance(category, str) or not category.strip() or len(category.strip()) > 40:
        raise HTTPException(400, '流程分类不能为空且不能超过40个字')
    category = category.strip()
    ids = payload.get('supervisorUserIds')
    if not isinstance(ids, list) or len(ids) > 50 or any(not isinstance(value, str) for value in ids):
        raise HTTPException(400, '请选择有效主管，最多50人')
    users = {str(item.get('userId', item.get('id', ''))) for item in employees}
    if any(not value or value not in users for value in ids):
        raise HTTPException(400, '主管必须使用当前Auth目录中有效的userId，请重新选择')
    ids = list(dict.fromkeys(ids))
    with transaction.atomic():
        state, _created = CategorySupervisorState.objects.select_for_update().get_or_create(pk=1)
        if str(payload.get('revision', '')) != str(state.revision):
            raise HTTPException(409, '分类主管已被其他人修改，请刷新后重新确认（REVISION_CONFLICT）')
        if ids:
            state.assignments[category] = ids
        else:
            state.assignments.pop(category, None)
        state.revision += 1
        state.save(update_fields=['assignments', 'revision'])
    return {**serialize_state(state), 'orgRevision': org_revision}


def resolve_category_supervisors(category, users):
    category = str(category or '').strip() or '常用流程'
    state = CategorySupervisorState.objects.filter(pk=1).first()
    ids = list(state.assignments.get(category, [])) if state else []
    if not ids:
        raise HTTPException(422, f'“{category}”尚未设置分类主管，请联系管理员设置')
    active = {user['username'] for user in users}
    if any(user_id not in active for user_id in ids):
        raise HTTPException(422, f'“{category}”的分类主管已离职或不可用，请联系管理员重新设置')
    return ids
