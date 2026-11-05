<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import { Download, Eye, FileText, Image, Upload, X } from "@lucide/vue";
import ImagePreviewDialog from "@/components/ImagePreviewDialog.vue";
import { isPdfAttachment } from "@/privateAttachment";

const props = defineProps({
  files: { type: Array, default: () => [] },
  multiple: { type: Boolean, default: true },
  buttonLabel: { type: String, default: "选择文件" },
  disabled: { type: Boolean, default: false },
  previewEnabled: { type: Boolean, default: false },
});

const emit = defineEmits(["change", "remove", "preview-change"]);
const inputRef = ref(null);
const previews = ref([]);
const previewFile = shallowRef(null);
const previewUrl = ref("");
const previewIsPdf = computed(() => isPdf(previewFile.value));

function isImage(file) {
  return String(file?.type || "").startsWith("image/")
    || /\.(png|jpe?g|gif|webp|bmp)$/i.test(String(file?.name || ""));
}

function isPdf(file) {
  return isPdfAttachment({ originalName: file?.name, mimeType: file?.type });
}

function isPreviewable(file) {
  return props.previewEnabled && (isImage(file) || isPdf(file));
}

function closePreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  previewUrl.value = "";
  if (!previewFile.value) return;
  previewFile.value = null;
  emit("preview-change", false);
}

function openPreview(file) {
  if (props.disabled || !isPreviewable(file)) return;
  closePreview();
  // A File is already a Blob: PDFs can use the same renderer before upload.
  // Image previews own their URL independently from the list thumbnails.
  previewFile.value = file;
  previewUrl.value = isPdf(file) ? "" : URL.createObjectURL(file);
  emit("preview-change", true);
}

function revokePreviews() {
  previews.value.forEach((item) => {
    if (item.url) URL.revokeObjectURL(item.url);
  });
}

watch(
  () => props.files,
  (files) => {
    if (previewFile.value && !(files || []).includes(previewFile.value)) closePreview();
    revokePreviews();
    previews.value = (files || []).map((file) => ({
      file,
      image: isImage(file),
      url: isImage(file) ? URL.createObjectURL(file) : "",
    }));
  },
  { immediate: true, deep: true },
);

function chooseFiles() {
  if (props.disabled) return;
  inputRef.value?.click();
}

function handleFiles(event) {
  if (props.disabled) return;
  emit("change", Array.from(event.target.files || []));
  event.target.value = "";
}

function formatSize(size) {
  const bytes = Number(size) || 0;
  if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
  if (bytes >= 1024) return Math.ceil(bytes / 1024) + " KB";
  return bytes + " B";
}

function downloadFile(file) {
  const objectUrl = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = file.name || "attachment";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

onBeforeUnmount(() => {
  closePreview();
  revokePreviews();
});
</script>

<template>
  <section class="as-file-picker">
    <input ref="inputRef" class="as-file-picker__input" type="file" :aria-label="buttonLabel" :multiple="multiple" :disabled="disabled" @change="handleFiles">
    <div class="as-file-picker__control"><button type="button" class="as-button as-button--secondary as-file-picker__button" :disabled="disabled" @click="chooseFiles"><Upload />{{ buttonLabel }}</button><span>{{ files.length ? `已选择 ${files.length} 个附件` : '暂无附件' }}</span></div>
    <div v-if="previews.length" class="as-file-picker__list">
      <article v-for="(item, index) in previews" :key="item.file.name + '-' + item.file.lastModified + '-' + index" class="as-file-picker__item">
        <button v-if="isPreviewable(item.file)" type="button" class="as-file-picker__file-icon as-file-picker__preview" :title="`预览${item.file.name}`" :aria-label="`预览缩略图：${item.file.name}`" :disabled="disabled" @click="openPreview(item.file)"><img v-if="item.image" :src="item.url" :alt="item.file.name"><FileText v-else /></button>
        <img v-else-if="item.image" :src="item.url" :alt="item.file.name">
        <span v-else class="as-file-picker__file-icon"><FileText /></span>
        <span class="as-file-picker__meta"><strong><Image v-if="item.image" /><button v-if="isPreviewable(item.file)" type="button" class="as-file-picker__name" :title="item.file.name" :aria-label="`预览文件：${item.file.name}`" :disabled="disabled" @click="openPreview(item.file)">{{ item.file.name }}</button><template v-else>{{ item.file.name }}</template></strong><small>{{ formatSize(item.file.size) }}</small></span>
        <span class="as-file-picker__actions"><button v-if="isPreviewable(item.file)" type="button" title="预览文件" :aria-label="`预览：${item.file.name}`" :disabled="disabled" @click="openPreview(item.file)"><Eye /></button><button type="button" title="下载文件" :aria-label="'下载 ' + item.file.name" :disabled="disabled" @click="downloadFile(item.file)"><Download /></button><button type="button" class="as-file-picker__remove" title="移除文件" :aria-label="'移除 ' + item.file.name" :disabled="disabled" @click="emit('remove', index)"><X /></button></span>
      </article>
    </div>
    <ImagePreviewDialog :open="Boolean(previewFile)" :src="previewUrl" :blob="previewIsPdf ? previewFile : null" :title="previewFile?.name || '附件预览'" :kind="previewIsPdf ? 'pdf' : 'image'" manage-focus @close="closePreview" @download="previewFile && downloadFile(previewFile)" />
  </section>
</template>

<style scoped>
.as-file-picker__preview { padding: 0; cursor: pointer; }
.as-file-picker__preview img { width: 100%; height: 100%; object-fit: cover; }
.as-file-picker__name { min-width: 0; overflow: hidden; border: 0; background: transparent; padding: 0; color: inherit; font: inherit; text-align: left; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.as-file-picker__preview:hover:enabled, .as-file-picker__name:hover:enabled { color: var(--as-primary); }
</style>
