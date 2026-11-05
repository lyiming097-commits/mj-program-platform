<script setup>
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from "vue";
import { Check, ChevronRight, Copy, LoaderCircle, Paperclip, Plus, Share2, Trash2 } from "@lucide/vue";
import AttachmentPanel from "@/components/AttachmentPanel.vue";
import FileSelectionPanel from "@/components/FileSelectionPanel.vue";
import UnsavedChangesDialog from "@/components/UnsavedChangesDialog.vue";
import DateField from "@/components/DateField.vue";
import ModalShell from "@/components/ModalShell.vue";
import PlatformConfirmDialog from "@platform-ui/PlatformConfirmDialog.vue";
import MallSolutionEntry from "@/components/MallSolutionEntry.vue";
import { serviceApi } from "@/serviceApi";
import { MAX_ATTACHMENT_MB, MAX_ATTACHMENT_SIZE } from "@/attachmentLimits";
import { createRoundSharer, presalesRoundCard } from "@/components/presalesRoundForward";
import { canAddPresalesProgressRound, canEditPresalesProgressRound, canRemovePresalesProgressRound, emptyPresalesProgressRound, presalesRoundTimeError, presalesRoundTiming } from "@/components/presalesProgressRounds";

const props = defineProps({
  nodeKey: { type: String, default: "" },
  nodeName: { type: String, default: "" },
  targetId: { type: [String, Number], default: "" },
  rounds: { type: Array, default: () => [] },
  editable: { type: Boolean, default: false },
  allowAddRound: { type: Boolean, default: false },
  submitEnabled: { type: Boolean, default: false },
  progressSubmitted: { type: Boolean, default: false },
  submitting: { type: Boolean, default: false },
  source: { type: String, default: "" },
  managed: { type: Boolean, default: false },
  sourceCrmId: { type: [String, Number], default: "" },
  now: { type: Number, default: () => Date.now() },
  completed: { type: Boolean, default: false },
  completedAt: { type: String, default: "" },
  focusRoundId: { type: String, default: "" },
  prepareForward: { type: Function, default: null },
  processRound: { type: Function, default: null },
});

const emit = defineEmits(["update:rounds", "changed", "error", "success", "submit", "draft-change"]);

const WORK_LABELS = Object.freeze({
  "early-plan": "前期方案设计",
  "budget-match": "预算匹配",
  "project-filing": "项目申报",
  "late-plan": "后期方案设计",
  "device-plan": "设备方案设计",
  budget: "工程预算",
  "device-budget": "设备预算",
  "cost-control": "工程成本管控",
  "device-cost-control": "设备成本管控",
  rendering: "效果图设计",
  "tender-plan": "招标方案设计",
  layout: "平面设计",
  "bid-prep": "投标准备",
  construction: "施工图设计",
});
const ATTACHMENT_CATEGORIES = Object.freeze([{ value: "scheme_submission", label: "提交附件" }]);
const REASON_ATTACHMENT_CATEGORIES = Object.freeze([{ value: "scheme_submission", label: "原因附件" }]);
const activeIndex = ref(-1);
const panelElement = ref(null);
const submissionCloseButton = ref(null);
const attachmentItems = ref([]);
const noteDraft = ref("");
const operationBusy = ref(false);
const forwardingIndex = ref(-1);
const operationError = ref("");
const reasonOpen = ref(false);
const reasonErrorId = useId();
const reasonDraft = ref("");
const reasonInvalid = ref(false);
const reasonFiles = ref([]);
const reasonPreviewOpen = ref(false);
const discardReasonOpen = ref(false);
let resolveReasonDiscard = null;
const reasonIndex = ref(-1);
const removalItem = ref(null);
const copyLink = ref("");
const sharer = createRoundSharer({ getConfig: serviceApi.roundShareConfig });
let openedFocus = "";
const roundList = computed(() => Array.isArray(props.rounds) ? props.rounds : []);
const workLabel = computed(() => WORK_LABELS[props.nodeKey] || props.nodeName || "节点工作");
const activeRound = computed(() => roundList.value[activeIndex.value] || null);
const activeAttachmentIds = computed(() => (
  Array.isArray(activeRound.value?.attachmentIds)
    ? activeRound.value.attachmentIds.map(String)
    : []
));
const submissionTitle = computed(() => `第 ${activeIndex.value + 1} 次提交`);
const canProcess = computed(() => props.managed && props.processRound && props.editable
  && activeIndex.value === roundList.value.length - 1 && Boolean(activeRound.value));
const busy = computed(() => props.submitting || operationBusy.value);
const reasonDirty = computed(() => reasonOpen.value && Boolean(reasonDraft.value.trim() || reasonFiles.value.length));
const reasonAttachmentIds = computed(() => (activeRound.value?.reasonAttachmentIds || []).map(String));

watch([reasonDirty, operationBusy], ([dirty, processing]) => {
  emit("draft-change", { dirty, busy: processing });
}, { immediate: true, flush: "sync" });

function discardReasonDraft() {
  reasonOpen.value = false;
  reasonDraft.value = "";
  reasonInvalid.value = false;
  reasonFiles.value = [];
  discardReasonOpen.value = false;
  resolveReasonDiscard?.(true);
  resolveReasonDiscard = null;
}

function requestCloseReason() {
  if (busy.value) return Promise.resolve(false);
  if (!reasonDirty.value) { discardReasonDraft(); return Promise.resolve(true); }
  if (discardReasonOpen.value) return Promise.resolve(false);
  discardReasonOpen.value = true;
  return new Promise(resolve => { resolveReasonDiscard = resolve; });
}

function keepReasonDraft() {
  discardReasonOpen.value = false;
  resolveReasonDiscard?.(false);
  resolveReasonDiscard = null;
}

function addReasonFiles(files) {
  if (busy.value) return;
  const next = [...reasonFiles.value, ...files];
  if (next.some(file => !file.size)) {
    operationError.value = "不能上传空文件";
    return;
  }
  if (next.reduce((total, file) => total + file.size, 0) > MAX_ATTACHMENT_SIZE) {
    operationError.value = `本次原因附件合计不能超过${MAX_ATTACHMENT_MB}MB`;
    return;
  }
  reasonFiles.value = next;
  operationError.value = "";
}

defineExpose({ discardReasonDraft, requestCloseReason });

function operationFailed(reason) {
  operationError.value = reason?.message || "操作失败，请重试";
  emit("error", operationError.value);
}

async function forwardRound(index) {
  if (busy.value || !props.prepareForward) return;
  operationBusy.value = true;
  forwardingIndex.value = index;
  operationError.value = "";
  try {
    if (index === activeIndex.value) saveNote();
    await nextTick();
    const prepared = await props.prepareForward({ index });
    const card = presalesRoundCard({ ...prepared, origin: window.location.origin });
    const result = await sharer.share(card);
    if (result.status === "unsupported") copyLink.value = card.url;
    else if (result.status === "shared") emit("success", "钉钉转发已完成");
  } catch (reason) { operationFailed(reason); }
  finally { operationBusy.value = false; forwardingIndex.value = -1; }
}

async function copyForwardLink() {
  try {
    await navigator.clipboard.writeText(copyLink.value);
    emit("success", "钉钉链接已复制，可粘贴到钉钉聊天");
  } catch { operationFailed(new Error("复制失败，请选中上方链接后手动复制")); }
}

function requestNewRound(index = roundList.value.length - 1) {
  if (busy.value) return;
  reasonIndex.value = index;
  reasonDraft.value = "";
  reasonInvalid.value = false;
  reasonFiles.value = [];
  operationError.value = "";
  reasonOpen.value = true;
}

async function processRound(action) {
  if (busy.value || !props.processRound) return;
  const index = action === "add_round" ? reasonIndex.value : activeIndex.value;
  if (action === "add_round" && !reasonDraft.value.trim()) {
    reasonInvalid.value = true;
    operationError.value = "请填写新增一轮的原因";
    return;
  }
  operationBusy.value = true;
  operationError.value = "";
  try {
    saveNote();
    await nextTick();
    const newIndex = await props.processRound({ index, action, reason: reasonDraft.value.trim(),
      reasonFiles: action === "add_round" ? [...reasonFiles.value] : [] });
    discardReasonDraft();
    if (action === "add_round") {
      operationBusy.value = false;
      await nextTick();
      openSubmission(newIndex);
      emit("success", "已新增一轮，可上传本轮附件");
    } else {
      resetSubmission();
      emit("success", "本轮已通过，节点已完成");
    }
  } catch (reason) { operationFailed(reason); }
  finally { operationBusy.value = false; }
}

function roundEditable(index) {
  return !operationBusy.value && canEditPresalesProgressRound(roundList.value, index, props);
}

function canAddRound() {
  return props.editable && !props.completed && props.allowAddRound && !busy.value && canAddPresalesProgressRound(roundList.value);
}

function updateRound(index, values) {
  if (!canEditPresalesProgressRound(roundList.value, index, props)) return;
  const next = { ...roundList.value[index], ...values };
  const error = presalesRoundTimeError(next);
  if (error) {
    emit("error", `第 ${index + 1} 轮任务${error}`);
    return;
  }
  emit("update:rounds", roundList.value.map((round, roundIndex) => (
    roundIndex === index ? { ...round, ...values } : { ...round }
  )));
}

function addRound() {
  if (!canAddRound()) return;
  if (props.managed && props.processRound && roundList.value.length) {
    requestNewRound();
    return;
  }
  emit("update:rounds", [...roundList.value.map((round) => ({ ...round })), emptyPresalesProgressRound()]);
}

function requestRemoveAttachment(item) {
  if (busy.value || !canProcess.value) return;
  removalItem.value = item;
  operationError.value = "";
}

async function removeRoundAttachment() {
  if (busy.value || !removalItem.value || !canProcess.value) return;
  operationBusy.value = true;
  operationError.value = "";
  try {
    saveNote();
    await nextTick();
    await props.processRound({ index: activeIndex.value, action: "remove_attachment", attachmentId: removalItem.value.id });
    removalItem.value = null;
    operationBusy.value = false;
    await nextTick();
    submissionCloseButton.value?.focus();
    emit("success", "已从本轮移除附件，历史轮次保留不变");
  } catch (reason) { operationFailed(reason); }
  finally { operationBusy.value = false; }
}

function removeLastRound() {
  if (!props.allowAddRound || busy.value || !roundEditable(roundList.value.length - 1) || roundList.value.length <= 1) return;
  if (!canRemovePresalesProgressRound(roundList.value)) {
    emit("error", "请先删除最后一轮的附件，再删除该轮次");
    return;
  }
  const last = roundList.value.at(-1);
  if ((last.plannedStartDate || last.plannedEndDate || last.designDate || last.submitDate || last.submittedAt || String(last.note || "").trim() || last.reasonAttachmentIds?.length)
    && !window.confirm(`确认删除第 ${roundList.value.length} 轮及其填写的内容？`)) return;
  emit("update:rounds", roundList.value.slice(0, -1).map((round) => ({ ...round })));
}

function submitRounds() {
  emit("submit", roundList.value.map((round) => ({
    ...round,
    attachmentIds: Array.isArray(round.attachmentIds) ? [...round.attachmentIds] : [],
  })));
}

function openSubmission(index) {
  if (busy.value) return;
  attachmentItems.value = [];
  activeIndex.value = index;
  noteDraft.value = String(roundList.value[index]?.note || "");
  operationError.value = "";
}

function saveNote() {
  if (!activeRound.value || !canEditPresalesProgressRound(roundList.value, activeIndex.value, props)) return;
  if (noteDraft.value !== String(activeRound.value.note || "")) {
    updateRound(activeIndex.value, { note: noteDraft.value });
  }
}

function resetSubmission() {
  activeIndex.value = -1;
  attachmentItems.value = [];
  noteDraft.value = "";
  discardReasonDraft();
  removalItem.value = null;
  copyLink.value = "";
  operationError.value = "";
}

function closeSubmission() {
  if (busy.value || removalItem.value) return;
  saveNote();
  resetSubmission();
}

function latestAttachment(items) {
  return [...items].sort((left, right) => (
    new Date(right.createdAt || 0).getTime() - new Date(left.createdAt || 0).getTime()
  ))[0] || null;
}

function handleAttachmentChanged(items) {
  attachmentItems.value = Array.isArray(items) ? items : [];
  emit("changed", attachmentItems.value);
}

function handleUploaded(items) {
  const uploaded = Array.isArray(items) ? items.filter((item) => item?.id) : [];
  if (!activeRound.value || !uploaded.length) return;
  const attachmentIds = [...new Set([
    ...activeAttachmentIds.value,
    ...uploaded.map((item) => String(item.id)),
  ])];
  const latest = latestAttachment(uploaded);
  const submittedAt = latest?.createdAt || new Date().toISOString();
  updateRound(activeIndex.value, {
    attachmentIds,
    submittedAt,
    submitDate: submittedAt.slice(0, 10),
  });
  emit("success", `${submissionTitle.value}附件已上传`);
}

function handleRemoved(item) {
  if (!activeRound.value || !item?.id) return;
  const attachmentIds = activeAttachmentIds.value.filter((id) => id !== String(item.id));
  const remaining = attachmentItems.value.filter((attachment) => attachmentIds.includes(String(attachment.id)));
  const latest = latestAttachment(remaining);
  updateRound(activeIndex.value, {
    attachmentIds,
    submittedAt: latest?.createdAt || "",
    submitDate: latest?.createdAt?.slice(0, 10) || "",
  });
  emit("success", `${submissionTitle.value}附件已更新`);
}

function formatDateTime(value) {
  return value ? String(value).replace("T", " ").slice(0, 16) : "尚未上传";
}

watch(() => props.targetId, resetSubmission);
onBeforeUnmount(() => {
  resolveReasonDiscard?.(false);
  emit("draft-change", { dirty: false, busy: false });
});
watch([() => props.focusRoundId, () => props.targetId, roundList], async ([id, target]) => {
  if (!id || openedFocus === `${target}:${id}`) return;
  await nextTick();
  const index = roundList.value.findIndex(round => round.roundId === id);
  openedFocus = `${target}:${id}`;
  if (index < 0) emit("error", "转发的轮次已删除，请查看项目中的最新轮次");
  else {
    openSubmission(index);
    await nextTick();
    const section = panelElement.value?.closest("details");
    if (section) section.open = true;
  }
}, { immediate: true });
</script>

<template>
  <div ref="panelElement" class="as-presales-progress-panel">
    <div v-if="roundList.length" class="as-scheme-rounds">
      <div v-for="(round, index) in roundList" :key="round.roundId || `${targetId}-${index}`" class="as-form-grid as-presales-round" :class="{ 'as-presales-round--scheduled': managed }">
        <template v-if="managed">
          <div class="as-presales-task-head"><strong>第 {{ index + 1 }} 次{{ workLabel }}</strong><span class="as-presales-task-status" :class="`is-${presalesRoundTiming(round, now, { completed, completedAt }).tone}`">{{ presalesRoundTiming(round, now, { completed, completedAt }).label }}</span></div>
          <div class="as-presales-task-dates">
            <label v-for="field in [{ key: 'plannedStartDate', label: '计划开始时间' }, { key: 'plannedEndDate', label: '预计完成时间' }]" :key="field.key" class="as-field">
              <span>{{ field.label }}</span>
              <DateField v-if="roundEditable(index)" :model-value="round[field.key] || ''" :disabled="busy" :aria-label="`第 ${index + 1} 次${workLabel}${field.label}`" @update:model-value="updateRound(index, { [field.key]: $event })" />
              <input v-else :value="round[field.key] || '未填写'" readonly :aria-label="`第 ${index + 1} 次${workLabel}${field.label}`">
            </label>
          </div>
        </template>
        <label v-else class="as-field">
          <span>第 {{ index + 1 }} 次{{ workLabel }}</span>
          <DateField v-if="roundEditable(index)" :model-value="round.designDate || ''" :aria-label="`第 ${index + 1} 次${workLabel}`" @update:model-value="updateRound(index, { designDate: $event })" />
          <input v-else :value="round.designDate || '未填写'" readonly>
        </label>
        <div class="as-field">
          <span>第 {{ index + 1 }} 次提交</span>
          <div class="as-round-submit-actions">
          <button type="button" class="as-round-attachment-button" :disabled="busy" :aria-label="`第 ${index + 1} 次提交：${roundEditable(index) ? '填写' : '查看'}附件和备注`" @click="openSubmission(index)">
            <Paperclip />
            <span><strong>{{ roundEditable(index) ? '提交附件与备注' : '查看提交' }}</strong><small>{{ (round.attachmentIds || []).length }} 个文件 · {{ round.note?.trim() ? '已填写备注' : '无备注' }}<template v-if="round.submittedAt"> · {{ formatDateTime(round.submittedAt) }}</template></small></span>
            <ChevronRight />
          </button>
          <button v-if="managed && prepareForward && editable" type="button" class="as-button as-button--secondary" :disabled="busy" :aria-label="`转发第 ${index + 1} 轮`" @click="forwardRound(index)"><LoaderCircle v-if="forwardingIndex === index" class="as-spin" /><Share2 v-else />{{ forwardingIndex === index ? '转发中…' : '转发' }}</button>
          </div>
        </div>
        <p v-if="round.reason" class="as-round-reason"><strong>新增原因：</strong>{{ round.reason }}<template v-if="round.reasonAttachmentIds?.length">（含 {{ round.reasonAttachmentIds.length }} 个原因附件，可在本轮提交窗口查看）</template></p>
      </div>
    </div>
    <div v-else class="as-empty as-empty--compact">{{ managed ? '尚未填写推进记录' : '项目人员尚未填写推进记录' }}</div>
    <div class="as-presales-progress-actions">
      <button v-if="allowAddRound" type="button" class="as-button as-button--secondary as-scheme-add-button" :disabled="!canAddRound()" @click="addRound"><Plus />新增一轮</button>
      <button v-if="allowAddRound && roundList.length > 1" type="button" class="as-button as-button--danger" :disabled="busy" @click="removeLastRound"><Trash2 />删除最后一轮</button>
      <button v-if="submitEnabled" type="button" class="as-button" :class="progressSubmitted ? 'as-button--secondary' : 'as-button--primary'" :disabled="submitting || progressSubmitted" @click="submitRounds"><LoaderCircle v-if="submitting" class="as-spin" /><Check v-else />{{ submitting ? '提交中' : progressSubmitted ? '已提交' : '提交推进' }}</button>
    </div>

    <p v-if="operationError && !activeRound && !reasonOpen && !copyLink" class="as-alert as-alert--error" role="alert">{{ operationError }}</p>
    <ModalShell :open="Boolean(activeRound) && !reasonOpen && !copyLink" :title="submissionTitle" @close="closeSubmission">
      <div v-if="activeRound" class="as-round-attachment-modal">
        <p v-if="operationError" class="as-alert as-alert--error" role="alert">{{ operationError }}</p>
        <p v-if="managed && processRound && !canProcess" class="as-round-context" role="status">{{ completed ? '节点已通过，本轮资料供查看。' : !editable ? '当前节点尚未解锁或项目已结束。' : '这是历史轮次，请查看最新一轮后处理。' }}</p>
        <p v-if="activeRound.reason" class="as-round-reason"><strong>新增原因：</strong>{{ activeRound.reason }}</p>
        <section v-if="reasonAttachmentIds.length" aria-label="新增原因附件">
          <h3 class="as-round-section-title">原因附件</h3>
          <AttachmentPanel target-type="project_node" :target-id="targetId" :categories="REASON_ATTACHMENT_CATEGORIES" :item-ids="reasonAttachmentIds" :editable="false" :source="source" compact @error="operationError = $event" />
        </section>
        <MallSolutionEntry v-if="managed" :key="`${targetId}:${activeIndex}`" :source-crm-id="sourceCrmId" />
        <AttachmentPanel target-type="project_node" :target-id="targetId" :categories="ATTACHMENT_CATEGORIES" :item-ids="activeAttachmentIds" :round-index="activeIndex" :round-id="activeRound.roundId || ''" :editable="roundEditable(activeIndex)" :request-remove="managed && processRound ? requestRemoveAttachment : null" :remove-label="managed && processRound ? '移除' : '删除'" :source="source" compact upload-label="上传附件" @changed="handleAttachmentChanged" @uploaded="handleUploaded" @removed="handleRemoved" @error="emit('error', $event)" />
        <label class="as-field">
          <span>备注</span>
          <textarea v-model="noteDraft" rows="4" maxlength="5000" :readonly="busy || !roundEditable(activeIndex)" :placeholder="roundEditable(activeIndex) ? '填写本轮说明' : '暂无备注'"></textarea>
        </label>
      </div>
      <template #footer>
        <button ref="submissionCloseButton" type="button" class="as-button as-button--secondary" :disabled="busy" @click="closeSubmission">{{ roundEditable(activeIndex) ? '保存并关闭' : '关闭' }}</button>
        <button v-if="canProcess" type="button" class="as-button as-button--secondary" :disabled="busy" @click="requestNewRound(activeIndex)"><Plus />新增一轮</button>
        <button v-if="canProcess" type="button" class="as-button as-button--primary" :disabled="busy" @click="processRound('pass')"><LoaderCircle v-if="operationBusy" class="as-spin" /><Check v-else />通过</button>
      </template>
    </ModalShell>
    <PlatformConfirmDialog :open="Boolean(removalItem)" title="移除本轮附件" :message="`确认从本轮移除“${removalItem?.originalName || ''}”？历史轮次的资料保留不变。`" confirm-text="确认移除" :busy="busy" :error="operationError" @cancel="removalItem = null" @confirm="removeRoundAttachment" />
    <ModalShell :open="reasonOpen" title="新增一轮" description="新一轮从空附件开始，历史轮次的附件仍可查看。" manage-focus :busy="busy" :suspended="discardReasonOpen || reasonPreviewOpen" @close="requestCloseReason">
      <p v-if="operationError" :id="reasonErrorId" class="as-alert as-alert--error" role="alert">{{ operationError }}</p>
      <label class="as-field"><span>新增原因</span><textarea v-model="reasonDraft" required rows="4" maxlength="5000" :disabled="busy" :aria-invalid="reasonInvalid && !reasonDraft.trim()" :aria-describedby="operationError ? reasonErrorId : undefined" placeholder="说明需要补充或修改的内容"></textarea></label>
      <section class="as-round-reason-files" aria-label="原因附件">
        <h3 class="as-round-section-title">原因附件（选填）</h3>
        <FileSelectionPanel :files="reasonFiles" :disabled="busy" preview-enabled button-label="添加原因附件" @preview-change="reasonPreviewOpen = $event" @change="addReasonFiles" @remove="reasonFiles = reasonFiles.filter((_, index) => index !== $event)" />
        <p class="as-round-context">支持任意类型，本次合计不超过 {{ MAX_ATTACHMENT_MB }}MB；点击确认新增后，与原因一起保存。</p>
      </section>
      <p v-if="operationBusy" class="as-round-context" role="status">正在保存原因和附件，请稍候…</p>
      <template #footer><button type="button" class="as-button as-button--secondary" :disabled="busy" @click="requestCloseReason">取消</button><button type="button" class="as-button as-button--primary" :disabled="busy" @click="processRound('add_round')"><LoaderCircle v-if="operationBusy" class="as-spin" /><Plus v-else />{{ operationBusy ? '正在保存…' : '确认新增' }}</button></template>
    </ModalShell>
    <UnsavedChangesDialog :open="discardReasonOpen" :layer="3400" message="新增原因和所选附件尚未提交，放弃后不会保留。" @cancel="keepReasonDraft" @confirm="discardReasonDraft" />
    <ModalShell :open="Boolean(copyLink)" title="转发项目轮次" description="复制下方链接发送到钉钉聊天，接收人点击后在钉钉中打开对应项目轮次。" @close="copyLink = ''">
      <p v-if="operationError" class="as-alert as-alert--error" role="alert">{{ operationError }}</p>
      <label class="as-field"><span>项目轮次链接</span><input :value="copyLink" readonly @focus="$event.target.select()"></label>
      <template #footer><button type="button" class="as-button as-button--secondary" @click="copyLink = ''">关闭</button><button type="button" class="as-button as-button--primary" @click="copyForwardLink"><Copy />复制链接</button></template>
    </ModalShell>
  </div>
</template>

<style scoped>
:global(.platform-confirm-backdrop) { --mj-layer-confirm: 3300; --mj-space: 16px; --mj-control-height: 32px; --mj-control-radius: 7px; --mj-text-size: 12px; --mj-font: inherit; --mj-border: var(--as-border); --mj-surface: var(--as-panel); --mj-body: var(--as-text); --mj-text: var(--as-text); --mj-muted: var(--as-muted); --mj-primary: var(--as-primary); --mj-danger: var(--as-danger); }
.as-presales-round--scheduled { grid-template-columns: minmax(0, 1.5fr) minmax(240px, 1fr); }
.as-presales-task-head { grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--as-text); }
.as-presales-task-head > strong { font-size: 12px; }
.as-presales-task-status { color: var(--as-muted); font-size: 12px; }
.as-presales-task-status.is-late { color: var(--as-danger); }
.as-presales-task-status.is-done { color: var(--as-success); }
.as-presales-task-dates { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; min-width: 0; }
.as-round-submit-actions { display: flex; align-items: stretch; gap: 8px; min-width: 0; }
.as-round-submit-actions .as-round-attachment-button { flex: 1; min-width: 0; }
.as-round-submit-actions .as-button { flex: 0 0 auto; }
.as-round-reason, .as-round-context { grid-column: 1 / -1; margin: 0; color: var(--as-muted); font-size: 12px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.as-round-reason-files { display: grid; gap: 10px; margin-top: 16px; }
.as-round-section-title { margin: 0 0 8px; color: var(--as-text); font-size: 12px; font-weight: 600; }
@media (max-width: 900px) {
  .as-presales-round--scheduled { grid-template-columns: minmax(0, 1fr); }
}
</style>
