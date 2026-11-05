import copy
from contextlib import ExitStack
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase

from identity_api.dingtalk.client import DingTalkAPIError
from identity_api.models import Department, DepartmentEmployee, DepartmentManager, Employee, OrganizationState
from identity_api.org.sync import sync_organization_contacts


class OrganizationSyncRevisionTests(TestCase):
    def setUp(self):
        self.departments = {
            1: {'dept_id': 1, 'name': '公司', 'parent_id': None, 'dept_manager_userid_list': ['u1']},
            2: {'dept_id': 2, 'name': '销售', 'parent_id': 1, 'dept_manager_userid_list': ['u1', 'u2']},
            3: {'dept_id': 3, 'name': '技术', 'parent_id': 1, 'dept_manager_userid_list': ['u3']},
        }
        self.users = {key: {'userid': key, 'name': '员工' + key, 'active': True, 'avatar': 'https://example.test/' + key + '.png'} for key in ['u1', 'u2', 'u3']}
        self.memberships = {1: [], 2: ['u1', 'u2'], 3: ['u3']}
        self.errors = set()
        self.first = self.sync()
        self.assertTrue(self.first['organizationChanged'])
        self.revision = self.first['orgRevision']

    def sync(self):
        def detail(_token, user_id):
            if user_id in self.errors:
                raise DingTalkAPIError('temporary detail failure')
            return copy.deepcopy(self.users[user_id])
        with ExitStack() as stack:
            stack.enter_context(patch.dict('os.environ', {
                'DINGTALK_ROOT_DEPT_ID': '1',
                'DINGTALK_ORG_SYNC_MAX_DEPARTMENT_DROP_RATIO': '1',
                'DINGTALK_ORG_SYNC_MAX_EMPLOYEE_DROP_RATIO': '1',
                'DINGTALK_ORG_SYNC_MAX_MEMBERSHIP_DROP_RATIO': '1',
                'DINGTALK_ORG_SYNC_MAX_USER_DETAIL_ERROR_RATIO': '1',
            }))
            stack.enter_context(patch('identity_api.org.sync._get_app_access_token', return_value='mock-token'))
            stack.enter_context(patch('identity_api.org.sync._get_department_detail', side_effect=lambda token, dept: copy.deepcopy(self.departments[dept])))
            stack.enter_context(patch('identity_api.org.sync._list_sub_departments', side_effect=lambda token, dept: [{'dept_id': key} for key, row in self.departments.items() if row.get('parent_id') == dept]))
            stack.enter_context(patch('identity_api.org.sync._list_department_users', side_effect=lambda token, dept: [copy.deepcopy(self.users[key]) for key in self.memberships.get(dept, [])]))
            stack.enter_context(patch('identity_api.org.sync._get_user_detail_by_userid', side_effect=detail))
            return sync_organization_contacts()

    def snapshot(self):
        return {model.__name__: list(model.objects.order_by('pk').values()) for model in (Department, Employee, DepartmentEmployee, DepartmentManager)}

    def assert_changed_once_then_stable(self):
        response = self.sync()
        self.assertTrue(response['organizationChanged'])
        self.assertEqual(response['orgRevision'], self.revision + 1)
        before = self.snapshot()
        again = self.sync()
        self.assertFalse(again['organizationChanged'])
        self.assertEqual(again['orgRevision'], response['orgRevision'])
        self.assertEqual(self.snapshot(), before)
        return response

    def test_identical_refresh_preserves_versions_ids_timestamps_and_advances_sync_time(self):
        before = self.snapshot()
        synced_at = OrganizationState.objects.get(pk=1).synced_at
        for minutes in (15, 30, 45):
            with patch('identity_api.org.sync.timezone.now', return_value=synced_at + timedelta(minutes=minutes)):
                response = self.sync()
            self.assertFalse(response['organizationChanged'])
            self.assertEqual(response['orgRevision'], self.revision)
            self.assertEqual(self.snapshot(), before)
            state = OrganizationState.objects.get(pk=1)
            self.assertEqual(state.synced_at, synced_at + timedelta(minutes=minutes))
            self.assertEqual(state.revision, self.revision)

    def test_source_order_and_duplicate_memberships_do_not_invalidate_snapshot(self):
        before = self.snapshot()
        self.departments = dict(reversed(list(self.departments.items())))
        self.memberships[2] = ['u2', 'u1', 'u1']
        response = self.sync()
        self.assertFalse(response['organizationChanged'])
        self.assertEqual(self.snapshot(), before)

    def test_profile_change_advances_once_without_rewriting_unrelated_rows(self):
        untouched = list(Employee.objects.exclude(pk='u1').values())
        relations = list(DepartmentEmployee.objects.values())
        self.users['u1'].update(name='新姓名', avatar='https://example.test/new.png')
        self.assert_changed_once_then_stable()
        self.assertEqual(list(Employee.objects.exclude(pk='u1').values()), untouched)
        self.assertEqual(list(DepartmentEmployee.objects.values()), relations)
        self.assertEqual(Employee.objects.get(pk='u1').auth_version, 1)

    def test_department_hierarchy_change_advances_once(self):
        self.departments[3]['parent_id'] = 2
        self.assert_changed_once_then_stable()
        self.assertEqual(Department.objects.get(pk=3).parent_dept_id, 2)

    def test_membership_change_with_same_counts_is_detected(self):
        self.memberships[2], self.memberships[3] = ['u1', 'u3'], ['u2']
        self.assert_changed_once_then_stable()
        self.assertEqual(set(DepartmentEmployee.objects.filter(department_id=3).values_list('employee_id', flat=True)), {'u2'})

    def test_manager_order_change_updates_primary_without_changing_relation_ids(self):
        old_ids = dict(DepartmentManager.objects.filter(department_id=2).values_list('employee_id', 'id'))
        self.departments[2]['dept_manager_userid_list'] = ['u2', 'u1']
        self.assert_changed_once_then_stable()
        self.assertEqual(dict(DepartmentManager.objects.filter(department_id=2).values_list('employee_id', 'id')), old_ids)
        self.assertTrue(DepartmentManager.objects.get(department_id=2, employee_id='u2').is_primary)
        self.assertFalse(DepartmentManager.objects.get(department_id=2, employee_id='u1').is_primary)

    def test_removing_employee_and_department_remains_a_real_change(self):
        del self.departments[3]
        self.memberships.pop(3)
        self.assert_changed_once_then_stable()
        employee = Employee.objects.get(pk='u3')
        self.assertEqual((employee.status, employee.account_status, employee.auth_version), (Employee.STATUS_INACTIVE, Employee.ACCOUNT_DISABLED, 2))
        self.assertEqual(employee.former_dingtalk_departments[0]['pathText'], '公司 / 技术')
        self.assertFalse(Department.objects.filter(pk=3).exists())

    def test_status_change_revokes_access_and_keeps_revision_stable_on_next_sync(self):
        self.users['u2']['active'] = False
        self.assert_changed_once_then_stable()
        employee = Employee.objects.get(pk='u2')
        self.assertEqual((employee.account_status, employee.auth_version), (Employee.ACCOUNT_DISABLED, 2))

    def test_manually_disabled_account_is_not_reenabled_or_rewritten(self):
        Employee.objects.filter(pk='u1').update(account_status=Employee.ACCOUNT_DISABLED, auth_version=4)
        before = self.snapshot()
        response = self.sync()
        self.assertFalse(response['organizationChanged'])
        self.assertEqual(response['orgRevision'], self.revision)
        self.assertEqual(self.snapshot(), before)

    def test_detail_fallback_uses_retained_profile_without_false_revision_change(self):
        before = self.snapshot()
        self.errors.add('u1')
        self.users['u1']['name'] = '不完整列表姓名'
        response = self.sync()
        self.assertEqual(response['userDetailFallbackCount'], 1)
        self.assertFalse(response['organizationChanged'])
        self.assertEqual(response['orgRevision'], self.revision)
        self.assertEqual(self.snapshot(), before)

    def test_new_employee_and_membership_advance_revision_once(self):
        self.users['u4'] = {'userid': 'u4', 'name': '新员工', 'active': True}
        self.memberships[2].append('u4')
        self.assert_changed_once_then_stable()
        self.assertTrue(Employee.objects.filter(pk='u4').exists())
