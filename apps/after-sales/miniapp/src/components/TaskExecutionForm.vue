<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, shallowRef, watch } from "vue";
import type { MobileTask } from "@/api/types";
import { saveMobileTask, taskDraft, taskSubmission } from "@/composables/useMobileTasks";
import DateTimeField from "@/components/DateTimeField.vue";

const props = defineProps<{ task: MobileTask }>();
const emit = defineEmits<{ completed: []; error: [message: string] }>();

const form = reactive({
  actualEndAt: "",
  actualFee: "",
  actualFeeNote: "",
  note: "",
});
const syncState = shallowRef<"idle" | "saving" | "saved" | "error">("idle");
const submitting = shallowRef(false);
const error = shallowRef("");
let hydrating = false;
let autosaveTimer: ReturnType<typeof setTimeout> | null = null;
let savePromise: Promise<void> | null = null;
let pendingSave = false;

function setError(message: string): void {
  error.value = message;
  emit("error", message);
}

const isSubmitted = computed(() => taskSubmission(props.task).submitted === true);
const isEditable = computed(() => (
  !isSubmitted.value
  && ["assigned", "accepted", "in_progress"].includes(props.task.assignmentStatus)
  && props.task.node.status === "active"
  && Boolean(props.task.node.actualStartAt)
));
const requiresActualFee = computed(() => props.task.serviceType !== "presales");
const actualDuration = computed(() => {
  const start = Date.parse(String(props.task.node.actualStartAt || ""));
  const end = Date.parse(form.actualEndAt);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "";
  const totalMinutes = Math.floor((end - start) / 60_000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  return `${days}天${hours}小时${minutes}分钟`;
});
const syncLabel = computed(() => ({
  idle: "",
  saving: "正在同步",
  saved: "已自动保存",
  error: "同步失败",
}[syncState.value]));

function localDateTime(value: unknown): string {
  if (!value) return "";
  const date = new Date(String(value));
  if (!Number.isFinite(date.getTime())) return String(value).slice(0, 19);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 19);
}

function hydrate(): void {
  hydrating = true;
  const submission = taskSubmission(props.task);
  const draft = taskDraft(props.task);
  form.actualEndAt = localDateTime(draft.actualEndAt ?? submission.actualEndAt ?? props.task.node.actualEndAt ?? "");
  form.actualFee = String(draft.actualFee ?? submission.actualFee ?? props.task.node.actualFee ?? "");
  form.actualFeeNote = String(draft.actualFeeNote ?? submission.actualFeeNote ?? props.task.node.businessData?.feeActualNote ?? "");
  form.note = String(draft.note ?? submission.note ?? "");
  syncState.value = "idle";
  hydrating = false;
}

function payload(): Record<string, unknown> {
  return {
    draft: true,
    actualEndAt: form.actualEndAt || null,
    ...(requiresActualFee.value ? { actualFee: form.actualFee === "" ? null : form.actualFee } : {}),
    actualFeeNote: form.actualFeeNote.trim(),
    note: form.note.trim(),
  };
}

async function persistDraft(): Promise<void> {
  if (!isEditable.value) return;
  if (savePromise) {
    pendingSave = true;
    return savePromise;
  }
  syncState.value = "saving";
  savePromise = saveMobileTask(props.task.id, payload())
    .then(() => {
      syncState.value = "saved";
      setError("");
    })
    .catch((reason: unknown) => {
      syncState.value = "error";
      setError(reason instanceof Error ? reason.message : "现场资料同步失败");
    })
    .finally(async () => {
      savePromise = null;
      if (pendingSave) {
        pendingSave = false;
        await persistDraft();
      }
    });
  return savePromise;
}

function scheduleAutosave(): void {
  if (hydrating || !isEditable.value) return;
  syncState.value = "idle";
  if (autosaveTimer) clearTimeout(autosaveTimer);
  autosaveTimer = setTimeout(() => { void persistDraft(); }, 800);
}

async function flushAutosave(): Promise<void> {
  if (autosaveTimer) {
    clearTimeout(autosaveTimer);
    autosaveTimer = null;
    await persistDraft();
  }
  if (savePromise) await savePromise;
}

async function confirmCompletion(): Promise<void> {
  if (!isEditable.value || submitting.value) return;
  setError("");
  if (!form.actualEndAt) {
    setError("请选择实际结束时间");
    return;
  }
  if (!actualDuration.value) {
    setError("实际结束时间不能早于实际开始时间");
    return;
  }
  if (requiresActualFee.value && form.actualFee === "") {
    setError("请填写实际费用，无费用时填写 0");
    return;
  }
  submitting.value = true;
  try {
    await flushAutosave();
    const values = payload();
    delete values.draft;
    await saveMobileTask(props.task.id, { ...values, submitted: true });
    uni.showToast({ title: "完工资料已上传", icon: "success" });
    emit("completed");
  } catch (reason) {
    setError(reason instanceof Error ? reason.message : "确认完工失败");
  } finally {
    submitting.value = false;
  }
}

defineExpose({ confirmCompletion });

watch(
  () => [props.task.id, props.task.node.businessData?.managerReviewStatus],
  hydrate,
  { immediate: true },
);
watch(
  () => [form.actualEndAt, form.actualFee, form.actualFeeNote, form.note],
  scheduleAutosave,
);

onBeforeUnmount(() => {
  if (autosaveTimer) clearTimeout(autosaveTimer);
  void persistDraft();
});
</script>

<template>
  <view class="execution-form">
    <view v-if="isSubmitted" class="success-banner">现场资料已上传，等待管理端推进节点</view>

    <view class="readonly-grid">
      <view class="readonly-grid-item">
        <text class="readonly-grid-label">实际开始时间</text>
        <text class="readonly-grid-value">{{ localDateTime(task.node.actualStartAt).replace("T", " ") || "等待管理端确认开始" }}</text>
      </view>
      <view class="readonly-grid-item">
        <text class="readonly-grid-label">实际服务时长</text>
        <text class="readonly-grid-value">{{ actualDuration || "待实际结束后计算" }}</text>
      </view>
    </view>

    <label class="form-field">
      <text class="field-label">实际结束时间</text>
      <DateTimeField v-if="isEditable" v-model="form.actualEndAt" />
      <text v-else class="readonly-value">{{ localDateTime(form.actualEndAt).replace("T", " ") || "-" }}</text>
    </label>
    <label v-if="requiresActualFee" class="form-field">
      <text class="field-label">实际费用</text>
      <input v-if="isEditable" v-model="form.actualFee" class="field-input" type="digit" placeholder="无费用时填写 0" />
      <text v-else class="readonly-value">{{ form.actualFee === "" ? "-" : `${Number(form.actualFee).toFixed(2)} 元` }}</text>
    </label>
    <label v-if="requiresActualFee" class="form-field">
      <text class="field-label">实际费用备注</text>
      <textarea v-if="isEditable" v-model="form.actualFeeNote" class="field-textarea" maxlength="5000" placeholder="记录交通、人工、辅材等费用" />
      <text v-else class="readonly-value">{{ form.actualFeeNote || "-" }}</text>
    </label>
    <label class="form-field">
      <text class="field-label">现场备注</text>
      <textarea v-if="isEditable" v-model="form.note" class="field-textarea" maxlength="5000" placeholder="记录现场差异、客户确认或后续事项" />
      <text v-else class="readonly-value">{{ form.note || "-" }}</text>
    </label>

    <view v-if="isEditable && syncLabel" class="sync-state-row">
      <text class="sync-state" :class="`is-${syncState}`">{{ syncLabel }}</text>
    </view>
  </view>
</template>

<style scoped>
.execution-form { display: grid; gap: 24rpx; }
.readonly-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16rpx; }
.readonly-grid-item { min-width: 0; }
.readonly-grid-label, .readonly-grid-value { display: block; }
.readonly-grid-label { margin-bottom: 10rpx; color: #475467; font-size: 22rpx; font-weight: 700; }
.readonly-grid-value { display: flex; min-height: 72rpx; align-items: center; overflow-wrap: anywhere; border: 1rpx solid #e1e7ef; border-radius: 14rpx; background: #f4f7fb; padding: 12rpx 20rpx; color: #526174; font-size: 22rpx; font-weight: 500; line-height: 32rpx; }
.form-field { display: block; }
.execution-form .field-input { height: 72rpx; }
.execution-form .field-textarea { width: 100%; height: 144rpx; min-height: 144rpx; }
.readonly-value { display: flex; min-height: 72rpx; align-items: center; border: 1rpx solid #e1e7ef; border-radius: 14rpx; background: #f4f7fb; padding: 12rpx 20rpx; color: #526174; font-size: 22rpx; line-height: 32rpx; }
.sync-state-row { display: flex; justify-content: flex-end; border-top: 1rpx solid #edf0f2; padding-top: 20rpx; }
.sync-state { color: #7a8794; font-size: 20rpx; font-weight: 600; }
.sync-state.is-saved { color: #155eef; }
.sync-state.is-error { color: #b42318; }
</style>
