<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { LoaderCircle } from "@lucide/vue";
import { serviceApi } from "@/serviceApi";
import AttachmentPanel from "@/components/AttachmentPanel.vue";
import ModalShell from "@/components/ModalShell.vue";

const props = defineProps({ projectId: { type: [String, Number], required: true }, editable: Boolean });
const emit = defineEmits(["busy-change"]);
const uploadBusy = ref(false);
const previewOpen = ref(false);
const removal = ref(null);
const removing = ref(false);
const error = ref("");
const revision = ref(0);
const heading = ref(null);
const busy = computed(() => uploadBusy.value || previewOpen.value || Boolean(removal.value) || removing.value);
watch(busy, value => emit("busy-change", value), { flush: "sync" });
onBeforeUnmount(() => emit("busy-change", false));

function requestRemoval(item) {
  if (!props.editable || uploadBusy.value || removing.value || !item.canDelete) return;
  error.value = "";
  removal.value = item;
}
function closeRemoval() { if (!removing.value) removal.value = null; }
async function removeDocument() {
  if (!props.editable || !removal.value || removing.value) return;
  removing.value = true;
  error.value = "";
  try {
    await serviceApi.deleteAttachment(removal.value.id);
    revision.value++;
    removal.value = null;
    await nextTick();
    heading.value?.focus();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "文档删除失败，请重试";
  } finally { removing.value = false; }
}
</script>

<template>
  <section class="as-panel" aria-label="项目需求文档">
    <header class="as-panel-head"><h3 ref="heading" tabindex="-1">项目需求文档</h3></header>
    <div class="as-requirement-documents">
      <p v-if="error && !removal" class="as-alert as-alert--error" role="alert">{{ error }}</p>
      <AttachmentPanel :key="`${projectId}:${revision}`" target-type="presales_project" :target-id="projectId" title="项目需求文档" :editable="editable && !removing" :request-remove="requestRemoval" :can-remove="item => item.canDelete" compact manage-preview-focus upload-label="上传文档" @error="error = $event" @uploaded="error = ''" @busy-change="uploadBusy = $event" @preview-change="previewOpen = $event" />
    </div>
    <ModalShell :open="Boolean(removal)" title="删除项目需求文档" :description="removal ? `确认删除“${removal.originalName}”？删除后将不再显示在项目需求文档中。` : ''" :busy="removing" manage-focus @close="closeRemoval">
      <p v-if="error" class="as-alert as-alert--error" role="alert">{{ error }}</p>
      <template #footer>
        <button type="button" class="as-button as-button--secondary" :disabled="removing" @click="closeRemoval">取消</button>
        <button type="button" class="as-button as-button--danger" :disabled="removing" @click="removeDocument"><LoaderCircle v-if="removing" class="as-spin" />{{ removing ? '正在删除' : '确认删除' }}</button>
      </template>
    </ModalShell>
  </section>
</template>

<style scoped>
.as-requirement-documents { min-width: 0; padding: var(--as-section-gap, 16px); }
</style>
