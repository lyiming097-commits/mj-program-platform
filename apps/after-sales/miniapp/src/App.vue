<script setup lang="ts">
import { onLaunch } from "@dcloudio/uni-app";
import { restoreSession } from "@/composables/useSession";

function initializeUpdateManager(): void {
  if (uni.getSystemInfoSync().platform === "devtools") return;
  if (typeof uni.getUpdateManager !== "function") return;
  const updateManager = uni.getUpdateManager();
  updateManager.onUpdateReady(() => {
    uni.showModal({
      title: "发现新版本",
      content: "新版本已经准备完成，请立即更新。",
      showCancel: false,
      confirmText: "立即更新",
      success: (result) => { if (result.confirm) updateManager.applyUpdate(); },
    });
  });
  updateManager.onUpdateFailed(() => {
    uni.showModal({
      title: "更新未完成",
      content: "新版本下载失败，请关闭小程序后重新打开。",
      showCancel: false,
    });
  });
}

onLaunch(() => {
  void restoreSession();
  initializeUpdateManager();
});
</script>

<style>
page {
  min-height: 100vh;
  --app-primary: #155eef;
  --app-primary-pressed: #0f4fd1;
  --app-text: #182230;
  --app-text-secondary: #526174;
  --app-text-muted: #7b8798;
  --app-border: #dfe5ec;
  --app-border-strong: #cbd5df;
  --app-surface: #ffffff;
  --app-surface-subtle: #f7f9fc;
  --app-danger: #b42318;
  background: #f4f6f8;
  color: var(--app-text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 28rpx;
}

view, text, input, textarea, button, image {
  box-sizing: border-box;
}

button::after {
  border: 0;
}

button {
  letter-spacing: 0;
}

button:active {
  opacity: .84;
}

.page-shell {
  min-height: 100vh;
  background: #f4f6f8;
}

.page-content {
  padding: 28rpx 32rpx 40rpx;
}

.primary-button,
.secondary-button,
.danger-button {
  display: flex;
  min-height: 76rpx;
  align-items: center;
  justify-content: center;
  border-radius: 10rpx;
  padding: 0 26rpx;
  font-size: 24rpx;
  font-weight: 700;
  line-height: 76rpx;
}

.primary-button {
  border: 1rpx solid var(--app-primary);
  background: var(--app-primary);
  color: #fff;
  box-shadow: 0 2rpx 5rpx rgba(21, 94, 239, .18);
}

.secondary-button {
  border: 1rpx solid var(--app-border-strong);
  background: var(--app-surface);
  color: #344054;
}

.danger-button {
  border: 1rpx solid #efc8cd;
  background: #fff;
  color: var(--app-danger);
}

.primary-button[disabled],
.secondary-button[disabled],
.danger-button[disabled] {
  opacity: .48;
}

.field-label {
  display: block;
  margin-bottom: 10rpx;
  color: #475467;
  font-size: 22rpx;
  font-weight: 700;
}

.field-input,
.field-textarea,
.field-picker {
  width: 100%;
  border: 1rpx solid var(--app-border-strong);
  border-radius: 10rpx;
  background: #fff;
  color: #263244;
  font-size: 24rpx;
}

.field-input,
.field-picker {
  height: 72rpx;
  padding: 0 20rpx;
  line-height: 72rpx;
}

.field-textarea {
  min-height: 144rpx;
  padding: 18rpx 20rpx;
  line-height: 36rpx;
}

.empty-state {
  display: flex;
  min-height: 320rpx;
  align-items: center;
  justify-content: center;
  color: #7b8796;
  font-size: 26rpx;
}

.error-banner,
.success-banner {
  margin-bottom: 20rpx;
  border-radius: 8rpx;
  padding: 18rpx 20rpx;
  font-size: 24rpx;
  line-height: 36rpx;
}

.error-banner {
  border: 1rpx solid #fecaca;
  background: #fff3f2;
  color: #b42318;
}

.success-banner {
  border: 1rpx solid #a7e3c7;
  background: #edfdf5;
  color: #087455;
}

/* Shared rhythm keeps form controls and section groups predictable on every tab. */
page {
  --field-control-height: 76rpx;
  --field-group-gap: 24rpx;
  --field-section-gap: 24rpx;
}

button.primary-button,
button.secondary-button,
button.danger-button,
.field-input,
.field-picker,
.date-time-field {
  min-height: var(--field-control-height);
  height: var(--field-control-height);
  border-radius: 10rpx;
}

button.primary-button,
button.secondary-button,
button.danger-button {
  line-height: var(--field-control-height);
}

.field-textarea {
  border-radius: 10rpx;
}

.segmented {
  min-height: var(--field-control-height);
  gap: 4rpx;
}

.segment-item {
  min-height: 64rpx;
}

.page-content,
.detail-page,
.field-main,
.progress-list,
.execution-form,
.create-panel {
  --section-gap: var(--field-section-gap);
}

.form-actions,
.fixed-action-bar,
.as-field-action-bar {
  gap: 16rpx;
}
</style>
