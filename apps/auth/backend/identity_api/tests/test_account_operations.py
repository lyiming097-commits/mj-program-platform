import json
from unittest.mock import patch

from django.test import TestCase

from identity_api.auth.session import create_auth_session_token
from identity_api.auth.tokens import AUTH_COOKIE_NAME
from identity_api.models import Employee, OrganizationAccountOperation, OrganizationState


class AccountOperationTests(TestCase):
    def setUp(self):
        self.client.defaults['HTTP_SEC_FETCH_SITE'] = 'same-origin'
        self.admin = Employee.objects.create(user_id='admin', name='测试管理员')
        self.actor = Employee.objects.create(user_id='actor', name='测试操作者')
        self.member = Employee.objects.create(user_id='member', name='测试成员')
        self.disabled = Employee.objects.create(user_id='disabled', name='已禁用成员', account_status='禁用')
        self.inactive = Employee.objects.create(user_id='inactive', name='离职成员', status='离职', account_status='禁用')
        self.mini = Employee.objects.create(user_id='mini', name='小程序成员', identity_source='wechat-mini')
        OrganizationState.objects.update_or_create(state_id=1, defaults={'revision': 5})
        self.whitelist = patch('identity_api.org.queries.FULL_ACCESS_USER_IDS', {'admin', 'actor'})
        self.whitelist.start()
        self.addCleanup(self.whitelist.stop)
        self.authenticate(self.admin)

    def authenticate(self, user, actor=None):
        self.client.cookies[AUTH_COOKIE_NAME] = create_auth_session_token(user, actor_employee=actor)['token']

    def preview(self, status='禁用', user_id=''):
        return self.client.get('/api/org/account-status/preview', {'accountStatus': status, 'userId': user_id})

    def change(self, payload, user_id=''):
        path = f'/api/org/employees/{user_id}/account-status' if user_id else '/api/org/employees/account-status/bulk'
        return self.client.post(path, json.dumps(payload), content_type='application/json')

    def test_preview_matches_bulk_scope_and_warns_of_own_session(self):
        response = self.preview()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 3)
        self.assertTrue(response.json()['affectsCurrentAccount'])
        self.assertEqual(self.preview('启用').json()['count'], 1)
        self.assertFalse(OrganizationAccountOperation.objects.exists())

    def test_single_change_records_actor_effective_user_and_before_after(self):
        self.authenticate(self.admin, self.actor)
        token = self.preview(user_id='member').json()['confirmationToken']
        response = self.change({'accountStatus': '禁用', 'confirmationToken': token}, 'member')
        self.assertEqual(response.status_code, 200, response.content)
        record = OrganizationAccountOperation.objects.get()
        self.assertEqual((record.actor_user_id, record.effective_user_id), ('actor', 'admin'))
        self.assertEqual(record.changes, [{'userId': 'member', 'name': '测试成员', 'before': '启用', 'after': '禁用'}])
        self.assertEqual(record.scope, 'employee')
        self.member.refresh_from_db()
        self.assertEqual(self.member.account_status, '禁用')
        self.assertEqual(response.json()['orgRevision'], 6)
        self.assertEqual(self.client.get('/api/org/account-operations').json()['total'], 1)

    def test_bulk_change_uses_preview_and_excludes_inactive_and_mini(self):
        token = self.preview().json()['confirmationToken']
        response = self.change({'accountStatus': '禁用', 'confirmationToken': token})
        self.assertEqual(response.status_code, 200, response.content)
        record = OrganizationAccountOperation.objects.get()
        self.assertEqual({item['userId'] for item in record.changes}, {'admin', 'actor', 'member'})
        self.mini.refresh_from_db()
        self.assertEqual(self.mini.account_status, '启用')

    def test_scope_change_after_preview_rejects_without_mutation(self):
        token = self.preview().json()['confirmationToken']
        Employee.objects.create(user_id='new-member', name='新增成员')
        response = self.change({'accountStatus': '禁用', 'confirmationToken': token})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'ACCOUNT_PREVIEW_CHANGED')
        self.member.refresh_from_db()
        self.assertEqual(self.member.account_status, '启用')
        self.assertFalse(OrganizationAccountOperation.objects.exists())

    def test_confirmation_cannot_be_reused_for_another_target_or_action(self):
        token = self.preview(user_id='member').json()['confirmationToken']
        self.assertEqual(self.change({'accountStatus': '禁用', 'confirmationToken': token}, 'actor').status_code, 409)
        self.assertEqual(self.change({'accountStatus': '启用', 'confirmationToken': token}, 'member').status_code, 409)
        self.assertEqual(self.change({'accountStatus': '禁用', 'confirmationToken': 'tampered'}, 'member').status_code, 409)
        self.assertFalse(OrganizationAccountOperation.objects.exists())

    def test_expired_preview_requires_reconfirmation(self):
        token = self.preview(user_id='member').json()['confirmationToken']
        with patch('django.core.signing.time.time', return_value=9999999999):
            # Use the validator directly so the separate login token remains unaffected.
            from identity_api.org.account_operations import validate_preview
            from django.test import RequestFactory
            request = RequestFactory().post('/')
            request.auth_user_id = 'admin'
            request.auth_actor_user_id = 'admin'
            response = validate_preview(request, {'confirmationToken': token}, '禁用', 'member', [self.member])
        self.assertEqual(response.status_code, 409)

    def test_noop_and_legacy_mobile_write(self):
        self.assertEqual(self.change({'accountStatus': '禁用'}, 'member').status_code, 200)
        self.assertEqual(self.change({'accountStatus': '禁用'}, 'member').status_code, 200)
        self.assertEqual(OrganizationAccountOperation.objects.count(), 1)
        self.assertEqual(self.preview(user_id='member').json()['count'], 0)
        self.assertEqual(self.preview('启用', 'inactive').status_code, 400)

    def test_non_admin_and_proxy_to_member_cannot_preview_change_or_read_records(self):
        for actor in [None, self.admin]:
            self.authenticate(self.member, actor)
            self.assertEqual(self.preview().status_code, 403)
            self.assertEqual(self.change({'accountStatus': '禁用'}, 'actor').status_code, 403)
            self.assertEqual(self.client.get('/api/org/account-operations').status_code, 403)
        self.assertFalse(OrganizationAccountOperation.objects.exists())

    def test_failed_write_rolls_back_accounts_and_operation_record(self):
        for user_id in ['member', '']:
            token = self.preview(user_id=user_id).json()['confirmationToken']
            with patch('identity_api.org.views._advance_request_organization_revision', side_effect=RuntimeError('test rollback')):
                with self.assertRaises(RuntimeError):
                    self.change({'accountStatus': '禁用', 'confirmationToken': token}, user_id)
            self.member.refresh_from_db()
            self.admin.refresh_from_db()
            self.assertEqual(self.member.account_status, '启用')
            self.assertEqual(self.admin.account_status, '启用')
            self.assertFalse(OrganizationAccountOperation.objects.exists())
