<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import SettingsWorkspacePhone from "@/components/settings/SettingsWorkspace_phone.vue";
import SettingsWorkspaceWeb from "@/components/settings/SettingsWorkspace_web.vue";

defineProps({
  initialManagementTab: {
    type: String,
    default: "department",
  },
});
const emit = defineEmits(["dirty-change", "saving-change"]);

const isPhone = ref(typeof window !== "undefined" ? window.matchMedia("(max-width: 767px)").matches : false);
const childDirty = ref(false);
const childSaving = ref(false);

function updateViewportMode() {
  const nextIsPhone = window.matchMedia("(max-width: 767px)").matches;
  if ((childDirty.value || childSaving.value) && nextIsPhone !== isPhone.value) return;
  isPhone.value = nextIsPhone;
}

function handleDirtyChange(value) {
  childDirty.value = Boolean(value);
  emit("dirty-change", childDirty.value);
  if (!childDirty.value) updateViewportMode();
}

function handleSavingChange(value) {
  childSaving.value = Boolean(value);
  emit("saving-change", childSaving.value);
  if (!childSaving.value) updateViewportMode();
}

onMounted(() => {
  updateViewportMode();
  window.addEventListener("resize", updateViewportMode);
  window.addEventListener("orientationchange", updateViewportMode);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", updateViewportMode);
  window.removeEventListener("orientationchange", updateViewportMode);
});
</script>

<template>
  <SettingsWorkspacePhone
    v-if="isPhone"
    :initial-management-tab="initialManagementTab"
    @dirty-change="handleDirtyChange"
    @saving-change="handleSavingChange"
  />
  <SettingsWorkspaceWeb
    v-else
    :initial-management-tab="initialManagementTab"
    @dirty-change="handleDirtyChange"
    @saving-change="handleSavingChange"
  />
</template>
