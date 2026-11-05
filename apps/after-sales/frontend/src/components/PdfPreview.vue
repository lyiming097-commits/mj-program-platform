<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { ChevronLeft, ChevronRight } from "@lucide/vue";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

GlobalWorkerOptions.workerSrc = workerUrl;

const props = defineProps({ blob: { type: Blob, required: true }, name: { type: String, default: "PDF" } });
const emit = defineEmits(["page-width"]);
const container = ref(null);
const canvas = ref(null);
const documentRef = shallowRef(null);
const loading = ref(true);
const error = ref("");
const pageNumber = ref(1);
const pageCount = ref(0);
let loadingTask = null;
let renderTask = null;
let resizeObserver = null;
let loadSequence = 0;
let renderSequence = 0;

async function renderPage() {
  const sequence = ++renderSequence;
  if (renderTask) {
    renderTask.cancel();
    try { await renderTask.promise; } catch { /* The previous render was canceled. */ }
    if (sequence !== renderSequence) return;
    renderTask = null;
  }
  if (!documentRef.value || !container.value) return;
  try {
    const page = await documentRef.value.getPage(pageNumber.value);
    await nextTick();
    if (sequence !== renderSequence || !canvas.value) return;
    const base = page.getViewport({ scale: 1 });
    const style = getComputedStyle(container.value);
    const width = Math.max(1, container.value.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight));
    const height = Math.max(1, container.value.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom));
    emit("page-width", height * base.width / base.height);
    const viewport = page.getViewport({ scale: Math.min(width / base.width, height / base.height) });
    const targetRatio = window.matchMedia("(min-width: 768px)").matches ? Math.max(2, window.devicePixelRatio || 1) : window.devicePixelRatio || 1;
    const pixelRatio = Math.max(0.1, Math.min(targetRatio, 2, 8192 / viewport.width, 8192 / viewport.height));
    const element = canvas.value;
    element.width = Math.ceil(viewport.width * pixelRatio);
    element.height = Math.ceil(viewport.height * pixelRatio);
    element.style.width = `${viewport.width}px`;
    element.style.height = `${viewport.height}px`;
    const task = page.render({
      canvasContext: element.getContext("2d"),
      viewport,
      transform: pixelRatio === 1 ? undefined : [pixelRatio, 0, 0, pixelRatio, 0, 0],
    });
    renderTask = task;
    try { await task.promise; } finally { if (renderTask === task) renderTask = null; }
    if (sequence === renderSequence) error.value = "";
  } catch (reason) {
    if (sequence === renderSequence && reason?.name !== "RenderingCancelledException") {
      error.value = "PDF 页面渲染失败，请下载原件查看";
    }
  }
}

async function loadPdf(blob) {
  const sequence = ++loadSequence;
  renderSequence += 1;
  renderTask?.cancel();
  loadingTask?.destroy();
  documentRef.value = null;
  error.value = "";
  loading.value = true;
  pageNumber.value = 1;
  pageCount.value = 0;
  try {
    loadingTask = getDocument({ data: new Uint8Array(await blob.arrayBuffer()), useSystemFonts: true });
    const pdf = await loadingTask.promise;
    if (sequence !== loadSequence) { await pdf.destroy(); return; }
    documentRef.value = pdf;
    pageCount.value = pdf.numPages;
    loading.value = false;
    await nextTick();
    await renderPage();
  } catch {
    if (sequence === loadSequence) {
      loading.value = false;
      error.value = "PDF 文件读取失败，请下载原件查看";
    }
  }
}

function changePage(delta) {
  pageNumber.value = Math.max(1, Math.min(pageCount.value, pageNumber.value + delta));
}

watch(() => props.blob, loadPdf, { immediate: true });
watch(pageNumber, () => { if (documentRef.value) renderPage(); });
onMounted(() => {
  resizeObserver = new ResizeObserver(() => { if (documentRef.value) renderPage(); });
  resizeObserver.observe(container.value);
});
onBeforeUnmount(() => {
  loadSequence += 1;
  renderSequence += 1;
  resizeObserver?.disconnect();
  renderTask?.cancel();
  loadingTask?.destroy();
});
</script>

<template>
  <div class="as-pdf-preview" :aria-label="`PDF 预览：${name}`">
    <div v-if="pageCount" class="as-pdf-preview-toolbar">
      <button type="button" title="上一页" aria-label="上一页" :disabled="pageNumber <= 1" @click="changePage(-1)"><ChevronLeft /></button>
      <span aria-live="polite">{{ pageNumber }} / {{ pageCount }}</span>
      <button type="button" title="下一页" aria-label="下一页" :disabled="pageNumber >= pageCount" @click="changePage(1)"><ChevronRight /></button>
    </div>
    <div ref="container" class="as-pdf-preview-page" :aria-busy="loading">
      <p v-if="loading" role="status">正在读取 PDF...</p>
      <p v-else-if="error" role="alert">{{ error }}</p>
      <canvas v-show="pageCount && !error" ref="canvas" role="img" :aria-label="`${name} 第 ${pageNumber} 页`" />
    </div>
  </div>
</template>

<style scoped>
.as-pdf-preview { display: flex; width: 100%; height: 100%; min-height: 0; flex-direction: column; }
.as-pdf-preview-toolbar { display: flex; min-height: 46px; flex: 0 0 auto; align-items: center; justify-content: center; gap: 7px; border-bottom: 1px solid #e2e8f0; background: #fff; color: #334155; }
.as-pdf-preview-toolbar span { min-width: 44px; font-size: 12px; text-align: center; font-variant-numeric: tabular-nums; }
.as-pdf-preview-toolbar button { display: grid; width: 36px; height: 36px; place-items: center; border: 0; border-radius: 6px; background: transparent; color: #334155; cursor: pointer; }
.as-pdf-preview-toolbar button:hover:not(:disabled) { background: #eff6ff; }
.as-pdf-preview-toolbar button:disabled { color: #94a3b8; cursor: default; }
.as-pdf-preview-toolbar button svg { width: 18px; height: 18px; }
.as-pdf-preview-page { display: grid; min-width: 0; min-height: 0; flex: 1; place-items: center; overflow: hidden; padding: 16px; text-align: center; }
.as-pdf-preview-page canvas { display: block; max-width: 100%; max-height: 100%; background: #fff; box-shadow: 0 2px 12px rgb(0 0 0 / 28%); }
.as-pdf-preview-page p { margin: 16px; color: #cbd5e1; font-size: 13px; }
@media (max-width: 640px) { .as-pdf-preview-page { padding: 8px; } }
</style>
