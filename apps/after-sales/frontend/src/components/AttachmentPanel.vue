<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import { Download, Eye, FileArchive, FileSpreadsheet, FileText, FileVideo, LoaderCircle, Trash2, Upload } from "@lucide/vue";
import { apiFetchRaw } from "@/api";
import { collectionRows, normalizeDatabaseId, serviceApi } from "@/serviceApi";
import ImagePreviewDialog from "@/components/ImagePreviewDialog.vue";
import { MAX_ATTACHMENT_MB, MAX_ATTACHMENT_SIZE } from "@/attachmentLimits";
import { downloadPrivateAttachment, fetchPrivateAttachment, isPdfAttachment } from "@/privateAttachment";

const props = defineProps({
  targetType: { type: String, required: true },
  targetId: { type: [String, Number], default: "" },
  title: { type: String, default: "附件资料" },
  categories: { type: Array, default: () => [{ value: "general", label: "附件" }] },
  editable: { type: Boolean, default: true },
  compact: { type: Boolean, default: false },
  managePreviewFocus: { type: Boolean, default: false },
  uploadLabel: { type: String, default: "上传" },
  itemIds: { type: Array, default: null },
  roundIndex: { type: Number, default: null },
  roundId: { type: String, default: "" },
  requestRemove: { type: Function, default: null },
  canRemove: { type: Function, default: null },
  removeLabel: { type: String, default: "删除" },
  source: { type: String, default: "" },
  sourceLabel: { type: String, default: "" },
  uploaderLabel: { type: String, default: "" },
  uploaderLabels: { type: Object, default: () => ({}) },
});

const emit = defineEmits(["changed", "uploaded", "removed", "error", "preview-change", "busy-change"]);
const loading = ref(false);
const busyKey = ref("");
const busyFileId = ref("");
const items = ref([]);
const previewFile = ref(null);
const previewUrl = ref("");
const previewPdfBlob = shallowRef(null);
const imageUrls = ref({});
let imageLoadSequence = 0;
let previewRequestSequence = 0;
const validTargetId = computed(() => normalizeDatabaseId(props.targetId));
watch(() => Boolean(previewFile.value), open => emit("preview-change", open), { flush: "sync" });
watch(() => Boolean(busyKey.value), busy => emit("busy-change", busy), { flush: "sync" });

const groups = computed(() => props.categories.map((item) => (
  Array.isArray(item)
    ? { value: item[0], label: item[1], required: Boolean(item[2]), editable: true }
    : { value: item.value || "general", label: item.label || "附件", required: Boolean(item.required), editable: item.editable !== false }
)));
const visibleItemIds = computed(() => (
  Array.isArray(props.itemIds)
    ? new Set(props.itemIds.map((item) => String(item)))
    : null
));

function filesFor(category) {
  return items.value.filter((item) => (
    (item.category || "general") === category
    && (!visibleItemIds.value || visibleItemIds.value.has(String(item.id)))
  ));
}

function formatSize(size) {
  const bytes = Number(size) || 0;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function isImageAttachment(item) {
  return String(item?.contentType || item?.content_type || item?.mimeType || "").startsWith("image/")
    || /\.(png|jpe?g|gif|webp|bmp)$/i.test(String(item?.originalName || ""));
}

function attachmentIcon(item) {
  const contentType = String(item?.contentType || item?.content_type || item?.mimeType || "").toLowerCase();
  const fileName = String(item?.originalName || "").toLowerCase();
  if (contentType.startsWith("video/") || /\.(mp4|mov|avi|mkv|webm)$/.test(fileName)) return FileVideo;
  if (/spreadsheet|excel|csv/.test(contentType) || /\.(xls|xlsx|csv)$/.test(fileName)) return FileSpreadsheet;
  if (/zip|archive|compressed/.test(contentType) || /\.(zip|rar|7z)$/.test(fileName)) return FileArchive;
  return FileText;
}

function uploaderName(item) {
  return item?.uploadedByName
    || item?.uploaderName
    || props.uploaderLabels[item?.category || "general"]
    || props.uploaderLabel
    || item?.uploadedBy
    || "未知上传人";
}

function isPreviewable(item) {
  return isImageAttachment(item) || isPdfAttachment(item);
}

async function openPreview(item) {
  if (busyFileId.value) return;
  if (!isPreviewable(item)) {
    await downloadFile(item);
    return;
  }
  const cachedImage = isImageAttachment(item) && imageUrls.value[String(item.id)];
  if (cachedImage) {
    previewFile.value = item;
    previewUrl.value = cachedImage;
    return;
  }
  const sequence = ++previewRequestSequence;
  busyFileId.value = String(item.id);
  try {
    const blob = await fetchPrivateAttachment(item, apiFetchRaw);
    if (sequence !== previewRequestSequence) return;
    const pdf = isPdfAttachment(item);
    if (pdf) {
      previewPdfBlob.value = blob;
    } else {
      const url = URL.createObjectURL(blob);
      imageUrls.value = { ...imageUrls.value, [String(item.id)]: url };
      previewUrl.value = url;
    }
    previewFile.value = item;
  } catch (reason) {
    if (sequence === previewRequestSequence) emit("error", reason instanceof Error ? reason.message : "附件预览失败");
  } finally {
    if (sequence === previewRequestSequence) busyFileId.value = "";
  }
}

function closePreview() {
  previewRequestSequence += 1;
  busyFileId.value = "";
  previewFile.value = null;
  previewUrl.value = "";
  previewPdfBlob.value = null;
}

async function downloadFile(item) {
  if (!item || busyFileId.value) return;
  const sequence = ++previewRequestSequence;
  busyFileId.value = String(item.id);
  try {
    const blob = previewFile.value?.id === item.id && previewPdfBlob.value
      ? previewPdfBlob.value
      : await fetchPrivateAttachment(item, apiFetchRaw);
    if (sequence !== previewRequestSequence) return;
    downloadPrivateAttachment(blob, item.originalName);
  } catch (reason) {
    if (sequence === previewRequestSequence) emit("error", reason instanceof Error ? reason.message : "附件下载失败");
  } finally {
    if (sequence === previewRequestSequence) busyFileId.value = "";
  }
}

function releaseImageUrls() {
  Object.values(imageUrls.value).forEach((url) => URL.revokeObjectURL(url));
  imageUrls.value = {};
}

async function preloadImageUrls(rows, sequence) {
  const categories = new Set(groups.value.map((group) => group.value));
  const imageRows = rows.filter((item) => isImageAttachment(item)
    && categories.has(item.category)
    && (!visibleItemIds.value || visibleItemIds.value.has(String(item.id))));
  let nextIndex = 0;
  const worker = async () => {
    while (sequence === imageLoadSequence && nextIndex < imageRows.length) {
      const item = imageRows[nextIndex++];
      try {
        const blob = await fetchPrivateAttachment(item, apiFetchRaw, 60_000);
        if (sequence !== imageLoadSequence) return;
        if (!imageUrls.value[String(item.id)]) {
          imageUrls.value = { ...imageUrls.value, [String(item.id)]: URL.createObjectURL(blob) };
        }
      } catch {
        // A failed thumbnail can still be retried through the preview action.
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(3, imageRows.length) }, worker));
}

async function load() {
  const sequence = ++imageLoadSequence;
  closePreview();
  releaseImageUrls();
  items.value = [];
  const targetId = validTargetId.value;
  if (!targetId) return;
  loading.value = true;
  try {
    const rows = collectionRows(await serviceApi.listAttachments(
      props.targetType,
      targetId,
      props.source ? { source: props.source } : {},
    ));
    if (sequence !== imageLoadSequence) return;
    items.value = rows;
    void preloadImageUrls(rows, sequence);
  } catch (reason) {
    if (sequence === imageLoadSequence) emit("error", reason instanceof Error ? reason.message : "附件加载失败");
  } finally { if (sequence === imageLoadSequence) loading.value = false; }
}

async function upload(category, event) {
  if (!props.editable) return;
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  const targetId = validTargetId.value;
  if (!files.length || !targetId) return;
  const oversizedFile = files.find((file) => file.size > MAX_ATTACHMENT_SIZE);
  if (oversizedFile) {
    emit("error", `${oversizedFile.name} 超过 ${MAX_ATTACHMENT_MB}MB`);
    return;
  }
  busyKey.value = `upload-${category}`;
  let uploaded = false;
  const uploadedItems = [];
  try {
    for (const file of files) {
      const response = await serviceApi.uploadAttachment(
        props.targetType,
        targetId,
        file,
        category,
        { source: props.source, roundIndex: props.roundIndex, roundId: props.roundId },
      );
      const item = response?.item || response;
      if (item?.id) uploadedItems.push(item);
      uploaded = true;
    }
  } catch (reason) {
    emit("error", reason instanceof Error ? reason.message : "附件上传失败");
  } finally {
    if (uploaded) {
      await load();
      emit("changed", items.value);
      emit("uploaded", uploadedItems);
    }
    busyKey.value = "";
  }
}

async function remove(item) {
  if (!props.editable || busyKey.value || (props.canRemove && !props.canRemove(item))) return;
  const attachmentId = normalizeDatabaseId(item?.id);
  if (!attachmentId) return;
  if (props.requestRemove) {
    props.requestRemove(item);
    return;
  }
  if (!window.confirm(`确认删除附件“${item.originalName}”？`)) return;
  busyKey.value = `delete-${attachmentId}`;
  try {
    await serviceApi.deleteAttachment(attachmentId, props.source ? { source: props.source } : {});
    await load();
    emit("changed", items.value);
    emit("removed", item);
  } catch (reason) {
    emit("error", reason instanceof Error ? reason.message : "附件删除失败");
  } finally { busyKey.value = ""; }
}

watch(() => [props.targetType, props.targetId, props.source, props.categories, props.itemIds], load, { immediate: true });
onBeforeUnmount(() => {
  emit("busy-change", false);
  imageLoadSequence += 1;
  closePreview();
  releaseImageUrls();
});
</script>

<template>
  <section v-if="validTargetId" class="as-attachment-panel" :class="{ 'as-attachment-panel--compact': compact }">
    <div v-if="!compact" class="as-attachment-panel__head"><div><h3>{{ title }}</h3><span>{{ items.length }} 个文件</span></div><div class="as-attachment-panel__meta"><em v-if="sourceLabel">{{ sourceLabel }}</em><LoaderCircle v-if="loading" class="as-spin" /></div></div>
    <div class="as-attachment-groups">
      <div v-for="group in groups" :key="group.value" class="as-attachment-group">
        <div v-if="groups.length > 1 || editable || !compact" class="as-attachment-group__head"><strong>{{ group.label }} <span>{{ filesFor(group.value).length }}</span><i v-if="group.required">*</i></strong><label v-if="editable && group.editable" :class="{ disabled: Boolean(busyKey) }" :aria-disabled="Boolean(busyKey)"><LoaderCircle v-if="busyKey === `upload-${group.value}`" class="as-spin" /><Upload v-else /><span>{{ uploadLabel }}</span><input type="file" multiple :disabled="Boolean(busyKey)" @change="upload(group.value, $event)"></label></div>
        <div v-if="filesFor(group.value).length" class="as-attachment-list">
          <div v-for="item in filesFor(group.value)" :key="item.id">
            <button type="button" class="as-attachment-preview" :title="`${isPreviewable(item) ? '预览' : '下载'}${item.originalName}`" :aria-label="`${isPreviewable(item) ? '预览' : '下载'}：${item.originalName}`" :disabled="Boolean(busyFileId)" @click="openPreview(item)">
              <LoaderCircle v-if="busyFileId === String(item.id)" class="as-spin" />
              <img v-else-if="isImageAttachment(item) && imageUrls[String(item.id)]" :src="imageUrls[String(item.id)]" :alt="item.originalName">
              <component v-else :is="attachmentIcon(item)" />
              <span v-if="isPreviewable(item)" class="as-attachment-preview__hint"><Eye /></span>
            </button>
            <span><strong>{{ item.originalName }}</strong><small>{{ formatSize(item.size) }} · {{ uploaderName(item) }} · {{ item.createdAt?.replace('T', ' ').slice(0, 16) }}</small></span>
            <span class="as-attachment-actions">
              <button v-if="isPreviewable(item)" type="button" class="as-attachment-open" :title="`预览${item.originalName}`" :aria-label="`预览：${item.originalName}`" :disabled="Boolean(busyFileId)" @click="openPreview(item)"><Eye /></button>
              <button type="button" class="as-attachment-open" :title="`下载${item.originalName}`" :aria-label="`下载：${item.originalName}`" :disabled="Boolean(busyFileId)" @click="downloadFile(item)"><Download /></button>
              <button v-if="editable && group.editable && (requestRemove || item.canDelete) && (!canRemove || canRemove(item))" type="button" :title="`${removeLabel}附件`" :aria-label="`${removeLabel}：${item.originalName}`" :disabled="Boolean(busyKey)" @click="remove(item)"><LoaderCircle v-if="busyKey === `delete-${item.id}`" class="as-spin" /><Trash2 v-else /></button>
            </span>
          </div>
        </div>
        <p v-else class="as-attachment-empty">暂无文件</p>
      </div>
    </div>
  </section>
  <ImagePreviewDialog :open="Boolean(previewFile)" :src="previewUrl" :blob="previewPdfBlob" :title="previewFile?.originalName || '附件预览'" :kind="isPdfAttachment(previewFile) ? 'pdf' : 'image'" :manage-focus="managePreviewFocus" @close="closePreview" @download="downloadFile(previewFile)" />
</template>
