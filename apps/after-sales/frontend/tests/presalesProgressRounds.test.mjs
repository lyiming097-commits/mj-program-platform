import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  canAddPresalesProgressRound,
  canEditPresalesProgressRound,
  canRemovePresalesProgressRound,
  emptyPresalesProgressRound,
  normalizePresalesProgressRound,
  presalesRoundTimeError,
  presalesRoundTiming,
} from "../src/components/presalesProgressRounds.js";

test("new presales rounds do not carry approval results", () => {
  assert.equal("result" in emptyPresalesProgressRound(), false);
  assert.equal("designDate" in emptyPresalesProgressRound(), false);
  assert.deepEqual(normalizePresalesProgressRound({
    designDate: "2026-09-20",
    result: "驳回",
    note: "待补充资料",
    attachmentIds: [12],
  }), {
    plannedStartDate: "",
    plannedEndDate: "",
    designDate: "2026-09-20",
    submitDate: "",
    submittedAt: "",
    note: "待补充资料",
    attachmentIds: ["12"],
  });
});

test("optional round schedules validate only the planned interval", () => {
  assert.equal(presalesRoundTimeError(emptyPresalesProgressRound()), "");
  assert.equal(presalesRoundTimeError({ plannedEndDate: "2026-10-14" }), "");
  assert.equal(presalesRoundTimeError({ plannedStartDate: "2026-10-14", plannedEndDate: "2026-10-13" }), "预计完成时间不能早于计划开始时间");
  assert.equal(presalesRoundTimeError({ plannedStartDate: "2026-10-14", plannedEndDate: "2026-10-14", designDate: "2026-10-12" }), "");
  assert.ok(canAddPresalesProgressRound([{ plannedEndDate: "2026-10-14" }]));
});

test("round deadlines use Shanghai calendar days and automatic node completion", () => {
  const deadline = { plannedEndDate: "2026-10-14" };
  assert.deepEqual(presalesRoundTiming({}, Date.parse("2026-10-15T00:00:00Z")), { label: "未设置预计完成时间", tone: "pending" });
  assert.deepEqual(presalesRoundTiming({ designDate: "2026-10-13" }), { label: "未设置预计完成时间", tone: "pending" });
  assert.deepEqual(presalesRoundTiming({}, Date.now(), { completed: true }), { label: "已完成", tone: "done" });
  assert.equal(presalesRoundTiming(deadline, Date.parse("2026-10-14T15:59:59Z")).label, "未超时");
  assert.equal(presalesRoundTiming(deadline, Date.parse("2026-10-14T16:00:00Z")).label, "已延期 1 天");
  assert.equal(presalesRoundTiming({ ...deadline, designDate: "2026-10-14" }, Date.parse("2026-10-14T16:00:00Z")).label, "已延期 1 天");
  assert.equal(presalesRoundTiming(deadline, Date.now(), { completed: true, completedAt: "2026-10-14T15:59:59Z" }).label, "按时完成");
  assert.equal(presalesRoundTiming(deadline, Date.now(), { completed: true, completedAt: "2026-10-16T16:00:00Z" }).label, "延期完成 3 天");
  assert.equal(presalesRoundTiming({ plannedStartDate: "2026-10-16", plannedEndDate: "2026-10-18" }, Date.parse("2026-10-14T16:00:00Z")).label, "未到开始日期");
});

test("another round needs a recorded activity, not an approval result", () => {
  assert.equal(canAddPresalesProgressRound([]), true);
  assert.equal(canAddPresalesProgressRound([{ result: "通过" }]), false);
  assert.equal(canAddPresalesProgressRound([{ designDate: "2026-09-20" }]), true);
  assert.equal(canAddPresalesProgressRound([{ attachmentIds: [12] }]), true);
  assert.equal(canAddPresalesProgressRound([{ note: "客户要求修改" }]), true);
  assert.equal(canAddPresalesProgressRound([{ note: "  " }]), false);
});

test("only a last round without attachments can be removed while preserving the first round", () => {
  const initial = emptyPresalesProgressRound();
  assert.equal(canRemovePresalesProgressRound([initial]), false);
  assert.equal(canRemovePresalesProgressRound([initial, emptyPresalesProgressRound()]), true);
  assert.equal(canRemovePresalesProgressRound([initial, { ...initial, designDate: "2026-09-20" }]), true);
  assert.equal(canRemovePresalesProgressRound([initial, { ...initial, attachmentIds: ["12"] }]), false);
});

test("only the latest round of an editable node can be changed", () => {
  const rounds = [emptyPresalesProgressRound(), emptyPresalesProgressRound()];
  const managed = { editable: true, managed: true, progressSubmitted: false };
  assert.equal(canEditPresalesProgressRound(rounds, 0, managed), false);
  assert.equal(canEditPresalesProgressRound(rounds, 1, managed), true);
  assert.equal(canEditPresalesProgressRound(rounds, -1, managed), false);
  assert.equal(canEditPresalesProgressRound(rounds, 2, managed), false);
  assert.equal(canEditPresalesProgressRound(rounds, 0, { ...managed, editable: false }), false);
  assert.equal(canEditPresalesProgressRound(rounds, 0, { ...managed, progressSubmitted: true }), false);
  assert.equal(canEditPresalesProgressRound(rounds, 1, { ...managed, completed: true }), false);
  assert.equal(canEditPresalesProgressRound(rounds, 0, { ...managed, managed: false }), false);
  assert.equal(canEditPresalesProgressRound(rounds, 1, { ...managed, managed: false }), true);
  assert.equal(canEditPresalesProgressRound(rounds, 1, { ...managed, managed: false, progressSubmitted: true }), false);
});

test("rounds changed during a save remain queued for autosave", () => {
  const workspace = readFileSync(new URL("../src/components/ProjectWorkspace.vue", import.meta.url), "utf8");
  const saveRounds = workspace.split("async function updatePresalesSchemeRounds(rounds) {")[1].split("function openPresalesProjectInfoModal()")[0];
  assert.match(saveRounds, /JSON\.stringify\(latestDraft\) === JSON\.stringify\(draft\)/);
  assert.match(saveRounds, /else if \(latestDraft && drawerOpen\.value && nodeEditable\.value\) \{\s*scheduleNodeAutosave\(latestDraft\)/);
});

test("presales submission keeps attachments and note in the same dialog", () => {
  const component = readFileSync(new URL("../src/components/PresalesProgressPanel.vue", import.meta.url), "utf8");
  const [card, dialog] = component.split("<ModalShell");
  assert.match(card, /@click="openSubmission\(index\)"/);
  assert.doesNotMatch(card, /<span>备注<\/span>/);
  assert.match(dialog, /<AttachmentPanel/);
  assert.match(dialog, /<span>备注<\/span>\s*<textarea v-model="noteDraft"/);
  assert.match(dialog, /@close="closeSubmission"/);
  assert.doesNotMatch(dialog, /as-round-submitted-time|<span>提交时间<\/span>/);
  assert.match(card, /删除最后一轮/);
  assert.match(card, /@click="removeLastRound"/);
});
