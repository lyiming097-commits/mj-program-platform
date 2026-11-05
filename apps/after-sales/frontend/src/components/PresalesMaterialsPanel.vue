<script setup>
import { onBeforeUnmount, ref, watch } from "vue";
import { LoaderCircle, RotateCcw } from "@lucide/vue";
import { serviceApi } from "@/serviceApi";
import AttachmentPanel from "@/components/AttachmentPanel.vue";
import MallSolutionEntry from "@/components/MallSolutionEntry.vue";

const props = defineProps({ projectId: { type: [String, Number], required: true } });
const loading = ref(false);
const error = ref("");
const attachmentError = ref("");
const archive = ref(null);
const opened = ref(new Set());
let requestSequence = 0;
async function load() {
  const sequence = ++requestSequence;
  loading.value = true;
  error.value = "";
  attachmentError.value = "";
  archive.value = null;
  opened.value = new Set();
  try {
    const response = await serviceApi.getPresalesMaterials(props.projectId);
    if (sequence === requestSequence) archive.value = response;
  } catch (reason) {
    if (sequence === requestSequence) error.value = reason?.message || "售前资料加载失败，请重试";
  } finally { if (sequence === requestSequence) loading.value = false; }
}
function toggleGroup(key, event) {
  if (event.target.open) opened.value = new Set([...opened.value, key]);
}
watch(() => props.projectId, load, { immediate: true });
onBeforeUnmount(() => { requestSequence += 1; });
</script>

<template>
  <section class="as-presales-materials" aria-label="售前资料">
    <p v-if="loading" class="as-empty" role="status"><LoaderCircle class="as-spin" />正在加载售前资料…</p>
    <div v-else-if="error" class="as-alert as-alert--error" role="alert">{{ error }}<button type="button" class="as-button as-button--secondary" @click="load"><RotateCcw />重试</button></div>
    <template v-else-if="archive?.project">
      <header class="as-panel-head"><div><h3>售前交接资料</h3><p>{{ archive.project.name }} · 共 {{ archive.attachmentCount }} 个附件 · 汇总各轮推进附件，同名文件保留最新上传版本</p></div></header>
      <MallSolutionEntry :source-crm-id="archive.project.sourceCrmId" />
      <p v-if="attachmentError" class="as-alert as-alert--error" role="alert">{{ attachmentError }}</p>
      <p v-if="!archive.groups.length" class="as-empty as-empty--compact">该售前项目暂无上传附件</p>
      <details v-for="group in archive.groups" :key="`${group.targetType}:${group.targetId}`" class="as-presales-fold" @toggle="toggleGroup(`${group.targetType}:${group.targetId}`, $event)">
        <summary>{{ group.name }}<small>{{ group.attachmentCount }} 个附件</small></summary>
        <div class="as-node-fold-body">
          <AttachmentPanel v-if="opened.has(`${group.targetType}:${group.targetId}`)" :target-type="group.targetType" :target-id="group.targetId" :categories="group.categories" :item-ids="group.itemIds ?? null" :editable="false" compact @error="attachmentError = $event" />
        </div>
      </details>
    </template>
    <p v-else class="as-empty">此售中项目未关联售前项目</p>
  </section>
</template>

<style scoped>
.as-presales-materials { display: grid; min-width: 0; gap: 12px; border: 1px solid var(--as-border); border-radius: 8px; background: var(--as-panel); padding: 14px; }
.as-panel-head { margin: 0; padding: 0; }
.as-panel-head p { overflow-wrap: anywhere; }
.as-alert { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }
.as-presales-fold > summary { overflow-wrap: anywhere; }
.as-presales-fold > summary small { margin-left: 8px; color: var(--as-muted); }
</style>
