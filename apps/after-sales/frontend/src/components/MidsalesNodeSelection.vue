<script setup>
import { MIDSALES_PROJECT_STAGES } from "@/midsalesNodes";
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  requiredNodes: { type: Array, default: () => [] },
});
const emit = defineEmits(["update:modelValue"]);
function toggle(key, checked) {
  if (props.disabled || props.requiredNodes.includes(key)) return;
  const values = new Set(props.modelValue);
  if (checked) values.add(key);
  else values.delete(key);
  emit("update:modelValue", MIDSALES_PROJECT_STAGES.map(([id]) => id).filter(id => values.has(id)));
}
</script>

<template>
  <fieldset class="as-fieldset as-field--wide" :disabled="disabled">
    <legend>本项目包含的节点</legend>
    <div class="as-check-grid">
      <label v-for="[id, name] in MIDSALES_PROJECT_STAGES" :key="id">
        <input type="checkbox" :checked="modelValue.includes(id)" :disabled="requiredNodes.includes(id)" @change="toggle(id, $event.target.checked)">
        <span>{{ name }}</span>
      </label>
    </div>
  </fieldset>
</template>
