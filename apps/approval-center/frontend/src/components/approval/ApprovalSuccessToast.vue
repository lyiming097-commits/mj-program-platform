<script setup>
import { onBeforeUnmount, watch } from "vue";
import { CheckCircle2, X } from "@lucide/vue";

const props = defineProps({
  notice: { type: Object, default: null },
});
const emit = defineEmits(["dismiss"]);
const durationMs = 3000;
let timer = null;

watch(() => props.notice, (notice) => {
  window.clearTimeout(timer);
  if (!notice) return;
  timer = window.setTimeout(() => emit("dismiss", notice.id), durationMs);
});

onBeforeUnmount(() => window.clearTimeout(timer));
</script>

<template>
  <Teleport to="body">
    <div class="approval-feedback-toast" aria-live="polite">
      <Transition name="approval-feedback" mode="out-in">
        <div v-if="notice" :key="notice.id" class="approval-feedback-toast-panel" role="status">
          <CheckCircle2 aria-hidden="true" />
          <span class="approval-feedback-toast-message">{{ notice.message }}</span>
          <button type="button" aria-label="关闭提示" title="关闭提示" @click="emit('dismiss', notice.id)">
            <X aria-hidden="true" />
          </button>
          <span class="approval-feedback-toast-progress" aria-hidden="true" />
        </div>
      </Transition>
    </div>
  </Teleport>
</template>
