<script setup lang="ts">
import { onHide, onShow, onUnload } from "@dcloudio/uni-app";
import { computed, getCurrentInstance, reactive, shallowRef } from "vue";
import { ApiError, readStoredSession } from "@/api/client";
import { createFieldFeedback, createServiceTicket, fetchMobileRecords, fetchServiceTicket, uploadAttachment } from "@/api/mobile";
import type { FieldFeedback, PendingUploadFile, ServiceTicket, TicketMessage } from "@/api/types";
import FieldPageHeader from "@/components/FieldPageHeader.vue";
import MobileAttachmentPanel from "@/components/MobileAttachmentPanel.vue";
import PendingFilePicker from "@/components/PendingFilePicker.vue";
import TaskSelectorField from "@/components/TaskSelectorField.vue";
import { takeFeedbackIntent } from "@/composables/useFeedbackIntent";
import { taskTiming, useMobileTasks } from "@/composables/useMobileTasks";
import { usePagedRecords } from "@/composables/usePagedRecords";
import { createBackdropTapHandlers } from "@/composables/backdropTap";

type FeedbackMode = "feedback" | "ticket";
type FeedbackView = "history" | "create";
type SubmissionRecord = FieldFeedback | ServiceTicket;

const { workspace, tasks, loading, error, loadMobileTasks } = useMobileTasks();
const mode = shallowRef<FeedbackMode>("feedback");
const view = shallowRef<FeedbackView>("history");
const selectedRecord = shallowRef<SubmissionRecord | null>(null);
const ticketDetail = shallowRef<ServiceTicket | null>(null);
const detailLoading = shallowRef(false);
const detailError = shallowRef("");
const taskSelectorOpen = shallowRef(false);
const saving = shallowRef(false);
const formError = shallowRef("");
const form = reactive({ taskId: 0, title: "", type: "issue", priority: "medium", content: "" });
const pendingFiles = shallowRef<PendingUploadFile[]>([]);
const createdSubmission = shallowRef<{ mode: FeedbackMode; id: number } | null>(null);
let syncTimer: ReturnType<typeof setInterval> | null = null;
let detailRequestId = 0;
const pageInstance = getCurrentInstance();
const detailBackdrop = createBackdropTapHandlers("feedback-detail-mask", (point) => new Promise<boolean>((resolve) => {
  const query = uni.createSelectorQuery();
  if (pageInstance?.proxy) query.in(pageInstance.proxy);
  query.select("#feedback-detail-mask").boundingClientRect();
  query.select(".detail-modal").boundingClientRect();
  query.exec((rects) => {
    const [mask, panel] = rects;
    const inside = (rect: UniApp.NodeInfo) => point.clientX >= Number(rect.left) && point.clientX <= Number(rect.right)
      && point.clientY >= Number(rect.top) && point.clientY <= Number(rect.bottom);
    resolve(Boolean(mask && panel && inside(mask) && !inside(panel)));
  });
}), closeDetail);

const nodeLabels: Readonly<Record<string, string>> = {
  "midsales-project": "项目立项",
  "construction-work": "工程施工",
  "furniture-install": "家具安装",
  "device-install": "设备安装",
  "device-debug": "设备调试",
  "school-support": "开学保障",
  "project-acceptance": "项目验收",
  "midsales-project-end": "售中项目结束",
  "onsite-service": "上门售后",
  "mail-service": "寄件售后",
  "school-inspection": "开学巡检",
};

const selectableTasks = computed(() => tasks.value.filter((task) => taskTiming(task).group !== "pending"));
const selectedTask = computed(() => selectableTasks.value.find((task) => task.id === form.taskId) || null);
const { rows: records, total: recordTotal, loading: recordsLoading, error: recordsError, hasMore: moreRecords, load: loadRecords, syncPreview } = usePagedRecords<SubmissionRecord>(() => mode.value === "feedback" ? "feedback" : "tickets");
const currentRecord = computed<SubmissionRecord | null>(() => (
  mode.value === "ticket" ? ticketDetail.value || selectedRecord.value : selectedRecord.value
));
const overlayOpen = computed(() => taskSelectorOpen.value || Boolean(selectedRecord.value));
const typeOptions = computed(() => mode.value === "feedback"
  ? [
    { value: "issue", label: "现场问题" },
    { value: "resource_suggestion", label: "资料建议" },
    { value: "reward_application", label: "奖励申请" },
  ]
  : [
    { value: "现场问题", label: "现场问题" },
    { value: "设备故障", label: "设备故障" },
    { value: "客户协调", label: "客户协调" },
  ]);
const typeIndex = computed(() => Math.max(0, typeOptions.value.findIndex((item) => item.value === form.type)));

function setMode(nextMode: FeedbackMode): void {
  if (saving.value) return;
  if (nextMode !== mode.value && createdSubmission.value && pendingFiles.value.length) {
    uni.showToast({ title: "请先完成剩余附件上传", icon: "none" });
    return;
  }
  detailRequestId += 1;
  detailBackdrop.reset();
  mode.value = nextMode;
  view.value = "history";
  selectedRecord.value = null;
  ticketDetail.value = null;
  detailLoading.value = false;
  detailError.value = "";
  pendingFiles.value = [];
  createdSubmission.value = null;
  form.type = typeOptions.value[0]?.value || "issue";
}

function setView(nextView: FeedbackView): void {
  if (nextView === view.value) return;
  if (nextView === "history" && createdSubmission.value && pendingFiles.value.length) {
    uni.showToast({ title: "请先完成剩余附件上传", icon: "none" });
    return;
  }
  if (nextView === "create") openCreate();
  else view.value = "history";
}

function openCreate(taskId = 0): void {
  const requestedTask = taskId > 0 ? selectableTasks.value.find((task) => task.id === taskId) : null;
  const selectedTaskId = requestedTask?.id || selectableTasks.value[0]?.id || 0;
  view.value = "create";
  formError.value = "";
  Object.assign(form, { taskId: selectedTaskId, title: "", content: "", priority: "medium" });
  pendingFiles.value = [];
  createdSubmission.value = null;
  form.type = typeOptions.value[0]?.value || "issue";
  selectTask(selectedTaskId);
}

function applySubmissionIntent(): void {
  const intent = takeFeedbackIntent();
  if (!intent) return;
  setMode(intent.mode);
  openCreate(intent.taskId);
}

function selectTask(taskId: number): void {
  form.taskId = taskId;
  const task = selectableTasks.value.find((item) => item.id === taskId);
  if (task) form.title = `${task.projectName} - ${task.nodeName}`;
}

function dateTime(value: unknown): string {
  return value ? String(value).replace("T", " ").slice(0, 16) : "-";
}

function recordNode(record: SubmissionRecord): string {
  const nodeName = String(record.nodeName || "");
  if (nodeName) return nodeName;
  const nodeKey = String(record.nodeKey || "");
  return nodeLabels[nodeKey] || nodeKey || "未关联节点";
}

function recordContent(record: SubmissionRecord): string {
  return mode.value === "feedback"
    ? String((record as FieldFeedback).content || "")
    : String((record as ServiceTicket).description || "");
}

function recordType(record: SubmissionRecord): string {
  return mode.value === "feedback"
    ? String((record as FieldFeedback).feedbackTypeLabel || (record as FieldFeedback).feedbackType || "-")
    : String((record as ServiceTicket).ticketType || "-");
}

function progressText(record: SubmissionRecord): string {
  if (mode.value === "ticket") {
    const labels: Record<string, string> = {
      open: "等待管理端分派处理人",
      assigned: `已分派给${String(record.ownerName || "处理人员")}`,
      in_progress: `${String(record.ownerName || "处理人员")}正在处理`,
      pending_review: "等待管理端审核处理结果",
      completed: "工单处理已完成",
      rejected: "工单已驳回，等待重新处理",
      closed: "工单处理已完成",
    };
    return labels[record.status] || record.statusLabel || "等待处理";
  }
  const feedback = record as FieldFeedback;
  const labels: Record<string, string> = {
    submitted: "等待管理端审核",
    under_review: "管理端正在审核",
    accepted: String(feedback.reviewNote || "反馈已采纳"),
    rejected: String(feedback.reviewNote || "反馈未采纳"),
  };
  return labels[feedback.status] || feedback.statusLabel || "等待审核";
}

function statusClass(record: SubmissionRecord): string {
  if (["completed", "closed", "accepted"].includes(record.status)) return "is-done";
  if (record.status === "rejected") return "is-danger";
  if (["assigned", "in_progress", "under_review", "pending_review"].includes(record.status)) return "is-active";
  return "";
}

function messageContent(message: TicketMessage): string {
  const content = String(message.content || "");
  const match = content.match(/^工单状态由 ([a-z_]+) 变更为 ([a-z_]+)$/);
  if (!match) return content;
  const labels: Record<string, string> = {
    open: "待分配",
    assigned: "已指派",
    in_progress: "正在执行",
    pending_review: "待审核",
    completed: "已完成",
    rejected: "已驳回",
    closed: "已完成",
  };
  const beforeKey = match[1] || "";
  const afterKey = match[2] || "";
  const before = labels[beforeKey] || beforeKey;
  const after = labels[afterKey] || afterKey;
  return before === after ? `工单状态更新为“${after}”` : `工单状态由“${before}”变更为“${after}”`;
}

function ticketMessages(record: SubmissionRecord): readonly TicketMessage[] {
  const messages = (record as ServiceTicket).messages;
  return Array.isArray(messages) ? messages : [];
}

async function openDetail(record: SubmissionRecord): Promise<void> {
  detailBackdrop.reset();
  const requestId = ++detailRequestId;
  selectedRecord.value = record;
  ticketDetail.value = null;
  detailError.value = "";
  detailLoading.value = true;
  try {
    if (mode.value === "ticket") {
      const response = await fetchServiceTicket(record.id);
      if (requestId === detailRequestId) ticketDetail.value = response.item;
    } else {
      const response = await fetchMobileRecords<FieldFeedback>("feedback", 1, 1, record.id);
      if (requestId === detailRequestId) selectedRecord.value = response.items[0] || null;
    }
  } catch (reason) {
    if (requestId === detailRequestId) {
      detailError.value = reason instanceof Error ? reason.message : "记录详情加载失败";
    }
  } finally {
    if (requestId === detailRequestId) detailLoading.value = false;
  }
}

function closeDetail(): void {
  detailBackdrop.reset();
  detailRequestId += 1;
  selectedRecord.value = null;
  ticketDetail.value = null;
  detailLoading.value = false;
  detailError.value = "";
}

async function uploadPendingAttachments(targetType: FeedbackMode, targetId: number): Promise<void> {
  while (pendingFiles.value.length) {
    const file = pendingFiles.value[0];
    if (!file) break;
    await uploadAttachment(targetType, targetId, file.path);
    pendingFiles.value = pendingFiles.value.slice(1);
  }
}

async function submit(): Promise<void> {
  const task = selectedTask.value;
  const existingTargetId = createdSubmission.value?.mode === mode.value ? createdSubmission.value.id : 0;
  if (!task && !existingTargetId) {
    formError.value = "当前没有可提交的进行中或已完成任务";
    return;
  }
  if (!existingTargetId && (!form.title.trim() || !form.content.trim())) {
    formError.value = "请填写标题和详细内容";
    return;
  }
  saving.value = true;
  formError.value = "";
  try {
    let targetId = existingTargetId;
    if (!targetId) {
      if (!task) throw new Error("当前没有可提交的进行中或已完成任务");
      if (mode.value === "feedback") {
        const response = await createFieldFeedback({
          projectId: task.projectId,
          nodeKey: task.nodeKey,
          title: form.title.trim(),
          feedbackType: form.type,
          content: form.content.trim(),
        });
        targetId = Number(response.item.id || 0);
      } else {
        const response = await createServiceTicket({
          projectId: task.projectId,
          nodeKey: task.nodeKey,
          title: form.title.trim(),
          ticketType: form.type,
          priority: form.priority,
          description: form.content.trim(),
        });
        targetId = Number(response.item.id || 0);
      }
      if (!Number.isInteger(targetId) || targetId <= 0) throw new Error("提交记录无效");
      createdSubmission.value = { mode: mode.value, id: targetId };
    }
    await uploadPendingAttachments(mode.value, targetId);
    await loadMobileTasks({ force: true, silent: true });
    await loadRecords(true);
    createdSubmission.value = null;
    pendingFiles.value = [];
    view.value = "history";
    uni.showToast({ title: mode.value === "feedback" ? "反馈已提交" : "工单已提交", icon: "success" });
  } catch (reason) {
    const message = reason instanceof Error ? reason.message : "提交失败";
    formError.value = createdSubmission.value
      ? `记录已提交，附件尚未全部上传：${message}`
      : message;
  } finally {
    saving.value = false;
  }
}

async function load(silent = false): Promise<void> {
  if (!readStoredSession()) {
    uni.reLaunch({ url: "/pages/login/index" });
    return;
  }
  try {
    await loadMobileTasks({ force: true, silent });
    if (!silent) await loadRecords(true);
    else if (workspace.value) {
      const kind = mode.value === "feedback" ? "feedback" : "tickets";
      const preview = kind === "feedback" ? workspace.value.feedback || []
        : (workspace.value.tickets || []).filter(item => item.reporterUserId === readStoredSession()?.user.userId)
          .map(item => ({ ...item, messages: item.messages ? [...item.messages] : undefined }));
      syncPreview(preview, workspace.value.recordCounts?.[kind]);
    }
  } catch (reason) {
    if (reason instanceof ApiError && reason.status === 401) uni.reLaunch({ url: "/pages/login/index" });
    else if (reason instanceof ApiError && ["SERVICE_PROVIDER_REQUIRED", "SERVICE_PROVIDER_NOT_CERTIFIED"].includes(reason.code)) {
      uni.reLaunch({ url: "/pages/pending/index" });
    }
  }
}

function stopSync(): void {
  detailBackdrop.reset();
  if (syncTimer) clearInterval(syncTimer);
  syncTimer = null;
}

onShow(async () => {
  await load();
  applySubmissionIntent();
  stopSync();
  syncTimer = setInterval(() => { if (!saving.value) void load(true); }, 5000);
});
onHide(stopSync);
onUnload(stopSync);
</script>

<template>
  <page-meta :page-style="overlayOpen ? 'overflow: hidden;' : ''" />
  <view class="page-shell field-page">
    <FieldPageHeader :profile="workspace?.profile" />
    <view class="page-content field-main">
      <view class="field-page-title">
        <text class="eyebrow">现场协同</text>
        <text class="page-title">反馈与支持</text>
        <text class="page-copy">反馈审核通过后可进入奖励记录；需专人跟进的问题请创建工单。</text>
      </view>

      <view class="feedback-mode-tabs" role="tablist" aria-label="反馈类型">
        <view class="feedback-mode-tab" :class="{ active: mode === 'feedback' }" role="tab" :aria-selected="mode === 'feedback'" hover-class="feedback-control--pressed" @tap.stop="setMode('feedback')"><text>问题反馈</text><text class="feedback-mode-count">{{ mode === 'feedback' ? recordTotal : (workspace?.recordCounts?.feedback ?? 0) }}</text></view>
        <view class="feedback-mode-tab" :class="{ active: mode === 'ticket' }" role="tab" :aria-selected="mode === 'ticket'" hover-class="feedback-control--pressed" @tap.stop="setMode('ticket')"><text>支持工单</text><text class="feedback-mode-count">{{ mode === 'ticket' ? recordTotal : (workspace?.recordCounts?.tickets ?? 0) }}</text></view>
      </view>

      <view v-if="error" class="error-banner">{{ error }}</view>
      <view v-if="loading && !workspace" class="empty-state">正在加载...</view>

      <view v-else-if="view === 'history'" class="history-panel">
        <view class="section-heading">
          <view><text class="eyebrow">进度跟踪</text><view class="section-title-line"><text class="section-title">{{ mode === "feedback" ? "我的反馈" : "我的工单" }}</text><text class="section-count">{{ recordTotal }}</text></view></view>
          <button class="feedback-create-button" hover-class="feedback-control--pressed" @tap.stop="setView('create')"><text class="feedback-create-icon">+</text><text>新建{{ mode === "feedback" ? "反馈" : "工单" }}</text></button>
        </view>
        <view v-if="records.length" class="record-list">
          <view v-for="record in records" :key="record.id" class="record-row" role="button" hover-class="record-row--pressed" @tap.stop="openDetail(record)">
            <view class="record-icon"><image src="/static/tabbar/feedback-active.png" mode="aspectFit" /></view>
            <view class="record-copy">
              <view><text class="record-title">{{ record.title }}</text><text class="status-chip" :class="statusClass(record)">{{ record.statusLabel || record.status }}</text></view>
              <text class="record-project">{{ record.projectName || "服务项目" }} · {{ recordNode(record) }}</text>
              <text class="record-progress">{{ progressText(record) }}</text>
              <text class="record-time">{{ dateTime(record.updatedAt || record.createdAt) }}</text>
            </view>
            <view class="row-arrow" />
          </view>
        </view>
        <view v-else-if="!recordsLoading && !recordsError" class="history-empty"><image src="/static/tabbar/feedback.png" mode="aspectFit" /><text class="history-empty-title">暂无{{ mode === "feedback" ? "反馈" : "工单" }}记录</text><text class="history-empty-copy">{{ mode === "feedback" ? "提交现场建议后，可在这里查看审核结果" : "提交需跟进的问题后，可在这里查看处理进度" }}</text></view>
        <view v-if="recordsError" class="error-banner">{{ recordsError }}</view>
        <button v-if="moreRecords || recordsLoading || recordsError" class="history-button" :disabled="recordsLoading" @tap="loadRecords(!records.length)">{{ recordsLoading ? '正在加载…' : recordsError ? '重试加载' : '加载更多' }}</button>
      </view>

      <view v-else class="create-panel">
        <view class="create-panel-head"><view><text class="eyebrow">现场协同</text><text class="create-panel-title">新建{{ mode === "feedback" ? "反馈" : "工单" }}</text></view><button class="history-button" hover-class="feedback-control--pressed" @tap.stop="setView('history')">返回记录</button></view>
        <view v-if="formError" class="error-banner">{{ formError }}</view>
        <view v-if="createdSubmission" class="success-banner">记录已创建，可继续上传剩余附件。</view>
        <view class="form-field"><text class="field-label">关联任务 *</text><TaskSelectorField :tasks="selectableTasks" :model-value="form.taskId" :disabled="Boolean(createdSubmission)" @update:model-value="selectTask" @open-change="taskSelectorOpen = $event" /></view>
        <label class="form-field"><text class="field-label">{{ mode === "ticket" ? "工单标题" : "反馈标题" }} *</text><input v-model="form.title" class="field-input" :disabled="Boolean(createdSubmission)" maxlength="255" placeholder="简明描述现场事项" /></label>
        <view class="form-field"><text class="field-label">类型</text><picker :disabled="Boolean(createdSubmission)" :range="typeOptions" range-key="label" :value="typeIndex" @change="form.type = typeOptions[Number($event.detail.value)]?.value || form.type"><view class="field-picker" :class="{ disabled: Boolean(createdSubmission) }">{{ typeOptions[typeIndex]?.label }}</view></picker></view>
        <view v-if="mode === 'ticket'" class="form-field"><text class="field-label">优先级</text><picker :disabled="Boolean(createdSubmission)" :range="['低', '中', '高']" :value="['low', 'medium', 'high'].indexOf(form.priority)" @change="form.priority = ['low', 'medium', 'high'][Number($event.detail.value)] || 'medium'"><view class="field-picker" :class="{ disabled: Boolean(createdSubmission) }">{{ { low: "低", medium: "中", high: "高" }[form.priority] }}</view></picker></view>
        <label class="form-field"><text class="field-label">详细内容 *</text><textarea v-model="form.content" class="field-textarea" :disabled="Boolean(createdSubmission)" maxlength="10000" placeholder="描述当前现象、已尝试步骤和现场配置差异" /></label>
        <view class="form-field"><text class="field-label">现场附件</text><PendingFilePicker :files="pendingFiles" button-label="选择现场附件" :disabled="saving" @update:files="pendingFiles = $event" @error="formError = $event" /></view>
        <button class="primary-button submit-button" :disabled="saving" @tap.stop="submit">{{ saving ? "提交中..." : createdSubmission ? "继续上传附件" : mode === "ticket" ? "提交工单" : "提交反馈" }}</button>
      </view>
    </view>

    <view
      v-if="selectedRecord"
      id="feedback-detail-mask"
      class="detail-mask"
      @touchstart="detailBackdrop.touchstart"
      @touchmove.stop.prevent="detailBackdrop.reset"
      @touchend="detailBackdrop.touchend"
      @touchcancel="detailBackdrop.reset"
      @tap="detailBackdrop.tap"
    >
      <view class="detail-modal">
        <view class="detail-head"><view><text class="eyebrow">{{ mode === "ticket" ? "工单详情" : "反馈详情" }}</text><text class="detail-title">{{ currentRecord?.title || selectedRecord.title }}</text><text class="detail-subtitle">{{ currentRecord?.projectName || selectedRecord.projectName }} · {{ recordNode(currentRecord || selectedRecord) }}</text></view><view class="close-button" role="button" aria-label="关闭详情" hover-class="close-button--pressed" @tap.stop="closeDetail">×</view></view>
        <scroll-view class="detail-body" scroll-y enhanced :bounces="false">
          <view v-if="detailLoading" class="detail-loading">正在加载记录详情...</view>
          <view v-else-if="currentRecord">
            <view v-if="detailError" class="error-banner">{{ detailError }}</view>
            <view class="detail-facts"><view><text>当前状态</text><strong>{{ currentRecord.statusLabel || currentRecord.status }}</strong></view><view><text>提交时间</text><strong>{{ dateTime(currentRecord.createdAt) }}</strong></view><view><text>关联节点</text><strong>{{ recordNode(currentRecord) }}</strong></view><view><text>事项类型</text><strong>{{ recordType(currentRecord) }}</strong></view><view v-if="mode === 'ticket'"><text>处理人员</text><strong>{{ String(currentRecord.ownerName || "待分配") }}</strong></view><view v-if="mode === 'ticket'"><text>最后更新</text><strong>{{ dateTime(currentRecord.updatedAt) }}</strong></view></view>
            <view class="detail-section"><text>处理进度</text><strong>{{ progressText(currentRecord) }}</strong></view>
            <view class="detail-section"><text>{{ mode === "ticket" ? "问题描述" : "反馈内容" }}</text><strong>{{ recordContent(currentRecord) }}</strong></view>
            <view v-if="mode === 'feedback'" class="detail-section result-section"><text>审核意见</text><strong>{{ String(currentRecord.reviewNote || progressText(currentRecord)) }}</strong></view>
            <view v-if="mode === 'ticket' && currentRecord.resolution" class="detail-section result-section"><text>处理结果</text><strong>{{ String(currentRecord.resolution) }}</strong></view>
            <view class="detail-section"><text>提交附件</text><MobileAttachmentPanel class="detail-attachments" :target-type="mode" :target-id="currentRecord.id" :editable="false" empty-label="暂无附件" @error="detailError = $event" /></view>
            <view v-if="mode === 'ticket'" class="detail-section"><text>处理记录</text><view v-if="!ticketMessages(currentRecord).length" class="timeline-empty">暂无处理记录</view><view v-else class="ticket-timeline"><view v-for="message in ticketMessages(currentRecord)" :key="message.id" class="timeline-row"><view class="timeline-marker" /><view><text>{{ message.authorName || "系统" }} · {{ dateTime(message.createdAt) }}</text><strong>{{ messageContent(message) }}</strong></view></view></view></view>
          </view>
        </scroll-view>
      </view>
    </view>
  </view>
</template>

<style scoped>
.field-main { min-width: 0; }
.field-page-title { border-bottom: 1rpx solid #dfe3e8; background: #fff; padding: 32rpx 36rpx 34rpx; }
.eyebrow, .page-title, .page-copy, .section-title { display: block; }
.eyebrow { color: #3e5d86; font-size: 21rpx; font-weight: 800; line-height: 32rpx; }
.page-title { margin-top: 4rpx; color: #111827; font-size: 38rpx; font-weight: 800; line-height: 54rpx; }
.page-copy { margin-top: 6rpx; color: #667085; font-size: 24rpx; line-height: 40rpx; }
.feedback-mode-tabs { display: flex; gap: 8rpx; margin: 24rpx 0; border: 1rpx solid #dce3eb; border-radius: 16rpx; background: #f1f4f7; padding: 8rpx; box-shadow: 0 2rpx 8rpx rgba(16, 24, 40, .04); }
.feedback-mode-tab { display: flex; min-width: 0; min-height: 88rpx; flex: 1 1 0; align-items: center; justify-content: center; gap: 10rpx; border-radius: 10rpx; color: #536174; font-size: 25rpx; font-weight: 750; white-space: nowrap; }
.feedback-mode-tab.active { background: #155eef; color: #fff; box-shadow: 0 3rpx 8rpx rgba(21, 94, 239, .2); }
.feedback-mode-count { display: inline-flex; min-width: 34rpx; height: 32rpx; align-items: center; justify-content: center; border-radius: 16rpx; background: #e1e6ed; padding: 0 8rpx; color: #526174; font-size: 19rpx; font-weight: 800; line-height: 32rpx; }
.feedback-mode-tab.active .feedback-mode-count { background: rgba(255, 255, 255, .2); color: #fff; }
.feedback-control--pressed { opacity: .72; }
.history-panel { padding: 2rpx 0 0; }
.section-heading { display: flex; min-height: 76rpx; align-items: center; justify-content: space-between; gap: 24rpx; margin-bottom: 18rpx; padding: 0 2rpx; }
.section-heading > view:first-child { min-width: 0; }
.section-title-line { display: flex; min-width: 0; align-items: center; gap: 10rpx; }
.section-title { margin-top: 4rpx; color: #182230; font-size: 30rpx; font-weight: 800; line-height: 40rpx; }
.section-count { display: inline-flex; min-width: 34rpx; height: 34rpx; align-items: center; justify-content: center; border-radius: 17rpx; background: #e7edf5; padding: 0 8rpx; color: #526174; font-size: 19rpx; font-weight: 800; line-height: 34rpx; }
.feedback-create-button { display: inline-flex; min-width: 190rpx; min-height: 72rpx; flex: 0 0 auto; align-items: center; justify-content: center; gap: 8rpx; margin: 0; border-radius: 12rpx; background: #155eef; padding: 0 20rpx; color: #fff; font-size: 23rpx; font-weight: 750; line-height: 72rpx; }
.feedback-create-icon { font-size: 31rpx; font-weight: 400; line-height: 1; }
.status-chip { display: inline-flex; min-height: 44rpx; flex: 0 0 auto; align-items: center; border: 1rpx solid #c9d9f7; border-radius: 10rpx; background: #f2f6fd; padding: 4rpx 14rpx; color: #315f9f; font-size: 20rpx; font-weight: 700; }
.status-chip.is-done { border-color: #b7decf; background: #eef9f4; color: #087550; }
.status-chip.is-danger { border-color: #efc8cd; background: #fff3f4; color: #b42318; }
.status-chip.is-active { border-color: #bfd2f7; background: #edf4ff; color: #155eef; }
.record-list { overflow: hidden; border: 1rpx solid #dfe5ec; border-radius: 16rpx; background: #fff; box-shadow: 0 2rpx 8rpx rgba(16, 24, 40, .04); }
.record-row { display: grid; width: 100%; min-height: 176rpx; grid-template-columns: 68rpx minmax(0, 1fr) 28rpx; align-items: center; gap: 20rpx; border-bottom: 1rpx solid #edf0f2; background: #fff; padding: 22rpx 8rpx; }
.record-row:last-child { border-bottom: 0; }
.record-row--pressed { background: #f8fbff; }
.record-icon { display: grid; width: 68rpx; height: 68rpx; place-items: center; border-radius: 14rpx; background: #edf3fb; }
.record-icon image { width: 34rpx; height: 34rpx; }
.record-copy { display: block; min-width: 0; }
.record-copy > view { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 16rpx; }
.record-title { min-width: 0; overflow: hidden; color: #263244; font-size: 24rpx; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.record-project, .record-progress, .record-time { display: block; overflow: hidden; margin-top: 6rpx; text-overflow: ellipsis; white-space: nowrap; }
.record-project { color: #7b8798; font-size: 19rpx; }
.record-progress { color: #526174; font-size: 21rpx; }
.record-time { color: #98a2b3; font-size: 18rpx; }
.row-arrow { width: 18rpx; height: 18rpx; border-top: 3rpx solid #98a2b3; border-right: 3rpx solid #98a2b3; transform: rotate(45deg); }
.history-empty { display: flex; min-height: 340rpx; flex-direction: column; align-items: center; justify-content: center; gap: 10rpx; border: 1rpx solid #dfe5ec; border-radius: 16rpx; background: #fff; padding: 36rpx; color: #8490a2; text-align: center; box-shadow: 0 2rpx 8rpx rgba(16, 24, 40, .04); }
.history-empty image { width: 56rpx; height: 56rpx; opacity: .52; }
.history-empty-title { margin-top: 4rpx; color: #5f6d80; font-size: 24rpx; font-weight: 700; line-height: 36rpx; }
.history-empty-copy { max-width: 500rpx; color: #98a2b3; font-size: 20rpx; line-height: 32rpx; }
.create-panel { display: grid; gap: 24rpx; border: 1rpx solid #dfe3e8; border-radius: 16rpx; background: #fff; padding: 30rpx; }
.create-panel-head { display: flex; align-items: center; justify-content: space-between; gap: 20rpx; border-bottom: 1rpx solid #e5eaf0; padding-bottom: 22rpx; }
.create-panel-title { display: block; margin-top: 3rpx; color: #182230; font-size: 30rpx; font-weight: 800; line-height: 42rpx; }
.history-button { min-height: 64rpx; flex: 0 0 auto; margin: 0; border: 1rpx solid #cdd7e2; border-radius: 10rpx; background: #f8fafc; padding: 0 20rpx; color: #475467; font-size: 22rpx; font-weight: 700; line-height: 62rpx; }
.form-field { display: block; }
.field-picker.disabled, .field-input[disabled], .field-textarea[disabled] { background: #f4f6f8; color: #7b8798; }
.submit-button { width: 100%; margin-top: 4rpx; }
.detail-mask { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; background: rgba(16, 24, 40, .48); padding: 32rpx; }
.detail-modal { display: flex; width: 100%; max-height: 82vh; flex-direction: column; overflow: hidden; border: 1rpx solid #d7dce3; border-radius: 16rpx; background: #fff; box-shadow: 0 30rpx 80rpx rgba(16, 24, 40, .24); }
.detail-head { display: flex; flex: 0 0 auto; align-items: flex-start; justify-content: space-between; gap: 24rpx; border-bottom: 1rpx solid #e4e7ec; padding: 28rpx 30rpx; }
.detail-head > view:first-child { min-width: 0; }
.detail-title, .detail-subtitle { display: block; }
.detail-title { margin-top: 4rpx; color: #172033; font-size: 32rpx; font-weight: 800; line-height: 44rpx; }
.detail-subtitle { margin-top: 6rpx; overflow: hidden; color: #7b8798; font-size: 20rpx; text-overflow: ellipsis; white-space: nowrap; }
.close-button { display: grid; width: 56rpx; height: 56rpx; flex: 0 0 auto; place-items: center; border-radius: 10rpx; background: #f4f6f8; color: #526174; font-size: 38rpx; line-height: 1; }
.close-button--pressed { background: #e9eef5; }
.detail-body { width: 100%; min-height: 0; box-sizing: border-box; padding: 28rpx 30rpx 34rpx; }
.detail-loading { display: grid; min-height: 260rpx; place-items: center; color: #7b8798; font-size: 23rpx; }
.detail-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border-top: 1rpx solid #e1e6ed; border-left: 1rpx solid #e1e6ed; }
.detail-facts > view { min-width: 0; border-right: 1rpx solid #e1e6ed; border-bottom: 1rpx solid #e1e6ed; padding: 20rpx; }
.detail-facts text, .detail-facts strong { display: block; }
.detail-facts text { color: #7b8798; font-size: 19rpx; }
.detail-facts strong { overflow: hidden; margin-top: 8rpx; color: #344054; font-size: 22rpx; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.detail-section { border-top: 1rpx solid #e4e7ec; margin-top: 24rpx; padding-top: 24rpx; }
.detail-section text, .detail-section strong { display: block; }
.detail-section text { color: #344054; font-size: 24rpx; font-weight: 700; }
.detail-section strong { margin-top: 14rpx; color: #526174; font-size: 22rpx; font-weight: 400; line-height: 38rpx; white-space: pre-wrap; }
.result-section { border: 1rpx solid #b7decf; border-radius: 14rpx; background: #f2faf6; padding: 22rpx; }
.detail-attachments { margin-top: 16rpx; }
.timeline-empty { display: grid; min-height: 96rpx; place-items: center; margin-top: 16rpx; color: #8a98aa; font-size: 21rpx; }
.ticket-timeline { display: grid; gap: 0; margin-top: 16rpx; }
.timeline-row { display: grid; grid-template-columns: 22rpx minmax(0, 1fr); gap: 14rpx; min-height: 92rpx; }
.timeline-marker { position: relative; width: 14rpx; height: 14rpx; border: 3rpx solid #6b8fc4; border-radius: 50%; background: #fff; margin-top: 8rpx; }
.timeline-marker::after { position: absolute; top: 14rpx; bottom: -78rpx; left: 4rpx; width: 2rpx; background: #d8e1ec; content: ""; }
.timeline-row:last-child .timeline-marker::after { display: none; }
.timeline-row text, .timeline-row strong { display: block; }
.timeline-row text { color: #7b8798; font-size: 19rpx; }
.timeline-row strong { margin-top: 7rpx; color: #344054; font-size: 21rpx; line-height: 34rpx; }
</style>
