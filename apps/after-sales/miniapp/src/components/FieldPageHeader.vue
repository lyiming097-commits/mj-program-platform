<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{
  profile?: {
    readonly name?: string;
    readonly certificationStatusLabel?: string;
  } | null;
}>();

const displayName = computed(() => props.profile?.name || "当前服务人员");
const initials = computed(() => displayName.value.slice(0, 1));
</script>

<template>
  <view class="field-head">
    <view class="field-avatar">{{ initials }}</view>
    <view class="field-identity"><text class="field-workspace">现场服务工作台</text><text class="field-person">{{ displayName }}</text></view>
  </view>
</template>

<style scoped>
.field-head { position: sticky; top: 0; z-index: 20; display: grid; min-height: 116rpx; grid-template-columns: 72rpx minmax(0, 1fr); align-items: center; gap: 20rpx; border-bottom: 1rpx solid #dfe3e8; background: rgba(255, 255, 255, .98); padding: 18rpx 24rpx; }
.field-avatar { display: grid; width: 72rpx; height: 72rpx; place-items: center; border-radius: 14rpx; background: #155eef; color: #fff; font-size: 27rpx; font-weight: 700; }
.field-identity { min-width: 0; }
.field-workspace, .field-person { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.field-workspace { color: #7c8797; font-size: 20rpx; }
.field-person { margin-top: 2rpx; color: #182230; font-size: 25rpx; font-weight: 700; }
</style>
