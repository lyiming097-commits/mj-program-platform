<script setup>
import { computed, ref } from "vue";

const props = defineProps({
  activeTab: { type: String, required: true },
  departmentLabel: { type: String, default: "钉钉组织架构" },
  disabled: { type: Boolean, default: false },
  showPermissions: { type: Boolean, default: false },
  showHandover: { type: Boolean, default: false },
});
const emit = defineEmits(["select"]);

const tabs = [
  { id: "department", label: "钉钉组织架构", tabId: "auth-dingtalk-organization-tab", panelId: "auth-dingtalk-organization-panel" },
  { id: "inactive", label: "离职人员", tabId: "auth-handover-tab", panelId: "auth-handover-panel" },
  { id: "permissions", label: "权限设置", tabId: "auth-permissions-tab", panelId: "auth-permissions-panel" },
];
const visibleTabs = computed(() => tabs.filter((tab) => (
  (tab.id !== "permissions" || props.showPermissions)
  && (tab.id !== "inactive" || props.showHandover)
)));
const buttons = ref([]);

function handleKeydown(event, index) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const available = buttons.value.filter((button) => button && !button.disabled);
  const nextIndex = event.key === "Home" ? 0
    : event.key === "End" ? available.length - 1
      : (available.indexOf(buttons.value[index]) + (event.key === "ArrowRight" ? 1 : -1) + available.length) % available.length;
  available[nextIndex]?.focus();
}
</script>

<template>
  <nav class="flex h-12 shrink-0 items-center overflow-x-auto border-b border-slate-200 bg-white px-3" aria-label="组织架构页面">
    <div class="flex w-max min-w-full gap-2" role="tablist" aria-label="组织架构页面">
      <button
        v-for="(tab, index) in visibleTabs"
        :id="tab.tabId"
        :key="tab.id"
        :ref="(element) => { buttons[index] = element; }"
        type="button"
        role="tab"
        :aria-selected="activeTab === tab.id"
        :aria-controls="tab.panelId"
        :tabindex="activeTab === tab.id ? 0 : -1"
        :disabled="disabled"
        class="inline-flex h-10 shrink-0 items-center whitespace-nowrap rounded-md px-3 text-sm font-medium transition-colors md:h-8"
        :class="[
          activeTab === tab.id ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200',
          tab.id === 'permissions' ? 'ml-auto' : '',
        ]"
        @click="emit('select', tab.id)"
        @keydown="handleKeydown($event, index)"
      >{{ tab.id === "department" ? departmentLabel : tab.label }}</button>
    </div>
  </nav>
</template>
