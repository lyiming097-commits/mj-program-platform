<script setup>
import { computed, useId } from "vue";

const props = defineProps({
  id: { type: String, default: "" },
  modelValue: { type: String, default: "" },
  name: { type: String, default: "" },
  type: {
    type: String,
    default: "date",
    validator: (value) => ["date", "month", "datetime-local"].includes(value),
  },
  disabled: { type: Boolean, default: false },
  ariaLabel: { type: String, default: "选择日期" },
  ariaInvalid: { type: Boolean, default: undefined },
  ariaDescribedby: { type: String, default: undefined },
});

const emit = defineEmits(["blur", "change", "update:modelValue"]);
const generatedId = useId();
const controlId = computed(() => props.id || generatedId);
const displayValue = computed(() => {
  const value = String(props.modelValue || "");
  if (value && props.type === "datetime-local") {
    const [date, time] = value.split("T");
    if (date && time) return `${date} ${time.slice(0, 5)}`;
  }
  if (value) return value;
  if (props.type === "month") return "年 / 月";
  if (props.type === "datetime-local") return "年 / 月 / 日  时 : 分";
  return "年 / 月 / 日";
});

function openPicker(event) {
  if (props.disabled || typeof event.currentTarget?.showPicker !== "function") return;
  try {
    event.currentTarget.showPicker();
  } catch {
    // Native keyboard and browser controls remain available.
  }
}

function updateValue(event) {
  emit("update:modelValue", event.currentTarget.value);
}
</script>

<template>
  <div class="as-date-field" :class="{ 'is-disabled': disabled, 'is-empty': !modelValue }">
    <span aria-hidden="true">{{ displayValue }}</span>
    <input
      :id="controlId"
      :value="modelValue"
      :name="name || controlId"
      :type="type"
      :disabled="disabled"
      :aria-label="ariaLabel"
      :aria-invalid="ariaInvalid"
      :aria-describedby="ariaDescribedby"
      @click="openPicker"
      @input="updateValue"
      @change="emit('change', $event)"
      @blur="emit('blur', $event)"
    >
  </div>
</template>

<style scoped>
.as-date-field { position: relative; width: 100%; height: 36px; overflow: hidden; border: 1px solid #d8e2ee; border-radius: 8px; background: linear-gradient(180deg, #fff 0%, #f8fafc 100%); color: #334155; box-shadow: inset 0 1px 0 rgb(255 255 255 / 90%), 0 1px 2px rgb(15 23 42 / 4%); transition: border-color 160ms ease, box-shadow 160ms ease; }
.as-date-field:focus-within { border-color: #60a5fa; box-shadow: 0 0 0 2px rgb(219 234 254 / 90%); }
.as-date-field > span { display: flex; height: 100%; align-items: center; overflow: hidden; padding: 0 10px; font-size: 12px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.as-date-field.is-empty > span { color: #94a3b8; font-weight: 500; }
.as-date-field.is-disabled { background: #f1f5f9; color: #64748b; box-shadow: none; }
.as-date-field > input { position: absolute; inset: 0; width: 100%; height: 100%; cursor: pointer; opacity: 0; }
.as-date-field.is-disabled > input { cursor: not-allowed; }
</style>
