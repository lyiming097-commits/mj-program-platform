import json
import uuid
from datetime import datetime, timezone
from django.db import IntegrityError
from .errors import HTTPException
from .repositories import FormRepository, SubmissionRepository, WorkflowRepository, WorkflowRunRepository, utc_now
from .organization import routing_users
from .schemas import ApprovalCreatePayload, FormPayload, RecordPayload, TaskActionPayload, WorkflowPayload, WorkflowRunPayload
from .services import (
    list_all_workflow_runs as list_all_workflow_runs_service,
    list_my_workflow_runs as list_my_workflow_runs_service, list_task_history, list_task_inbox,
    load_form, load_workflow, normalize_form_schema, normalize_workflow_schema, perform_task_action,
    publish_workflow as publish_workflow_service, seed_form, seed_workflow, recall_workflow_run,
    start_workflow_run as start_workflow_run_service, preview_workflow_run, list_approval_records, get_approval_record,
)


def seed_sample_records(form_id: str) -> None:
    pass


def serialize_record(row: tuple) -> dict:
    record_id, form_id, title, applicant, values_json, created_at, updated_at, deleted_at = row
    return {'id': record_id, 'formId': form_id, 'title': title, 'applicant': applicant, 'values': json.loads(values_json), 'createdAt': created_at, 'updatedAt': updated_at, 'deletedAt': deleted_at}


def list_form_records(form_id: str, current_user: dict, recycle: bool=False) -> list[dict]:
    seed_sample_records(form_id)
    rows = SubmissionRepository.list_records(form_id, recycle)
    return [serialize_record(row) for row in rows]


def create_form_record(form_id: str, payload: RecordPayload, current_user: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    record_id = uuid.uuid4().hex
    SubmissionRepository.create_record(record_id, form_id, payload.title, payload.applicant, json.dumps(payload.values, ensure_ascii=False), now)
    return {'id': record_id, 'formId': form_id, **payload.model_dump(), 'createdAt': now, 'updatedAt': now, 'deletedAt': None}


def update_form_record(form_id: str, record_id: str, payload: RecordPayload, current_user: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    row = SubmissionRepository.update_record(record_id, form_id, payload.title, payload.applicant, json.dumps(payload.values, ensure_ascii=False), now)
    if row is None:
        raise HTTPException(status_code=404, detail='记录不存在')
    return serialize_record(row)


def delete_form_record(form_id: str, record_id: str, current_user: dict, permanent: bool=False) -> dict:
    if not SubmissionRepository.delete_record(record_id, form_id, permanent, utc_now()):
        raise HTTPException(status_code=404, detail='记录不存在或状态不匹配')
    return {'ok': True}


def restore_form_record(form_id: str, record_id: str, current_user: dict) -> dict:
    row = SubmissionRepository.restore_record(record_id, form_id, utc_now())
    if row is None:
        raise HTTPException(status_code=404, detail='回收站中未找到记录')
    return serialize_record(row)


def list_forms(current_user: dict) -> list[dict]:
    rows = FormRepository.list_schemas()
    forms = [normalize_form_schema(json.loads(row[0])) for row in rows]
    if not any((form['id'] == 'sample' for form in forms)):
        forms.append(seed_form())
    if current_user['role'] != 'admin':
        workflow_rows = WorkflowRepository.list_schemas()
        published_form_ids = {(json.loads(row[0]).get('publishedSnapshot') or {}).get('formId') for row in workflow_rows}
        forms = []
        for form_id in published_form_ids:
            if not form_id:
                continue
            try:
                forms.append(load_form(form_id, current_user))
            except HTTPException as error:
                if error.status_code not in {403, 404}:
                    raise
    return forms


def get_form(form_id: str, current_user: dict) -> dict:
    return load_form(form_id, current_user)


def put_form(form_id: str, payload: FormPayload, current_user: dict) -> dict:
    if form_id != payload.id:
        raise HTTPException(status_code=400, detail='表单 ID 不匹配')
    result = payload.model_dump()
    result['updatedAt'] = datetime.now(timezone.utc).isoformat()
    FormRepository.save_schema(form_id, result)
    return result


def list_workflows(current_user: dict, recycle: bool = False) -> list[dict]:
    if recycle and current_user.get('canManagePermissions') is not True:
        raise HTTPException(status_code=403, detail='只有应用管理员可以查看流程回收站')
    rows = WorkflowRepository.list_schemas()
    if not rows:
        return [seed_workflow()] if current_user['role'] == 'admin' and not recycle else []
    workflows = [normalize_workflow_schema(json.loads(row[0])) for row in rows]
    workflows = [workflow for workflow in workflows if bool(workflow.get('deletedAt')) == recycle]
    if current_user['role'] != 'admin':
        published_workflows = []
        for workflow in workflows:
            snapshot = workflow.get('publishedSnapshot')
            if not snapshot or workflow.get('deletedAt'):
                continue
            applicant_permissions = snapshot.get('applicantFieldPermissions') or []
            hidden_field_ids = {item.get('fieldId') for item in applicant_permissions if item.get('permission') == 'hidden'}
            form_schema = snapshot.get('formSchema')
            if not form_schema and snapshot.get('formId'):
                form_schema = load_form(snapshot['formId'], current_user)
            if form_schema:
                form_schema = {**form_schema, 'fields': [field for field in form_schema.get('fields') or [] if field.get('id') not in hidden_field_ids]}
            published_workflows.append({'id': workflow['id'], 'name': snapshot.get('name', workflow['name']), 'nodes': [], 'disabledAt': workflow.get('disabledAt'), 'deletedAt': None, 'publishedAt': workflow.get('publishedAt'), 'publishedVersion': snapshot.get('version', workflow.get('publishedVersion', 0)), 'publishedSnapshot': {'name': snapshot.get('name', workflow['name']), 'category': snapshot.get('category') or workflow.get('category') or '常用流程', 'formId': snapshot.get('formId'), 'formSchema': form_schema, 'version': snapshot.get('version', workflow.get('publishedVersion', 0)), 'nodes': [], 'applicantFieldPermissions': applicant_permissions}, 'updatedAt': workflow.get('updatedAt')})
        workflows = published_workflows
    return workflows


def get_workflow(workflow_id: str, current_user: dict) -> dict:
    workflow = load_workflow(workflow_id)
    if workflow.get('deletedAt'):
        raise HTTPException(status_code=410, detail='流程已删除，只能查看历史记录')
    return workflow


def create_workflow(payload: WorkflowPayload, current_user: dict) -> dict:
    result = normalize_workflow_schema(payload.model_dump())
    result['updatedAt'] = datetime.now(timezone.utc).isoformat()
    try:
        WorkflowRepository.create_schema(result)
    except IntegrityError as error:
        raise HTTPException(status_code=409, detail='工作流 ID 已存在') from error
    return result


def put_workflow(workflow_id: str, payload: WorkflowPayload, current_user: dict) -> dict:
    if workflow_id != payload.id:
        raise HTTPException(status_code=400, detail='工作流 ID 不匹配')
    result = normalize_workflow_schema(payload.model_dump())
    result['updatedAt'] = datetime.now(timezone.utc).isoformat()
    previous = WorkflowRepository.get_schema(workflow_id)
    if previous:
        stored = json.loads(previous[0])
        if stored.get('deletedAt'):
            raise HTTPException(status_code=410, detail='流程已删除，不能编辑')
        for key in ('publishedAt', 'publishedVersion', 'publishedSnapshot', 'disabledAt', 'deletedAt'):
            result[key] = stored.get(key)
        result['publishedVersion'] = result.get('publishedVersion') or 0
    WorkflowRepository.save_schema(workflow_id, result)
    return result


def change_workflow_status(workflow_id: str, current_user: dict, action: str) -> dict:
    if current_user.get('canManagePermissions') is not True:
        raise HTTPException(status_code=403, detail='只有应用管理员可以管理流程状态')
    schema = load_workflow(workflow_id)
    if action == 'restore':
        if not schema.get('deletedAt'):
            raise HTTPException(status_code=409, detail='流程不在回收站，请刷新列表')
    elif schema.get('deletedAt'):
        raise HTTPException(status_code=410, detail='流程已移入回收站，请先恢复')
    now = utc_now()
    if action == 'restore':
        schema['deletedAt'] = None
    elif action == 'delete':
        schema['deletedAt'] = now
    elif action == 'disable':
        schema['disabledAt'] = schema.get('disabledAt') or now
    elif action == 'enable':
        if not schema.get('publishedSnapshot'):
            raise HTTPException(status_code=409, detail='请先发布流程，再启用')
        schema['disabledAt'] = None
    schema['updatedAt'] = now
    WorkflowRepository.save_schema(workflow_id, schema)
    return schema


def disable_workflow(workflow_id: str, current_user: dict) -> dict:
    return change_workflow_status(workflow_id, current_user, 'disable')


def enable_workflow(workflow_id: str, current_user: dict) -> dict:
    return change_workflow_status(workflow_id, current_user, 'enable')


def delete_workflow(workflow_id: str, current_user: dict) -> dict:
    return change_workflow_status(workflow_id, current_user, 'delete')


def restore_workflow(workflow_id: str, current_user: dict) -> dict:
    return change_workflow_status(workflow_id, current_user, 'restore')


def publish_workflow(workflow_id: str, current_user: dict) -> dict:
    return publish_workflow_service(workflow_id, current_user)


def start_workflow_run(workflow_id: str, payload: WorkflowRunPayload, current_user: dict) -> dict:
    return start_workflow_run_service(workflow_id, payload, current_user)


def list_workflow_runs(workflow_id: str, current_user: dict) -> list[dict]:
    rows = WorkflowRunRepository.list_for_workflow(workflow_id)
    return [json.loads(row[0]) for row in rows]


def list_my_workflow_runs(current_user: dict) -> list[dict]:
    return list_my_workflow_runs_service(current_user)


def list_all_workflow_runs(current_user: dict) -> list[dict]:
    return list_all_workflow_runs_service()


def task_inbox(current_user: dict) -> list[dict]:
    return list_task_inbox(current_user)


def task_history(current_user: dict) -> list[dict]:
    return list_task_history(current_user)


def act_on_task(run_id: str, task_id: str, payload: TaskActionPayload, current_user: dict) -> dict:
    return perform_task_action(run_id, task_id, payload, current_user)

def create_approval(payload: ApprovalCreatePayload, current_user: dict) -> dict:
    if current_user.get("canManagePermissions") is not True:
        raise HTTPException(status_code=403, detail="只有应用管理员可以新建审批")
    assignees = list(dict.fromkeys(payload.assignees))
    valid_ids = {user["username"] for user in routing_users()}
    if not assignees or any(user_id not in valid_ids for user_id in assignees):
        raise HTTPException(status_code=422, detail="请选择有效的审批人")
    form_id, workflow_id = "form-" + uuid.uuid4().hex, "flow-" + uuid.uuid4().hex
    now = utc_now()
    form = FormPayload(id=form_id, name=payload.name.strip(), description=payload.description.strip(), fields=[
        {"id": "reason", "type": "textarea", "label": "申请事由", "required": True,
         "placeholder": "请填写申请事由", "width": "full", "options": []},
    ]).model_dump()
    form["updatedAt"] = now
    workflow = normalize_workflow_schema(WorkflowPayload(id=workflow_id, name=payload.name.strip() + "审批流程", category=payload.category.strip(), nodes=[
        {"id": "start", "type": "start", "name": "发起申请", "formId": form_id},
        {"id": "approval", "type": "approval", "name": "审批人审批", "assigneeMode": "specified", "assignees": assignees,
         "fieldPermissions": [], "approvalMode": "sequential"},
        {"id": "end", "type": "end", "name": "流程结束"},
    ]).model_dump())
    workflow["updatedAt"] = now
    FormRepository.save_schema(form_id, form)
    WorkflowRepository.create_schema(workflow)
    return {"form": form, "workflow": workflow}
