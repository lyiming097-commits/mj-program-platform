<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { apiGet, apiPost } from "@/api";
import SettingsUnsavedChangesDialog from "./SettingsUnsavedChangesDialog.vue";
const props = defineProps({ target: { type: Object, default: null } });
const emit = defineEmits(["close", "saved", "busy-change"]);
const preview = ref(null),
  loading = ref(false),
  saving = ref(false),
  error = ref("");
let requestId = 0;
const disabling = computed(() => props.target?.accountStatus === "禁用");
const title = computed(
  () =>
    `确认${disabling.value ? "禁用" : "启用"}${props.target?.employee?.name || "全部在职账号"}`,
);
const message = computed(() => {
  const scope = props.target?.employee
    ? `员工：${props.target.employee.name}（${props.target.employee.userId}）`
    : "范围：全部在职钉钉员工，包含所有部门。";
  const count = loading.value
    ? "正在核对影响人数…"
    : preview.value
      ? `本次将${disabling.value ? "禁用" : "启用"} ${preview.value.count} 人。`
      : "请重新加载影响人数后确认。";
  const effect = disabling.value
    ? "禁用后无法登录平台，现有会话将失效。"
    : "启用后可重新登录；业务权限仍按各应用配置生效。";
  const self =
    disabling.value && preview.value?.affectsCurrentAccount
      ? "本次包含当前登录账号或代理操作者，执行后当前会话也会失效。"
      : "";
  return [
    scope,
    count,
    effect,
    self,
    "操作人、时间和受影响人员将记录在账号操作记录中。",
  ]
    .filter(Boolean)
    .join("\n");
});
async function loadPreview() {
  const seq = ++requestId;
  preview.value = null;
  error.value = "";
  loading.value = true;
  try {
    const data = await apiGet("/api/org/account-status/preview", {
      accountStatus: props.target.accountStatus,
      userId: props.target.employee?.userId,
    });
    if (seq === requestId) preview.value = data;
  } catch (reason) {
    if (seq === requestId) error.value = reason.message || "影响人数加载失败";
  } finally {
    if (seq === requestId) loading.value = false;
  }
}
async function confirm() {
  if (
    saving.value ||
    loading.value ||
    !preview.value?.confirmationToken ||
    !preview.value.count
  )
    return;
  saving.value = true;
  error.value = "";
  try {
    const employee = props.target.employee;
    const path = employee
      ? `/api/org/employees/${encodeURIComponent(employee.userId)}/account-status`
      : "/api/org/employees/account-status/bulk";
    await apiPost(path, {
      accountStatus: props.target.accountStatus,
      confirmationToken: preview.value.confirmationToken,
    });
    emit("saved", {
      count: preview.value.count,
      accountStatus: props.target.accountStatus,
    });
  } catch (reason) {
    error.value = reason.message || "账号状态更新失败";
    if (reason.status === 409) preview.value = null;
  } finally {
    saving.value = false;
  }
}
watch(
  () => props.target,
  (target) => {
    ++requestId;
    if (target) void loadPreview();
  },
  { immediate: true },
);
watch(saving, (value) => emit("busy-change", value), { flush: "sync" });
onBeforeUnmount(() => {
  ++requestId;
  emit("busy-change", false);
});
</script>
<template>
  <SettingsUnsavedChangesDialog
    :open="Boolean(target)"
    :title="title"
    :message="message"
    cancel-text="取消"
    cancel-tone="secondary"
    :confirm-text="disabling ? '确认禁用' : '确认启用'"
    :confirm-tone="disabling ? 'danger' : 'primary'"
    :confirm-disabled="
      loading || !preview?.confirmationToken || !preview?.count
    "
    :busy="saving"
    :error="error"
    @cancel="emit('close')"
    @confirm="confirm"
  >
    <button
      v-if="error && !saving"
      type="button"
      class="mt-2 text-sm font-semibold text-blue-600"
      :disabled="loading"
      @click="loadPreview"
    >
      重新核对影响人数
    </button>
  </SettingsUnsavedChangesDialog>
</template>
