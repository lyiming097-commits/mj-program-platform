<script setup lang="ts">
import { onLoad, onShow } from "@dcloudio/uni-app";
import { shallowRef } from "vue";
import { ApiError } from "@/api/client";
import type { ServiceReward } from "@/api/types";
import { fetchMobileRecords } from "@/api/mobile";

const loading = shallowRef(false);
const error = shallowRef("");
const rewardId = shallowRef(0);
const reward = shallowRef<ServiceReward | null>(null);

function dateTime(value: unknown): string {
  return value ? String(value).replace("T", " ").slice(0, 16) : "-";
}

function rewardValue(item: ServiceReward): string {
  if (item.rewardType === "cash" && item.amount !== undefined && item.amount !== "") return `${item.amount} 元`;
  if (item.rewardType === "points" && item.points !== undefined) return `${item.points} 积分`;
  return item.prize || "以管理端记录为准";
}

async function load(): Promise<void> {
  if (!rewardId.value) { reward.value = null; return; }
  loading.value = true;
  error.value = "";
  try {
    const response = await fetchMobileRecords<ServiceReward>("rewards", 1, 1, rewardId.value);
    reward.value = response.items[0] || null;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "奖励详情加载失败";
    if (reason instanceof ApiError && reason.status === 401) uni.reLaunch({ url: "/pages/login/index" });
  } finally { loading.value = false; }
}

onLoad((options) => {
  const parsed = Number(options?.id || 0);
  if (Number.isInteger(parsed) && parsed > 0) rewardId.value = parsed;
});
onShow(() => { void load(); });
</script>

<template>
  <view class="page-shell reward-page">
    <view v-if="error" class="error-banner">{{ error }}</view>
    <view v-if="loading && !reward" class="empty-state">正在加载奖励记录...</view>
    <view v-else-if="!reward" class="empty-state">奖励记录不存在或已删除</view>
    <template v-else>
      <view class="reward-head">
        <view class="reward-mark">奖</view>
        <view class="reward-heading">
          <text class="reward-type">{{ reward.rewardTypeLabel || "服务奖励" }}</text>
          <text class="reward-title">{{ reward.title || reward.prize || "服务奖励" }}</text>
          <text class="reward-code">{{ reward.code || `奖励记录 #${reward.id}` }}</text>
        </view>
        <text class="status-chip" :class="{ 'is-issued': reward.status === 'issued' || reward.status === 'completed' }">{{ reward.statusLabel || reward.status || "-" }}</text>
      </view>

      <view class="reward-section reward-value-card">
        <text class="section-label">奖励内容</text>
        <text class="reward-value">{{ rewardValue(reward) }}</text>
      </view>

      <view class="reward-section">
        <view class="section-heading"><text>记录信息</text></view>
        <view class="detail-row"><text>关联项目</text><strong>{{ reward.projectName || "未关联项目" }}</strong></view>
        <view class="detail-row"><text>获得人员</text><strong>{{ reward.providerName || "-" }}</strong></view>
        <view class="detail-row"><text>所在地区</text><strong>{{ reward.providerCity || reward.projectProvince || "-" }}</strong></view>
        <view class="detail-row"><text>创建时间</text><strong>{{ dateTime(reward.createdAt) }}</strong></view>
        <view class="detail-row"><text>发放时间</text><strong>{{ dateTime(reward.issuedAt) }}</strong></view>
      </view>

      <view v-if="reward.description || reward.transitionNote" class="reward-section">
        <view class="section-heading"><text>奖励说明</text></view>
        <view v-if="reward.description" class="copy-block"><text class="copy-label">奖励原因</text><text class="copy-value">{{ reward.description }}</text></view>
        <view v-if="reward.transitionNote" class="copy-block"><text class="copy-label">发放备注</text><text class="copy-value">{{ reward.transitionNote }}</text></view>
      </view>
    </template>
  </view>
</template>

<style scoped>
.reward-page { min-height: 100vh; padding: 28rpx 32rpx calc(40rpx + env(safe-area-inset-bottom)); }
.reward-head { display: grid; grid-template-columns: 82rpx minmax(0, 1fr) auto; align-items: start; gap: 20rpx; border: 1rpx solid #dfe3e8; background: #fff; padding: 30rpx 28rpx; }
.reward-mark { display: grid; width: 82rpx; height: 82rpx; place-items: center; border-radius: 12rpx; background: #fff5d9; color: #936c12; font-size: 30rpx; font-weight: 800; }
.reward-heading { min-width: 0; }
.reward-type, .reward-title, .reward-code { display: block; }
.reward-type { color: #8a6a21; font-size: 19rpx; font-weight: 700; }
.reward-title { overflow-wrap: anywhere; margin-top: 5rpx; color: #182230; font-size: 31rpx; font-weight: 800; line-height: 42rpx; }
.reward-code { margin-top: 7rpx; color: #8a96a7; font-size: 19rpx; }
.status-chip { min-height: 42rpx; border: 1rpx solid #d3dbe6; border-radius: 8rpx; background: #f6f8fa; padding: 4rpx 12rpx; color: #526174; font-size: 19rpx; font-weight: 700; }
.status-chip.is-issued { border-color: #b7decf; background: #eef9f4; color: #087550; }
.reward-section { border: 1rpx solid #dfe3e8; background: #fff; margin-top: 22rpx; padding: 28rpx; }
.reward-value-card { border-left: 6rpx solid #c39a39; }
.section-label { display: block; color: #7b8798; font-size: 20rpx; }
.reward-value { display: block; overflow-wrap: anywhere; margin-top: 9rpx; color: #6f5317; font-size: 34rpx; font-weight: 800; line-height: 46rpx; }
.section-heading { border-bottom: 1rpx solid #edf0f2; padding-bottom: 18rpx; color: #182230; font-size: 27rpx; font-weight: 800; }
.detail-row { display: grid; min-height: 82rpx; grid-template-columns: 150rpx minmax(0, 1fr); align-items: start; gap: 22rpx; border-bottom: 1rpx solid #edf0f2; padding: 22rpx 0; }
.detail-row:last-child { border-bottom: 0; padding-bottom: 0; }
.detail-row > text { color: #7b8798; font-size: 21rpx; line-height: 32rpx; }
.detail-row strong { overflow-wrap: anywhere; color: #344054; font-size: 23rpx; line-height: 34rpx; text-align: right; }
.copy-block { padding-top: 22rpx; }
.copy-block + .copy-block { border-top: 1rpx solid #edf0f2; margin-top: 22rpx; }
.copy-label, .copy-value { display: block; }
.copy-label { color: #7b8798; font-size: 20rpx; font-weight: 700; }
.copy-value { overflow-wrap: anywhere; margin-top: 9rpx; color: #344054; font-size: 23rpx; line-height: 38rpx; white-space: pre-wrap; }
@media (max-width: 360px) {
  .reward-head { grid-template-columns: 70rpx minmax(0, 1fr); }
  .reward-mark { width: 70rpx; height: 70rpx; }
  .status-chip { grid-column: 2; justify-self: start; }
}
</style>
