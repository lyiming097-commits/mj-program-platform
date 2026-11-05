import base64
import io
import json

from PIL import Image
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from identity_api.auth.session import create_auth_session_token
from identity_api.auth.tokens import AUTH_COOKIE_NAME
from identity_api.models import (
    Department,
    DepartmentEmployee,
    Employee,
    NotificationCategory,
    NotificationAcknowledgement,
    NotificationPermissionState,
    NotificationRecipient,
    OrganizationState,
    PlatformDepartmentState,
    PlatformNotification,
)


BASE = "/api/org/notices"


class NotificationTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_SEC_FETCH_SITE"] = "same-origin"
        self.admin = Employee.objects.create(user_id="system-admin", name="系统管理员")
        self.notice_admin = Employee.objects.create(user_id="notice-admin", name="通知管理员")
        self.publisher = Employee.objects.create(user_id="publisher", name="通知发布者")
        self.recipient = Employee.objects.create(user_id="recipient", name="接收人")
        self.other = Employee.objects.create(user_id="other", name="其他人员")
        self.root = Department.objects.create(dept_id=1, name="销售部")
        self.child = Department.objects.create(dept_id=2, name="华东组", parent_dept_id=1)
        for department, employee in [
            (self.root, self.recipient),
            (self.child, self.recipient),
            (self.child, self.other),
        ]:
            DepartmentEmployee.objects.create(department=department, employee=employee)
        PlatformDepartmentState.objects.update_or_create(pk=1, defaults={"configured": False})
        OrganizationState.objects.update_or_create(pk=1, defaults={"revision": 5})
        self.permission_state = NotificationPermissionState.objects.create(roles={
            "admin": [{"scopeType": "employee", "targetId": self.notice_admin.user_id}],
            "publisher": [{"scopeType": "employee", "targetId": self.publisher.user_id}],
        })
        self.category = NotificationCategory.objects.create(name="制度通知")
        self.full_access = patch("identity_api.org.queries.FULL_ACCESS_USER_IDS", {self.admin.user_id})
        self.full_access.start()
        self.addCleanup(self.full_access.stop)
        self.authenticate(self.admin)

    def authenticate(self, employee):
        self.client.cookies[AUTH_COOKIE_NAME] = create_auth_session_token(employee)["token"]

    def create_notice(self, **changes):
        payload = {
            "title": "部门会议安排",
            "contentHtml": "<p>请准时参加。</p>",
            "categoryId": self.category.id,
            "expiresAt": (timezone.now() + timedelta(days=4)).isoformat(),
            "recipientSelection": {
                "departments": [
                    {"deptId": self.root.dept_id, "includeSubDepartments": True},
                    {"deptId": self.child.dept_id, "includeSubDepartments": False},
                ],
                "people": [self.recipient.user_id, self.other.user_id, self.recipient.user_id],
            },
        }
        payload.update(changes)
        response = self.client.post(BASE, json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def publish(self, notice_id, **payload):
        response = self.client.post(f"{BASE}/{notice_id}/publish", json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_department_scope_distinguishes_direct_members_from_all_descendants(self):
        grandchild = Department.objects.create(dept_id=3, name="孙级组", parent_dept_id=self.child.dept_id)
        descendant = Employee.objects.create(user_id="grandchild-member", name="孙级人员")
        DepartmentEmployee.objects.create(department=grandchild, employee=descendant)
        for include_children, expected in [
            (False, [self.recipient.user_id]),
            (True, [self.recipient.user_id, self.other.user_id, descendant.user_id]),
        ]:
            with self.subTest(include_children=include_children):
                notice = self.create_notice(recipientSelection={
                    "departments": [{"deptId": self.root.dept_id, "includeSubDepartments": include_children}],
                    "people": [],
                })
                self.publish(notice["id"])
                self.assertCountEqual(
                    NotificationRecipient.objects.filter(notification_id=notice["id"]).values_list("user_id", flat=True),
                    expected,
                )

    def test_notification_admin_can_manage_notification_roles_without_platform_admin(self):
        self.authenticate(self.notice_admin)
        response = self.client.get(f"{BASE}/capabilities")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["canManagePermissions"])
        self.assertTrue(response.json()["canManageCategories"])

        current = self.client.get(f"{BASE}/permissions/publisher").json()
        payload = {
            "rules": [{"scopeType": "employee", "targetId": self.other.user_id}],
            "revision": current["revision"],
            "orgRevision": current["orgRevision"],
        }
        saved = self.client.put(
            f"{BASE}/permissions/publisher",
            json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()["rules"][0]["targetId"], self.other.user_id)

        self.authenticate(self.other)
        self.assertEqual(self.client.get(f"{BASE}/permissions/publisher").status_code, 403)

    def test_published_department_audience_is_deduplicated_and_frozen(self):
        self.authenticate(self.publisher)
        notice = self.create_notice()
        self.publish(notice["id"])
        self.assertCountEqual(
            NotificationRecipient.objects.filter(notification_id=notice["id"]).values_list("user_id", flat=True),
            [self.recipient.user_id, self.other.user_id],
        )

        self.authenticate(self.recipient)
        unread = self.client.get(f"{BASE}/unread").json()
        self.assertEqual(unread["total"], 1)
        self.assertEqual(unread["items"][0]["id"], notice["id"])
        self.assertEqual(self.client.post(
            f"{BASE}/{notice['id']}/read", "{}", content_type="application/json"
        ).status_code, 200)
        self.assertEqual(self.client.get(f"{BASE}/unread").json()["total"], 0)
        self.assertEqual(self.client.get(f"{BASE}/history").json()["items"][0]["readAt"] != "", True)

        newcomer = Employee.objects.create(user_id="newcomer", name="新员工")
        DepartmentEmployee.objects.create(department=self.root, employee=newcomer)
        self.authenticate(self.publisher)
        self.client.post(f"{BASE}/{notice['id']}/withdraw", "{}", content_type="application/json")
        republished = self.publish(notice["id"])
        self.assertEqual(republished["recipientCount"], 2)
        self.assertEqual(republished["unreadCount"], 1)
        self.assertFalse(NotificationRecipient.objects.filter(notification_id=notice["id"], user_id=newcomer.user_id).exists())
        self.assertIsNotNone(NotificationRecipient.objects.get(notification_id=notice["id"], user_id=self.recipient.user_id).read_at)
        self.assertEqual(self.client.post(
            f"{BASE}/{notice['id']}/publish", "{}", content_type="application/json"
        ).status_code, 200)

    def test_save_preserves_reads_and_explicit_republication_resets_frozen_recipients(self):
        self.authenticate(self.publisher)
        notice = self.create_notice()
        self.publish(notice["id"])
        unrelated = self.create_notice(title="另一条通知")
        self.publish(unrelated["id"])
        for person in [self.recipient, self.other]:
            self.authenticate(person)
            self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/read", "{}", content_type="application/json").status_code, 200)
        self.authenticate(self.recipient)
        self.client.post(f"{BASE}/{unrelated['id']}/read", "{}", content_type="application/json")
        recipient_rows = NotificationRecipient.objects.filter(notification_id=notice["id"])
        frozen = list(recipient_rows.order_by("user_id").values("id", "user_id", "name", "department_names", "read_at"))
        published_at = PlatformNotification.objects.get(pk=notice["id"]).published_at
        self.authenticate(self.publisher)
        response = self.client.patch(f"{BASE}/{notice['id']}", json.dumps({
            "title": "更新后的通知", "contentHtml": "<p>更新后的正文</p>", "categoryId": self.category.id,
            "expiresAt": notice["expiresAt"], "recipientSelection": notice["recipientSelection"],
        }), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(list(recipient_rows.order_by("user_id").values("id", "user_id", "name", "department_names", "read_at")), frozen)
        ordinary = self.publish(notice["id"])
        self.assertEqual(ordinary["unreadCount"], 0)
        self.assertEqual(ordinary["contentHtml"], "<p>更新后的正文</p>")
        self.assertEqual(PlatformNotification.objects.get(pk=notice["id"]).published_at, published_at)

        newcomer = Employee.objects.create(user_id="newcomer", name="后来加入的人员")
        DepartmentEmployee.objects.create(department=self.root, employee=newcomer)
        DepartmentEmployee.objects.filter(employee=self.recipient).delete()
        republished = self.publish(notice["id"], resetRead=True)
        self.assertEqual((republished["recipientCount"], republished["unreadCount"]), (2, 2))
        self.assertEqual(republished["contentHtml"], "<p>更新后的正文</p>")
        self.assertEqual(list(recipient_rows.order_by("user_id").values("id", "user_id", "name", "department_names", "read_at")), [{**row, "read_at": None} for row in frozen])
        self.assertGreater(PlatformNotification.objects.get(pk=notice["id"]).published_at, published_at)
        self.assertFalse(recipient_rows.filter(user_id=newcomer.user_id).exists())
        self.assertIsNotNone(NotificationRecipient.objects.get(notification_id=unrelated["id"], user_id=self.recipient.user_id).read_at)
        self.authenticate(self.recipient)
        self.assertEqual([item["id"] for item in self.client.get(f"{BASE}/unread").json()["items"]], [notice["id"]])
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/read", "{}", content_type="application/json").status_code, 200)
        self.authenticate(self.publisher)
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/withdraw", "{}", content_type="application/json").status_code, 200)
        self.assertEqual(self.publish(notice["id"], resetRead=True)["unreadCount"], 2)

    def test_republication_checks_authorization_and_expiry_before_clearing_reads(self):
        self.authenticate(self.publisher)
        notice = self.create_notice()
        self.publish(notice["id"])
        self.authenticate(self.recipient)
        self.client.post(f"{BASE}/{notice['id']}/read", "{}", content_type="application/json")
        receipt = NotificationRecipient.objects.get(notification_id=notice["id"], user_id=self.recipient.user_id)
        original_read = receipt.read_at
        def remains_read():
            receipt.refresh_from_db()
            self.assertEqual(receipt.read_at, original_read)
        response = self.client.post(f"{BASE}/{notice['id']}/publish", '{"resetRead":true}', content_type="application/json")
        self.assertEqual(response.status_code, 403)
        remains_read()
        outsider = Employee.objects.create(user_id="another-publisher", name="另一发布者")
        self.permission_state.roles["publisher"].append({"scopeType": "employee", "targetId": outsider.user_id})
        self.permission_state.save(update_fields=["roles"])
        self.authenticate(outsider)
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/publish", '{"resetRead":true}', content_type="application/json").status_code, 403)
        remains_read()
        self.authenticate(self.notice_admin)
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/publish", '{"resetRead":"true"}', content_type="application/json").status_code, 400)
        remains_read()
        PlatformNotification.objects.filter(pk=notice["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/publish", '{"resetRead":true}', content_type="application/json").status_code, 400)
        remains_read()
        PlatformNotification.objects.filter(pk=notice["id"]).update(expires_at=timezone.now() + timedelta(days=1))
        self.assertEqual(self.publish(notice["id"], resetRead=True)["unreadCount"], 2)
        receipt.refresh_from_db()
        self.assertIsNone(receipt.read_at)

    def test_expired_notices_stop_reminding_but_remain_in_private_history(self):
        self.authenticate(self.publisher)
        notice = self.create_notice()
        self.publish(notice["id"])
        PlatformNotification.objects.filter(pk=notice["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))

        self.authenticate(self.recipient)
        self.assertEqual(self.client.get(f"{BASE}/unread").json()["total"], 0)
        history = self.client.get(f"{BASE}/history", {"keyword": "部门会议"}).json()
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["items"][0]["status"], "expired")

        self.authenticate(self.other)
        self.assertEqual(self.client.get(f"{BASE}/history").json()["total"], 1)
        self.assertEqual(self.client.get(f"{BASE}/{notice['id']}").status_code, 200)
        self.authenticate(self.admin)
        outsider = Employee.objects.create(user_id="outsider", name="未通知人员")
        self.authenticate(outsider)
        self.assertEqual(self.client.get(f"{BASE}/{notice['id']}").status_code, 403)

    def test_person_filters_use_frozen_recipients_and_preserve_full_counts(self):
        self.authenticate(self.publisher)
        mixed = self.create_notice(title="部分已读")
        self.publish(mixed["id"])
        self.authenticate(self.recipient)
        self.assertEqual(self.client.post(f"{BASE}/{mixed['id']}/read", "{}", content_type="application/json").status_code, 200)
        self.authenticate(self.publisher)
        both_unread = self.create_notice(title="两人未读")
        self.publish(both_unread["id"])
        individual = self.create_notice(title="个人未读", recipientSelection={"departments": [], "people": [self.recipient.user_id]})
        self.publish(individual["id"])
        self.create_notice(title="尚未发布")
        # Directory changes never replace the published notification snapshots.
        DepartmentEmployee.objects.filter(employee=self.recipient).delete()

        def results(**params):
            response = self.client.get(BASE, params)
            self.assertEqual(response.status_code, 200, response.content)
            return response.json()

        received = results(recipientUserId=self.recipient.user_id)
        self.assertEqual(received["total"], 3)
        unread = results(unreadUserId=self.recipient.user_id)
        self.assertCountEqual([item["id"] for item in unread["items"]], [both_unread["id"], individual["id"]])
        combined = results(recipientUserId=self.recipient.user_id, unreadUserId=self.other.user_id)
        self.assertCountEqual([item["id"] for item in combined["items"]], [mixed["id"], both_unread["id"]])
        stats = {item["id"]: (item["recipientCount"], item["unreadCount"]) for item in combined["items"]}
        self.assertEqual(stats[mixed["id"]], (2, 1))
        self.assertEqual(stats[both_unread["id"]], (2, 2))
        inverse = results(recipientUserId=self.other.user_id, unreadUserId=self.recipient.user_id)
        self.assertEqual([item["id"] for item in inverse["items"]], [both_unread["id"]])
        self.assertEqual(results(recipientUserId="unknown")["total"], 0)
        self.assertEqual(results(unreadUserId="unknown")["total"], 0)
        paginated = results(recipientUserId=self.recipient.user_id, pageSize=1, page=2)
        self.assertEqual(paginated["total"], 3)
        self.assertEqual([item["id"] for item in paginated["items"]], [both_unread["id"]])
        self.assertEqual(results(unreadUserId=self.recipient.user_id, keyword="个人", categoryId=self.category.id)["total"], 1)
        PlatformNotification.objects.filter(pk=individual["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(results(unreadUserId=self.recipient.user_id, status="expired")["items"][0]["id"], individual["id"])

    def test_person_filters_do_not_expand_publisher_or_recipient_access(self):
        self.authenticate(self.admin)
        managed_by_admin = self.create_notice()
        self.publish(managed_by_admin["id"])
        self.authenticate(self.publisher)
        own = self.create_notice()
        self.publish(own["id"])
        for filters in [{"recipientUserId": self.recipient.user_id}, {"unreadUserId": self.other.user_id}]:
            with self.subTest(filters=filters):
                own_records = self.client.get(BASE, filters)
                self.assertEqual(own_records.status_code, 200)
                self.assertEqual([item["id"] for item in own_records.json()["items"]], [own["id"]])
        self.authenticate(self.notice_admin)
        self.assertEqual(self.client.get(BASE, {"recipientUserId": self.recipient.user_id}).json()["total"], 2)
        self.authenticate(self.recipient)
        self.assertEqual(self.client.get(BASE, {"unreadUserId": self.other.user_id}).status_code, 403)
        private_history = self.client.get(f"{BASE}/history", {"recipientUserId": "unknown", "unreadUserId": self.other.user_id})
        self.assertEqual(private_history.status_code, 200)
        self.assertEqual(private_history.json()["total"], 2)

    def test_confirmation_levels_require_exact_text_and_current_version(self):
        for level, statement in [
            ("confirm", "本人已阅读并知晓本次通知的全部内容"),
            ("accept", "本人已阅读并知晓本次通知的全部内容，并同意按通知要求执行相关规定"),
        ]:
            with self.subTest(level=level):
                self.authenticate(self.admin)
                notice = self.create_notice(level=level)
                published = self.publish(notice["id"])
                self.assertEqual(published["confirmationStatement"], statement)
                self.authenticate(self.recipient)
                invalid_payloads = [({}, 409), ({"confirmationVersion": published["confirmationVersion"]}, 400)]
                invalid_payloads.extend(
                    ({"confirmationVersion": published["confirmationVersion"], "statement": entered}, 400)
                    for entered in [None, " \n\t", "本人已阅读", statement.replace("的", ""),
                                    statement.replace("的", "的的"), statement.replace("知晓", "知悉"),
                                    statement + "。", " " + statement, statement + "\n"]
                )
                if level == "accept":
                    invalid_payloads.extend(
                        ({"confirmationVersion": published["confirmationVersion"], "statement": entered}, 400)
                        for entered in [statement.replace("，", ""), statement.replace("相关规定", "")]
                    )
                for payload, status in invalid_payloads:
                    result = self.client.post(f"{BASE}/{notice['id']}/read", json.dumps(payload), content_type="application/json")
                    self.assertEqual(result.status_code, status, result.content)
                    self.assertFalse(NotificationAcknowledgement.objects.filter(notification_id=notice["id"]).exists())
                entered = statement
                payload = {"confirmationVersion": published["confirmationVersion"], "statement": entered}
                for _ in range(2):
                    result = self.client.post(f"{BASE}/{notice['id']}/read", json.dumps(payload), content_type="application/json")
                    self.assertEqual(result.status_code, 200, result.content)
                record = NotificationAcknowledgement.objects.get(notification_id=notice["id"])
                self.assertEqual(record.statement, statement)
                self.assertEqual(record.entered_statement, entered)
                self.assertEqual(record.user_id, self.recipient.user_id)
                self.assertEqual(record.actor_user_id, self.recipient.user_id)
                self.assertEqual(record.content_snapshot["title"], notice["title"])
                self.assertEqual(self.client.get(f"{BASE}/{notice['id']}").json()["confirmation"]["statement"], statement)
                self.authenticate(self.publisher)
                self.assertEqual(self.client.get(f"{BASE}/{notice['id']}/recipients").status_code, 403)
                self.authenticate(self.admin)
                rows = self.client.get(f"{BASE}/{notice['id']}/recipients", {"status": "read"}).json()["items"]
                self.assertEqual(rows[0]["confirmation"]["statement"], statement)
                self.assertEqual(rows[0]["confirmation"]["enteredStatement"], entered)

    def test_level_changes_require_republish_and_keep_snapshot_audit(self):
        notice = self.create_notice(level="confirm")
        first = self.publish(notice["id"])
        self.authenticate(self.recipient)
        payload = {"confirmationVersion": first["confirmationVersion"], "statement": first["confirmationStatement"]}
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/read", json.dumps(payload), content_type="application/json").status_code, 200)
        record = NotificationAcknowledgement.objects.get(notification_id=notice["id"])
        self.authenticate(self.admin)
        edited = self.client.patch(f"{BASE}/{notice['id']}", json.dumps({"title": "更新标题", "contentHtml": "<p>更新正文</p>"}), content_type="application/json")
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(NotificationRecipient.objects.get(notification_id=notice["id"], user_id=self.recipient.user_id).read_at, record.confirmed_at)
        record.refresh_from_db()
        self.assertEqual(record.content_snapshot["title"], notice["title"])
        for endpoint, body in [(f"{BASE}/{notice['id']}", {"level": "accept"}), (f"{BASE}/{notice['id']}/publish", {"level": "accept"})]:
            method = self.client.patch if endpoint.endswith(notice["id"]) else self.client.post
            self.assertEqual(method(endpoint, json.dumps(body), content_type="application/json").status_code, 409)
        before_ids = list(NotificationRecipient.objects.filter(notification_id=notice["id"]).values_list("id", flat=True))
        second = self.publish(notice["id"], resetRead=True, level="accept")
        self.assertEqual(second["level"], "accept")
        self.assertEqual(list(NotificationRecipient.objects.filter(notification_id=notice["id"]).values_list("id", flat=True)), before_ids)
        self.assertFalse(NotificationRecipient.objects.filter(notification_id=notice["id"], read_at__isnull=False).exists())
        self.assertEqual(NotificationAcknowledgement.objects.filter(notification_id=notice["id"]).count(), 1)
        self.authenticate(self.recipient)
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/read", json.dumps(payload), content_type="application/json").status_code, 409)
        payload = {"confirmationVersion": second["confirmationVersion"], "statement": second["confirmationStatement"]}
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/read", json.dumps(payload), content_type="application/json").status_code, 200)
        self.assertEqual(NotificationAcknowledgement.objects.filter(notification_id=notice["id"]).count(), 2)

    def test_stale_content_and_attachment_versions_cannot_be_confirmed(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            notice = self.create_notice(level="accept")
            published = self.publish(notice["id"])
            self.client.patch(f"{BASE}/{notice['id']}", json.dumps({"contentHtml": "<p>新条款</p>"}), content_type="application/json")
            self.authenticate(self.recipient)
            stale = {"confirmationVersion": published["confirmationVersion"], "statement": published["confirmationStatement"]}
            self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/read", json.dumps(stale), content_type="application/json").status_code, 409)
            current = self.client.get(f"{BASE}/{notice['id']}").json()
            self.authenticate(self.admin)
            upload = self.client.post(f"{BASE}/{notice['id']}/attachments", {"files": SimpleUploadedFile("条款.txt", b"terms")})
            self.assertEqual(upload.status_code, 200)
            self.authenticate(self.recipient)
            stale["confirmationVersion"] = current["confirmationVersion"]
            self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/read", json.dumps(stale), content_type="application/json").status_code, 409)
            self.assertFalse(NotificationAcknowledgement.objects.filter(notification_id=notice["id"]).exists())

    def test_invalid_levels_and_failed_republish_leave_completion_unchanged(self):
        notice = self.create_notice()
        first = self.publish(notice["id"])
        self.assertEqual(first["level"], "ordinary")
        self.authenticate(self.recipient)
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/read", "{}", content_type="application/json").status_code, 200)
        self.authenticate(self.admin)
        for level in ["", "urgent", None, 3, {}]:
            result = self.client.post(f"{BASE}/{notice['id']}/publish", json.dumps({"resetRead": True, "level": level}), content_type="application/json")
            self.assertEqual(result.status_code, 400)
        PlatformNotification.objects.filter(pk=notice["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
        result = self.client.post(f"{BASE}/{notice['id']}/publish", json.dumps({"resetRead": True, "level": "accept"}), content_type="application/json")
        self.assertEqual(result.status_code, 400)
        current = PlatformNotification.objects.get(pk=notice["id"])
        self.assertEqual((current.level, current.publication_revision), ("ordinary", 1))
        self.assertTrue(NotificationRecipient.objects.get(notification_id=notice["id"], user_id=self.recipient.user_id).read_at)

    def test_withdrawn_expired_or_unaddressed_confirmation_is_rejected(self):
        notice = self.create_notice(level="confirm", recipientSelection={"people": [self.recipient.user_id]})
        published = self.publish(notice["id"])
        payload = {"confirmationVersion": published["confirmationVersion"], "statement": published["confirmationStatement"]}
        self.authenticate(self.other)
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/read", json.dumps(payload), content_type="application/json").status_code, 403)
        self.authenticate(self.admin)
        self.client.post(f"{BASE}/{notice['id']}/withdraw", "{}", content_type="application/json")
        self.authenticate(self.recipient)
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/read", json.dumps(payload), content_type="application/json").status_code, 409)
        PlatformNotification.objects.filter(pk=notice["id"]).update(status="published", expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.post(f"{BASE}/{notice['id']}/read", json.dumps(payload), content_type="application/json").status_code, 409)
        self.assertFalse(NotificationAcknowledgement.objects.filter(notification_id=notice["id"]).exists())

    def test_optional_expiration_can_be_omitted_or_blank_and_stays_active(self):
        for expiration in [{}, {"expiresAt": ""}, {"expiresAt": None}, {"expiresAt": "  "}]:
            with self.subTest(expiration=expiration):
                payload = {
                    "title": "长期通知", "contentHtml": "<p>长期有效。</p>",
                    "categoryId": self.category.id,
                    "recipientSelection": {"people": [self.recipient.user_id]},
                    **expiration,
                }
                response = self.client.post(BASE, json.dumps(payload), content_type="application/json")
                self.assertEqual(response.status_code, 201, response.content)
                notice = response.json()
                self.assertEqual((notice["expiresAt"], notice["expiresOn"]), ("", ""))
                self.assertIsNone(PlatformNotification.objects.get(pk=notice["id"]).expires_at)
                self.assertEqual(self.publish(notice["id"])["status"], "published")
        self.assertEqual(self.client.get(BASE, {"status": "published"}).json()["total"], 4)
        self.assertEqual(self.client.get(BASE, {"status": "expired"}).json()["total"], 0)
        self.authenticate(self.recipient)
        with patch("identity_api.notifications.timezone", wraps=timezone) as notice_clock:
            notice_clock.now.return_value = timezone.now() + timedelta(days=36500)
            self.assertEqual(self.client.get(f"{BASE}/unread").json()["total"], 4)
            self.assertTrue(all(row["status"] == "published" for row in self.client.get(f"{BASE}/history").json()["items"]))

    def test_expiration_can_be_cleared_or_set_without_resetting_reads(self):
        notice = self.create_notice()
        self.publish(notice["id"])
        self.authenticate(self.recipient)
        self.client.post(f"{BASE}/{notice['id']}/read", "{}", content_type="application/json")
        read_at = NotificationRecipient.objects.get(notification_id=notice["id"], user_id=self.recipient.user_id).read_at
        self.authenticate(self.admin)
        for changes in [{"expiresAt": ""}, {"title": "保留空日期"}, {"expiresAt": "2099-03-01"}, {"expiresAt": None}]:
            response = self.client.patch(f"{BASE}/{notice['id']}", json.dumps(changes), content_type="application/json")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["expiresOn"], "2099-03-01" if changes.get("expiresAt") else "")
            self.assertEqual(NotificationRecipient.objects.get(notification_id=notice["id"], user_id=self.recipient.user_id).read_at, read_at)
        self.publish(notice["id"], resetRead=True)
        self.assertFalse(NotificationRecipient.objects.filter(notification_id=notice["id"], read_at__isnull=False).exists())
        self.authenticate(self.recipient)
        self.assertEqual(self.client.get(f"{BASE}/unread").json()["total"], 1)
        self.authenticate(self.admin)
        self.client.post(f"{BASE}/{notice['id']}/withdraw", "{}", content_type="application/json")
        self.authenticate(self.recipient)
        self.assertEqual(self.client.get(f"{BASE}/unread").json()["total"], 0)

    def test_expiration_status_filters_include_unbounded_and_exclude_expired_notices(self):
        unbounded = self.create_notice(expiresAt="")
        dated = self.create_notice()
        expired = self.create_notice()
        for notice in [unbounded, dated, expired]:
            self.publish(notice["id"])
        PlatformNotification.objects.filter(pk=expired["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertCountEqual([row["id"] for row in self.client.get(BASE, {"status": "published"}).json()["items"]], [unbounded["id"], dated["id"]])
        self.assertEqual([row["id"] for row in self.client.get(BASE, {"status": "expired"}).json()["items"]], [expired["id"]])
        self.authenticate(self.recipient)
        self.assertEqual(self.client.get(f"{BASE}/unread").json()["total"], 2)

    def test_date_only_expiration_includes_selected_day_and_expires_at_next_midnight(self):
        self.authenticate(self.publisher)
        today = timezone.localdate()
        notice = self.create_notice(expiresAt=today.isoformat())
        deadline = parse_datetime(notice["expiresAt"])
        self.assertEqual(notice["expiresOn"], today.isoformat())
        local_deadline = timezone.localtime(deadline)
        self.assertEqual(local_deadline.date(), today + timedelta(days=1))
        self.assertEqual((local_deadline.hour, local_deadline.minute, local_deadline.second), (0, 0, 0))
        self.publish(notice["id"])
        # Move the notification clock without expiring the login session clock.
        with patch("identity_api.notifications.timezone", wraps=timezone) as notice_clock:
            notice_clock.now.return_value = deadline - timedelta(microseconds=1)
            self.authenticate(self.recipient)
            self.assertEqual(self.client.get(f"{BASE}/unread").json()["total"], 1)
        with patch("identity_api.notifications.timezone", wraps=timezone) as notice_clock:
            notice_clock.now.return_value = deadline
            self.authenticate(self.recipient)
            self.assertEqual(self.client.get(f"{BASE}/unread").json()["total"], 0)
            history = self.client.get(f"{BASE}/history").json()
            self.assertEqual(history["items"][0]["status"], "expired")
            self.assertEqual(history["items"][0]["expiresOn"], today.isoformat())

    def test_past_or_invalid_expiration_dates_are_rejected_without_losing_notice(self):
        notice = self.create_notice()
        for value in [(timezone.localdate() - timedelta(days=1)).isoformat(), "2099-02-30", "9999-12-31", "invalid"]:
            with self.subTest(value=value):
                response = self.client.patch(f"{BASE}/{notice['id']}", json.dumps({"expiresAt": value}), content_type="application/json")
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.client.get(f"{BASE}/{notice['id']}").json()["expiresAt"], notice["expiresAt"])

    def test_legacy_timestamp_expiration_remains_unchanged_until_date_is_edited(self):
        expiration = timezone.now() + timedelta(days=3)
        notice = self.create_notice(expiresAt=expiration.isoformat())
        updated = self.client.patch(f"{BASE}/{notice['id']}", json.dumps({"title": "修改标题"}), content_type="application/json")
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(parse_datetime(updated.json()["expiresAt"]), expiration)
        self.assertEqual(updated.json()["expiresOn"], timezone.localtime(expiration).date().isoformat())

    def test_withdrawn_and_expired_notifications_cannot_be_marked_as_unread(self):
        self.authenticate(self.publisher)
        notice = self.create_notice()
        self.publish(notice["id"])
        self.client.post(f"{BASE}/{notice['id']}/withdraw", "{}", content_type="application/json")
        self.authenticate(self.recipient)
        self.assertEqual(self.client.get(f"{BASE}/unread").json()["total"], 0)

    def test_used_category_can_be_renamed_but_not_deleted(self):
        self.authenticate(self.admin)
        self.authenticate(self.publisher)
        notice = self.create_notice()
        self.authenticate(self.notice_admin)
        renamed = self.client.patch(
            f"{BASE}/categories/{self.category.id}",
            json.dumps({"name": "重要制度"}),
            content_type="application/json",
        )
        self.assertEqual(renamed.status_code, 200, renamed.content)
        self.authenticate(self.admin)
        deleted = self.client.delete(f"{BASE}/categories/{self.category.id}")
        self.assertEqual(deleted.status_code, 409)
        self.assertEqual(deleted.json()["code"], "NOTIFICATION_CATEGORY_IN_USE")
        self.assertEqual(self.client.get(f"{BASE}/{notice['id']}").json()["category"]["name"], "重要制度")

    def test_attachment_download_requires_recipient_or_notice_management_access(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.authenticate(self.publisher)
        notice = self.create_notice()
        upload = self.client.post(
            f"{BASE}/{notice['id']}/attachments",
            {"files": SimpleUploadedFile("agenda.txt", b"meeting agenda", content_type="text/plain")},
        )
        self.assertEqual(upload.status_code, 200, upload.content)
        attachment = upload.json()["items"][0]
        self.publish(notice["id"])

        self.authenticate(self.recipient)
        allowed = self.client.get(attachment["url"])
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(allowed["Content-Type"], "application/octet-stream")
        self.assertEqual(attachment["previewUrl"], "")
        self.assertEqual(b"".join(allowed.streaming_content), b"meeting agenda")
        self.authenticate(self.admin)
        outsider = Employee.objects.create(user_id="file-outsider", name="附件无权用户")
        self.authenticate(outsider)
        self.assertEqual(self.client.get(attachment["url"]).status_code, 403)

    def test_only_pdf_and_browser_images_offer_authenticated_inline_preview(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings = override_settings(MEDIA_ROOT=media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        notice = self.create_notice()
        image = io.BytesIO()
        Image.new("RGB", (2, 2), "blue").save(image, format="PNG")
        files = [
            SimpleUploadedFile("会议资料.PDF", b"%PDF-1.4\n%%EOF", content_type="application/octet-stream"),
            SimpleUploadedFile("现场.png", image.getvalue(), content_type="image/png"),
            SimpleUploadedFile("会议记录.docx", b"office document", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            SimpleUploadedFile("说明.txt", b"plain text", content_type="application/pdf"),
            SimpleUploadedFile("page.html", b"<h1>HTML</h1>", content_type="text/html"),
        ]
        upload = self.client.post(f"{BASE}/{notice['id']}/attachments", {"files": files})
        self.assertEqual(upload.status_code, 200, upload.content)
        attachments = upload.json()["items"]
        self.publish(notice["id"])
        self.authenticate(self.recipient)
        for attachment, expected_type in zip(attachments, ["application/pdf", "image/png", None, None, None]):
            with self.subTest(filename=attachment["name"]):
                download = self.client.get(attachment["url"])
                self.assertEqual(download.status_code, 200)
                self.assertTrue(download["Content-Disposition"].startswith("attachment;"))
                self.assertEqual(download["Content-Type"], "application/octet-stream")
                self.assertTrue(b"".join(download.streaming_content))
                preview = self.client.get(attachment["url"] + "?preview=1")
                if expected_type:
                    self.assertEqual(attachment["previewUrl"], attachment["url"] + "?preview=1")
                    self.assertEqual(preview.status_code, 200)
                    self.assertTrue(preview["Content-Disposition"].startswith("inline;"))
                    self.assertEqual(preview["Content-Type"], expected_type)
                    self.assertEqual(preview["X-Content-Type-Options"], "nosniff")
                    self.assertTrue(b"".join(preview.streaming_content))
                else:
                    self.assertEqual(attachment["previewUrl"], "")
                    self.assertEqual(preview.status_code, 415)
        outsider = Employee.objects.create(user_id="preview-outsider", name="预览无权用户")
        self.authenticate(outsider)
        self.assertEqual(self.client.get(attachments[0]["previewUrl"]).status_code, 403)


class NotificationRichTextTests(TestCase):
    setUp = NotificationTests.setUp
    authenticate = NotificationTests.authenticate
    create_notice = NotificationTests.create_notice
    publish = NotificationTests.publish
    def image_source(self, size=(3, 2)):
        output = io.BytesIO()
        Image.new("RGB", size, (40, 80, 120)).save(output, format="PNG")
        return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()

    def test_pasted_images_survive_save_edit_and_recipient_read_without_public_url(self):
        source = self.image_source()
        notice = self.create_notice(contentHtml=f'<p><b>会议</b></p><img src="{source}" onerror="alert(1)">')
        self.assertIn(source, notice["contentHtml"])
        self.assertNotIn("onerror", notice["contentHtml"])
        image_only = self.client.patch(f"{BASE}/{notice['id']}", json.dumps({"contentHtml": f'<img src="{source}">'}), content_type="application/json")
        self.assertEqual(image_only.status_code, 200, image_only.content)
        self.publish(notice["id"])
        self.authenticate(self.recipient)
        self.assertIn(source, self.client.get(f"{BASE}/{notice['id']}").json()["contentHtml"])
        self.authenticate(self.other)
        # This user is a recipient too; outsiders still cannot fetch inline image content.
        outsider = Employee.objects.create(user_id="outsider", name="无关人员")
        self.authenticate(outsider)
        self.assertEqual(self.client.get(f"{BASE}/{notice['id']}").status_code, 403)

    def test_unsafe_remote_invalid_and_excess_images_are_rejected(self):
        from identity_api.notifications import sanitize_notification_html
        from identity_api.org.organization_access import OrganizationAccessError
        source = self.image_source()
        for content in ['<img src="javascript:alert(1)">', '<img src="https://example.test/image.png">', '<img src="data:image/svg+xml;base64,PHN2Zz4=">', '<img src="data:image/png;base64,YWJj">', f'<img src="{source}">' * 7]:
            with self.subTest(content=content[:80]), self.assertRaises(OrganizationAccessError):
                sanitize_notification_html(content)

    def test_large_valid_inline_image_body_uses_bounded_reader_and_preserves_plain_text_limit(self):
        # Poorly compressible RGB pixels put the request above Django's default request.body limit.
        import random
        from identity_api.notifications import MAX_HTML_LENGTH, sanitize_notification_html
        from identity_api.org.organization_access import OrganizationAccessError
        pixels = random.Random(1).randbytes(920 * 920 * 3)
        output = io.BytesIO()
        Image.frombytes("RGB", (920, 920), pixels).save(output, format="PNG")
        source = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
        self.assertGreater(len(source), 2_621_440)
        self.create_notice(contentHtml=f'<img src="{source}">')
        with self.assertRaises(OrganizationAccessError):
            sanitize_notification_html("a" * (MAX_HTML_LENGTH + 1))
