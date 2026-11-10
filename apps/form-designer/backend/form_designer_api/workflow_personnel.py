import json
from copy import deepcopy

from django.db.models import Q

from .category_supervisors import category_key, list_categories
from .errors import HTTPException
from .models import CategorySupervisorState, WorkflowRun
from .organization import routing_users
from .repositories import WorkflowRepository, utc_now
from .services import load_workflow


def walk_nodes(nodes):
    for node in nodes or []:
        yield node
        for branch in node.get('branches') or []:
            yield from walk_nodes(branch.get('nodes'))


def explicit_assignees(node):
    if node.get('type') not in {'approval', 'executor', 'cc'} or node.get('assigneeMode') not in {None, '', 'specified'}:
        return []
    return node.get('assignees') or []


def category_assignees(node, category, supervisors):
    if node.get('type') == 'approval' and node.get('assigneeMode') == 'direct_manager':
        return supervisors.get(category, [])
    return []


def listed_assignees(node, category, supervisors):
    return explicit_assignees(node) or category_assignees(node, category, supervisors)


def describe_flow(workflow, supervisors, categories):
    published = workflow.get('publishedSnapshot')
    definition = published or workflow
    category = category_key(definition.get('category'))
    nodes = deepcopy(definition.get('nodes') or [])
    for node in walk_nodes(nodes):
        if node.get('type') in {'approval', 'executor', 'cc'}:
            node['assignees'] = listed_assignees(node, category, supervisors)
    return {
        'id': workflow['id'], 'name': definition.get('name') or workflow['name'],
        'category': categories.get(category, category), 'updatedAt': workflow.get('updatedAt') or '',
        'publishedVersion': (published.get('version') or workflow.get('publishedVersion') or 1) if published else None,
        'nodes': nodes,
    }


def personnel_impact(user_id):
    directory = {item['username']: {'id': item['username'], 'name': item['displayName'], 'active': True}
                 for item in routing_users()}
    state = CategorySupervisorState.objects.filter(pk=1).first()
    supervisors = state.assignments if state else {}
    categories = {item['key']: item['name'] for item in list_categories(state)}
    templates, runs, flows = [], [], []
    for row in WorkflowRepository.list_schemas():
        workflow = json.loads(row[0])
        if workflow.get('deletedAt'):
            continue
        hits = {}
        published = workflow.get('publishedSnapshot')
        current_definition = published or workflow
        current_category = category_key(current_definition.get('category'))
        if state and current_category in state.deleted_categories:
            continue
        if user_id and any(user_id in listed_assignees(node, current_category, supervisors)
                           for node in walk_nodes(current_definition.get('nodes'))):
            flows.append(describe_flow(workflow, supervisors, categories))
        draft_nodes = {node.get('id') for node in walk_nodes(workflow.get('nodes'))}
        for version, definition in [('published', published), ('draft', workflow)]:
            if not definition:
                continue
            category = category_key(definition.get('category'))
            for node in walk_nodes(definition.get('nodes')):
                explicit = explicit_assignees(node)
                derived = category_assignees(node, category, supervisors)
                for person in [*explicit, *derived]:
                    directory.setdefault(person, {'id': person, 'name': person, 'active': False})
                if not user_id or (user_id not in explicit and user_id not in derived):
                    continue
                node_id = node.get('id', '')
                hit = hits.setdefault(node_id, {
                    'workflowId': workflow['id'], 'workflowName': definition.get('name') or workflow['name'],
                    'nodeId': node_id, 'nodeName': node.get('name') or '审批节点',
                    'category': categories.get(category, category), 'categoryKey': category,
                    'updatedAt': workflow.get('updatedAt', ''), 'locatable': node_id in draft_nodes,
                    'publishedVersion': None, 'draft': False, 'replaceable': False, 'supervisor': False,
                })
                if version == 'published':
                    hit['publishedVersion'] = published.get('version') or workflow.get('publishedVersion') or 1
                else:
                    hit['draft'] = True
                    hit['replaceable'] = bool(node_id and user_id in explicit)
                hit['supervisor'] = hit['supervisor'] or user_id in derived
        templates.extend(hits.values())

    # Only open instances and tasks that still have work to do count as impact.
    open_runs = WorkflowRun.objects.filter(status__in=['pending', 'pending_assignment'])
    if user_id:
        # Narrow the scan before decoding. Exact membership is checked below.
        open_runs = open_runs.filter(Q(result_json__contains=json.dumps(user_id, ensure_ascii=False)) |
                                     Q(result_json__contains=json.dumps(user_id)))
    for raw in open_runs.order_by('-created_at').values_list('result_json', flat=True).iterator():
        run = json.loads(raw)
        impacted = []
        for task in run.get('tasks') or []:
            if task.get('status') not in {'pending', 'waiting', 'unassigned'}:
                continue
            names = task.get('assigneeNames') or []
            for index, person in enumerate(task.get('assignees') or []):
                if task.get('assigneeProgress', {}).get(person, 'pending') != 'pending':
                    continue
                name = names[index] if index < len(names) else person
                entry = directory.setdefault(person, {'id': person, 'name': name, 'active': False})
                if not entry['active'] and entry['name'] == person:
                    entry['name'] = name
                if user_id == person:
                    impacted.append({'id': task['id'], 'name': task.get('nodeName') or '审批节点', 'status': task['status']})
        if impacted:
            category = category_key(run.get('workflowCategory'))
            runs.append({'id': run['id'], 'title': run.get('title') or run.get('workflowName', ''),
                         'workflowName': run.get('workflowName', ''), 'category': categories.get(category, category),
                         'tasks': impacted})
    return {'people': sorted(directory.values(), key=lambda item: (item['active'], item['name'], item['id'])) if not user_id else [],
            'person': directory.get(user_id), 'templates': templates, 'runs': runs, 'flows': flows}


def assign_replacement(node, assignees, source, target):
    node['assigneeMode'] = 'specified'
    node['assignees'] = list(dict.fromkeys(target if person == source else person for person in assignees))
    node.pop('assigneeFieldId', None)


def replace_current_person(payload):
    workflow_id, node_id = payload.get('workflowId'), payload.get('nodeId')
    source, target = payload.get('source'), payload.get('target')
    updated_at, expected = payload.get('updatedAt'), payload.get('assignees')
    if (any(not isinstance(value, str) or not value for value in (workflow_id, node_id, source, target))
            or source == target or not isinstance(updated_at, str) or not isinstance(expected, list)):
        raise HTTPException(422, '请选择有效节点和不同的接替人员')
    if target not in {person['username'] for person in routing_users()}:
        raise HTTPException(422, '接替人员必须在当前在职目录中')
    WorkflowRepository.lock_definition(workflow_id)
    workflow = load_workflow(workflow_id)
    if workflow.get('deletedAt') or (workflow.get('updatedAt') or '') != updated_at:
        raise HTTPException(409, '流程已变更，请重新排查后再修改')

    state = CategorySupervisorState.objects.select_for_update().filter(pk=1).first()
    supervisors = state.assignments if state else {}
    published = workflow.get('publishedSnapshot')
    definition = published or workflow
    category = category_key(definition.get('category'))
    if state and category in state.deleted_categories:
        raise HTTPException(409, '请先恢复此流程所属的分组')
    matches = [node for node in walk_nodes(definition.get('nodes')) if node.get('id') == node_id]
    if len(matches) != 1:
        raise HTTPException(409, '流程节点已变更，请重新排查')
    node = matches[0]
    assignees = listed_assignees(node, category, supervisors)
    if assignees != expected or source not in assignees:
        raise HTTPException(409, '处理人已变更，请重新排查')
    if target in assignees:
        raise HTTPException(422, '接替人员已在此节点中')

    original_mode = node.get('assigneeMode') or 'specified'
    assign_replacement(node, assignees, source, target)
    now = utc_now()
    if published:
        # Update the effective snapshot without publishing unrelated editor changes.
        version = int(published.get('version') or workflow.get('publishedVersion') or 1) + 1
        published['version'] = version
        workflow['publishedVersion'] = version
        workflow['publishedAt'] = now
        draft_matches = [candidate for candidate in walk_nodes(workflow.get('nodes'))
                         if candidate.get('id') == node_id and candidate.get('type') == node.get('type')]
        if len(draft_matches) == 1:
            draft = draft_matches[0]
            draft_mode = draft.get('assigneeMode') or 'specified'
            draft_assignees = listed_assignees(draft, category_key(workflow.get('category')), supervisors)
            if source in draft_assignees and draft_mode == original_mode and (
                draft_mode == 'specified' or draft_assignees == assignees
            ):
                assign_replacement(draft, draft_assignees, source, target)
    workflow['updatedAt'] = now
    WorkflowRepository.save_schema(workflow_id, workflow)
    categories = {item['key']: item['name'] for item in list_categories(state)}
    return {'workflow': workflow, 'flow': describe_flow(workflow, supervisors, categories)}


def replace_template_person(payload):
    source, target, selections = payload.get('source'), payload.get('target'), payload.get('nodes')
    if not isinstance(source, str) or not source or not isinstance(target, str) or source == target:
        raise HTTPException(422, '请选择不同的原人员和替换人员')
    if target not in {person['username'] for person in routing_users()}:
        raise HTTPException(422, '替换人员必须在当前在职目录中')
    if not isinstance(selections, list) or not 1 <= len(selections) <= 200:
        raise HTTPException(422, '请选择1至200个待替换节点')
    grouped = {}
    for item in selections:
        if not isinstance(item, dict) or any(not isinstance(item.get(field), str) or not item[field] for field in ('workflowId', 'nodeId', 'updatedAt')):
            raise HTTPException(422, '节点选择无效，请重新排查')
        group = grouped.setdefault(item['workflowId'], {'updatedAt': item['updatedAt'], 'ids': set()})
        if group['updatedAt'] != item['updatedAt']:
            raise HTTPException(422, '节点版本不一致，请重新排查')
        group['ids'].add(item['nodeId'])
    replaced = 0
    for workflow_id in sorted(grouped):
        WorkflowRepository.lock_definition(workflow_id)
        workflow = load_workflow(workflow_id)
        group = grouped[workflow_id]
        nodes = {node['id']: node for node in walk_nodes(workflow.get('nodes')) if node.get('id') in group['ids']}
        if (workflow.get('deletedAt') or workflow.get('updatedAt') != group['updatedAt'] or
                nodes.keys() != group['ids'] or any(source not in explicit_assignees(node) for node in nodes.values())):
            raise HTTPException(409, '审批草稿已变更，请重新排查后再替换')
        for node in nodes.values():
            node['assignees'] = list(dict.fromkeys(target if person == source else person for person in node['assignees']))
        workflow['updatedAt'] = utc_now()
        WorkflowRepository.save_schema(workflow_id, workflow)
        replaced += len(nodes)
    return {'replaced': replaced}
