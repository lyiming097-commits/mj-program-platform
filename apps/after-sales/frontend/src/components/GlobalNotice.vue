<script setup>
import { onBeforeUnmount, watch } from "vue";
import { Check, CircleAlert, X } from "@lucide/vue";

const error = defineModel("error", { type: String, default: "" });
const success = defineModel("success", { type: String, default: "" });
let errorTimer = 0;
let successTimer = 0;

watch(error, (message) => {
  window.clearTimeout(errorTimer);
  if (!message) return;
  errorTimer = window.setTimeout(() => {
    if (error.value === message) error.value = "";
  }, 5000);
}, { immediate: true });

watch(success, (message) => {
  window.clearTimeout(successTimer);
  if (!message) return;
  successTimer = window.setTimeout(() => {
    if (success.value === message) success.value = "";
  }, 3000);
}, { immediate: true });

onBeforeUnmount(() => {
  window.clearTimeout(errorTimer);
  window.clearTimeout(successTimer);
});
</script>

<template>
  <Teleport to="body">
    <div v-if="error || success" class="as-global-notice-layer" aria-live="polite">
      <div v-if="error" class="as-global-notice as-global-notice--error" role="alert">
        <CircleAlert />
        <span>{{ error }}</span>
        <button type="button" class="as-global-notice__close" aria-label="关闭错误提示" title="关闭" @click="error = ''"><X /></button>
      </div>
      <div v-if="success" class="as-global-notice as-global-notice--success" role="status">
        <Check />
        <span>{{ success }}</span>
        <button type="button" class="as-global-notice__close" aria-label="关闭成功提示" title="关闭" @click="success = ''"><X /></button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.as-global-notice-layer {
  position: fixed;
  z-index: 10000;
  top: max(14px, env(safe-area-inset-top));
  left: 50%;
  display: grid;
  width: min(520px, calc(100vw - 24px));
  gap: 8px;
  pointer-events: none;
  transform: translateX(-50%);
}

.as-global-notice {
  display: flex;
  min-height: 44px;
  align-items: center;
  gap: 9px;
  border: 1px solid;
  border-radius: 7px;
  padding: 10px 13px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.45;
  pointer-events: auto;
  box-shadow: 0 12px 32px rgb(15 23 42 / 18%);
}

.as-global-notice svg { width: 17px; height: 17px; flex: 0 0 auto; }
.as-global-notice > span { min-width: 0; flex: 1; }
.as-global-notice__close { display: inline-flex; width: 26px; height: 26px; flex: 0 0 auto; align-items: center; justify-content: center; border: 0; border-radius: 6px; background: transparent; color: currentColor; cursor: pointer; opacity: .72; }
.as-global-notice__close:hover { background: rgb(255 255 255 / 70%); opacity: 1; }
.as-global-notice__close svg { width: 15px; height: 15px; }
.as-global-notice--error { border-color: #efb4ba; background: #fff4f5; color: #a32635; }
.as-global-notice--success { border-color: #8ed6b8; background: #effaf5; color: #087550; }
</style>
