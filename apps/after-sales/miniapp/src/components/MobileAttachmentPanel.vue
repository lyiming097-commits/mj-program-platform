<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";
import { ApiError, downloadAuthenticatedFile } from "@/api/client";
import { deleteAttachment, fetchAttachments, uploadAttachment, type AttachmentTargetType } from "@/api/mobile";
import type { MobileAttachment } from "@/api/types";
import { MAX_ATTACHMENT_MB, MAX_ATTACHMENT_SIZE } from "@/attachmentLimits";

interface Props {
  targetId: number;
  targetType?: AttachmentTargetType;
  category?: string;
  categories?: readonly AttachmentCategory[];
  editable?: boolean;
  uploadLabel?: string;
  emptyLabel?: string;
  successMessage?: string;
}

interface AttachmentCategory {
  readonly value: string;
  readonly label: string;
  readonly editable?: boolean;
  readonly uploadLabel?: string;
  readonly emptyLabel?: string;
}

interface ChosenFile {
  readonly path: string;
  readonly name?: string;
  readonly size?: number;
}

const props = withDefaults(defineProps<Props>(), {
  targetType: "project_node",
  category: "general",
  editable: true,
  uploadLabel: "上传交付附件",
  emptyLabel: "暂无交付附件",
  successMessage: "交付附件已上传",
});
const emit = defineEmits<{
  changed: [items: readonly MobileAttachment[]];
  error: [message: string];
}>();

const items = shallowRef<MobileAttachment[]>([]);
const imageSources = shallowRef<Record<string, string>>({});
const imageLoading = shallowRef<Record<string, boolean>>({});
const imageFailed = shallowRef<Record<string, boolean>>({});
const loading = shallowRef(false);
const uploadingCategory = shallowRef("");
const busyId = shallowRef(0);
let imageLoadToken = 0;
const groups = computed<readonly AttachmentCategory[]>(() => (
  props.categories?.length
    ? props.categories
    : [{ value: props.category, label: "" }]
));
const grouped = computed(() => Boolean(props.categories?.length));
const visibleCategories = computed(() => new Set(groups.value.map((group) => group.value)));
const visibleFiles = computed(() => items.value.filter((item) => visibleCategories.value.has(item.category)));

function filesFor(category: string): readonly MobileAttachment[] {
  return items.value.filter((item) => item.category === category);
}

function groupEditable(group: AttachmentCategory): boolean {
  return props.editable && group.editable !== false;
}

function formatSize(value: number): string {
  const size = Number(value) || 0;
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size >= 1024) return `${Math.ceil(size / 1024)} KB`;
  return `${size} B`;
}

function dateTime(value: unknown): string {
  return value ? String(value).replace("T", " ").slice(0, 16) : "";
}

function isImage(item: MobileAttachment): boolean {
  return String(item.mimeType || "").startsWith("image/")
    || /\.(png|jpe?g|gif|webp|bmp|avif|heic|heif)$/i.test(item.originalName);
}

function previewImage(current: string): void {
  const urls = visibleFiles.value
    .filter(isImage)
    .map((image) => imageSources.value[String(image.id)])
    .filter((source): source is string => Boolean(source));
  uni.previewImage({ current, urls: urls.includes(current) ? urls : [current, ...urls] });
}

function reportError(reason: unknown, fallback: string): void {
  const message = reason instanceof Error ? reason.message : fallback;
  emit("error", message);
  uni.showToast({ title: message, icon: "none" });
}

function setImageState(id: number, state: "loading" | "loaded" | "failed"): void {
  const key = String(id);
  const nextLoading = { ...imageLoading.value };
  const nextFailed = { ...imageFailed.value };
  if (state === "loading") nextLoading[key] = true;
  else delete nextLoading[key];
  if (state === "failed") nextFailed[key] = true;
  else delete nextFailed[key];
  imageLoading.value = nextLoading;
  imageFailed.value = nextFailed;
}

async function preloadImages(nextItems: readonly MobileAttachment[], token: number): Promise<void> {
  const pending = nextItems.filter((item) => (
    isImage(item) && !imageSources.value[String(item.id)]
  ));
  let nextIndex = 0;
  const worker = async (): Promise<void> => {
    while (nextIndex < pending.length && token === imageLoadToken) {
      const item = pending[nextIndex];
      nextIndex += 1;
      if (!item) continue;
      setImageState(item.id, "loading");
      try {
        const filePath = await downloadAuthenticatedFile(item.downloadUrl);
        if (token !== imageLoadToken || !items.value.some((current) => current.id === item.id)) continue;
        imageSources.value = { ...imageSources.value, [String(item.id)]: filePath };
        setImageState(item.id, "loaded");
      } catch {
        if (token === imageLoadToken) setImageState(item.id, "failed");
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(2, pending.length) }, worker));
}

async function load(): Promise<void> {
  const token = ++imageLoadToken;
  if (!Number.isInteger(props.targetId) || props.targetId <= 0) {
    items.value = [];
    imageSources.value = {};
    imageLoading.value = {};
    imageFailed.value = {};
    return;
  }
  loading.value = true;
  try {
    const response = await fetchAttachments(props.targetType, props.targetId);
    const nextItems = Array.isArray(response.items) ? response.items : [];
    items.value = nextItems;
    const nextIds = new Set(nextItems.map((item) => String(item.id)));
    imageSources.value = Object.fromEntries(
      Object.entries(imageSources.value).filter(([id]) => nextIds.has(id)),
    );
    imageLoading.value = Object.fromEntries(
      Object.entries(imageLoading.value).filter(([id]) => nextIds.has(id)),
    );
    imageFailed.value = Object.fromEntries(
      Object.entries(imageFailed.value).filter(([id]) => nextIds.has(id)),
    );
    void preloadImages(nextItems, token);
  } catch (reason) {
    reportError(reason, "附件加载失败");
  } finally {
    loading.value = false;
  }
}

async function uploadFiles(group: AttachmentCategory, chosenFiles: readonly ChosenFile[]): Promise<void> {
  if (!groupEditable(group) || uploadingCategory.value || !chosenFiles.length) return;
  const oversized = chosenFiles.find((file) => Number(file.size || 0) > MAX_ATTACHMENT_SIZE);
  if (oversized) {
    reportError(null, `${oversized.name || "所选文件"}超过 ${MAX_ATTACHMENT_MB}MB`);
    return;
  }
  uploadingCategory.value = group.value;
  let uploadedAny = false;
  try {
    for (const file of chosenFiles) {
      if (!file.path) continue;
      await uploadAttachment(props.targetType, props.targetId, file.path, group.value);
      uploadedAny = true;
    }
    await load();
    emit("changed", visibleFiles.value);
    uni.showToast({ title: props.successMessage, icon: "success" });
  } catch (reason) {
    if (uploadedAny) {
      await load();
      emit("changed", visibleFiles.value);
    }
    reportError(reason, "附件上传失败");
  } finally {
    uploadingCategory.value = "";
  }
}

function chooseMessageFiles(group: AttachmentCategory): void {
  uni.chooseMessageFile({
    count: 9,
    type: "all",
    success: (result) => { void uploadFiles(group, result.tempFiles); },
    fail: (reason) => {
      if (!String(reason.errMsg || "").includes("cancel")) reportError(reason, "选择附件失败");
    },
  });
}

function chooseMediaFiles(group: AttachmentCategory): void {
  uni.chooseMedia({
    count: 9,
    mediaType: ["image"],
    sourceType: ["album", "camera"],
    success: (result) => {
      void uploadFiles(group, result.tempFiles.map((file) => ({
        path: file.tempFilePath,
        size: file.size,
      })));
    },
    fail: (reason) => {
      if (!String(reason.errMsg || "").includes("cancel")) reportError(reason, "选择图片失败");
    },
  });
}

function chooseFiles(group: AttachmentCategory): void {
  if (!groupEditable(group) || uploadingCategory.value) return;
  uni.showActionSheet({
    itemList: ["拍照或相册", "微信文件"],
    success: (result) => {
      if (result.tapIndex === 0) chooseMediaFiles(group);
      else chooseMessageFiles(group);
    },
  });
}

async function openFile(item: MobileAttachment): Promise<void> {
  if (busyId.value) return;
  const cachedImagePath = imageSources.value[String(item.id)];
  if (isImage(item) && cachedImagePath) {
    previewImage(cachedImagePath);
    return;
  }
  busyId.value = item.id;
  uni.showLoading({ title: "正在打开" });
  try {
    const filePath = await downloadAuthenticatedFile(item.downloadUrl);
    if (isImage(item)) {
      imageSources.value = { ...imageSources.value, [String(item.id)]: filePath };
      setImageState(item.id, "loaded");
      previewImage(filePath);
    }
    else {
      uni.openDocument({
        filePath,
        showMenu: true,
        fail: () => uni.showToast({ title: "暂不支持预览该文件", icon: "none" }),
      });
    }
  } catch (reason) {
    if (reason instanceof ApiError && reason.status === 401) {
      uni.reLaunch({ url: "/pages/login/index" });
    } else {
      reportError(reason, "附件下载失败");
    }
  } finally {
    busyId.value = 0;
    uni.hideLoading();
  }
}

function handleImageError(item: MobileAttachment): void {
  const key = String(item.id);
  const nextSources = { ...imageSources.value };
  delete nextSources[key];
  imageSources.value = nextSources;
  setImageState(item.id, "failed");
}

function removeFile(item: MobileAttachment): void {
  if (!props.editable || !item.canDelete || busyId.value) return;
  uni.showModal({
    title: "删除附件",
    content: `确定删除“${item.originalName}”吗？`,
    success: (result) => {
      if (!result.confirm) return;
      busyId.value = item.id;
      void deleteAttachment(item.id)
        .then(async () => {
          await load();
          emit("changed", visibleFiles.value);
          uni.showToast({ title: "附件已删除", icon: "success" });
        })
        .catch((reason: unknown) => reportError(reason, "附件删除失败"))
        .finally(() => { busyId.value = 0; });
    },
  });
}

watch(() => [props.targetType, props.targetId], () => { void load(); }, { immediate: true });
</script>

<template>
  <view class="attachment-panel">
    <view v-for="group in groups" :key="group.value" class="attachment-group">
      <view v-if="grouped" class="attachment-group-head">
        <view class="attachment-group-title">
          <text>{{ group.label }}</text>
          <text class="attachment-count">{{ filesFor(group.value).length }}</text>
        </view>
        <view
          v-if="groupEditable(group)"
          class="upload-button upload-button--compact"
          :class="{ disabled: Boolean(uploadingCategory) }"
          role="button"
          hover-class="upload-button--pressed"
          @tap.stop="chooseFiles(group)"
        >
          <view class="upload-icon"><view class="upload-icon-line" /></view>
          <text>{{ uploadingCategory === group.value ? "上传中..." : (group.uploadLabel || uploadLabel) }}</text>
        </view>
      </view>
      <view
        v-else-if="groupEditable(group)"
        class="upload-button upload-button--wide"
        :class="{ disabled: Boolean(uploadingCategory) }"
        role="button"
        hover-class="upload-button--pressed"
        @tap.stop="chooseFiles(group)"
      >
        <view class="upload-icon-wrap"><view class="upload-icon"><view class="upload-icon-line" /></view></view>
        <view class="upload-copy"><text class="upload-label">{{ uploadingCategory ? "上传中..." : uploadLabel }}</text><text class="upload-hint">支持拍照、相册或微信文件</text></view>
      </view>

      <view v-if="loading && !filesFor(group.value).length" class="attachment-empty">正在加载附件...</view>
      <view v-else-if="filesFor(group.value).length" class="attachment-list">
        <view v-for="item in filesFor(group.value)" :key="item.id" class="attachment-row" :class="{ 'attachment-row--image': isImage(item) }">
          <view class="file-icon" :class="{ 'file-icon--image': isImage(item) }" role="button" :aria-label="isImage(item) ? `查看大图：${item.originalName}` : `查看附件：${item.originalName}`" hover-class="file-icon--pressed" @tap.stop="openFile(item)">
            <image v-if="isImage(item) && imageSources[String(item.id)]" class="attachment-image" :src="imageSources[String(item.id)]" mode="aspectFill" @error="handleImageError(item)" />
            <text v-else-if="isImage(item)" class="attachment-type">{{ imageLoading[String(item.id)] ? "加载中" : imageFailed[String(item.id)] ? "点击重试" : "图片" }}</text>
            <text v-else class="attachment-type">文件</text>
          </view>
          <view class="file-copy"><text class="attachment-file-name">{{ item.originalName }}</text><text class="attachment-file-meta">{{ formatSize(item.size) }}<template v-if="dateTime(item.createdAt)"> · {{ dateTime(item.createdAt) }}</template></text></view>
          <view class="file-actions">
            <view role="button" hover-class="file-action--pressed" @tap.stop="openFile(item)">{{ busyId === item.id ? "打开中" : isImage(item) ? "查看大图" : "查看" }}</view>
            <view v-if="groupEditable(group) && item.canDelete" class="delete-action" role="button" hover-class="file-action--pressed" @tap.stop="removeFile(item)">删除</view>
          </view>
        </view>
      </view>
      <view v-else-if="grouped || !groupEditable(group)" class="attachment-empty">{{ group.emptyLabel || (grouped ? "暂无文件" : emptyLabel) }}</view>
    </view>
  </view>
</template>

<style scoped>
.attachment-panel { display: grid; gap: 18rpx; }
.attachment-group { display: grid; gap: 16rpx; }
.attachment-group + .attachment-group { border-top: 1rpx solid #e4e7ec; padding-top: 20rpx; }
.attachment-group-head { display: flex; min-height: 64rpx; align-items: center; justify-content: space-between; gap: 16rpx; }
.attachment-group-title { display: flex; min-width: 0; align-items: center; gap: 10rpx; color: #344054; font-size: 23rpx; font-weight: 800; }
.attachment-count { display: grid; min-width: 34rpx; height: 34rpx; place-items: center; border-radius: 8rpx; background: #eef4ff; padding: 0 8rpx; color: #315f9f; font-size: 19rpx; }
.upload-button { display: grid; width: 100%; min-height: 106rpx; grid-template-columns: 62rpx minmax(0, 1fr); align-items: center; gap: 15rpx; border: 1rpx dashed #b9c5d4; border-radius: 10rpx; background: #f9fbfd; padding: 15rpx 18rpx; color: #155eef; }
.upload-button--compact { display: flex; width: max-content; min-height: 58rpx; flex: 0 0 auto; gap: 10rpx; border-style: solid; border-color: #bfd2f7; background: #edf4ff; padding: 0 18rpx; font-size: 20rpx; font-weight: 700; }
.upload-button--pressed { border-color: #93b4ef; background: #e3edff; }
.upload-button.disabled { opacity: .55; }
.upload-icon-wrap { display: grid; width: 62rpx; height: 62rpx; place-items: center; border-radius: 9rpx; background: #eaf2ff; color: #155eef; }
.upload-button--compact .upload-icon { transform: scale(.84); }
.upload-icon { position: relative; width: 25rpx; height: 25rpx; border: 2rpx solid currentColor; border-top: 0; border-radius: 3rpx; }
.upload-icon::before { position: absolute; top: -6rpx; left: 10rpx; width: 3rpx; height: 16rpx; background: currentColor; content: ""; }
.upload-icon::after { position: absolute; top: -7rpx; left: 6rpx; width: 9rpx; height: 9rpx; border-top: 3rpx solid currentColor; border-left: 3rpx solid currentColor; content: ""; transform: rotate(45deg); }
.upload-icon-line { position: absolute; right: 4rpx; bottom: 4rpx; left: 4rpx; border-top: 2rpx solid currentColor; }
.upload-copy { min-width: 0; }
.upload-label, .upload-hint { display: block; }
.upload-label { color: #344054; font-size: 22rpx; font-weight: 800; }
.upload-hint { margin-top: 5rpx; color: #8a96a7; font-size: 18rpx; }
.attachment-list { border: 1rpx solid #dbe5ef; border-radius: 12rpx; background: #fff; }
.attachment-row { display: grid; min-height: 108rpx; grid-template-columns: 64rpx minmax(0, 1fr); align-items: center; column-gap: 18rpx; border-bottom: 1rpx solid #edf0f2; padding: 16rpx 18rpx; }
.attachment-row--image { min-height: 148rpx; grid-template-columns: 148rpx minmax(0, 1fr); }
.attachment-row:last-child { border-bottom: 0; }
.file-icon { display: grid; width: 64rpx; height: 64rpx; grid-row: 1 / span 2; place-items: center; overflow: hidden; border: 1rpx solid #d7e2f0; border-radius: 10rpx; background: #edf3fb; color: #315f9f; }
.file-icon--image { width: 148rpx; height: 112rpx; background: #f7faff; }
.attachment-image { width: 100%; height: 100%; }
.file-icon--pressed { opacity: .72; }
.attachment-type { padding: 8rpx; font-size: 19rpx; font-weight: 800; text-align: center; }
.file-copy { min-width: 0; grid-column: 2; align-self: end; }
.attachment-file-name, .attachment-file-meta { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attachment-file-name { color: #263244; font-size: 23rpx; font-weight: 700; }
.attachment-file-meta { margin-top: 6rpx; color: #7b8798; font-size: 19rpx; }
.file-actions { display: flex; min-width: 0; grid-column: 2; align-self: start; align-items: center; justify-content: flex-start; gap: 14rpx; color: #155eef; font-size: 20rpx; font-weight: 700; }
.file-actions > view { display: flex; min-height: 56rpx; align-items: center; white-space: nowrap; }
.delete-action { color: #b42318; }
.file-action--pressed { opacity: .58; }
.attachment-empty { display: grid; min-height: 96rpx; place-items: center; border: 1rpx dashed #cad5e2; border-radius: 12rpx; background: #fbfcfe; color: #8a98aa; font-size: 21rpx; }
@media (max-width: 360px) {
  .upload-button--wide { grid-template-columns: 58rpx minmax(0, 1fr); }
  .upload-icon-wrap { width: 58rpx; height: 58rpx; }
  .attachment-row--image { grid-template-columns: 124rpx minmax(0, 1fr); }
  .file-icon--image { width: 124rpx; height: 100rpx; }
}
</style>
