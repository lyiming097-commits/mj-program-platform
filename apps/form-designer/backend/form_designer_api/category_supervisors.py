from django.db import transaction

from .errors import HTTPException
from .models import CategorySupervisorState
from .organization import organization_snapshot


def serialize_state(state):
    return {'items': [{'category': category, 'supervisorUserIds': list(ids)}
                      for category, ids in sorted(state.assignments.items())],
            'revision': str(state.revision)}


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
