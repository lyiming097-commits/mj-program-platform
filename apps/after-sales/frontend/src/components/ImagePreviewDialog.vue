<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import { computed, defineAsyncComponent, h, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { ChevronLeft, ChevronRight, Download, X } from "@lucide/vue";

const PdfPreview = defineAsyncComponent({
  loader: () => import("@/components/PdfPreview.vue"),
  loadingComponent: { render: () => h("p", { role: "status" }, "正在打开 PDF 预览...") },
  delay: 0,
});

const props = defineProps({
  open: { type: Boolean, default: false },
  src: { type: String, default: "" },
  blob: { type: Blob, default: null },
  kind: { type: String, default: "image" },
  title: { type: String, default: "图片预览" },
  images: { type: Array, default: () => [] },
  initialIndex: { type: Number, default: 0 },
  manageFocus: { type: Boolean, default: false },
});

const emit = defineEmits(["close", "download"]);
const pdfPageWidth = ref(0);
const dialogRef = ref(null);
const thumbnailStrip = ref(null);
const selectedIndex = ref(0);
const failedSources = ref([]);
const gallery = computed(() => props.kind === "image" && props.images.length > 0);
const manageFocus = computed(() => props.manageFocus || gallery.value);
const currentImage = computed(() => props.images[selectedIndex.value]);
const currentSource = computed(() => {
  if (!gallery.value) return props.src;
  const image = currentImage.value;
  if (!image) return props.src;
  if (image.preview && !failedSources.value.includes(image.preview)) return image.preview;
  return failedSources.value.includes(image.thumbnail) ? "" : image.thumbnail || "";
});
const dialogTitle = computed(() => gallery.value ? `${props.title}图片预览` : props.title);
let previousFocus = null;
let captureKeydown = false;

function selectImage(index) {
  if (!gallery.value) return;
  selectedIndex.value = (index + props.images.length) % props.images.length;
  nextTick(() => {
    const active = thumbnailStrip.value?.querySelector('[aria-current="true"]');
    active?.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
}

function markFailed(url) {
  if (url && !failedSources.value.includes(url)) failedSources.value = [...failedSources.value, url];
}

function close() {
  emit("close");
}

function handleKeydown(event) {
  if (!props.open) return;
  if (event.key === "Escape") {
    if (manageFocus.value) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
    close();
  } else if (gallery.value && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
    event.preventDefault();
    selectImage(selectedIndex.value + (event.key === "ArrowRight" ? 1 : -1));
  } else if (manageFocus.value && event.key === "Tab") {
    const focusable = [...(dialogRef.value?.querySelectorAll("button:not(:disabled)") || [])];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || !dialogRef.value.contains(document.activeElement) || document.activeElement === dialogRef.value)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !dialogRef.value.contains(document.activeElement))) {
      event.preventDefault();
      first.focus();
    }
  }
}

watch(() => props.open, (open) => {
  if (open) {
    selectedIndex.value = Math.min(Math.max(props.initialIndex, 0), Math.max(props.images.length - 1, 0));
    failedSources.value = [];
    previousFocus = document.activeElement;
    captureKeydown = manageFocus.value;
    window.addEventListener("keydown", handleKeydown, captureKeydown);
    if (manageFocus.value) nextTick(() => dialogRef.value?.focus({ preventScroll: true }));
  } else {
    pdfPageWidth.value = 0;
    window.removeEventListener("keydown", handleKeydown, captureKeydown);
    const returnFocus = previousFocus;
    if (manageFocus.value && returnFocus?.isConnected) nextTick(() => {
      if (!returnFocus.closest("[inert]")) returnFocus.focus({ preventScroll: true });
    });
    previousFocus = null;
  }
}, { immediate: true });

onBeforeUnmount(() => window.removeEventListener("keydown", handleKeydown, captureKeydown));
</script>

<template>
  <Teleport to="body">
    <Transition name="as-image-preview">
      <div v-if="open && (kind === 'pdf' ? blob : src || currentSource)" class="as-image-preview-mask" role="presentation" v-backdrop-dismiss="close">
        <section ref="dialogRef" class="as-image-preview-dialog" :class="{ 'as-image-preview-dialog--pdf': kind === 'pdf', 'as-image-preview-dialog--gallery': gallery }" :style="kind === 'pdf' && pdfPageWidth ? { '--pdf-page-width': `${pdfPageWidth}px` } : null" role="dialog" aria-modal="true" :aria-label="dialogTitle" tabindex="-1" @click.stop>
          <header class="as-image-preview-head">
            <div><small>{{ gallery ? '产品图片' : kind === 'pdf' ? 'PDF 预览' : '图片预览' }}</small><strong :title="title">{{ title }}</strong></div>
            <span class="as-image-preview-actions">
              <button v-if="kind === 'pdf'" type="button" title="下载原件" aria-label="下载原件" @click="emit('download')"><Download /></button>
              <button type="button" :title="kind === 'pdf' ? '关闭预览' : '关闭大图'" :aria-label="kind === 'pdf' ? '关闭预览' : '关闭大图'" @click="close"><X /></button>
            </span>
          </header>
          <div class="as-image-preview-stage" :class="{ 'as-image-preview-stage--pdf': kind === 'pdf', 'as-image-preview-stage--gallery': gallery }">
            <PdfPreview v-if="kind === 'pdf'" :blob="blob" :name="title" @page-width="pdfPageWidth = $event" />
            <template v-else-if="gallery">
              <button v-if="images.length > 1" type="button" class="as-image-preview-arrow as-image-preview-arrow--left" aria-label="上一张图片" title="上一张图片" @click="selectImage(selectedIndex - 1)"><ChevronLeft aria-hidden="true" /></button>
              <img v-if="currentSource" :src="currentSource" :alt="`${title}第${selectedIndex + 1}张图片`" @error="markFailed($event.target.getAttribute('src'))">
              <p v-else role="status">该图片暂时无法加载</p>
              <button v-if="images.length > 1" type="button" class="as-image-preview-arrow as-image-preview-arrow--right" aria-label="下一张图片" title="下一张图片" @click="selectImage(selectedIndex + 1)"><ChevronRight aria-hidden="true" /></button>
              <span v-if="images.length > 1" class="as-image-preview-count" aria-live="polite">{{ selectedIndex + 1 }} / {{ images.length }}</span>
            </template>
            <img v-else :src="src" :alt="title">
          </div>
          <div v-if="gallery && images.length > 1" ref="thumbnailStrip" class="as-image-preview-strip" role="group" aria-label="产品图片缩略图">
            <button v-for="(image, index) in images" :key="image.key || index" type="button" class="as-image-preview-thumb" :aria-label="`查看第${index + 1}张图片`" :aria-current="selectedIndex === index ? 'true' : undefined" :class="{ 'is-selected': selectedIndex === index }" @click="selectImage(index)">
              <img v-if="image.thumbnail || image.preview" :src="image.thumbnail || image.preview" :alt="`${title}缩略图${index + 1}`" loading="lazy">
              <span>{{ index + 1 }}</span>
            </button>
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.as-image-preview-mask {
  position: fixed;
  inset: 0;
  z-index: 5200;
  display: grid;
  place-items: center;
  background: rgb(15 23 42 / 72%);
  padding: 20px;
  backdrop-filter: blur(3px);
}

.as-image-preview-dialog {
  display: flex;
  width: max-content;
  min-width: min(320px, calc(100vw - 40px));
  max-width: min(1180px, calc(100vw - 40px));
  max-height: min(860px, calc(100dvh - 40px));
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgb(255 255 255 / 22%);
  border-radius: 8px;
  background: #111827;
  box-shadow: 0 28px 72px rgb(8 15 28 / 42%);
}
.as-image-preview-dialog--pdf { width: min(1180px, calc(100vw - 40px), max(320px, calc(var(--pdf-page-width, 840px) + 32px))); height: min(860px, calc(100dvh - 40px)); }
.as-image-preview-dialog--gallery { width: min(1280px, calc(100vw - 40px)); height: min(860px, calc(100dvh - 40px)); background: #fff; }

.as-image-preview-head {
  display: flex;
  min-height: 58px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid rgb(255 255 255 / 12%);
  background: #fff;
  padding: 10px 12px 10px 16px;
}

.as-image-preview-head > div { width: 0; min-width: 0; flex: 1 1 0; }
.as-image-preview-head small, .as-image-preview-head strong { display: block; }
.as-image-preview-head small { color: #667085; font-size: 10px; font-weight: 700; }
.as-image-preview-head strong { overflow: hidden; margin-top: 2px; color: #172033; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.as-image-preview-dialog--gallery .as-image-preview-head { min-height: 64px; }
.as-image-preview-dialog--gallery .as-image-preview-head small { color: #0f172a; font-size: 16px; }
.as-image-preview-dialog--gallery .as-image-preview-head strong { color: #64748b; font-size: 12px; font-weight: 500; }
.as-image-preview-actions { display: flex; flex: 0 0 auto; gap: 6px; }
.as-image-preview-actions button { display: grid; width: 36px; height: 36px; flex: 0 0 auto; place-items: center; border: 1px solid #d5dbe4; border-radius: 6px; background: #fff; color: #526174; cursor: pointer; }
.as-image-preview-actions button:hover { border-color: #9cabc0; background: #f5f7fa; color: #172033; }
.as-image-preview-actions button:focus-visible { outline: 2px solid #7aa7ef; outline-offset: 2px; }
.as-image-preview-actions button svg { width: 18px; height: 18px; }

.as-image-preview-stage { display: grid; min-width: 0; min-height: 0; place-items: center; overflow: hidden; padding: 18px; }
.as-image-preview-stage--pdf { flex: 1 1 auto; padding: 0; }
.as-image-preview-stage--gallery { position: relative; width: 100%; flex: 1 1 auto; background: #e2e8f0; padding: 20px 56px; color: #475569; }
.as-image-preview-stage--gallery img { width: 100%; height: 100%; max-width: 100%; max-height: 100%; object-fit: contain; }
.as-image-preview-arrow { position: absolute; z-index: 1; top: 50%; display: grid; width: 42px; height: 56px; place-items: center; transform: translateY(-50%); border: 0; border-radius: 6px; background: rgb(15 23 42 / 42%); color: #fff; cursor: pointer; }
.as-image-preview-arrow:hover { background: rgb(15 23 42 / 70%); }
.as-image-preview-arrow--left { left: 12px; }
.as-image-preview-arrow--right { right: 12px; }
.as-image-preview-arrow svg { width: 23px; height: 23px; }
.as-image-preview-count { position: absolute; bottom: 16px; left: 50%; transform: translateX(-50%); border-radius: 6px; background: rgb(15 23 42 / 75%); padding: 7px 12px; color: #fff; font-size: 12px; font-weight: 750; font-variant-numeric: tabular-nums; }
.as-image-preview-strip { display: flex; min-height: 90px; flex: 0 0 auto; align-items: center; gap: 10px; overflow-x: auto; border-top: 1px solid #cbd5e1; background: #f1f5f9; padding: 10px 18px; scrollbar-width: thin; }
.as-image-preview-thumb { position: relative; display: grid; width: 92px; height: 68px; flex: 0 0 92px; place-items: center; overflow: hidden; border: 2px solid transparent; border-radius: 6px; background: #dbe2eb; padding: 0; cursor: pointer; }
.as-image-preview-thumb:hover { border-color: #94a3b8; }
.as-image-preview-thumb.is-selected { border-color: #2563eb; }
.as-image-preview-thumb img { width: 100%; height: 100%; object-fit: contain; }
.as-image-preview-thumb span { position: absolute; right: 3px; bottom: 3px; min-width: 18px; border-radius: 3px; background: rgb(15 23 42 / 76%); padding: 2px 4px; color: #fff; font-size: 11px; font-variant-numeric: tabular-nums; }
.as-image-preview-dialog--gallery button:focus-visible { outline: 2px solid #2563eb; outline-offset: -2px; }
.as-image-preview-stage img {
  display: block;
  width: auto;
  height: auto;
  max-width: min(1142px, calc(100vw - 78px));
  max-height: min(744px, calc(100dvh - 160px));
  object-fit: contain;
}

.as-image-preview-enter-active, .as-image-preview-leave-active { transition: opacity 180ms ease; }
.as-image-preview-enter-active .as-image-preview-dialog, .as-image-preview-leave-active .as-image-preview-dialog { transition: transform 180ms ease; }
.as-image-preview-enter-from, .as-image-preview-leave-to { opacity: 0; }
.as-image-preview-enter-from .as-image-preview-dialog, .as-image-preview-leave-to .as-image-preview-dialog { transform: scale(.985); }

@media (max-width: 640px) {
  .as-image-preview-mask { padding: 8px; }
  .as-image-preview-dialog { width: calc(100vw - 16px); min-width: 0; max-width: none; height: calc(100dvh - 16px); max-height: none; }
  .as-image-preview-dialog--pdf { width: calc(100vw - 16px); }
  .as-image-preview-dialog--gallery { width: calc(100vw - 16px); }
  .as-image-preview-stage { flex: 1 1 auto; padding: 8px; }
  .as-image-preview-stage--pdf { padding: 0; }
  .as-image-preview-stage--gallery { padding: 8px 40px; }
  .as-image-preview-strip { min-height: 74px; gap: 6px; padding: 7px; }
  .as-image-preview-thumb { width: 74px; height: 54px; flex-basis: 74px; }
  .as-image-preview-arrow { width: 34px; height: 48px; }
  .as-image-preview-arrow--left { left: 3px; }
  .as-image-preview-arrow--right { right: 3px; }
  .as-image-preview-stage img { width: auto; height: auto; max-width: 100%; max-height: calc(100dvh - 92px); }
  .as-image-preview-stage--gallery img { width: 100%; height: 100%; max-height: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  .as-image-preview-enter-active, .as-image-preview-leave-active,
  .as-image-preview-enter-active .as-image-preview-dialog, .as-image-preview-leave-active .as-image-preview-dialog { transition: none; }
}
</style>
