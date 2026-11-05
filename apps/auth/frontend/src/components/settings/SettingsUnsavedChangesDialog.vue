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
  cancelTone: { type: String, default: "primary" },
  confirmText: { type: String, default: "确认放弃" },
  busyText: { type: String, default: "处理中..." },
  busy: { type: Boolean, default: false },
  confirmDisabled: Boolean,
  confirmTone: { type: String, default: "danger" },
  error: { type: String, default: "" },
});
const emit = defineEmits(["cancel", "confirm"]);

const dialogRef = ref(null);
const cancelButtonRef = ref(null);
const confirmButtonRef = ref(null);
const dialogId = useId();
const titleId = `${dialogId}-title`;
const descriptionId = `${dialogId}-description`;
let previousFocus = null;

function cancel() {
  if (!props.busy) emit("cancel");
}

function confirm() {
  if (!props.busy && !props.confirmDisabled) emit("confirm");
}

function handleKeydown(event) {
  if (!props.open) return;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopImmediatePropagation();
    cancel();
    return;
  }
  if (event.key !== "Tab") return;
  const elements = [...(dialogRef.value?.querySelectorAll('button:not([disabled]), a[href], input:not([disabled])') || [])];
  const first = elements[0];
  const last = elements.at(-1);
  if (!first) { event.preventDefault(); dialogRef.value?.focus(); return; }
  const activeElement = document.activeElement;
  const focusInside = dialogRef.value?.contains(activeElement);
  if (event.shiftKey && (activeElement === first || !focusInside)) {
    event.preventDefault();
    last?.focus?.();
  } else if (!event.shiftKey && (activeElement === last || !focusInside)) {
    event.preventDefault();
    first?.focus?.();
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
    if (focusTarget?.isConnected) focusTarget.focus?.();
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
        class="w-[360px] max-w-[calc(100vw-32px)] rounded-lg border border-slate-200 bg-white shadow-xl"
        tabindex="-1"
        role="alertdialog"
        aria-modal="true"
        :aria-busy="busy"
        :aria-labelledby="titleId"
        :aria-describedby="descriptionId"
        @click.stop
      >
        <div class="border-b border-slate-100 px-4 py-4">
          <h2 :id="titleId" class="text-base font-semibold text-slate-900">{{ title }}</h2>
          <p :id="descriptionId" class="mt-1 whitespace-pre-line text-sm leading-6 text-slate-500">{{ message }}</p>
          <slot />
          <p v-if="error" class="mt-2 text-sm text-red-700" role="alert">{{ error }}</p>
        </div>
        <div class="flex justify-end gap-2 px-4 py-3">
          <button
            ref="cancelButtonRef"
            type="button"
            class="inline-flex h-8 items-center rounded-md px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
            :class="cancelTone === 'secondary' ? 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50' : 'bg-blue-600 text-white hover:bg-blue-700'"
            :disabled="busy"
            @click="cancel"
          >
            {{ cancelText }}
          </button>
          <button
            ref="confirmButtonRef"
            type="button"
            class="inline-flex h-8 items-center rounded-md px-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            :class="confirmTone === 'primary' ? 'bg-blue-600 hover:bg-blue-700' : 'bg-red-600 hover:bg-red-700'"
            :disabled="busy || confirmDisabled"
            @click="confirm"
          >
            {{ busy ? busyText : confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
