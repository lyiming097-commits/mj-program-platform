<script setup>
import { Clock3, Paperclip } from "@lucide/vue";

defineProps({
  title: { type: String, required: true },
  count: { type: Number, default: 0 },
  sourceLabel: { type: String, default: "小程序上传" },
  syncedAt: { type: String, default: "" },
  status: { type: String, default: "" },
  tone: { type: String, default: "mobile" },
});
</script>

<template>
  <section class="material-group">
    <header class="material-group-head">
      <div class="material-group-title"><span><Paperclip /></span><div><h3>{{ title }}</h3><p>{{ count }} 个文件<template v-if="syncedAt"> · 最近同步 {{ syncedAt }}</template></p></div></div>
      <div class="material-group-meta"><em :class="`is-${tone}`">{{ sourceLabel }}</em><strong v-if="status"><Clock3 />{{ status }}</strong></div>
    </header>
    <div class="material-group-body"><slot /></div>
  </section>
</template>

<style scoped>
.material-group { overflow: hidden; border: 1px solid #dce5ef; border-radius: 8px; background: #fff; }
.material-group-head { display: flex; min-height: 58px; align-items: center; justify-content: space-between; gap: 14px; border-bottom: 1px solid #e6edf4; background: #fbfdff; padding: 10px 13px; }
.material-group-title { display: flex; min-width: 0; align-items: center; gap: 10px; }
.material-group-title > span { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; border-radius: 7px; background: #edf4ff; color: #315f9f; }
.material-group-title svg { width: 16px; height: 16px; }
.material-group-title h3 { margin: 0; color: #223047; font-size: 13px; }
.material-group-title p { margin: 3px 0 0; color: #7b8798; font-size: 9px; }
.material-group-meta { display: flex; flex: 0 0 auto; align-items: center; gap: 7px; }
.material-group-meta em, .material-group-meta strong { display: inline-flex; min-height: 24px; align-items: center; gap: 4px; border-radius: 5px; padding: 3px 7px; font-size: 9px; font-style: normal; font-weight: 750; }
.material-group-meta em { background: #eaf8f2; color: #087550; }
.material-group-meta em.is-admin { background: #edf4ff; color: #315f9f; }
.material-group-meta em.is-pending { background: #fff6df; color: #8a5d00; }
.material-group-meta strong { background: #f1f5f9; color: #64748b; }
.material-group-meta svg { width: 12px; height: 12px; }
.material-group-body { min-width: 0; }
.material-group-body :deep(.as-attachment-panel) { border: 0; border-radius: 0; margin: 0; }
.material-group-body :deep(.as-empty) { margin: 0; }
@media (max-width: 700px) { .material-group-head { align-items: flex-start; flex-direction: column; } .material-group-meta { flex-wrap: wrap; } }
</style>
