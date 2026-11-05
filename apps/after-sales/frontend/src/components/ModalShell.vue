<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import { X } from "@lucide/vue";
import { nextTick, onBeforeUnmount, ref, watch } from "vue";

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: "" },
  description: { type: String, default: "" },
  wide: { type: Boolean, default: false },
  manageFocus: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  suspended: { type: Boolean, default: false },
});

const emit = defineEmits(["close"]);
const panel = ref(null);
let previousFocus = null;
function close() { if (!props.busy && !props.suspended) emit("close"); }
function handleKeydown(event) {
  if (!props.open || !props.manageFocus || props.suspended) return;
  if (event.key === "Escape") {
    event.preventDefault(); event.stopImmediatePropagation(); close(); return;
  }
  if (event.key !== "Tab") return;
  const controls = [...(panel.value?.querySelectorAll('button:not([disabled]), textarea:not([disabled]), input:not([disabled]), [tabindex="0"]') || [])]
    .filter(element => element.getClientRects().length);
  const first = controls[0], last = controls.at(-1), active = document.activeElement;
  if (!first) { event.preventDefault(); panel.value?.focus(); }
  else if (event.shiftKey && (active === first || !panel.value.contains(active))) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (active === last || !panel.value.contains(active))) { event.preventDefault(); first.focus(); }
}
watch(() => props.open && props.manageFocus, async open => {
  if (open) {
    previousFocus = document.activeElement;
    window.addEventListener("keydown", handleKeydown, true);
    await nextTick();
    (panel.value?.querySelector("textarea") || panel.value?.querySelector("button"))?.focus();
  } else {
    window.removeEventListener("keydown", handleKeydown, true);
    const target = previousFocus;
    previousFocus = null;
    await nextTick();
    if (target?.isConnected) target.focus();
  }
}, { immediate: true });
onBeforeUnmount(() => window.removeEventListener("keydown", handleKeydown, true));
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="as-modal-mask" role="presentation" v-backdrop-dismiss="close" :inert="suspended ? true : undefined" :aria-hidden="suspended ? 'true' : undefined">
      <section ref="panel" class="as-modal" :class="{ 'as-modal--wide': wide }" role="dialog" aria-modal="true" :aria-label="title" :aria-busy="busy" tabindex="-1">
        <header class="as-modal__head">
          <div class="as-min-width-0">
            <h2>{{ title }}</h2>
            <p v-if="description">{{ description }}</p>
          </div>
          <button type="button" class="as-icon-button" title="关闭" aria-label="关闭" :disabled="busy" @click="close">
            <X />
          </button>
        </header>
        <div class="as-modal__body"><slot /></div>
        <footer v-if="$slots.footer" class="as-modal__foot"><slot name="footer" /></footer>
      </section>
    </div>
  </Teleport>
</template>
