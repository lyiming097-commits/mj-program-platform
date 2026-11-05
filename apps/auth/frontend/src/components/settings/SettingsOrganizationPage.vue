<script setup>
import SettingsWorkspace from "@/components/settings/SettingsWorkspace.vue";

defineProps({
  initialManagementTab: { type: String, default: "department" },
});
const emit = defineEmits(["dirty-change", "saving-change"]);
</script>

<template>
  <SettingsWorkspace
    :initial-management-tab="initialManagementTab"
    @dirty-change="emit('dirty-change', $event)"
    @saving-change="emit('saving-change', $event)"
  />
</template>
