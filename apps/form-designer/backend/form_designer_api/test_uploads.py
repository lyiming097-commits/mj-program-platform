import io
import json
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TransactionTestCase
from PIL import Image

from . import services, views
from .errors import HTTPException
from .models import Form, UploadedFile, Workflow, WorkflowRun
from .schemas import RecordPayload, TaskActionPayload, WorkflowRunPayload


class UploadTests(TransactionTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.owner = {'username': 'employee-a', 'displayName': '申请人', 'role': 'employee'}
        self.approver = {'username': 'approver', 'displayName': '审批人', 'role': 'manager'}
        self.other = {'username': 'employee-b', 'displayName': '其他人', 'role': 'employee'}
        self.form = {'id': 'upload-form', 'name': '上传测试', 'fields': [
            {'id': 'title', 'type': 'text', 'label': '标题'},
            {'id': 'photo', 'type': 'image', 'label': '图片'},
            {'id': 'files', 'type': 'attachment', 'label': '附件'},
        ], 'permissions': {'canSubmit': True, 'accessMode': 'all'}}
        self.schema = {'id': 'upload-workflow', 'name': '上传测试', 'category': '常用流程',
            'publishedSnapshot': {'version': 1, 'name': '上传测试', 'formId': self.form['id'], 'formSchema': self.form,
                'nodes': [{'id': 'start', 'type': 'start', 'formId': self.form['id']},
                          {'id': 'approve', 'type': 'approval', 'name': '审批', 'assigneeMode': 'specified',
                           'assignees': ['approver'], 'approvalMode': 'sequential',
                           'approvalButtons': [{'key': 'agree', 'enabled': True}], 'fieldPermissions': []},
                          {'id': 'end', 'type': 'end'}]}}
        self.save_schema()
        Form.objects.create(id=self.form['id'], schema_json=json.dumps(self.form), updated_at='now')
        users = patch('form_designer_api.services.UserRepository.list_active_for_routing', return_value=[('approver', '审批人', 'manager', '', None)])
        users.start()
        self.addCleanup(users.stop)
        image = io.BytesIO()
        Image.new('RGB', (8, 8), '#1888ff').save(image, format='PNG')
        self.png = image.getvalue()

    def save_schema(self):
        Workflow.objects.update_or_create(id=self.schema['id'], defaults={'schema_json': json.dumps(self.schema), 'updated_at': 'now'})

    def request(self, resource, user=None, data=None, grants=None, query=None):
        request = self.factory.post('/api/form-designer/' + resource, data=data) if data is not None else self.factory.get('/api/form-designer/' + resource, data=query or {})
        user = user or self.owner
        request.auth_user_id = user['username']
        with patch.object(views, 'capabilities', return_value={'user'} if grants is None else grants), patch.object(views, 'current_user', return_value=user):
            return views.endpoint(request, resource)

    def upload(self, field='files', data=b'attachment content', name='测试附件.txt', user=None, **context):
        return self.request('uploads', user, {'file': SimpleUploadedFile(name, data, content_type='image/png' if field == 'photo' else 'application/octet-stream'),
            'workflowId': self.schema['id'], 'fieldId': field, **context})

    def uploaded(self, **kwargs):
        response = self.upload(**kwargs)
        self.assertEqual(response.status_code, 201, response.content)
        return json.loads(response.content)

    def start(self, **values):
        return services.start_workflow_run(self.schema['id'], WorkflowRunPayload(values=values), self.owner)

    def test_attachment_and_image_are_persisted_with_exact_bytes_and_chinese_names(self):
        attachment = self.uploaded()
        image = self.uploaded(field='photo', data=self.png, name='截图.png')
        self.assertFalse(attachment['isImage'])
        self.assertEqual(image['contentType'], 'image/png')
        self.assertEqual(image['size'], len(self.png))
        run = self.start(title='文件申请', files=[attachment['id']], photo=[image['id']])
        response = self.request('uploads/' + attachment['id'] + '/content', query={'runId': run['id']})
        self.assertEqual(b''.join(response.streaming_content), b'attachment content')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('%E6%B5%8B%E8%AF%95', response['Content-Disposition'])
        response = self.request('uploads/' + image['id'] + '/content', self.approver, query={'runId': run['id'], 'inline': 'true'})
        self.assertEqual(b''.join(response.streaming_content), self.png)
        self.assertIn('inline;', response['Content-Disposition'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(bytes(UploadedFile.objects.get(pk=image['id']).content), self.png)

    def test_unrelated_user_cannot_read_metadata_or_download_guessing_ids(self):
        item = self.uploaded()
        run = self.start(files=[item['id']])
        for suffix in ['', '/content']:
            for query in [{}, {'runId': run['id']}]:
                self.assertEqual(self.request('uploads/' + item['id'] + suffix, self.other, query=query).status_code, 404)

    def test_hidden_field_cannot_download_even_if_user_is_current_handler(self):
        self.schema['publishedSnapshot']['nodes'][1]['fieldPermissions'] = [{'fieldId': 'files', 'permission': 'hidden'}]
        self.save_schema()
        item = self.uploaded()
        run = self.start(files=[item['id']])
        self.assertEqual(self.request('uploads/' + item['id'], self.approver, query={'runId': run['id']}).status_code, 404)
        self.assertEqual(self.request('uploads/' + item['id'] + '/content', self.approver, query={'runId': run['id']}).status_code, 404)

    def test_upload_requires_app_access_editable_upload_field_and_enabled_published_workflow(self):
        self.assertEqual(self.request('uploads', data={'file': SimpleUploadedFile('a.txt', b'a')}, grants=set()).status_code, 403)
        self.assertEqual(self.upload(field='title').status_code, 403)
        self.schema['publishedSnapshot']['applicantFieldPermissions'] = [{'fieldId': 'files', 'permission': 'readonly'}]
        self.save_schema()
        self.assertEqual(self.upload().status_code, 403)
        self.schema['disabledAt'] = 'now'
        self.save_schema()
        self.assertEqual(self.upload().status_code, 409)
        self.schema.pop('disabledAt')
        self.schema['publishedSnapshot'] = None
        self.save_schema()
        self.assertEqual(self.upload().status_code, 409)

    def test_access_members_are_checked(self):
        self.form['permissions']['accessMode'] = 'members'
        self.form['permissions']['members'] = ['approver']
        self.save_schema()
        self.assertEqual(self.upload().status_code, 403)

    def test_invalid_images_empty_and_oversize_files_rejected_without_storing(self):
        for content in [b'fake PNG', b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>']:
            self.assertEqual(self.upload(field='photo', data=content, name='fake.png').status_code, 422)
        self.assertEqual(self.upload(data=b'').status_code, 422)
        with patch('form_designer_api.uploads.MAX_FILE_SIZE', 3):
            self.assertEqual(self.upload(data=b'1234').status_code, 413)
        self.assertEqual(UploadedFile.objects.count(), 0)

    def test_active_content_is_forced_to_download(self):
        item = self.uploaded(data=b'<script>alert(1)</script>', name='page.html')
        self.assertEqual(item['contentType'], 'application/octet-stream')
        response = self.request('uploads/' + item['id'] + '/content', query={'inline': 'true'})
        self.assertIn('attachment;', response['Content-Disposition'])
        response.close()

    def test_submission_rejects_invalid_missing_other_field_and_other_owner_files(self):
        other_file = self.uploaded(user=self.other)
        photo = self.uploaded(field='photo', data=self.png)
        for values, code in [({'files': ['0' * 32]}, 422), ({'files': 'a.txt'}, 422),
                             ({'files': [photo['id']]}, 422), ({'files': [other_file['id']]}, 403),
                             ({'files': ['0' * 32] * 11}, 422)]:
            with self.assertRaises(HTTPException) as error:
                self.start(**values)
            self.assertEqual(error.exception.status_code, code)
        self.assertEqual(WorkflowRun.objects.count(), 0)

    def test_required_upload_field_is_enforced(self):
        self.form['fields'][2]['required'] = True
        self.save_schema()
        with self.assertRaises(HTTPException):
            self.start(files=[])

    def test_current_handler_can_add_files_and_submit_but_readonly_and_unrelated_cannot(self):
        item = self.uploaded()
        run = self.start(files=[item['id']])
        task = run['tasks'][0]
        context = {'runId': run['id'], 'taskId': task['id']}
        self.assertEqual(self.upload(user=self.other, **context).status_code, 403)
        added = self.uploaded(user=self.approver, name='审批补充.txt', **context)
        services.perform_task_action(run['id'], task['id'], TaskActionPayload(action='agree', values={'files': [item['id'], added['id']]}), self.approver)
        self.assertEqual(self.request('uploads/' + added['id'], query={'runId': run['id']}).status_code, 200)
        self.assertEqual(self.upload(user=self.approver, **context).status_code, 403)

    def test_readonly_task_field_rejects_upload(self):
        self.schema['publishedSnapshot']['nodes'][1]['fieldPermissions'] = [{'fieldId': 'files', 'permission': 'readonly'}]
        self.save_schema()
        run = self.start()
        self.assertEqual(self.upload(user=self.approver, runId=run['id'], taskId=run['tasks'][0]['id']).status_code, 403)

    def test_copy_recipient_obeys_own_field_permissions_for_file_access(self):
        self.schema['publishedSnapshot']['nodes'][1] = {'id': 'copy', 'type': 'cc', 'name': '抄送',
            'assigneeMode': 'specified', 'assignees': ['approver'], 'fieldPermissions': [{'fieldId': 'files', 'permission': 'hidden'}]}
        self.save_schema()
        item = self.uploaded()
        image = self.uploaded(field='photo', data=self.png)
        run = self.start(files=[item['id']], photo=[image['id']])
        self.assertEqual(self.request('uploads/' + item['id'], self.approver, query={'runId': run['id']}).status_code, 404)
        self.assertEqual(self.request('uploads/' + image['id'], self.approver, query={'runId': run['id']}).status_code, 200)

    def test_executor_can_upload_and_complete_task(self):
        self.schema['publishedSnapshot']['nodes'][1]['type'] = 'executor'
        self.save_schema()
        run = self.start()
        item = self.uploaded(user=self.approver, runId=run['id'], taskId=run['tasks'][0]['id'])
        result = services.perform_task_action(run['id'], run['tasks'][0]['id'], TaskActionPayload(action='complete', values={'files': [item['id']]}), self.approver)
        self.assertEqual(result['runStatus'], 'completed')
        self.assertEqual(self.request('uploads/' + item['id'], query={'runId': run['id']}).status_code, 200)

    def test_data_admin_can_download_record_files_and_edit_without_losing_references(self):
        from . import handlers
        item = self.uploaded()
        run = self.start(files=[item['id']])
        admin = {'username': 'admin', 'displayName': '管理员', 'role': 'admin', 'canManagePermissions': True}
        payload = RecordPayload(title='更新标题', applicant='申请人', values={'files': [item['id']]})
        saved = handlers.update_form_record(self.form['id'], run['submissionId'], payload, admin)
        self.assertEqual(saved['values']['files'], [item['id']])
        self.assertEqual(self.request('uploads/' + item['id'], admin, query={'recordId': run['submissionId']}).status_code, 200)
        self.assertEqual(self.request('uploads/' + item['id'], self.other, query={'recordId': run['submissionId']}).status_code, 404)

    def test_recalled_application_can_reuse_files_added_by_approver(self):
        item = self.uploaded()
        run = self.start(files=[item['id']])
        added = self.uploaded(user=self.approver, runId=run['id'], taskId=run['tasks'][0]['id'])
        # Existing handlers can save editable files. Simulate persisted progress before recall.
        row = WorkflowRun.objects.get(pk=run['id'])
        stored = json.loads(row.result_json)
        stored['values']['files'].append(added['id'])
        stored['status'] = 'recalled'
        row.result_json = json.dumps(stored)
        row.save(update_fields=['result_json'])
        new_run = self.start(files=[item['id'], added['id']])
        self.assertNotEqual(new_run['id'], run['id'])
        self.assertEqual(new_run['values']['files'], [item['id'], added['id']])
