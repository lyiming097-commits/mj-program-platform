<script setup lang="ts">
import { onHide, onLoad, onShow, onUnload } from "@dcloudio/uni-app";
import { computed, ref, shallowRef } from "vue";
import { ApiError, downloadAuthenticatedFile } from "@/api/client";
import type { JsonRecord, MobileTask, ProductManual } from "@/api/types";
import CollapsibleSection from "@/components/CollapsibleSection.vue";
import MidsalesDeliveryContent from "@/components/MidsalesDeliveryContent.vue";
import MobileAttachmentPanel from "@/components/MobileAttachmentPanel.vue";
import TaskExecutionForm from "@/components/TaskExecutionForm.vue";
import TaskRelatedProductMaterials from "@/components/TaskRelatedProductMaterials.vue";
import { saveFeedbackIntent, type FeedbackIntentMode } from "@/composables/useFeedbackIntent";
import { resetAccordionState } from "@/composables/useAccordionState";
import { taskSubmission, taskTiming, useMobileTasks } from "@/composables/useMobileTasks";

const { tasks, loading, error, loadMobileTasks, manualsForTask } = useMobileTasks();
const taskId = shallowRef(0);
const openingManual = shallowRef("");
const initialSection = shallowRef("");
const actionBusy = shallowRef(false);
const completionError = shallowRef("");
const taskExecutionRef = ref<InstanceType<typeof TaskExecutionForm> | null>(null);
let syncTimer: ReturnType<typeof setInterval> | null = null;

const task = computed(() => tasks.value.find((item) => item.id === taskId.value) || null);
const timing = computed(() => task.value ? taskTiming(task.value) : null);
const manuals = computed(() => task.value ? manualsForTask(task.value) : []);
const projectData = computed<JsonRecord>(() => task.value?.project.businessData || {});
const nodeData = computed<JsonRecord>(() => task.value?.node.businessData || {});
const relatedProducts = computed<JsonRecord[]>(() => {
  const current = task.value;
  if (!current) return [];
  const source = current.serviceType === "aftersales" ? current.project.businessData : current.node.businessData;
  return Array.isArray(source?.relatedProducts)
    ? source.relatedProducts.filter((row): row is JsonRecord => Boolean(row && typeof row === "object"))
    : [];
});
const taskInstruction = computed(() => {
  const current = task.value;
  if (!current) return "-";
  return String(current.node.businessData?.deliveryNote || current.assignment.note || current.project.summary || "管理端尚未填写任务说明");
});
const managerName = computed(() => {
  const current = task.value;
  if (!current) return "-";
  return String(current.project.managerName || current.project.ownerName || current.project.applicantName || current.assignment.providerName || "-");
});
const managerContact = computed(() => String(projectData.value.managerContact || projectData.value.contactPhone || "-"));
const customerName = computed(() => String(task.value?.project.customer || "-"));
const estimatedFeeNote = computed(() => String(nodeData.value.feeEstimatedNote || "").trim());
const completionRejected = computed(() => nodeData.value.managerReviewStatus === "rejected");
const completionReviewNote = computed(() => String(nodeData.value.managerReviewNote || "").trim());
const completionReviewedAt = computed(() => String(nodeData.value.managerReviewedAt || ""));
const isAftersales = computed(() => task.value?.serviceType === "aftersales");
const AFTERSALES_ATTACHMENT_GROUPS = [
  { value: "package", label: "包装照片" },
  { value: "model_label", label: "型号标签" },
  { value: "appearance", label: "产品外观" },
  { value: "installation", label: "安装完成" },
  { value: "debugging", label: "调试完成" },
  { value: "other", label: "其他附件" },
] as const;
const FEE_ATTACHMENT_GROUPS = [
  { value: "fee_estimated", label: "预计费用清单", editable: false, emptyLabel: "管理端暂未上传" },
  { value: "fee_actual", label: "实际费用清单", uploadLabel: "上传", emptyLabel: "暂无文件" },
] as const;
const midsalesProofNodeKeys = new Set(["construction-work", "furniture-install", "device-install", "device-debug", "school-support"]);
const usesMidsalesProofs = computed(() => task.value?.serviceType === "midsales" && midsalesProofNodeKeys.has(task.value.nodeKey));
const showsDeliveryAttachments = computed(() => Boolean(task.value && task.value.serviceType === "midsales" && !usesMidsalesProofs.value));
const taskEditable = computed(() => {
  const current = task.value;
  if (!current || taskSubmission(current).submitted === true) return false;
  return ["assigned", "accepted", "in_progress"].includes(current.assignmentStatus)
    && current.node.status === "active"
    && Boolean(current.node.actualStartAt);
});

function dateLabel(value: unknown): string {
  if (!value) return "";
  const date = new Date(String(value));
  if (!Number.isFinite(date.getTime())) return String(value).replace("T", " ").slice(0, 10);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

function planLabel(current: MobileTask): string {
  const start = dateLabel(current.node.plannedStartAt || current.assignment.plannedStartDate);
  const end = dateLabel(current.node.plannedEndAt);
  if (!start && !end) return "-";
  return [start, end].filter(Boolean).join(" 至 ");
}

function moneyLabel(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未填写";
  const amount = Number(value);
  return Number.isFinite(amount) ? `${amount.toFixed(2)} 元` : String(value);
}

async function openManual(manual: ProductManual): Promise<void> {
  if (openingManual.value) return;
  openingManual.value = manual.id;
  uni.showLoading({ title: "正在准备" });
  try {
    const filePath = await downloadAuthenticatedFile(manual.externalUrl, 120_000);
    await new Promise<void>((resolve, reject) => {
      uni.openDocument({
        filePath,
        fileType: "pdf",
        showMenu: true,
        success: () => resolve(),
        fail: (reason) => reject(new Error(reason.errMsg || "说明书打开失败")),
      });
    });
  } catch (reason) {
    if (reason instanceof ApiError && reason.status === 401) {
      uni.reLaunch({ url: "/pages/login/index" });
    } else {
      uni.showToast({ title: reason instanceof Error ? reason.message : "说明书打开失败，请稍后重试", icon: "none" });
    }
  } finally {
    openingManual.value = "";
    uni.hideLoading();
  }
}

function openSubmission(mode: FeedbackIntentMode): void {
  const current = task.value;
  if (!current) return;
  saveFeedbackIntent(mode, current.id);
  uni.switchTab({ url: "/pages/feedback/index" });
}

async function confirmCompletion(): Promise<void> {
  if (!taskEditable.value || actionBusy.value || !taskExecutionRef.value) return;
  actionBusy.value = true;
  try { await taskExecutionRef.value.confirmCompletion(); } finally { actionBusy.value = false; }
}

function handleCompletionError(message: string): void {
  completionError.value = message;
  if (!message) return;
  uni.pageScrollTo({ scrollTop: 0, duration: 180 });
}

async function reload(silent = false): Promise<void> {
  try { await loadMobileTasks({ force: true, silent }); }
  catch (reason) { if (reason instanceof ApiError && reason.status === 401) uni.reLaunch({ url: "/pages/login/index" }); }
}

function stopSync(): void {
  if (syncTimer) clearInterval(syncTimer);
  syncTimer = null;
}

onLoad((options) => {
  resetAccordionState();
  const parsed = Number(options?.id || 0);
  if (Number.isInteger(parsed) && parsed > 0) taskId.value = parsed;
  initialSection.value = String(options?.openSection || "");
});
onShow(() => { void reload(); stopSync(); syncTimer = setInterval(() => { void reload(true); }, 5_000); });
onHide(stopSync);
onUnload(stopSync);
</script>

<template>
  <view class="page-shell detail-page">
    <view v-if="error" class="error-banner">{{ error }}</view>
    <view v-if="completionError" class="completion-submit-error" role="alert">
      <view class="completion-submit-error__mark">!</view>
      <view class="completion-submit-error__copy"><text class="completion-submit-error__title">无法确认完工</text><text class="completion-submit-error__message">{{ completionError }}</text></view>
    </view>
    <view v-if="loading && !task" class="empty-state">正在同步现场任务...</view>
    <view v-else-if="!task" class="empty-state">任务不存在或已取消</view>
    <template v-else>
      <view class="detail-head">
        <view class="detail-heading">
          <text class="status-chip" :class="`is-${timing?.group}`">{{ timing?.label }}</text>
          <text class="detail-title">{{ task.projectName }}</text>
          <text class="detail-subtitle">{{ task.serviceTypeLabel }} · {{ task.nodeName }}</text>
        </view>
        <view class="planned-start"><view class="clock-icon" /><text>{{ task.node.plannedStartAt || task.assignment.plannedStartDate ? `计划开始时间：${dateLabel(task.node.plannedStartAt || task.assignment.plannedStartDate)}` : "未设置计划开始时间" }}</text></view>
      </view>

      <view class="section-list">
        <view v-if="completionRejected" class="completion-review-alert" role="alert">
          <view class="completion-review-alert__mark">!</view>
          <view>
            <text>管理端已驳回本次完工资料</text>
            <text>{{ completionReviewNote || "请核对资料后重新提交" }}</text>
            <text v-if="completionReviewedAt">{{ completionReviewedAt.replace("T", " ").slice(0, 16) }}</text>
          </view>
        </view>
        <CollapsibleSection title="项目概览">
          <view class="overview-grid">
            <view class="overview-item">
              <text class="info-label">客户名称</text>
              <strong class="info-value">{{ customerName }}</strong>
            </view>
            <view class="overview-item">
              <text class="info-label">计划完成时间</text>
              <strong class="info-value">{{ dateLabel(task.node.plannedEndAt) || "-" }}</strong>
            </view>
            <view class="overview-item">
              <text class="info-label">项目负责人</text>
              <strong class="info-value">{{ managerName }}</strong>
            </view>
            <view class="overview-item">
              <text class="info-label">负责人联系电话</text>
              <strong class="info-value">{{ managerContact }}</strong>
            </view>
          </view>
        </CollapsibleSection>
        <CollapsibleSection :title="task.nodeName" :meta="task.node.statusLabel || timing?.label">
          <view class="node-info">
            <view class="task-brief">
              <text class="info-label">现场任务说明</text>
              <strong class="info-value">{{ taskInstruction }}</strong>
            </view>
            <view class="node-info-row">
              <text class="info-label">计划时间</text>
              <strong class="info-value">{{ planLabel(task) }}</strong>
            </view>
            <view class="node-info-row">
              <text class="info-label">预计费用</text>
              <strong class="info-value info-value--number">{{ moneyLabel(task.node.estimatedFee) }}</strong>
            </view>
            <view v-if="estimatedFeeNote" class="node-info-row">
              <text class="info-label">预计费用备注</text>
              <strong class="info-value">{{ estimatedFeeNote }}</strong>
            </view>
            <template v-if="isAftersales">
              <view class="node-info-row">
                <text class="info-label">服务地址</text>
                <strong class="info-value">{{ String(task.project.address || projectData.address || "-") }}</strong>
              </view>
              <view class="node-info-row">
                <text class="info-label">费用约定</text>
                <strong class="info-value">{{ String(projectData.feeAgreement || "-") }}</strong>
              </view>
              <view class="node-info-row">
                <text class="info-label">费用备注</text>
                <strong class="info-value">{{ String(projectData.feeRemark || "-") }}</strong>
              </view>
            </template>
          </view>
        </CollapsibleSection>
        <CollapsibleSection
          v-if="relatedProducts.length || manuals.length"
          title="相关产品资料"
          :meta="`${relatedProducts.length} 项 / ${manuals.length} 份`"
          :initially-expanded="initialSection === 'products'"
        >
          <TaskRelatedProductMaterials
            :products="relatedProducts"
            :manuals="manuals"
            :opening-manual="openingManual"
            :project-id="task.projectId"
            :node-key="task.nodeKey"
            @open="openManual"
          />
        </CollapsibleSection>
        <CollapsibleSection v-if="usesMidsalesProofs" title="交付内容">
          <MidsalesDeliveryContent :project-id="task.projectId" :node-key="task.nodeKey" :editable="taskEditable" :enabled="usesMidsalesProofs" />
        </CollapsibleSection>
        <CollapsibleSection v-if="showsDeliveryAttachments" title="交付附件">
          <MobileAttachmentPanel :target-id="task.nodeId" :editable="taskEditable" />
        </CollapsibleSection>
        <CollapsibleSection v-if="usesMidsalesProofs || isAftersales" title="费用清单附件">
          <MobileAttachmentPanel
            target-type="project_node"
            :target-id="task.nodeId"
            :categories="FEE_ATTACHMENT_GROUPS"
            :editable="taskEditable"
            upload-label="上传"
            success-message="实际费用清单已上传"
          />
        </CollapsibleSection>
        <CollapsibleSection v-if="isAftersales" title="售后完工附件">
          <MobileAttachmentPanel
            target-type="project_node"
            :target-id="task.nodeId"
            :categories="AFTERSALES_ATTACHMENT_GROUPS"
            :editable="taskEditable"
            upload-label="上传"
            empty-label="暂无文件"
            success-message="完工附件已上传"
          />
        </CollapsibleSection>
        <CollapsibleSection v-if="timing?.group !== 'pending'" title="任务记录" :meta="timing?.group === 'completed' ? '已上传' : '待确认完工'">
          <TaskExecutionForm ref="taskExecutionRef" :task="task" @completed="reload" @error="handleCompletionError" />
        </CollapsibleSection>
      </view>

      <view v-if="taskEditable" class="fixed-action-bar"><view class="action-button secondary" role="button" hover-class="action-button--pressed" @tap.stop="openSubmission('ticket')"><view class="headset-icon" /><text>提交工单</text></view><view class="action-button secondary" role="button" hover-class="action-button--pressed" @tap.stop="openSubmission('feedback')"><image src="/static/tabbar/feedback.png" mode="aspectFit" /><text>提交反馈</text></view><view class="action-button primary" :class="{ disabled: actionBusy }" role="button" hover-class="action-button--pressed" @tap.stop="confirmCompletion"><text class="check-icon">✓</text><text>{{ actionBusy ? "提交中" : "确认完工" }}</text></view></view>
    </template>
  </view>
</template>

<style scoped>
.detail-page { min-height: 100vh; padding: 28rpx 32rpx calc(156rpx + env(safe-area-inset-bottom)); }
.detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 24rpx; border-bottom: 1rpx solid #dfe3e8; background: #fff; padding: 30rpx 32rpx; }
.detail-heading { min-width: 0; }
.status-chip { display: inline-flex; min-height: 46rpx; align-items: center; border: 1rpx solid #c9d9f7; border-radius: 10rpx; background: #f2f6fd; padding: 4rpx 14rpx; color: #315f9f; font-size: 20rpx; font-weight: 700; }
.status-chip.is-completed { border-color: #b7decf; background: #eef9f4; color: #087550; }
.detail-title, .detail-subtitle { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-title { margin-top: 14rpx; color: #111827; font-size: 38rpx; font-weight: 800; line-height: 52rpx; }
.detail-subtitle { margin-top: 6rpx; color: #667085; font-size: 22rpx; }
.planned-start { display: flex; flex: 0 0 auto; align-items: center; gap: 10rpx; color: #315f9f; font-size: 20rpx; font-weight: 700; }
.clock-icon { position: relative; width: 24rpx; height: 24rpx; flex: 0 0 auto; border: 2rpx solid currentColor; border-radius: 50%; }
.clock-icon::before { position: absolute; top: 5rpx; left: 10rpx; width: 2rpx; height: 6rpx; background: currentColor; content: ""; }
.clock-icon::after { position: absolute; top: 10rpx; left: 10rpx; width: 5rpx; height: 2rpx; background: currentColor; content: ""; }
.section-list { display: grid; gap: 24rpx; margin-top: 24rpx; }
.completion-review-alert { display: grid; grid-template-columns: 52rpx minmax(0, 1fr); align-items: start; gap: 18rpx; border: 1rpx solid #efc8cd; border-left: 6rpx solid #b42318; border-radius: 12rpx; background: #fff7f7; padding: 22rpx 24rpx; }
.completion-review-alert__mark { display: grid; width: 52rpx; height: 52rpx; place-items: center; border-radius: 50%; background: #b42318; color: #fff; font-size: 26rpx; font-weight: 800; }
.completion-review-alert > view:last-child { min-width: 0; }
.completion-review-alert text { display: block; overflow-wrap: anywhere; }
.completion-review-alert text:first-child { color: #8f1d2c; font-size: 24rpx; font-weight: 800; line-height: 34rpx; }
.completion-review-alert text:nth-child(2) { margin-top: 8rpx; color: #6f2630; font-size: 22rpx; line-height: 34rpx; white-space: pre-wrap; }
.completion-review-alert text:last-child:not(:nth-child(2)) { margin-top: 8rpx; color: #98636a; font-size: 19rpx; }
.completion-submit-error { display: grid; grid-template-columns: 52rpx minmax(0, 1fr); align-items: start; gap: 18rpx; border: 1rpx solid #efc8cd; border-left: 6rpx solid #b42318; border-radius: 12rpx; background: #fff7f7; padding: 22rpx 24rpx; }
.completion-submit-error__mark { display: grid; width: 52rpx; height: 52rpx; place-items: center; border-radius: 50%; background: #b42318; color: #fff; font-size: 26rpx; font-weight: 800; }
.completion-submit-error__copy { min-width: 0; }
.completion-submit-error__title, .completion-submit-error__message { display: block; overflow-wrap: anywhere; }
.completion-submit-error__title { color: #8f1d2c; font-size: 24rpx; font-weight: 800; line-height: 34rpx; }
.completion-submit-error__message { margin-top: 8rpx; color: #6f2630; font-size: 22rpx; line-height: 34rpx; white-space: pre-wrap; }
.info-label, .info-value { display: block; }
.info-label { color: #667085; font-size: 20rpx; font-weight: 600; line-height: 30rpx; }
.info-value { overflow-wrap: anywhere; color: #182230; font-size: 25rpx; font-weight: 700; line-height: 38rpx; }
.info-value--number { font-variant-numeric: tabular-nums; }
.overview-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 32rpx; }
.overview-item { min-width: 0; padding: 8rpx 4rpx; }
.overview-item .info-value { margin-top: 8rpx; }
.node-info { min-width: 0; }
.task-brief { min-width: 0; border-left: 6rpx solid #002fa7; background: #f7f7f8; padding: 22rpx 24rpx; }
.task-brief .info-label { color: #445064; }
.task-brief .info-value { margin-top: 8rpx; font-size: 26rpx; line-height: 40rpx; }
.node-info-row { display: grid; min-width: 0; min-height: 88rpx; grid-template-columns: 156rpx minmax(0, 1fr); align-items: start; gap: 20rpx; border-bottom: 1rpx solid #e4e7ec; padding: 24rpx 4rpx; }
.node-info-row:last-child { border-bottom: 0; padding-bottom: 8rpx; }
.node-info-row .info-label { padding-top: 4rpx; }
.fixed-action-bar { position: fixed; right: 0; bottom: 0; left: 0; z-index: 30; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16rpx; border-top: 1rpx solid #dfe3e8; background: rgba(255, 255, 255, .98); padding: 18rpx 16rpx calc(18rpx + env(safe-area-inset-bottom)); box-shadow: 0 -8rpx 28rpx rgba(28, 55, 90, .08); }
.action-button { display: flex; min-width: 0; height: 72rpx; align-items: center; justify-content: center; gap: 12rpx; border-radius: 14rpx; padding: 0 12rpx; font-size: 22rpx; font-weight: 700; white-space: nowrap; }
.action-button.secondary { border: 1rpx solid #ccd2da; background: #fff; color: #344054; }
.action-button.primary { border: 1rpx solid #155eef; background: #155eef; color: #fff; }
.action-button--pressed { opacity: .78; }
.action-button.disabled { opacity: .55; }
.action-button image { width: 28rpx; height: 28rpx; }
.check-icon { font-size: 27rpx; line-height: 1; }
.headset-icon { position: relative; width: 26rpx; height: 24rpx; flex: 0 0 auto; border: 3rpx solid currentColor; border-bottom: 0; border-radius: 16rpx 16rpx 0 0; }
.headset-icon::before, .headset-icon::after { position: absolute; top: 11rpx; width: 5rpx; height: 10rpx; border: 2rpx solid currentColor; background: #fff; content: ""; }
.headset-icon::before { left: -5rpx; border-radius: 4rpx 0 0 4rpx; }
.headset-icon::after { right: -5rpx; border-radius: 0 4rpx 4rpx 0; }
@media (max-width: 360px) {
  .detail-head { flex-direction: column; }
  .planned-start { align-self: flex-start; }
  .overview-grid { grid-template-columns: 1fr; }
  .overview-item + .overview-item { border-top: 1rpx solid #e4e7ec; margin-top: 20rpx; padding-top: 20rpx; }
  .node-info-row { grid-template-columns: 132rpx minmax(0, 1fr); gap: 16rpx; }
}
</style>
