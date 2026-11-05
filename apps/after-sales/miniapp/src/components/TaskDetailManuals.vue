<script setup lang="ts">
import type { ProductManual } from "@/api/types";

defineProps<{
  manuals: readonly ProductManual[];
  openingManual: string;
}>();
const emit = defineEmits<{ open: [manual: ProductManual] }>();
</script>

<template>
  <view class="manual-list">
    <view
      v-for="(manual, index) in manuals"
      :key="manual.id"
      class="manual-row"
      :class="{ 'is-last': index === manuals.length - 1 }"
      role="button"
      :aria-label="`打开${manual.title}`"
      hover-class="manual-row--pressed"
      @tap.stop="emit('open', manual)"
    >
      <view class="manual-icon"><image class="manual-icon-image" src="/static/tabbar/tasks-active.png" mode="aspectFit" /></view>
      <view class="manual-copy"><text class="manual-title">{{ manual.title }}</text><text class="manual-type">{{ manual.resourceTypeLabel || "产品说明书" }}</text></view>
      <text class="manual-action">{{ openingManual === manual.id ? "打开中" : "查看" }}</text>
    </view>
  </view>
</template>

<style scoped>
.manual-list { border-top: 1rpx solid #e4e7ec; }
.manual-row { display: grid; min-height: 148rpx; grid-template-columns: 76rpx minmax(0, 1fr) auto; align-items: center; gap: 20rpx; border-bottom: 1rpx solid #edf0f2; background: #fff; padding: 20rpx 8rpx; }
.manual-row.is-last { border-bottom: 0; }
.manual-row--pressed { background: #f8fbff; }
.manual-icon { display: grid; width: 76rpx; height: 76rpx; place-items: center; border-radius: 14rpx; background: #edf3fb; }
.manual-icon-image { width: 36rpx; height: 36rpx; }
.manual-copy { min-width: 0; }
.manual-title, .manual-type { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.manual-title { color: #283548; font-size: 23rpx; font-weight: 700; }
.manual-type { margin-top: 6rpx; color: #667085; font-size: 19rpx; }
.manual-action { color: #155eef; font-size: 22rpx; font-weight: 700; }
</style>
