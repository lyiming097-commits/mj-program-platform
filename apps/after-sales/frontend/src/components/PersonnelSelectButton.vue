<script setup>
import { ChevronRight, LoaderCircle } from "@lucide/vue";

defineProps({
  name: { type: String, default: "" },
  detail: { type: String, default: "" },
  placeholder: { type: String, default: "选择项目人员" },
  label: { type: String, default: "项目人员" },
  disabled: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
});
defineEmits(["select"]);
</script>

<template>
  <button
    type="button"
    class="as-personnel-picker"
    :disabled="disabled || busy"
    :aria-label="`${label}：${name || '未选择'}，${name ? '点击更换' : '点击选择'}`"
    aria-haspopup="dialog"
    :title="name ? `更换${label}：${name}` : placeholder"
    @click="$emit('select', $event)"
  >
    <span class="as-avatar" aria-hidden="true">{{ String(name || '选').slice(0, 1) }}</span>
    <span><strong>{{ name || placeholder }}</strong><small v-if="detail">{{ detail }}</small></span>
    <LoaderCircle v-if="busy" class="as-spin" aria-hidden="true" />
    <ChevronRight v-else aria-hidden="true" />
  </button>
</template>
