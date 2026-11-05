<script setup lang="ts">
import { onHide, onShow, onUnload } from "@dcloudio/uni-app";
import { computed, shallowRef } from "vue";
import { ApiError } from "@/api/client";
import { fetchProviderMe } from "@/api/mobile";
import type { ServiceProvider } from "@/api/types";
import { clearSession, logoutWithWeChat } from "@/composables/useSession";
import { useAccountDeletion } from "@/composables/useAccountDeletion";

const provider = shallowRef<ServiceProvider | null>(null);
const loading = shallowRef(true);
const error = shallowRef("");
const loggingOut = shallowRef(false);
const { deleting, deletionError, requestAccountDeletion } = useAccountDeletion();
let syncTimer: ReturnType<typeof setInterval> | null = null;

const statusLabel = computed(() => provider.value?.certificationStatusLabel
  || ({ pending: "待审核", certified: "已认证", paused: "已暂停" }[provider.value?.certificationStatus || ""])
  || "待审核");

async function load(silent = false): Promise<void> {
  if (!silent) loading.value = true;
  try {
    const response = await fetchProviderMe();
    provider.value = response.item;
    if (provider.value?.certificationStatus === "certified") {
      uni.reLaunch({ url: "/pages/tasks/index" });
    } else if (!provider.value) {
      uni.reLaunch({ url: "/pages/login/index" });
    }
  } catch (reason) {
    if (reason instanceof ApiError && reason.status === 401) {
      clearSession();
      uni.reLaunch({ url: "/pages/login/index" });
      return;
    }
    if (!silent) error.value = reason instanceof Error ? reason.message : "认证状态读取失败";
  } finally {
    if (!silent) loading.value = false;
  }
}

function stopSync(): void {
  if (syncTimer) clearInterval(syncTimer);
  syncTimer = null;
}

async function logout(): Promise<void> {
  if (loggingOut.value) return;
  loggingOut.value = true;
  stopSync();
  try {
    await logoutWithWeChat();
    uni.reLaunch({ url: "/pages/login/index" });
  } finally {
    loggingOut.value = false;
  }
}

onShow(() => {
  void load();
  stopSync();
  syncTimer = setInterval(() => { void load(true); }, 5000);
});
onHide(stopSync);
onUnload(stopSync);
</script>

<template>
  <view class="pending-page">
    <view v-if="error" class="error-banner">{{ error }}</view>
    <view v-if="loading" class="empty-state">正在读取认证状态...</view>
    <template v-else-if="provider">
      <view class="status-mark"><text>✓</text></view>
      <text class="status-title">注册资料已提交</text>
      <text class="status-chip">{{ statusLabel }}</text>
      <view class="profile-summary">
        <view><text>姓名</text><strong>{{ provider.name || "-" }}</strong></view>
        <view><text>服务角色</text><strong>{{ provider.roleLabel || provider.role || "-" }}</strong></view>
        <view><text>联系电话</text><strong>{{ provider.phone || "-" }}</strong></view>
        <view><text>所在城市</text><strong>{{ provider.city || "-" }}</strong></view>
      </view>
      <view v-if="provider.skills?.length" class="skill-list"><text v-for="skill in provider.skills" :key="skill">{{ skill }}</text></view>
      <view class="account-actions">
        <view class="document-links"><navigator url="/pages/privacy/index?document=agreement">用户协议</navigator><navigator url="/pages/privacy/index?document=privacy">隐私保护指引</navigator></view>
        <view v-if="deletionError" class="error-banner">{{ deletionError }}</view>
        <button class="secondary-button" :disabled="loggingOut" @click="logout">{{ loggingOut ? "正在退出..." : "退出登录" }}</button>
        <button class="danger-button" :disabled="deleting" @click="requestAccountDeletion">{{ deleting ? "正在注销..." : "注销服务账号" }}</button>
      </view>
    </template>
  </view>
</template>

<style scoped>
.pending-page { display: flex; min-height: 100vh; flex-direction: column; align-items: center; background: #fff; padding: 110rpx 40rpx 80rpx; }
.status-mark { display: grid; width: 88rpx; height: 88rpx; place-items: center; border-radius: 16rpx; background: #edf4ff; color: #155eef; }
.status-mark text { font-size: 40rpx; }
.status-title { margin-top: 28rpx; color: #182230; font-size: 36rpx; font-weight: 600; }
.status-chip { margin-top: 16rpx; border-radius: 8rpx; background: #fff4d8; padding: 8rpx 16rpx; color: #8a5b00; font-size: 23rpx; }
.profile-summary { display: grid; width: 100%; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22rpx; margin-top: 46rpx; border-top: 1rpx solid #e8edf1; border-bottom: 1rpx solid #e8edf1; padding: 28rpx 0; }
.profile-summary text, .profile-summary strong { display: block; }
.profile-summary text { color: #8792a0; font-size: 22rpx; }
.profile-summary strong { overflow-wrap: anywhere; margin-top: 7rpx; color: #334155; font-size: 26rpx; font-weight: 500; }
.skill-list { display: flex; width: 100%; flex-wrap: wrap; gap: 10rpx; margin-top: 24rpx; }
.skill-list text { border-radius: 7rpx; background: #eef3f6; padding: 9rpx 14rpx; color: #526273; font-size: 22rpx; }
.account-actions { display: grid; width: 100%; gap: 16rpx; margin-top: auto; padding-top: 36rpx; }
.account-actions button { width: 100%; }
.document-links { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12rpx; }
.document-links navigator { min-height: 56rpx; color: #155eef; font-size: 22rpx; line-height: 56rpx; text-align: center; }
.account-actions .error-banner { margin-bottom: 0; }
</style>
