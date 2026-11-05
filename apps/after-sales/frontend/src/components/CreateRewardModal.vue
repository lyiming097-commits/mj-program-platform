<script setup>
import { computed, reactive, watch } from "vue";
import { Banknote, Gift, LoaderCircle, Send, TimerReset } from "@lucide/vue";
import { ElOption, ElSelect } from "element-plus/es/components/select/index.mjs";
import "element-plus/es/components/select/style/css";
import ModalShell from "@/components/ModalShell.vue";

const props = defineProps({
  open: { type: Boolean, default: false },
  projects: { type: Array, default: () => [] },
  providers: { type: Array, default: () => [] },
  prizes: { type: Array, default: () => [] },
  prizeLoading: { type: Boolean, default: false },
  prizeError: { type: String, default: "" },
  loading: { type: Boolean, default: false },
  projectLoading: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
});

const emit = defineEmits(["close", "provider-change", "retry-prizes", "submit"]);
const rewardTypes = [
  { value: "prize", label: "实物奖励", icon: Gift },
  { value: "cash", label: "现金奖励", icon: Banknote },
  { value: "time_off", label: "调休奖励", icon: TimerReset },
];
const form = reactive(defaultForm());
const selectedProvider = computed(() => props.providers.find((provider) => String(provider.id) === String(form.providerId)) || null);
const providerCity = computed(() => selectedProvider.value?.city || selectedProvider.value?.region || "未设置地区");
const providerOptionLabel = (provider) => [provider.name, provider.roleLabel || provider.role, provider.city || provider.region, provider.phone]
  .filter(Boolean).join(" · ");
const projectOptionLabel = (project) => [project.name, project.customer, project.serviceTypeLabel || project.serviceType, project.code]
  .filter(Boolean).join(" · ");
const canSubmit = computed(() => Boolean(form.providerId && form.title.trim())
  && (form.rewardType !== "prize" || (!props.prizeLoading && !props.prizeError && props.prizes.some((item) => String(item.id) === String(form.prizeId))))
  && (form.rewardType !== "cash" || Number(form.amount) > 0));

function defaultForm() {
  return {
    providerId: "",
    projectId: "",
    rewardType: "prize",
    title: "",
    prizeId: "",
    prize: "",
    amount: "",
    description: "",
  };
}

function close() {
  if (!props.saving) emit("close");
}

function selectProvider(providerId) {
  form.providerId = String(providerId || "");
  form.projectId = "";
  emit("provider-change", form.providerId);
}

const projectPlaceholder = computed(() => {
  if (!form.providerId) return "请先选择人员";
  if (props.projectLoading) return "正在加载关联项目...";
  if (!props.projects.length) return "该人员暂无关联项目";
  return "输入项目名或客户搜索（可不选）";
});

function submit() {
  if (!canSubmit.value || props.saving) return;
  emit("submit", {
    providerId: Number(form.providerId),
    projectId: form.projectId ? Number(form.projectId) : null,
    rewardType: form.rewardType,
    title: form.title.trim(),
    prizeId: form.rewardType === "prize" ? Number(form.prizeId) : null,
    prize: form.rewardType === "time_off" ? form.prize.trim() : "",
    amount: form.rewardType === "cash" ? Number(form.amount) : null,
    description: form.description.trim(),
  });
}

watch(() => props.open, (open) => {
  if (open) Object.assign(form, defaultForm());
});
</script>

<template>
  <ModalShell :open="open" title="新增奖励" description="为服务人员创建奖励记录。" wide @close="close">
    <div v-if="loading" class="as-create-reward-loading"><LoaderCircle class="as-spin" />正在加载服务人员...</div>
    <div v-else class="as-create-reward-form">
      <div class="as-create-reward-meta-grid">
        <label class="as-field"><span>获得人员 *</span><ElSelect :model-value="form.providerId" class="as-searchable-select" popper-class="as-searchable-select-popper" filterable placeholder="输入姓名、角色或城市搜索" no-data-text="未找到匹配的服务人员" aria-label="获得人员" @update:model-value="selectProvider"><ElOption v-for="provider in providers" :key="provider.id" :label="providerOptionLabel(provider)" :value="String(provider.id)" /></ElSelect></label>
        <label class="as-field"><span>关联项目</span><ElSelect v-model="form.projectId" class="as-searchable-select" popper-class="as-searchable-select-popper" filterable clearable :disabled="!form.providerId || projectLoading" :loading="projectLoading" :placeholder="projectPlaceholder" no-data-text="该人员暂无关联项目" aria-label="关联项目"><ElOption v-for="project in projects" :key="project.id" :label="projectOptionLabel(project)" :value="String(project.id)" /></ElSelect></label>
        <label class="as-field"><span>地区（自动取人员城市）</span><input :value="providerCity" readonly></label>
      </div>
      <fieldset class="as-create-reward-types"><legend>奖励类型 *</legend><button v-for="type in rewardTypes" :key="type.value" type="button" :class="{ active: form.rewardType === type.value }" @click="form.rewardType = type.value"><component :is="type.icon" />{{ type.label }}</button></fieldset>
      <div class="as-create-reward-grid">
        <label class="as-field"><span>奖励名称 *</span><input v-model="form.title" maxlength="255" placeholder="例如：服务质量优秀奖励"></label>
        <div v-if="form.rewardType === 'prize'" class="as-field as-create-reward-prize"><span>实物奖品 *</span><ElSelect v-model="form.prizeId" class="as-searchable-select" popper-class="as-searchable-select-popper" filterable :loading="prizeLoading" :disabled="prizeLoading || Boolean(prizeError) || !prizes.length" :placeholder="prizeLoading ? '正在加载奖品...' : '搜索并选择实物奖品'" no-data-text="未找到匹配的奖品" aria-label="实物奖品"><ElOption v-for="item in prizes" :key="item.id" :label="item.name" :value="String(item.id)" /></ElSelect><span v-if="prizeError" class="as-create-reward-prize-status" role="alert">{{ prizeError }} <button type="button" @click="emit('retry-prizes')">重试</button></span><span v-else-if="!prizeLoading && !prizes.length" class="as-create-reward-prize-status">暂无可用奖品，请先在设置的“实物奖励”中添加。</span></div>
        <label v-else-if="form.rewardType === 'cash'" class="as-field"><span>奖励金额 *</span><input v-model="form.amount" type="number" min="0.01" step="0.01" inputmode="decimal" placeholder="0.00"></label>
        <label v-else class="as-field"><span>调休安排</span><input v-model="form.prize" maxlength="255" placeholder="例如：调休半天"></label>
      </div>
      <label class="as-field"><span>奖励说明</span><textarea v-model="form.description" rows="4" maxlength="10000" placeholder="填写奖励原因或发放说明"></textarea></label>
    </div>
    <template #footer><button type="button" class="as-button as-button--secondary" :disabled="saving" @click="close">取消</button><button type="button" class="as-button as-button--primary" :disabled="loading || saving || !canSubmit" @click="submit"><LoaderCircle v-if="saving" class="as-spin" /><Send v-else />创建奖励</button></template>
  </ModalShell>
</template>

<style scoped>
.as-create-reward-loading { display: flex; min-height: 220px; align-items: center; justify-content: center; gap: 7px; color: #718096; font-size: 11px; }
.as-create-reward-loading svg { width: 16px; height: 16px; }
.as-create-reward-form { display: grid; gap: 14px; }
.as-create-reward-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px; }
.as-create-reward-meta-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 13px; }
.as-form-select { width: 100%; }
.as-create-reward-prize { min-width: 0; }
.as-create-reward-prize-status { margin: 5px 0 0; color: var(--as-muted); font-size: 12px; line-height: 18px; }
.as-create-reward-prize-status button { border: 0; background: none; color: var(--as-primary); cursor: pointer; text-decoration: underline; }
.as-field input[readonly] { border-color: #dce5ef; background: #f4f7fa; color: #526273; }
.as-create-reward-types { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; border: 1px solid #dce5ef; border-radius: 7px; margin: 0; padding: 10px 11px 11px; }
.as-create-reward-types legend { padding: 0 4px; color: #475467; font-size: 11px; font-weight: 750; }
.as-create-reward-types button { display: flex; min-height: 36px; align-items: center; justify-content: center; gap: 5px; border: 1px solid #d6dee8; border-radius: 6px; background: #fff; color: #617087; font-size: 10px; font-weight: 700; }
.as-create-reward-types button:hover { border-color: #8cafeb; background: #f7faff; }
.as-create-reward-types button.active { border-color: #7ea5e8; background: #eef5ff; color: #155eef; }
.as-create-reward-types button svg { width: 14px; height: 14px; }
@media (max-width: 800px) { .as-create-reward-meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .as-create-reward-grid, .as-create-reward-meta-grid { grid-template-columns: minmax(0, 1fr); } .as-create-reward-types { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
