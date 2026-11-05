<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import { nextTick, onBeforeUnmount, ref, useId, watch } from "vue";

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: "是否放弃修改" },
  message: {
    type: String,
    default: "当前页面的修改尚未保存，离开后本次修改不会保留。",
  },
  cancelText: { type: String, default: "继续编辑" },
  confirmText: { type: String, default: "确认放弃" },
  busy: { type: Boolean, default: false },
  error: { type: String, default: "" },
  fallbackFocusSelector: { type: String, default: "" },
});
const emit = defineEmits(["cancel", "confirm"]);

const cancelButtonRef = ref(null);
const confirmButtonRef = ref(null);
const dialogRef = ref(null);
const dialogId = useId();
const titleId = `${dialogId}-title`;
const descriptionId = `${dialogId}-description`;
let previousFocus = null;

function cancel() {
  if (props.busy) return;
  emit("cancel");
}

function confirm() {
  if (props.busy) return;
  emit("confirm");
}

function handleKeydown(event) {
  if (!props.open) {
    return;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopImmediatePropagation();
    cancel();
    return;
  }
  if (event.key !== "Tab") {
    return;
  }

  const first = cancelButtonRef.value;
  const last = confirmButtonRef.value;
  const activeElement = document.activeElement;
  const focusInsideDialog = dialogRef.value?.contains(activeElement);
  if (event.shiftKey && (activeElement === first || !focusInsideDialog)) {
    event.preventDefault();
    last?.focus?.();
  } else if (!event.shiftKey && (activeElement === last || !focusInsideDialog)) {
    event.preventDefault();
    first?.focus?.();
  }
}

function fallbackFocusTarget() {
  if (!props.fallbackFocusSelector) {
    return null;
  }
  try {
    return document.querySelector(props.fallbackFocusSelector);
  } catch {
    return null;
  }
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      previousFocus = document.activeElement;
      window.addEventListener("keydown", handleKeydown, true);
      await nextTick();
      cancelButtonRef.value?.focus?.();
      return;
    }

    window.removeEventListener("keydown", handleKeydown, true);
    const focusTarget = previousFocus;
    previousFocus = null;
    await nextTick();
    const nextFocusTarget = focusTarget?.isConnected ? focusTarget : fallbackFocusTarget();
    nextFocusTarget?.focus?.();
  },
);

onBeforeUnmount(() => {
  window.removeEventListener("keydown", handleKeydown, true);
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-[220] flex items-center justify-center bg-slate-950/40 p-4"
      v-backdrop-dismiss="cancel"
    >
      <div
        ref="dialogRef"
        class="w-[360px] max-w-[calc(100vw-32px)] rounded-md border border-slate-200 bg-white shadow-xl"
        role="alertdialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        :aria-describedby="descriptionId"
      >
        <div class="border-b border-slate-100 px-4 py-4">
          <h2 :id="titleId" class="text-base font-semibold text-slate-900">{{ title }}</h2>
          <p :id="descriptionId" class="mt-1 text-sm leading-6 text-slate-500">{{ message }}</p>
          <p v-if="error" class="mt-2 text-sm text-red-600" role="alert">{{ error }}</p>
        </div>
        <div class="flex justify-end gap-2 px-4 py-3">
          <button
            ref="cancelButtonRef"
            type="button"
            class="inline-flex h-9 items-center rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60 md:h-8"
            :disabled="busy"
            @click="cancel"
          >
            {{ cancelText }}
          </button>
          <button
            ref="confirmButtonRef"
            type="button"
            class="inline-flex h-9 items-center rounded-md bg-red-600 px-3 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60 md:h-8"
            :disabled="busy"
            :aria-busy="busy"
            @click="confirm"
          >
            {{ confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
