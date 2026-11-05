<script setup>
import { computed, onMounted, ref, watch } from "vue";
import {
  ArrowLeftFromLine,
  Check,
  CheckCircle2,
  CircleAlert,
  Clock3,
  FileCheck2,
  History,
  LoaderCircle,
  MessageSquareText,
  RotateCcw,
  Send,
  Undo2,
  UserRound,
  UsersRound,
  X,
  XCircle,
} from "@lucide/vue";
import { PlatformDetailDrawer } from "@platform-ui";

import { approvalApi, itemOf } from "@/approvalApi";

const props = defineProps({
  open: { type: Boolean, default: false },
  applicationId: { type: [String, Number], default: "" },
});

const emit = defineEmits(["close", "changed"]);

const loading = ref(false);
const acting = ref(false);
const errorMessage = ref("");
const application = ref(null);
const actionMode = ref("");
const comment = ref("");
const actionError = ref("");

const fields = computed(() => Array.isArray(application.value?.formSchema?.fields) ? application.value.formSchema.fields : []);
const tasks = computed(() => Array.isArray(application.value?.tasks) ? application.value.tasks : []);
const events = computed(() => Array.isArray(application.value?.events) ? application.value.events : []);
const availableActions = computed(() => Array.isArray(application.value?.availableActions) ? application.value.availableActions : []);
const activeTask = computed(() => tasks.value.find((task) => task.canAct) || null);
const statusClass = computed(() => {
  const status = String(application.value?.status || "").toLowerCase();
  if (status === "approved") return "is-success";
  if (["rejected", "returned", "exception"].includes(status)) return "is-danger";
  if (status === "pending") return "is-warning";
  return "is-neutral";
});
const actionConfig = computed(() => ({
  approve: { title: "同意审批", button: "确认同意", icon: Check, className: "approval-button-primary", required: Boolean(application.value?.settings?.requireApprovalComment), placeholder: "填写审批意见（可选）" },
  reject: { title: "拒绝审批", button: "确认拒绝", icon: XCircle, className: "approval-button-danger", required: application.value?.settings?.requireRejectComment !== false, placeholder: "请填写拒绝原因" },
  return: { title: "退回并结束", button: "确认退回并结束", icon: Undo2, className: "approval-button-warning", required: application.value?.settings?.requireReturnComment !== false, placeholder: "请填写退回原因" },
  withdraw: { title: "撤回申请", button: "确认撤回", icon: ArrowLeftFromLine, className: "approval-button-danger", required: false, placeholder: "填写撤回原因（可选）" },
}[actionMode.value] || null));

function fieldKey(field, index) {
  return String(field?.key || field?.id || `field_${index + 1}`);
}

function fieldLabel(field) {
  return String(field?.label || field?.name || "未命名字段");
}

function isWideField(field) {
  if (["textarea", "attachment", "description"].includes(field?.type)) return true;
  if (field?.type !== "text") return false;
  const rows = Number(field.rows);
  return Number.isFinite(rows) && Math.trunc(rows) > 1;
}

function displayValue(field, index) {
  const value = application.value?.values?.[fieldKey(field, index)];
  if (value === undefined || value === null || value === "") return "-";
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (item && typeof item === "object") return item.name || item.label || item.value || "附件";
      return String(item);
    }).join("、") || "-";
  }
  if (typeof value === "object") return value.name || value.label || JSON.stringify(value);
  return String(value);
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date).replaceAll("/", "-");
}

function taskStatusLabel(task) {
  return {
    pending: "待处理",
    waiting: "未开始",
    approved: "已同意",
    rejected: "已拒绝",
    returned: "已退回",
    skipped: "已跳过",
    copied: "已抄送",
  }[String(task?.status || "").toLowerCase()] || task?.status || "-";
}

function taskStatusClass(task) {
  const status = String(task?.status || "").toLowerCase();
  if (["approved", "copied"].includes(status)) return "is-success";
  if (["rejected", "returned"].includes(status)) return "is-danger";
  if (status === "pending") return "is-warning";
  return "is-neutral";
}

function eventIcon(action) {
  if (["approved", "completed"].includes(action)) return CheckCircle2;
  if (["rejected", "exception"].includes(action)) return XCircle;
  if (action === "returned") return Undo2;
  if (action === "withdrawn") return ArrowLeftFromLine;
  return Clock3;
}

function eventActorLabel(event) {
  const actorName = event?.actorName || "系统";
  if (!event?.data?.isProxying && !event?.data?.isProxy) return actorName;
  const effectiveUser = event.data.effectiveUserName || event.data.effectiveUserId || "有效用户";
  return `${actorName}（代${effectiveUser}操作）`;
}

async function load() {
  if (!props.open || !props.applicationId) return;
  loading.value = true;
  errorMessage.value = "";
  actionMode.value = "";
  comment.value = "";
  try {
    const result = await approvalApi.application(props.applicationId);
    application.value = itemOf(result, ["application"]);
    if (!application.value) throw new Error("审批申请不存在");
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "审批详情加载失败";
    application.value = null;
  } finally {
    loading.value = false;
  }
}

function beginAction(action) {
  actionMode.value = action;
  comment.value = "";
  actionError.value = "";
}

function resetAction() {
  actionMode.value = "";
  comment.value = "";
  actionError.value = "";
}

function cancelAction() {
  if (acting.value) return;
  resetAction();
}

async function submitAction() {
  if (!actionConfig.value || acting.value) return;
  if (actionConfig.value.required && !comment.value.trim()) {
    actionError.value = "请填写处理意见";
    return;
  }
  acting.value = true;
  actionError.value = "";
  try {
    const result = await approvalApi.actOnApplication(application.value.id, actionMode.value, {
      comment: comment.value.trim(),
      taskId: activeTask.value?.id || undefined,
      revision: application.value.revision,
    });
    application.value = itemOf(result, ["application"]);
    const completedAction = actionMode.value;
    resetAction();
    emit("changed", { action: completedAction, application: application.value });
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : "审批操作失败";
  } finally {
    acting.value = false;
  }
}

watch(() => [props.open, props.applicationId], load);
onMounted(load);
</script>

<template>
  <PlatformDetailDrawer :open="open" labelled-by="approval-detail-title" :suspended="acting" @close="emit('close')">
    <header class="approval-drawer-header">
      <div class="approval-drawer-title">
        <span class="approval-record-icon"><FileCheck2 aria-hidden="true" /></span>
        <div class="min-w-0">
          <h2 id="approval-detail-title">{{ application?.title || application?.templateName || "审批详情" }}</h2>
          <p>{{ application?.serialNo || "正在加载审批信息" }}</p>
        </div>
      </div>
      <button type="button" class="approval-icon-button" aria-label="关闭审批详情" @click="emit('close')"><X aria-hidden="true" /></button>
    </header>

    <div v-if="errorMessage" class="approval-alert is-error approval-drawer-alert" role="alert">
      <CircleAlert aria-hidden="true" /><span class="flex-1">{{ errorMessage }}</span><button type="button" class="approval-link-button" @click="load"><RotateCcw aria-hidden="true" />重试</button>
    </div>

    <div v-if="loading" class="approval-status-panel approval-drawer-status" role="status"><LoaderCircle class="animate-spin text-blue-600" aria-hidden="true" />正在加载审批详情...</div>

    <div v-else-if="application" class="approval-detail-content">
      <section class="approval-detail-summary" aria-label="审批概要">
        <div><span>审批状态</span><strong><i class="approval-status" :class="statusClass">{{ application.statusLabel || application.status }}</i></strong></div>
        <div><span>发起人</span><strong>{{ application.initiatorName || "-" }}</strong></div>
        <div><span>当前节点</span><strong>{{ application.currentNodeName || "流程已结束" }}</strong></div>
        <div><span>提交时间</span><strong>{{ formatDate(application.submittedAt) }}</strong></div>
      </section>

      <section class="approval-form-section" aria-labelledby="approval-detail-form-title">
        <div class="approval-form-section-title"><span /><h3 id="approval-detail-form-title">申请内容</h3></div>
        <dl class="approval-detail-fields">
          <template v-for="(field, index) in fields" :key="fieldKey(field, index)">
            <div v-if="field.type !== 'divider'" :class="{ 'is-wide': isWideField(field) }">
              <dt>{{ fieldLabel(field) }}</dt>
              <dd>{{ field.type === 'description' ? field.placeholder || '-' : displayValue(field, index) }}</dd>
            </div>
          </template>
        </dl>
      </section>

      <section class="approval-form-section" aria-labelledby="approval-detail-progress-title">
        <div class="approval-form-section-title"><span /><h3 id="approval-detail-progress-title">审批进度</h3></div>
        <ol class="approval-task-list">
          <li v-for="task in tasks" :key="task.id">
            <span class="approval-task-marker"><UsersRound v-if="task.taskType === 'cc'" aria-hidden="true" /><UserRound v-else aria-hidden="true" /></span>
            <div class="min-w-0 flex-1">
              <div class="approval-task-heading"><strong>{{ task.nodeName || "审批节点" }}</strong><span class="approval-status" :class="taskStatusClass(task)">{{ taskStatusLabel(task) }}</span></div>
              <p>{{ task.assigneeName || task.assigneeUserId || "-" }}<template v-if="task.comment"> · {{ task.comment }}</template></p>
              <small>{{ formatDate(task.actedAt || task.activatedAt) }}</small>
            </div>
          </li>
          <li v-if="!tasks.length" class="approval-empty-inline">暂无审批任务</li>
        </ol>
      </section>

      <section class="approval-form-section" aria-labelledby="approval-detail-history-title">
        <div class="approval-form-section-title"><span /><History aria-hidden="true" /><h3 id="approval-detail-history-title">流转记录</h3></div>
        <ol class="approval-event-list">
          <li v-for="event in events" :key="event.id">
            <span><component :is="eventIcon(event.action)" aria-hidden="true" /></span>
            <div><strong>{{ event.actionLabel || event.action }}</strong><p>{{ eventActorLabel(event) }}<template v-if="event.nodeName"> · {{ event.nodeName }}</template></p><blockquote v-if="event.comment">{{ event.comment }}</blockquote><small>{{ formatDate(event.createdAt) }}</small></div>
          </li>
          <li v-if="!events.length" class="approval-empty-inline">暂无流转记录</li>
        </ol>
      </section>
    </div>

    <section v-if="actionConfig" class="approval-action-panel" :aria-labelledby="`approval-action-${actionMode}-title`">
      <div class="approval-action-panel-head"><component :is="actionConfig.icon" aria-hidden="true" /><h3 :id="`approval-action-${actionMode}-title`">{{ actionConfig.title }}</h3></div>
      <label class="approval-field"><span>处理意见 <b v-if="actionConfig.required" aria-hidden="true">*</b></span><textarea v-model.trim="comment" rows="3" :required="actionConfig.required" :placeholder="actionConfig.placeholder" :aria-invalid="Boolean(actionError)" /></label>
      <p v-if="actionError" class="approval-field-error" role="alert">{{ actionError }}</p>
      <div class="approval-action-panel-buttons"><button type="button" class="approval-button approval-button-secondary" :disabled="acting" @click="cancelAction">取消</button><button type="button" class="approval-button" :class="actionConfig.className" :disabled="acting" :aria-busy="acting" data-ai-action="approval.application.action.confirm" @click="submitAction"><LoaderCircle v-if="acting" class="animate-spin" aria-hidden="true" /><component :is="actionConfig.icon" v-else aria-hidden="true" />{{ acting ? "处理中..." : actionConfig.button }}</button></div>
    </section>

    <footer v-else-if="application && availableActions.length" class="approval-drawer-footer approval-action-footer">
      <button v-if="availableActions.includes('withdraw')" type="button" class="approval-button approval-button-danger-text" @click="beginAction('withdraw')"><ArrowLeftFromLine aria-hidden="true" />撤回</button>
      <span class="flex-1" />
      <button v-if="availableActions.includes('return')" type="button" class="approval-button approval-button-warning-text" @click="beginAction('return')"><Undo2 aria-hidden="true" />退回并结束</button>
      <button v-if="availableActions.includes('reject')" type="button" class="approval-button approval-button-danger" @click="beginAction('reject')"><XCircle aria-hidden="true" />拒绝</button>
      <button v-if="availableActions.includes('approve')" type="button" class="approval-button approval-button-primary" @click="beginAction('approve')"><Check aria-hidden="true" />同意</button>
    </footer>
  </PlatformDetailDrawer>
</template>
