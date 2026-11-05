<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId } from "vue";
import { ChevronDown } from "@lucide/vue";

const props = defineProps({
  modelValue: { type: String, default: "" },
  options: { type: Array, required: true },
  ariaLabel: { type: String, required: true },
});

const emit = defineEmits(["change"]);
const rootRef = ref(null);
const triggerRef = ref(null);
const menuRef = ref(null);
const open = ref(false);
const activeIndex = ref(0);
const menuStyle = ref({});
const controlId = useId();
const listboxId = `${controlId}-listbox`;

const items = computed(() => {
  const seen = new Set();
  return props.options.map((option) => {
    const value = String(option.value ?? "");
    return { value, label: String(option.label ?? value) };
  }).filter((option) => {
    if (seen.has(option.value)) return false;
    seen.add(option.value);
    return true;
  });
});
const selectedValue = computed(() => String(props.modelValue ?? ""));
const selectedLabel = computed(() => (
  items.value.find((option) => option.value === selectedValue.value)?.label
  || selectedValue.value
  || items.value[0]?.label
  || "请选择"
));
const activeOptionId = computed(() => (
  open.value && items.value[activeIndex.value]
    ? `${controlId}-option-${activeIndex.value}`
    : undefined
));

function updateMenuPosition() {
  if (!open.value || !rootRef.value || !menuRef.value) return;
  const anchor = rootRef.value.getBoundingClientRect();
  const padding = 12;
  const gap = 5;
  const width = Math.min(Math.max(anchor.width, 160), window.innerWidth - padding * 2);
  const height = Math.min(menuRef.value.scrollHeight, 240);
  const below = window.innerHeight - anchor.bottom - padding - gap;
  const above = anchor.top - padding - gap;
  const opensAbove = below < height && above > below;
  const availableHeight = Math.max(44, opensAbove ? above : below);
  const renderedHeight = Math.min(height, availableHeight);
  menuStyle.value = {
    left: `${Math.round(Math.min(Math.max(padding, anchor.left), window.innerWidth - width - padding))}px`,
    top: `${Math.round(opensAbove ? anchor.top - renderedHeight - gap : anchor.bottom + gap)}px`,
    width: `${Math.round(width)}px`,
    maxHeight: `${Math.round(availableHeight)}px`,
  };
}

async function openMenu() {
  if (open.value) return;
  const index = items.value.findIndex((option) => option.value === selectedValue.value);
  activeIndex.value = index < 0 ? 0 : index;
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

function selectOption(option) {
  if (!option) return;
  closeMenu({ restoreFocus: true });
  if (option.value !== selectedValue.value) emit("change", option.value);
}

function handleKeydown(event) {
  if (event.key === "Escape" && open.value) {
    event.preventDefault();
    event.stopPropagation();
    closeMenu({ restoreFocus: true });
    return;
  }
  if (event.key === "Tab") {
    closeMenu();
    return;
  }
  if (["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "].includes(event.key)) {
    event.preventDefault();
    event.stopPropagation();
  } else {
    return;
  }
  const wasOpen = open.value;
  if (!wasOpen) openMenu();
  const count = items.value.length;
  if (!count) return;
  if (event.key === "ArrowDown") activeIndex.value = (activeIndex.value + 1) % count;
  else if (event.key === "ArrowUp") activeIndex.value = (activeIndex.value - 1 + count) % count;
  else if (event.key === "Home") activeIndex.value = 0;
  else if (event.key === "End") activeIndex.value = count - 1;
  else if (wasOpen) selectOption(items.value[activeIndex.value]);
  nextTick(() => {
    if (open.value) document.getElementById(activeOptionId.value)?.scrollIntoView?.({ block: "nearest" });
  });
}

function handleDocumentPointerDown(event) {
  if (open.value && !rootRef.value?.contains(event.target) && !menuRef.value?.contains(event.target)) closeMenu();
}

function handleDocumentFocusIn(event) {
  if (open.value && !rootRef.value?.contains(event.target) && !menuRef.value?.contains(event.target)) closeMenu();
}

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
  <div ref="rootRef" class="approval-filter-select">
    <button
      ref="triggerRef"
      type="button"
      class="approval-filter-trigger"
      :class="{ 'is-open': open, 'is-filtered': Boolean(selectedValue) }"
      role="combobox"
      aria-haspopup="listbox"
      :aria-label="ariaLabel"
      :aria-describedby="`${controlId}-value`"
      :aria-expanded="open"
      :aria-controls="open ? listboxId : undefined"
      :aria-activedescendant="activeOptionId"
      @click="open ? closeMenu() : openMenu()"
      @keydown="handleKeydown"
    >
      <span :id="`${controlId}-value`">{{ selectedLabel }}</span>
      <ChevronDown aria-hidden="true" />
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        :id="listboxId"
        ref="menuRef"
        class="approval-filter-menu"
        :style="menuStyle"
        role="listbox"
        :aria-label="ariaLabel"
        @mousedown.prevent
      >
        <button
          v-for="(option, index) in items"
          :id="`${controlId}-option-${index}`"
          :key="option.value"
          type="button"
          tabindex="-1"
          class="approval-filter-option"
          :class="{ 'is-selected': selectedValue === option.value, 'is-active': activeIndex === index }"
          role="option"
          :aria-selected="selectedValue === option.value"
          @mouseenter="activeIndex = index"
          @click="selectOption(option)"
        >{{ option.label }}</button>
        <p v-if="!items.length" class="approval-filter-empty" role="status">暂无可选项</p>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.approval-filter-select { min-width: 130px; flex: 0 0 auto; }
.approval-filter-trigger {
  display: flex;
  width: 100%;
  height: 36px;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 1px solid #dbe5ef;
  border-radius: 6px;
  background: linear-gradient(180deg, #fff 0%, #f8fafc 100%);
  padding: 0 10px;
  color: #334155;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  text-align: left;
}
.approval-filter-trigger span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.approval-filter-trigger svg { width: 15px; height: 15px; flex: 0 0 auto; color: #64748b; }
.approval-filter-trigger:hover, .approval-filter-trigger.is-open { border-color: #60a5fa; background: #fff; }
.approval-filter-trigger.is-open, .approval-filter-trigger:focus-visible { outline: 2px solid #bfdbfe; outline-offset: 1px; box-shadow: 0 6px 16px rgb(37 99 235 / 10%); }
.approval-filter-trigger.is-filtered { border-color: #bfdbfe; background: #eff6ff; color: #1d4ed8; }
.approval-filter-menu {
  position: fixed;
  z-index: 90;
  overflow-y: auto;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: rgb(255 255 255 / 98%);
  padding: 6px;
  box-shadow: 0 16px 34px rgb(15 23 42 / 16%), 0 3px 10px rgb(37 99 235 / 8%);
}
.approval-filter-option {
  display: flex;
  width: 100%;
  min-height: 36px;
  align-items: center;
  border: 0;
  border-radius: 6px;
  background: transparent;
  padding: 7px 10px;
  color: #475569;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  text-align: left;
}
.approval-filter-option:hover, .approval-filter-option.is-active:not(.is-selected) { background: #eff6ff; color: #1d4ed8; box-shadow: inset 0 0 0 1px #bfdbfe; }
.approval-filter-option.is-selected { background: #2563eb; color: #fff; box-shadow: 0 4px 10px rgb(37 99 235 / 22%); }
.approval-filter-empty { margin: 0; padding: 10px; color: #94a3b8; font-size: 12px; }
@media (max-width: 767px) {
  .approval-filter-select { min-width: 130px; flex: 1 1 130px; }
  .approval-filter-trigger, .approval-filter-option { min-height: 44px; }
}
</style>
