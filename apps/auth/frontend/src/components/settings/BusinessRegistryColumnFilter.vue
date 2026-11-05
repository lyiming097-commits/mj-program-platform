<script setup>
import { PlatformSearchSelect } from "@platform-ui";

const props = defineProps({
  modelValue: { type: String, default: "" },
  label: { type: String, required: true },
  type: { type: String, default: "search" },
  options: { type: Array, default: () => [] },
  min: { type: Number, default: undefined },
  max: { type: Number, default: undefined },
});
const emit = defineEmits(["change"]);
function update(event, immediate = false) {
  if (event.target.validity.valid) emit("change", event.target.value, immediate);
}
</script>

<template>
  <div class="registry-column-filter">
    <PlatformSearchSelect v-if="type === 'select'" :model-value="modelValue" :options="options" :aria-label="label" placeholder="全部" search-placeholder="搜索选项" :menu-z-index="90" @change="emit('change', $event, true)" />
    <input v-else :value="modelValue" :type="type" :aria-label="label" :placeholder="type === 'search' ? '搜索' : '全部'"
      :min="min" :max="max" :maxlength="type === 'search' ? 200 : undefined" class="registry-input registry-column-input" :class="{ 'is-active': modelValue }"
      @input="type !== 'date' && update($event)" @change="type === 'date' && update($event, true)" @keydown.enter.prevent="update($event, true)" />
  </div>
</template>
