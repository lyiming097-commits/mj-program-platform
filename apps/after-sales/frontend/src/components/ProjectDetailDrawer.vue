<script setup>
import { shallowRef, watch } from "vue";
import { X } from "@lucide/vue";
import { ElDrawer } from "element-plus/es/components/drawer/index.mjs";
import "element-plus/es/components/drawer/style/css";

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: "项目详情" },
  eyebrow: { type: String, default: "项目服务工作台" },
  size: { type: String, default: "84%" },
  level: { type: Number, default: 1 },
  closeGuard: { type: Function, default: null },
});

const emit = defineEmits(["close", "closed"]);
const drawerOpen = shallowRef(false);

watch(
  () => props.open,
  (open) => {
    drawerOpen.value = open;
  },
  { immediate: true },
);

async function requestClose(done) {
  if (props.closeGuard && !(await props.closeGuard())) return;
  emit("close");
  if (typeof done === "function") done();
}

function handleCloseClick() {
  void requestClose();
}
</script>

<template>
  <ElDrawer
    v-model="drawerOpen"
    :title="title"
    direction="rtl"
    :size="size"
    resizable
    :z-index="level > 2 ? 2500 : level > 1 ? 2300 : 2100"
    append-to-body
    destroy-on-close
    class="module-route-drawer"
    :class="{
      'is-nested-drawer': level > 1,
      'is-third-level-drawer': level > 2,
    }"
    modal-class="module-route-drawer-mask"
    :show-close="false"
    :lock-scroll="true"
    :close-on-click-modal="true"
    :close-on-press-escape="false"
    :before-close="requestClose"
    @closed="emit('closed')"
  >
    <template #header>
      <slot name="header" :close="handleCloseClick">
        <div class="drawer-heading">
          <div class="drawer-title">
            <span class="drawer-mark" aria-hidden="true"></span>
            <div class="drawer-title-copy">
              <small>{{ eyebrow }}</small>
              <strong>{{ title }}</strong>
            </div>
          </div>
          <button type="button" class="drawer-close" aria-label="关闭" title="关闭" @click="handleCloseClick">
            <X :size="18" />
          </button>
        </div>
      </slot>
    </template>
    <div class="drawer-body">
      <slot />
    </div>
    <template v-if="$slots.footer" #footer>
      <slot name="footer" />
    </template>
  </ElDrawer>
</template>

<style scoped>
.drawer-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.drawer-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
  color: #0f172a;
}

.drawer-title-copy { min-width: 0; }
.drawer-title-copy small, .drawer-title-copy strong { display: block; }
.drawer-title-copy small { color: #7b8da3; font-size: 10px; font-weight: 700; line-height: 14px; }
.drawer-title-copy strong {
  overflow: hidden;
  margin-top: 1px;
  color: #142033;
  font-size: 16px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-mark {
  width: 4px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 3px;
  background: #2563eb;
}

.drawer-close {
  display: inline-flex;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  background: #fff;
  color: #64748b;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease, transform 0.18s ease;
}

.drawer-close:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
  color: #0f172a;
}

.drawer-close:active {
  transform: translateY(1px);
}

.drawer-close:focus-visible {
  outline: 2px solid #93c5fd;
  outline-offset: 2px;
}

.drawer-body {
  min-height: 100%;
  padding: 14px 16px 18px;
  background: #f4f7fb;
}

:global(.module-route-drawer.el-drawer) {
  isolation: isolate;
  overflow: visible;
  min-width: min(520px, 100vw);
  max-width: 96vw;
  background: #f4f7fb;
  box-shadow: -18px 0 48px rgba(15, 23, 42, 0.18);
}

:global(.module-route-drawer.is-nested-drawer.el-drawer) {
  max-width: 92vw;
  box-shadow: -24px 0 58px rgba(15, 23, 42, 0.24);
}

:global(.module-route-drawer.is-third-level-drawer.el-drawer) {
  max-width: 88vw;
  box-shadow: -28px 0 64px rgba(15, 23, 42, 0.28);
}

:global(.module-route-drawer > .el-drawer__dragger) {
  z-index: 4 !important;
}

:global(.module-route-drawer > .el-drawer__dragger::before) {
  width: 4px;
  background: rgba(37, 99, 235, 0.12);
}

:global(.module-route-drawer > .el-drawer__dragger:hover::before) {
  background: #2563eb;
}

:global(.module-route-drawer .el-drawer__header) {
  position: relative;
  z-index: 2;
  min-height: 54px;
  margin: 0;
  padding: 10px 14px;
  border-bottom: 1px solid #e2e8f0;
  background: #fff;
}

:global(.module-route-drawer .el-drawer__body) {
  position: relative;
  z-index: 2;
  overflow: auto;
  padding: 0;
}

:global(.module-route-drawer .el-drawer__footer) {
  position: relative;
  z-index: 3;
  border-top: 1px solid #dbe3ec;
  background: #fff;
  padding: 0;
}

:global(.module-route-drawer-mask) {
  background: rgba(15, 23, 42, 0.3);
  backdrop-filter: blur(1px);
}

@media (max-width: 767px) {
  :global(.module-route-drawer.el-drawer) {
    width: 100% !important;
    min-width: 100%;
    max-width: none;
  }

  :global(.module-route-drawer > .el-drawer__dragger) {
    display: none;
  }

  .drawer-body { padding: 10px; }
}
</style>
