<script setup lang="ts">
import type { PendingUploadFile } from "@/api/types";
import { MAX_ATTACHMENT_MB, MAX_ATTACHMENT_SIZE } from "@/attachmentLimits";

interface Props {
  files: readonly PendingUploadFile[];
  buttonLabel?: string;
  disabled?: boolean;
  maxCount?: number;
}

const props = withDefaults(defineProps<Props>(), {
  buttonLabel: "选择附件",
  disabled: false,
  maxCount: 9,
});
const emit = defineEmits<{
  "update:files": [files: PendingUploadFile[]];
  error: [message: string];
}>();

function fileName(path: string, fallback: string): string {
  const value = String(path || "").replace(/\\/g, "/").split("/").pop();
  return value || fallback;
}

function formatSize(value: number): string {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${Math.ceil(value / 1024)} KB`;
  return `${value || 0} B`;
}

function reportError(message: string): void {
  emit("error", message);
  uni.showToast({ title: message, icon: "none" });
}

function isImage(file: PendingUploadFile): boolean {
  return /\.(png|jpe?g|gif|webp|bmp|avif|heic|heif)(?:$|[?#])/i.test(file.name || file.path);
}

function previewImage(file: PendingUploadFile): void {
  const urls = props.files.filter(isImage).map((item) => item.path).filter(Boolean);
  if (!file.path || !urls.length) return;
  uni.previewImage({ current: file.path, urls });
}

function appendFiles(incoming: readonly PendingUploadFile[]): void {
  const oversized = incoming.find((file) => file.size > MAX_ATTACHMENT_SIZE);
  if (oversized) {
    reportError(`${oversized.name || "所选文件"}超过 ${MAX_ATTACHMENT_MB}MB`);
    return;
  }
  const available = Math.max(0, props.maxCount - props.files.length);
  if (!available) {
    reportError(`最多选择 ${props.maxCount} 个附件`);
    return;
  }
  const accepted = incoming.slice(0, available);
  emit("update:files", [...props.files, ...accepted]);
  if (accepted.length < incoming.length) reportError(`最多选择 ${props.maxCount} 个附件`);
}

function chooseMessageFiles(): void {
  const count = Math.max(1, props.maxCount - props.files.length);
  uni.chooseMessageFile({
    count,
    type: "all",
    success: (result) => {
      appendFiles(result.tempFiles.map((file) => ({
        path: file.path,
        name: file.name || fileName(file.path, "微信文件"),
        size: Number(file.size || 0),
      })));
    },
    fail: (reason) => {
      if (!String(reason.errMsg || "").includes("cancel")) reportError("选择附件失败");
    },
  });
}

function chooseMediaFiles(): void {
  const count = Math.max(1, props.maxCount - props.files.length);
  uni.chooseMedia({
    count,
    mediaType: ["image"],
    sourceType: ["album", "camera"],
    success: (result) => {
      appendFiles(result.tempFiles.map((file, index) => ({
        path: file.tempFilePath,
        name: fileName(file.tempFilePath, `现场图片${index + 1}.jpg`),
        size: Number(file.size || 0),
      })));
    },
    fail: (reason) => {
      if (!String(reason.errMsg || "").includes("cancel")) reportError("选择图片失败");
    },
  });
}

function chooseFiles(): void {
  if (props.disabled) return;
  if (props.files.length >= props.maxCount) {
    reportError(`最多选择 ${props.maxCount} 个附件`);
    return;
  }
  uni.showActionSheet({
    itemList: ["拍照或相册", "微信文件"],
    success: (result) => {
      if (result.tapIndex === 0) chooseMediaFiles();
      else chooseMessageFiles();
    },
  });
}

function removeFile(index: number): void {
  if (props.disabled) return;
  emit("update:files", props.files.filter((_file, fileIndex) => fileIndex !== index));
}
</script>

<template>
  <view class="pending-file-picker">
    <view class="pending-upload-frame" :class="{ disabled }">
      <view
        class="pending-upload-button"
        role="button"
        hover-class="pending-upload-button--pressed"
        @tap.stop="chooseFiles"
      >
        <view class="pending-upload-icon-wrap"><view class="pending-upload-icon"><view class="pending-upload-icon-line" /></view></view>
        <view class="pending-upload-copy"><text class="pending-upload-label">{{ buttonLabel }}</text><text class="pending-upload-hint">支持拍照、相册或微信文件，单个不超过 {{ MAX_ATTACHMENT_MB }}MB</text></view>
      </view>
      <view v-if="files.length" class="pending-file-list">
        <view v-for="(file, index) in files" :key="`${file.path}-${index}`" class="pending-file-row" :class="{ 'pending-file-row--image': isImage(file) }">
          <view class="pending-file-icon" :class="{ 'pending-file-icon--image': isImage(file) }" :role="isImage(file) ? 'button' : undefined" :aria-label="isImage(file) ? `查看大图：${file.name}` : undefined" hover-class="pending-file-icon--pressed" @tap.stop="isImage(file) && previewImage(file)"><image v-if="isImage(file)" class="pending-file-image" :src="file.path" mode="aspectFill" /><text v-else class="pending-file-type">文件</text></view>
          <view class="pending-file-copy"><text class="pending-file-name">{{ file.name }}</text><text class="pending-file-meta">{{ formatSize(file.size) }}</text></view>
          <view class="pending-file-actions"><view v-if="isImage(file)" class="pending-file-preview" role="button" hover-class="pending-file-action--pressed" @tap.stop="previewImage(file)">查看大图</view><view class="pending-file-remove" role="button" hover-class="pending-file-action--pressed" @tap.stop="removeFile(index)">移除</view></view>
        </view>
      </view>
    </view>
  </view>
</template>

<style scoped>
.pending-file-picker { min-width: 0; }
.pending-upload-frame { overflow: hidden; border: 1rpx dashed #b9c5d4; border-radius: 10rpx; background: #f9fbfd; }
.pending-upload-frame.disabled { opacity: .55; }
.pending-upload-button { display: grid; min-height: 112rpx; grid-template-columns: 64rpx minmax(0, 1fr); align-items: center; gap: 16rpx; padding: 16rpx 18rpx; }
.pending-upload-button--pressed { background: #edf4ff; }
.pending-upload-icon-wrap { display: grid; width: 64rpx; height: 64rpx; place-items: center; border-radius: 9rpx; background: #eaf2ff; color: #155eef; }
.pending-upload-icon { position: relative; width: 25rpx; height: 25rpx; border: 2rpx solid currentColor; border-top: 0; border-radius: 3rpx; }
.pending-upload-icon::before { position: absolute; top: -6rpx; left: 10rpx; width: 3rpx; height: 16rpx; background: currentColor; content: ""; }
.pending-upload-icon::after { position: absolute; top: -7rpx; left: 6rpx; width: 9rpx; height: 9rpx; border-top: 3rpx solid currentColor; border-left: 3rpx solid currentColor; content: ""; transform: rotate(45deg); }
.pending-upload-icon-line { position: absolute; right: 4rpx; bottom: 4rpx; left: 4rpx; border-top: 2rpx solid currentColor; }
.pending-upload-copy { min-width: 0; }
.pending-upload-label, .pending-upload-hint { display: block; }
.pending-upload-label { color: #344054; font-size: 22rpx; font-weight: 800; }
.pending-upload-hint { margin-top: 5rpx; color: #8a96a7; font-size: 18rpx; line-height: 28rpx; }
.pending-file-list { border-top: 1rpx solid #dbe5ef; background: #fff; }
.pending-file-row { display: grid; min-height: 92rpx; grid-template-columns: 52rpx minmax(0, 1fr); align-items: center; column-gap: 16rpx; border-bottom: 1rpx solid #edf0f2; padding: 14rpx 16rpx; }
.pending-file-row--image { min-height: 132rpx; grid-template-columns: 120rpx minmax(0, 1fr); }
.pending-file-row:last-child { border-bottom: 0; }
.pending-file-icon { display: grid; width: 52rpx; height: 52rpx; grid-row: 1 / span 2; place-items: center; border-radius: 10rpx; background: #edf3fb; color: #315f9f; font-size: 18rpx; font-weight: 800; }
.pending-file-icon--image { width: 120rpx; height: 96rpx; overflow: hidden; border: 1rpx solid #d7e2f0; background: #f7faff; }
.pending-file-image { width: 100%; height: 100%; }
.pending-file-icon--pressed { opacity: .72; }
.pending-file-copy { min-width: 0; grid-column: 2; align-self: end; }
.pending-file-name, .pending-file-meta { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pending-file-name { color: #263244; font-size: 22rpx; font-weight: 700; }
.pending-file-meta { margin-top: 5rpx; color: #7b8798; font-size: 18rpx; }
.pending-file-actions { display: flex; min-width: 0; grid-column: 2; align-self: start; align-items: center; justify-content: flex-start; gap: 14rpx; font-size: 20rpx; font-weight: 700; }
.pending-file-preview, .pending-file-remove { display: grid; min-height: 56rpx; place-items: center; }
.pending-file-preview { color: #155eef; }
.pending-file-remove { min-width: 64rpx; color: #b42318; }
.pending-file-action--pressed { opacity: .58; }
@media (max-width: 360px) {
  .pending-upload-button { grid-template-columns: 58rpx minmax(0, 1fr); }
  .pending-upload-icon-wrap { width: 58rpx; height: 58rpx; }
  .pending-file-row--image { grid-template-columns: 104rpx minmax(0, 1fr); }
  .pending-file-icon--image { width: 104rpx; height: 88rpx; }
}
</style>
