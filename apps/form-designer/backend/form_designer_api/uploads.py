import io
import json
import re
import uuid
import warnings

from django.http import FileResponse
from PIL import Image, UnidentifiedImageError

from .errors import HTTPException
from .models import UploadedFile, WorkflowRun, Submission

MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_FILES = 10
UPLOAD_TYPES = {'image', 'attachment'}
IMAGE_TYPES = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'GIF': 'image/gif', 'WEBP': 'image/webp'}


def file_ids(value):
    if value is None or value == '':
        return []
    if (not isinstance(value, list) or len(value) > MAX_FILES
            or any(not isinstance(item, str) or not re.fullmatch(r'[0-9a-f]{32}', item) for item in value)
            or len(set(value)) != len(value)):
        raise HTTPException(422, '附件格式不正确，每个字段最多支持 10 个文件，请重新选择文件')
    return value


def metadata(item):
    return {'id': item.id, 'name': item.name, 'size': item.size,
            'contentType': item.content_type, 'isImage': item.content_type in IMAGE_TYPES.values()}


def upload_context(workflow_id, field_id, user, run_id='', task_id=''):
    from .services import load_workflow, task_is_actionable_by_user
    if run_id:
        row = WorkflowRun.objects.filter(pk=run_id).first()
        if row is None:
            raise HTTPException(404, '审批记录不存在')
        run = json.loads(row.result_json)
        task = next((task for task in run.get('tasks', []) if task.get('id') == task_id), None)
        if (run.get('status') != 'pending' or run.get('workflowId') != workflow_id
                or not task or not task_is_actionable_by_user(task, user['username'])):
            raise HTTPException(403, '当前任务不允许上传文件')
        form = run.get('formSchema') or {}
        permissions = task.get('fieldPermissions') or []
    else:
        workflow = load_workflow(workflow_id)
        snapshot = workflow.get('publishedSnapshot')
        if not snapshot or workflow.get('deletedAt') or workflow.get('disabledAt'):
            raise HTTPException(409, '请先发布并启用流程后再上传文件')
        form = snapshot.get('formSchema') or {}
        access = form.get('permissions') or {}
        if access.get('canSubmit') is False or (access.get('accessMode') == 'members' and user['username'] not in access.get('members', [])):
            raise HTTPException(403, '当前表单不允许你发起申请')
        permissions = snapshot.get('applicantFieldPermissions') or []
    field = next((field for field in form.get('fields', []) if field.get('id') == field_id), None)
    level = next((item.get('permission') for item in permissions if item.get('fieldId') == field_id), 'editable')
    if not field or field.get('type') not in UPLOAD_TYPES or level != 'editable':
        raise HTTPException(403, '该字段不允许上传，请确认字段已发布且具有编辑权限')
    return form, field


def create_upload(request, user):
    if len(request.FILES) != 1 or len(request.FILES.getlist('file')) != 1:
        raise HTTPException(422, '请每次上传一个文件')
    file = request.FILES.get('file')
    if file is None or not file.size:
        raise HTTPException(422, '不能上传空文件')
    if file.size > MAX_FILE_SIZE:
        raise HTTPException(413, '单个文件不能超过 20 MB')
    workflow_id, field_id = request.POST.get('workflowId', ''), request.POST.get('fieldId', '')
    form, field = upload_context(workflow_id, field_id, user, request.POST.get('runId', ''), request.POST.get('taskId', ''))
    name = re.split(r'[/\\]', file.name)[-1]
    name = ''.join(char for char in name if ord(char) >= 32)[:240].strip() or '附件'
    content = file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, '单个文件不能超过 20 MB')
    content_type = 'application/octet-stream'
    # Never trust the supplied filename or MIME. Only verified raster images render inline.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                kind = image.format
                image.verify()
            content_type = IMAGE_TYPES.get(kind, 'application/octet-stream')
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        pass
    if field['type'] == 'image' and content_type not in IMAGE_TYPES.values():
        raise HTTPException(422, '请选择有效的 PNG、JPG、GIF 或 WebP 图片')
    item = UploadedFile.objects.create(id=uuid.uuid4().hex, owner_id=user['username'], workflow_id=workflow_id,
        form_id=form['id'], field_id=field_id, name=name, size=len(content), content_type=content_type, content=content)
    return metadata(item)


def visible_reference(item, user, run_id='', record_id=''):
    if run_id:
        from .services import get_approval_record
        try:
            run = get_approval_record(run_id, user)
        except HTTPException:
            return False
        return (run.get('workflowId') == item.workflow_id
                and item.id in file_ids((run.get('values') or {}).get(item.field_id)))
    if record_id and user.get('canManagePermissions') is True:
        row = Submission.objects.filter(pk=record_id, form_id=item.form_id).first()
        return row is not None and item.id in file_ids(json.loads(row.values_json).get(item.field_id))
    return not record_id and item.owner_id == user['username']


def read_upload(file_id, user, run_id='', record_id='', content=False, inline=False):
    item = UploadedFile.objects.defer('content').filter(pk=file_id).first()
    if item is None or not visible_reference(item, user, run_id, record_id):
        raise HTTPException(404, '文件不存在或没有访问权限')
    if not content:
        return metadata(item)
    response = FileResponse(io.BytesIO(bytes(item.content)), as_attachment=not (inline and item.content_type in IMAGE_TYPES.values()),
                            filename=item.name, content_type=item.content_type)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


def validate_upload_value(field, value, user, workflow_id, existing=()):
    ids = file_ids(value)
    items = {item.id: item for item in UploadedFile.objects.defer('content').filter(pk__in=ids)}
    for file_id in ids:
        item = items.get(file_id)
        if (item is None or item.workflow_id != workflow_id or item.field_id != field['id']
                or (field['type'] == 'image' and item.content_type not in IMAGE_TYPES.values())):
            raise HTTPException(422, '文件已失效或不属于当前上传字段，请重新上传')
        if item.owner_id == user['username'] or file_id in existing:
            continue
        # Recalled applications may retain files added by previous handlers.
        runs = WorkflowRun.objects.filter(workflow_id=workflow_id).values_list('id', flat=True)
        if not any(visible_reference(item, user, run_id) for run_id in runs):
            raise HTTPException(403, '不能使用其他人员未授权的文件')


def validate_record_files(form_id, values):
    from .models import Form
    row = Form.objects.filter(pk=form_id).first()
    fields = json.loads(row.schema_json).get('fields', []) if row else []
    for field in fields:
        if field.get('type') in UPLOAD_TYPES:
            ids = file_ids(values.get(field['id']))
            if UploadedFile.objects.filter(pk__in=ids, form_id=form_id, field_id=field['id']).count() != len(ids):
                raise HTTPException(422, '记录中的文件不属于当前表单字段')
