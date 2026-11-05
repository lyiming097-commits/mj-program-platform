<script setup>
import { onBeforeUnmount, ref } from "vue";

defineProps({ label: { type: String, required: true } });
const scroll = ref(null);
let drag = null;
let dragged = false;

function startDrag(event) {
  dragged = false;
  if (event.button !== 0 || event.target.closest('button, a, input, textarea, select, [contenteditable="true"]')) return;
  drag = { x: event.clientX, left: scroll.value.scrollLeft };
  window.addEventListener("mousemove", moveDrag);
  window.addEventListener("mouseup", stopDrag);
}
function moveDrag(event) {
  if (!drag) return;
  if (Math.abs(event.clientX - drag.x) > 5) dragged = true;
  if (dragged) {
    event.preventDefault();
    scroll.value.scrollLeft = drag.left + drag.x - event.clientX;
  }
}
function stopDrag() {
  drag = null;
  window.removeEventListener("mousemove", moveDrag);
  window.removeEventListener("mouseup", stopDrag);
}
function captureClick(event) {
  if (dragged) { event.preventDefault(); event.stopPropagation(); dragged = false; }
}
function scrollKeys(event) {
  if (event.target !== scroll.value || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  scroll.value.scrollLeft += event.key === "ArrowLeft" ? -120 : 120;
}
onBeforeUnmount(stopDrag);
</script>

<template>
  <div ref="scroll" class="registry-table-scroll min-h-0 min-w-0 flex-1 overflow-auto" role="region" tabindex="0" :aria-label="label"
    @mousedown="startDrag" @click.capture="captureClick" @keydown="scrollKeys">
    <slot />
  </div>
</template>
