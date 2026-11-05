<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";
import { Check, ChevronDown } from "@lucide/vue";

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: "请选择" },
  ariaLabel: { type: String, default: "下拉多选" },
  describedBy: { type: String, default: "" },
  invalid: { type: Boolean, default: false },
  required: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue"]);
const rootRef = ref(null);
const triggerRef = ref(null);
const menuRef = ref(null);
const open = ref(false);
const activeIndex = ref(0);
const menuStyle = ref({});
const controlId = useId();
const listboxId = `${controlId}-listbox`;

const normalizedOptions = computed(() => {
  const seen = new Set();
  return (Array.isArray(props.options) ? props.options : []).map((option) => {
    if (option && typeof option === "object") {
      const value = String(option.value ?? option.label ?? "").trim();
      const label = String(option.label ?? option.value ?? "").trim() || value;
      return { value, label };
    }
    const value = String(option ?? "").trim();
    return { value, label: value };
  }).filter((option) => {
    if (!option.value || seen.has(option.value)) return false;
    seen.add(option.value);
    return true;
  });
});

const selectedValues = computed(() => [...new Set(
  (Array.isArray(props.modelValue) ? props.modelValue : [])
    .map((value) => String(value ?? "").trim())
    .filter(Boolean),
)]);
const selectedSet = computed(() => new Set(selectedValues.value));
const selectionLabel = computed(() => {
  if (!selectedValues.value.length) return props.placeholder;
  if (selectedValues.value.length === 1) {
    const value = selectedValues.value[0];
    return normalizedOptions.value.find((option) => option.value === value)?.label || value;
  }
  return `已选择 ${selectedValues.value.length} 项`;
});
const activeOptionId = computed(() => (
  open.value && normalizedOptions.value[activeIndex.value]
    ? `${controlId}-option-${activeIndex.value}`
    : undefined
));

function clampActiveIndex() {
  activeIndex.value = Math.min(activeIndex.value, Math.max(0, normalizedOptions.value.length - 1));
}

function updateMenuPosition() {
  if (!open.value || !rootRef.value || !menuRef.value) return;
  const anchor = rootRef.value.getBoundingClientRect();
  const viewportPadding = 12;
  const gap = 5;
  const width = Math.min(anchor.width, window.innerWidth - viewportPadding * 2);
  const desiredHeight = Math.min(menuRef.value.scrollHeight || 240, 240);
  const spaceBelow = window.innerHeight - anchor.bottom - viewportPadding - gap;
  const spaceAbove = anchor.top - viewportPadding - gap;
  const opensAbove = spaceBelow < Math.min(desiredHeight, 160) && spaceAbove > spaceBelow;
  const availableHeight = Math.max(80, opensAbove ? spaceAbove : spaceBelow);
  const renderedHeight = Math.min(desiredHeight, availableHeight);
  const left = Math.min(
    Math.max(viewportPadding, anchor.left),
    Math.max(viewportPadding, window.innerWidth - width - viewportPadding),
  );
  const top = opensAbove
    ? Math.max(viewportPadding, anchor.top - renderedHeight - gap)
    : Math.min(window.innerHeight - viewportPadding - renderedHeight, anchor.bottom + gap);
  menuStyle.value = {
    left: `${Math.round(left)}px`,
    top: `${Math.round(top)}px`,
    width: `${Math.round(width)}px`,
    maxHeight: `${Math.round(availableHeight)}px`,
  };
}

async function openMenu() {
  if (props.disabled || open.value) return;
  const selectedIndex = normalizedOptions.value.findIndex((option) => selectedSet.value.has(option.value));
  activeIndex.value = selectedIndex >= 0 ? selectedIndex : 0;
  open.value = true;
  await nextTick();
  updateMenuPosition();
}

function closeMenu({ restoreFocus = false } = {}) {
  if (!open.value) return;
  open.value = false;
  menuStyle.value = {};
  if (restoreFocus) nextTick(() => triggerRef.value?.focus?.({ preventScroll: true }));
}

function toggleMenu() {
  if (open.value) closeMenu();
  else openMenu();
}

function toggleOption(option) {
  if (!option || props.disabled) return;
  const next = new Set(selectedValues.value);
  if (next.has(option.value)) next.delete(option.value);
  else next.add(option.value);
  emit("update:modelValue", [...next]);
  nextTick(() => triggerRef.value?.focus?.({ preventScroll: true }));
}

function moveActiveIndex(offset) {
  const count = normalizedOptions.value.length;
  if (!count) return;
  activeIndex.value = (activeIndex.value + offset + count) % count;
  nextTick(() => document.getElementById(activeOptionId.value)?.scrollIntoView?.({ block: "nearest" }));
}

function handleKeydown(event) {
  if (event.key === "Escape" && open.value) {
    event.preventDefault();
    event.stopPropagation();
    closeMenu({ restoreFocus: true });
    return;
  }
  if (event.key === "Tab" && open.value) {
    closeMenu();
    return;
  }
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    event.stopPropagation();
    if (!open.value) openMenu();
    else moveActiveIndex(event.key === "ArrowDown" ? 1 : -1);
    return;
  }
  if (["Enter", " "].includes(event.key)) {
    event.preventDefault();
    event.stopPropagation();
    if (!open.value) openMenu();
    else toggleOption(normalizedOptions.value[activeIndex.value]);
    return;
  }
  if (event.key === "Home" && open.value) {
    event.preventDefault();
    activeIndex.value = 0;
  } else if (event.key === "End" && open.value) {
    event.preventDefault();
    activeIndex.value = Math.max(0, normalizedOptions.value.length - 1);
  }
}

function handleDocumentPointerDown(event) {
  if (open.value && !rootRef.value?.contains(event.target) && !menuRef.value?.contains(event.target)) closeMenu();
}

function handleDocumentFocusIn(event) {
  if (open.value && !rootRef.value?.contains(event.target) && !menuRef.value?.contains(event.target)) closeMenu();
}

watch(normalizedOptions, clampActiveIndex);
watch(() => props.disabled, (disabled) => {
  if (disabled) closeMenu();
});

onMounted(() => {
  document.addEventListener("pointerdown", handleDocumentPointerDown, true);
  document.addEventListener("focusin", handleDocumentFocusIn, true);
  window.addEventListener("resize", updateMenuPosition);
  window.addEventListener("scroll", updateMenuPosition, true);
});

onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", handleDocumentPointerDown, true);
  document.removeEventListener("focusin", handleDocumentFocusIn, true);
  window.removeEventListener("resize", updateMenuPosition);
  window.removeEventListener("scroll", updateMenuPosition, true);
});
</script>

<template>
  <div ref="rootRef" class="approval-multi-select" :class="{ 'is-open': open, 'is-invalid': invalid }">
    <button
      ref="triggerRef"
      type="button"
      class="approval-multi-select-trigger"
      role="combobox"
      aria-haspopup="listbox"
      :aria-label="ariaLabel"
      :aria-expanded="open"
      :aria-controls="listboxId"
      :aria-activedescendant="activeOptionId"
      :aria-describedby="describedBy || undefined"
      :aria-invalid="invalid || undefined"
      :aria-required="required || undefined"
      :disabled="disabled"
      @click="toggleMenu"
      @keydown="handleKeydown"
    >
      <span :class="{ 'is-placeholder': !selectedValues.length }">{{ selectionLabel }}</span>
      <ChevronDown aria-hidden="true" />
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        :id="listboxId"
        ref="menuRef"
        class="approval-multi-select-menu"
        :style="menuStyle"
        role="listbox"
        :aria-label="ariaLabel"
        aria-multiselectable="true"
        @mousedown.prevent
      >
        <button
          v-for="(option, index) in normalizedOptions"
          :id="`${controlId}-option-${index}`"
          :key="option.value"
          type="button"
          tabindex="-1"
          class="approval-multi-select-option"
          :class="{ 'is-active': activeIndex === index, 'is-selected': selectedSet.has(option.value) }"
          role="option"
          :aria-selected="selectedSet.has(option.value)"
          @mouseenter="activeIndex = index"
          @click="toggleOption(option)"
        >
          <span class="approval-multi-select-check"><Check aria-hidden="true" /></span>
          <span>{{ option.label }}</span>
        </button>
        <div v-if="!normalizedOptions.length" class="approval-multi-select-empty">暂无可选项</div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.approval-multi-select {
  width: 100%;
  min-width: 0;
}

.approval-multi-select-trigger {
  display: flex;
  width: 100%;
  min-height: 38px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid #dbe5ef;
  border-radius: 6px;
  background: #fff;
  padding: 8px 10px;
  color: #1e293b;
  cursor: pointer;
  font-size: 13px;
  text-align: left;
}

.approval-multi-select-trigger > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.approval-multi-select-trigger > span.is-placeholder { color: #94a3b8; }
.approval-multi-select-trigger > svg { width: 15px; height: 15px; flex: 0 0 auto; color: #94a3b8; transition: transform 140ms ease; }
.approval-multi-select.is-open .approval-multi-select-trigger > svg { transform: rotate(180deg); }
.approval-multi-select-trigger:hover:not(:disabled) { border-color: #bfdbfe; }
.approval-multi-select-trigger:focus-visible,
.approval-multi-select.is-open .approval-multi-select-trigger { border-color: #60a5fa; outline: 0; box-shadow: 0 0 0 3px #dbeafe; }
.approval-multi-select.is-invalid .approval-multi-select-trigger { border-color: #f87171; }

.approval-multi-select-menu {
  position: fixed;
  z-index: 90;
  overflow-y: auto;
  border: 1px solid #dbe5ef;
  border-radius: 6px;
  background: #fff;
  padding: 4px;
  box-shadow: 0 10px 28px rgb(15 23 42 / 14%);
}

.approval-multi-select-option {
  display: flex;
  width: 100%;
  min-height: 38px;
  align-items: center;
  gap: 9px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  padding: 7px 9px;
  color: #334155;
  cursor: pointer;
  font-size: 13px;
  text-align: left;
}

.approval-multi-select-option:hover,
.approval-multi-select-option.is-active { background: #eff6ff; color: #1d4ed8; }
.approval-multi-select-check { display: inline-flex; width: 16px; height: 16px; flex: 0 0 auto; align-items: center; justify-content: center; border: 1px solid #cbd5e1; border-radius: 4px; background: #fff; color: transparent; }
.approval-multi-select-check svg { width: 12px; height: 12px; }
.approval-multi-select-option.is-selected .approval-multi-select-check { border-color: #2563eb; background: #2563eb; color: #fff; }
.approval-multi-select-empty { padding: 12px 10px; color: #94a3b8; font-size: 12px; text-align: center; }

@media (max-width: 767px) {
  .approval-multi-select-trigger,
  .approval-multi-select-option { min-height: 44px; }
}
</style>
