from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

from . import attachment_views, crm_source, presales_round_actions, services, views
from .models import PrivateAttachment, ServiceProject
from .tests import CleanDomainMixin, RequestMixin


class PresalesRoundActionTests(RequestMixin, CleanDomainMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        media = tempfile.TemporaryDirectory()
        self.media_root = media.name
        self.addCleanup(media.cleanup)
        media_settings = override_settings(MEDIA_ROOT=media.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        self.clear_domain()
        self.project = services.create_project(self.request("post", "/"), {
            "code": "round-forward", "name": "转发推进测试", "customer": "测试学校", "service_type": "presales",
        })
        for node in self.project.nodes.all():
            node.business_data = {"managementAssignment": {"userId": "designer", "name": "设计人员"}}
            node.save()
        services.advance_project(self.request("post", "/"), self.project.pk,
                                 expected_node_key="early-approval", node_values={"outcome": "approved"})
        self.node = self.project.nodes.get(node_key="early-plan")
        self.node.business_data["schemeRounds"] = [{"note": "原备注", "attachmentIds": ["88"]}]
        self.node.save()

    def action(self, operation, payload, **identity):
        return views.project_round_action(self.request("post", "/", payload, **identity),
                                          self.project.pk, self.node.node_key, operation)

    def prepare(self, index=0):
        self.node.refresh_from_db()
        response = self.action("prepare-forward", {"roundIndex": index, "expectedUpdatedAt": self.node.updated_at.isoformat()})
        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        return self.data(response)["roundId"]

    def process(self, round_id, action, **extra):
        self.node.refresh_from_db()
        return self.action("process", {"roundId": round_id, "action": action,
                                      "expectedUpdatedAt": self.node.updated_at.isoformat(), **extra})

    def process_with_files(self, round_id, files, **extra):
        self.node.refresh_from_db()
        payload = {"roundId": round_id, "action": "add_round", "reason": "按客户批注修改",
                   "expectedUpdatedAt": self.node.updated_at.isoformat(), **extra}
        request = self.factory.post("/", {"payload": json.dumps(payload), "reasonFiles": files})
        identity = self.request("post", "/", proxy=True)
        for key, value in vars(identity).items():
            if key.startswith("auth_"):
                setattr(request, key, value)
        return views.project_round_action(request, self.project.pk, self.node.node_key, "process")

    def test_reason_files_are_atomic_separate_read_only_and_not_inherited(self):
        round_id = self.prepare()
        original = deepcopy(self.node.business_data["schemeRounds"][0])
        response = self.process_with_files(round_id, [
            SimpleUploadedFile("客户批注.pdf", b"%PDF-1.4", content_type="application/pdf"),
            SimpleUploadedFile("布局.dwg", b"cad-data", content_type="application/octet-stream"),
            SimpleUploadedFile("无后缀", b"notes", content_type="application/octet-stream"),
        ])
        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        latest = self.node.business_data["schemeRounds"][-1]
        ids = latest["reasonAttachmentIds"]
        self.assertEqual(len(ids), 3)
        self.assertEqual(latest["attachmentIds"], [])
        self.assertTrue(set(ids).isdisjoint(latest["attachmentIds"]))
        self.assertEqual(self.node.business_data["schemeRounds"][0], original)
        for item in PrivateAttachment.objects.filter(pk__in=ids):
            self.assertEqual((item.target_type, item.target_id, item.uploaded_by, item.uploaded_actor_id),
                             ("project_node", self.node.pk, "system-admin", "actor-admin"))
            download = attachment_views.attachment_download(self.request("get", "/"), item.pk)
            self.assertEqual(download.status_code, 200)
            download.close()
            self.assertFalse(attachment_views._serialize_attachment(
                item, self.request("get", "/"), is_admin=True, target=self.node)["canDelete"])
            self.assertEqual(attachment_views.attachment_item(self.request("delete", "/"), item.pk).status_code, 409)
        event = self.project.events.get(event_type="presales_round_processed")
        self.assertEqual(event.after_values["reasonAttachmentIds"], ids)
        self.assertEqual(event.after_values["newRoundId"], latest["roundId"])
        self.assertEqual(self.process(latest["roundId"], "add_round", reason="下一次修改").status_code, 200)
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["schemeRounds"][-1]["reasonAttachmentIds"], [])
        self.assertEqual(self.node.business_data["schemeRounds"][-2]["reasonAttachmentIds"], ids)

    def test_invalid_reason_files_and_conflicts_do_not_leave_partial_uploads(self):
        round_id = self.prepare()
        original = deepcopy(self.node.business_data)
        for extra in ({}, {"reason": "  "}, {"expectedUpdatedAt": "stale"}):
            response = self.process_with_files(round_id, [
                SimpleUploadedFile("valid.pdf", b"%PDF-1.4", content_type="application/pdf"),
                SimpleUploadedFile("empty.txt", b"", content_type="text/plain"),
            ], **extra)
            self.assertIn(response.status_code, (400, 409), self.data(response))
            self.node.refresh_from_db()
            self.assertEqual(self.node.business_data, original)
            self.assertFalse(PrivateAttachment.objects.exists())
            self.assertFalse(any(path.is_file() for path in Path(self.media_root).rglob("*")))

    def test_event_failure_rolls_back_round_metadata_and_stored_files(self):
        round_id = self.prepare()
        original = deepcopy(self.node.business_data)
        with patch.object(presales_round_actions, "record_project_event", side_effect=RuntimeError("event unavailable")):
            with self.assertRaisesMessage(RuntimeError, "event unavailable"):
                self.process_with_files(round_id, [SimpleUploadedFile("reason.txt", b"notes")])
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data, original)
        self.assertFalse(PrivateAttachment.objects.exists())
        self.assertFalse(any(path.is_file() for path in Path(self.media_root).rglob("*")))

    def test_reason_file_limits_and_locked_nodes_reject_before_storage(self):
        round_id = self.prepare()
        for sizes in ([attachment_views.MAX_ATTACHMENT_SIZE + 1],
                      [attachment_views.MAX_ATTACHMENT_SIZE // 2 + 1] * 2):
            files = [SimpleUploadedFile(f"reason-{index}.bin", b"data") for index in range(len(sizes))]
            for file, size in zip(files, sizes):
                file.size = size
            with self.assertRaises(services.DomainValidationError) as raised:
                presales_round_actions.process_presales_round(self.request("post", "/"), self.project.pk,
                    self.node.node_key, {"roundId": round_id, "action": "add_round", "reason": "修改",
                                         "expectedUpdatedAt": self.node.updated_at.isoformat()}, reason_files=files)
            self.assertEqual(raised.exception.code, "ATTACHMENT_TOO_LARGE")
            self.assertFalse(PrivateAttachment.objects.exists())
        self.node.status = "completed"
        self.node.save()
        response = self.process_with_files(round_id, [SimpleUploadedFile("reason.txt", b"notes")])
        self.assertEqual(response.status_code, 409, self.data(response))
        self.assertFalse(PrivateAttachment.objects.exists())

    def test_reason_files_cannot_be_forged_or_changed_by_autosave(self):
        round_id = self.prepare()
        self.assertEqual(self.process_with_files(round_id, [SimpleUploadedFile("reason.txt", b"notes")]).status_code, 200)
        self.node.refresh_from_db()
        original = deepcopy(self.node.business_data)
        ids = original["schemeRounds"][-1]["reasonAttachmentIds"]
        for values in ({"reasonAttachmentIds": []}, {"reasonAttachmentIds": ["999"]}, {"attachmentIds": ids}):
            rounds = deepcopy(original["schemeRounds"])
            rounds[-1].update(values)
            response = views.project_node_autosave(self.request("patch", "/", {
                "businessData": {"schemeRounds": rounds}, "expectedUpdatedAt": self.node.updated_at.isoformat(),
            }), self.project.pk, self.node.node_key)
            self.assertEqual(response.status_code, 409, self.data(response))
            self.node.refresh_from_db()
            self.assertEqual(self.node.business_data, original)

    def test_deleting_last_round_cleans_only_its_reason_files_after_commit(self):
        self.node.business_data["schemeRounds"][0]["attachmentIds"] = []
        self.node.save()
        round_id = self.prepare()
        self.assertEqual(self.process_with_files(round_id, [SimpleUploadedFile("reason.txt", b"notes")]).status_code, 200)
        self.node.refresh_from_db()
        rounds = deepcopy(self.node.business_data["schemeRounds"])
        item = PrivateAttachment.objects.get(pk=rounds[-1]["reasonAttachmentIds"][0])
        with self.captureOnCommitCallbacks(execute=True):
            response = views.project_node_autosave(self.request("patch", "/", {
                "businessData": {"schemeRounds": rounds[:-1]}, "expectedUpdatedAt": self.node.updated_at.isoformat(),
            }), self.project.pk, self.node.node_key)
            self.assertEqual(response.status_code, 200, self.data(response))
            self.assertTrue(item.file.storage.exists(item.file.name))
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["schemeRounds"], rounds[:-1])
        self.assertFalse(PrivateAttachment.objects.filter(pk=item.pk).exists())
        self.assertFalse(item.file.storage.exists(item.file.name))

    def test_preparing_link_assigns_stable_ids_without_claiming_delivery(self):
        events = self.project.events.count()
        round_id = self.prepare()
        self.assertEqual(round_id, self.prepare())
        self.assertEqual(self.project.events.count(), events)
        self.assertEqual(self.node.business_data["schemeRounds"][0]["note"], "原备注")
        self.assertEqual(self.node.business_data["schemeRounds"][0]["attachmentIds"], ["88"])
        response = self.action("prepare-forward", {"roundIndex": True, "expectedUpdatedAt": self.node.updated_at.isoformat()})
        self.assertEqual(response.status_code, 404)

    def test_pass_finishes_node_and_keeps_parallel_branch_independent(self):
        round_id = self.prepare()
        stamp = self.node.updated_at.isoformat()
        response = self.process(round_id, "pass")
        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        self.assertEqual(self.node.status, "completed")
        self.assertEqual(self.project.nodes.get(node_key="budget-match").status, "active")
        self.assertEqual(self.project.nodes.get(node_key="early-plan-result").status, "pending")
        event = self.project.events.get(event_type="presales_round_processed")
        self.assertEqual(event.auth_user_id, "system-admin")
        self.assertEqual(event.after_values["roundId"], round_id)
        repeated = self.action("process", {"roundId": round_id, "action": "pass", "expectedUpdatedAt": stamp})
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(self.project.events.filter(event_type="presales_round_processed").count(), 1)

    def test_new_round_requires_reason_and_preserves_previous_materials(self):
        round_id = self.prepare()
        original = deepcopy(self.node.business_data["schemeRounds"][0])
        for reason in (None, "  ", 12, "x" * 5001):
            response = self.process(round_id, "add_round", reason=reason)
            self.assertEqual(response.status_code, 400, self.data(response))
            self.node.refresh_from_db()
            self.assertEqual(self.node.business_data["schemeRounds"], [original])
        stamp = self.node.updated_at.isoformat()
        response = self.process(round_id, "add_round", reason="  调整设备数量  ")
        self.assertEqual(response.status_code, 200, self.data(response))
        self.node.refresh_from_db()
        rounds = self.node.business_data["schemeRounds"]
        self.assertEqual(rounds[0], original)
        self.assertEqual(rounds[1]["reason"], "调整设备数量")
        self.assertEqual(rounds[1]["attachmentIds"], [])
        self.assertEqual(rounds[1]["note"], "")
        self.assertEqual(rounds[1]["plannedEndDate"], "")
        self.assertNotEqual(rounds[1]["roundId"], round_id)
        self.assertEqual(self.node.status, "active")
        self.assertEqual(self.node.presales_tasks.count(), 2)
        event = self.project.events.get(event_type="presales_round_processed")
        self.assertEqual(event.detail, "调整设备数量")
        repeated = self.action("process", {"roundId": round_id, "action": "add_round", "reason": "重复点击", "expectedUpdatedAt": stamp})
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(self.process(round_id, "pass").status_code, 409)

    def round_attachment(self):
        item = PrivateAttachment.objects.create(
            target_type="project_node", target_id=self.node.pk, category="scheme_submission",
            original_name="方案.pdf", mime_type="application/pdf", size=10,
            file=SimpleUploadedFile("plan.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
            uploaded_by="system-admin",
        )
        self.node.business_data["schemeRounds"][-1]["attachmentIds"] = [item.id]
        self.node.save()
        return item

    def test_inherited_attachment_can_be_removed_without_destroying_history_or_file(self):
        item = self.round_attachment()
        first = self.prepare()
        self.assertEqual(self.process(first, "add_round", reason="修改附件").status_code, 200)
        # Older saved rounds can still share an attachment. Preserve their
        # removal behavior even though newly created rounds no longer inherit.
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["schemeRounds"][-1]["attachmentIds"], [])
        self.node.business_data["schemeRounds"][-1]["attachmentIds"] = [item.id]
        self.node.save()
        second = self.prepare(1)
        before = deepcopy(self.node.business_data["schemeRounds"][0])
        self.assertEqual(self.process(first, "remove_attachment", attachmentId=item.id).status_code, 409)
        stale = self.node.updated_at.isoformat()
        self.node.business_data["schemeRounds"][-1]["note"] = "别人正在补充"
        self.node.save()
        response = self.action("process", {"roundId": second, "action": "remove_attachment",
                                          "attachmentId": item.id, "expectedUpdatedAt": stale})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.process(second, "remove_attachment", attachmentId=item.id).status_code, 200)
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["schemeRounds"][0], before)
        self.assertEqual(self.node.business_data["schemeRounds"][-1]["attachmentIds"], [])
        self.assertEqual(self.node.business_data["schemeRounds"][-1]["note"], "别人正在补充")
        self.assertTrue(PrivateAttachment.objects.filter(pk=item.pk).exists())
        self.assertTrue(item.file.storage.exists(item.file.name))
        download = attachment_views.attachment_download(self.request("get", "/"), item.pk)
        self.assertEqual(download.status_code, 200)
        download.close()
        self.assertEqual(attachment_views.attachment_item(self.request("delete", "/"), item.pk).status_code, 409)
        self.assertEqual(self.process(second, "remove_attachment", attachmentId=item.id).status_code, 404)
        self.assertEqual(self.process(second, "add_round", reason="第三轮").status_code, 200)
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["schemeRounds"][-1]["attachmentIds"], [])

    def test_unshared_file_is_deleted_and_other_nodes_files_cannot_be_removed(self):
        item = self.round_attachment()
        round_id = self.prepare()
        for changed in ({"target_id": self.project.nodes.get(node_key="budget-match").id},
                        {"category": "general"}):
            PrivateAttachment.objects.filter(pk=item.pk).update(**changed)
            self.assertEqual(self.process(round_id, "remove_attachment", attachmentId=item.id).status_code, 404)
            PrivateAttachment.objects.filter(pk=item.pk).update(target_id=self.node.pk, category="scheme_submission")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.process(round_id, "remove_attachment", attachmentId=item.id)
        self.assertEqual(response.status_code, 200, self.data(response))
        self.assertFalse(PrivateAttachment.objects.filter(pk=item.pk).exists())
        self.assertFalse(item.file.storage.exists(item.file.name))
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["schemeRounds"][-1]["attachmentIds"], [])

    def test_deleted_link_never_targets_a_replacement_round(self):
        first_id = self.prepare()
        self.assertEqual(self.process(first_id, "add_round", reason="修改").status_code, 200)
        removed_id = self.prepare(1)
        self.node.business_data["schemeRounds"] = self.node.business_data["schemeRounds"][:1]
        self.node.save()
        self.assertEqual(self.process(first_id, "add_round", reason="重新新增").status_code, 200)
        self.assertNotEqual(self.prepare(1), removed_id)
        response = self.process(removed_id, "pass")
        self.assertEqual(response.status_code, 404, self.data(response))

    def test_older_autosave_cannot_erase_a_new_round_or_bypass_latest_round(self):
        round_id = self.prepare()
        stamp = self.node.updated_at.isoformat()
        old_rounds = deepcopy(self.node.business_data["schemeRounds"])
        self.assertEqual(self.process(round_id, "add_round", reason="其他人要求补充").status_code, 200)
        for version in (None, stamp):
            payload = {"businessData": {"schemeRounds": old_rounds}}
            if version is not None:
                payload["expectedUpdatedAt"] = version
            response = views.project_node_autosave(self.request("patch", "/", payload), self.project.pk, self.node.node_key)
            self.assertEqual(response.status_code, 409, self.data(response))
            response = views.project_advance(self.request("post", "/", {**payload, "nodeKey": self.node.node_key}), self.project.pk)
            self.assertEqual(response.status_code, 409, self.data(response))
        self.node.refresh_from_db()
        rounds = self.node.business_data["schemeRounds"]
        self.assertEqual(len(rounds), 2)
        rounds[0]["note"] = "不能修改前一轮的备注"
        response = views.project_node_autosave(self.request("patch", "/", {
            "businessData": {"schemeRounds": rounds}, "expectedUpdatedAt": self.node.updated_at.isoformat(),
        }), self.project.pk, self.node.node_key)
        self.assertEqual(response.status_code, 409, self.data(response))
        self.assertEqual(self.data(response)["code"], "PRESALES_ROUND_READ_ONLY")
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["schemeRounds"][0]["note"], "原备注")
        rounds = deepcopy(self.node.business_data["schemeRounds"])
        rounds[-1]["note"] = "最新一轮仍可修改"
        response = views.project_node_autosave(self.request("patch", "/", {
            "businessData": {"schemeRounds": rounds}, "expectedUpdatedAt": self.node.updated_at.isoformat(),
        }), self.project.pk, self.node.node_key)
        self.assertEqual(response.status_code, 200, self.data(response))

    def test_history_cannot_be_rewritten_by_save_submit_or_advance(self):
        round_id = self.prepare()
        self.assertEqual(self.process(round_id, "add_round", reason="补充材料").status_code, 200)
        for changed in ({"plannedEndDate": "2026-10-20"}, {"attachmentIds": []}, {"reason": "改写历史原因"}):
            for action in ("draft", "submit_version", "advance"):
                self.node.refresh_from_db()
                original = deepcopy(self.node.business_data)
                rounds = deepcopy(original["schemeRounds"])
                rounds[0].update(changed)
                payload = {"businessData": {"schemeRounds": rounds}, "expectedUpdatedAt": self.node.updated_at.isoformat()}
                with self.subTest(changed=changed, action=action):
                    if action == "draft":
                        response = views.project_node_autosave(self.request("patch", "/", payload), self.project.pk, self.node.node_key)
                    elif action == "advance":
                        response = views.project_advance(self.request("post", "/", {**payload, "nodeKey": self.node.node_key}), self.project.pk)
                    else:
                        with self.assertRaises(services.DomainValidationError) as raised:
                            services.submit_project_node_version(self.request("post", "/"), self.project.pk,
                                node_key=self.node.node_key, node_values={"business_data": {"schemeRounds": rounds},
                                                                       "expected_updated_at": self.node.updated_at.isoformat()})
                        self.assertEqual(raised.exception.code, "PRESALES_ROUND_READ_ONLY")
                        response = None
                    if response is not None:
                        self.assertEqual(response.status_code, 409, self.data(response))
                        self.assertEqual(self.data(response)["code"], "PRESALES_ROUND_READ_ONLY")
                    self.node.refresh_from_db()
                    self.assertEqual(self.node.business_data, original)
                    self.assertEqual(self.node.status, "active")

    def test_completed_node_is_read_only_while_parallel_node_remains_editable(self):
        round_id = self.prepare()
        self.assertEqual(self.process(round_id, "pass").status_code, 200)
        self.node.refresh_from_db()
        original = deepcopy(self.node.business_data)
        response = views.project_node_autosave(self.request("patch", "/", {
            "businessData": {"deliveryNote": "不能改写完成节点"},
        }), self.project.pk, self.node.node_key)
        self.assertEqual(response.status_code, 409, self.data(response))
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data, original)
        response = views.project_node_autosave(self.request("patch", "/", {
            "businessData": {"deliveryNote": "并列节点仍在进行"},
        }), self.project.pk, "budget-match")
        self.assertEqual(response.status_code, 200, self.data(response))

    def test_completed_approval_info_cannot_be_rewritten_through_project_patch(self):
        original = {"early-approval": {"reason": "已完成立项的历史信息"}}
        self.project.business_data = {"projectInfoRecords": original}
        self.project.save()
        for records in ({}, {"early-approval": {"reason": "修改已完成立项"}}):
            response = views.project_item(self.request("patch", "/", {
                "businessData": {"projectInfoRecords": records},
            }), self.project.pk)
            self.assertEqual(response.status_code, 409, self.data(response))
            self.project.refresh_from_db()
            self.assertEqual(self.project.business_data["projectInfoRecords"], original)

    def test_completed_midsales_node_cannot_change_related_products(self):
        self.project.service_type = ServiceProject.TYPE_MIDSALES
        self.project.save()
        self.node.node_key = "device-install"
        self.node.status = "completed"
        self.node.business_data = {"relatedProducts": [{"productId": 123}]}
        self.node.save()
        with patch.object(views, "fetch_products_by_ids", return_value={}):
            response = views.project_node_related_products(self.request("patch", "/", {"productIds": []}),
                                                          self.project.pk, self.node.node_key)
        self.assertEqual(response.status_code, 409, self.data(response))
        self.node.refresh_from_db()
        self.assertEqual(self.node.business_data["relatedProducts"], [{"productId": 123}])

    def test_invalid_or_duplicate_ids_are_rejected_without_partial_writes(self):
        for round_id in ([], {}, 12, " ", "x" * 65):
            self.node.business_data["schemeRounds"] = [{"roundId": round_id}]
            self.node.save()
            response = self.action("prepare-forward", {"roundIndex": 0, "expectedUpdatedAt": self.node.updated_at.isoformat()})
            self.assertEqual(response.status_code, 400, self.data(response))
        self.node.business_data["schemeRounds"] = [{"roundId": "same"}, {"roundId": "same"}]
        self.node.save()
        response = self.action("prepare-forward", {"roundIndex": 0, "expectedUpdatedAt": self.node.updated_at.isoformat()})
        self.assertEqual(response.status_code, 400, self.data(response))

    def test_stale_content_unknown_operation_and_locked_nodes_do_not_write(self):
        round_id = self.prepare()
        stamp = self.node.updated_at.isoformat()
        self.node.business_data["schemeRounds"][0]["note"] = "有人刚修改"
        self.node.save()
        for operation, payload in (("prepare-forward", {"roundIndex": 0}), ("process", {"roundId": round_id, "action": "pass"})):
            response = self.action(operation, {**payload, "expectedUpdatedAt": stamp})
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.process(round_id, "invalid").status_code, 400)
        self.node.status = "pending"
        self.node.save()
        self.assertEqual(self.process(round_id, "pass").status_code, 409)

    def test_management_channel_and_crm_access_remain_required(self):
        round_id = self.prepare()
        payload = {"roundId": round_id, "action": "pass", "expectedUpdatedAt": self.node.updated_at.isoformat()}
        request = self.request("post", "/", payload, admin=False)
        request.auth_token_claims = {"chn": "wechat-mini", "aud": "after-sales-mobile"}
        response = views.project_round_action(request, self.project.pk, self.node.node_key, "process")
        self.assertEqual(response.status_code, 403)
        self.project.source_crm_id = "restricted-crm"
        self.project.save()
        denied = services.DomainValidationError("CRM无权限", code="CRM_PERMISSION_DENIED", status=403)
        with patch.object(crm_source, "assert_crm_project_access", side_effect=denied) as check:
            response = self.action("process", payload)
            self.assertEqual(response.status_code, 403)
            check.assert_called_once()
        self.node.refresh_from_db()
        self.assertEqual(self.node.status, "active")

    def test_other_service_types_cannot_use_round_processing(self):
        self.project.service_type = ServiceProject.TYPE_MIDSALES
        self.project.save()
        response = self.action("prepare-forward", {"roundIndex": 0, "expectedUpdatedAt": self.node.updated_at.isoformat()})
        self.assertEqual(response.status_code, 404)
