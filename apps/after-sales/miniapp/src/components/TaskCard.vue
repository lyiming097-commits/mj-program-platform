<script setup lang="ts">
import { computed } from "vue";
import type { MobileTask } from "@/api/types";
import { taskTiming } from "@/composables/useMobileTasks";

const props = defineProps<{ task: MobileTask }>();
const emit = defineEmits<{ open: [id: number] }>();
const timing = computed(() => taskTiming(props.task));

function dateLabel(value: unknown): string {
  const match = String(value || "").match(/^\d{4}-\d{2}-\d{2}/);
  return match?.[0] || "";
}

const planLabel = computed(() => {
  const start = dateLabel(props.task.node.plannedStartAt || props.task.assignment.plannedStartDate);
  const end = dateLabel(props.task.node.plannedEndAt);
  return [start, end].filter(Boolean).join(" 至 ") || "未设置计划时间";
});
</script>

<template>
  <view class="task-card" role="button" hover-class="task-card--pressed" @tap.stop="emit('open', task.id)">
    <view class="task-card-top">
      <text class="task-state" :class="`is-${timing.group}`">{{ timing.label }}</text>
      <view class="task-countdown" :class="{ overdue: timing.label === '已超时' }"><view class="clock-icon" />{{ timing.detail }}</view>
    </view>
    <text class="task-title">{{ task.projectName }}</text>
    <text class="task-subtitle">{{ task.serviceTypeLabel }} · {{ task.nodeName }}</text>
    <view class="task-plan"><view class="calendar-icon" />{{ planLabel }}</view>
    <view class="task-arrow" />
  </view>
</template>

<style scoped>
.task-card { position: relative; display: block; width: 100%; min-height: 260rpx; border: 1rpx solid #dfe3e8; border-radius: 16rpx; background: #fff; padding: 24rpx 50rpx 24rpx 24rpx; color: #344054; }
.task-card--pressed { border-color: #8dafeb; background: #f8fbff; }
.task-card-top { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 12rpx; }
.task-state { display: inline-flex; min-height: 46rpx; align-items: center; border: 1rpx solid #c9d9f7; border-radius: 10rpx; background: #f2f6fd; padding: 4rpx 14rpx; color: #315f9f; font-size: 20rpx; font-weight: 700; white-space: nowrap; }
.task-state.is-completed { border-color: #b7decf; background: #eef9f4; color: #087550; }
.task-countdown { display: flex; min-width: 0; flex: 1 1 auto; align-items: center; justify-content: flex-end; gap: 8rpx; color: #3a5f8d; font-size: 20rpx; font-weight: 700; text-align: right; white-space: nowrap; }
.task-countdown.overdue { color: #bd2938; }
.clock-icon { position: relative; width: 22rpx; height: 22rpx; flex: 0 0 auto; border: 2rpx solid currentColor; border-radius: 50%; }
.clock-icon::before { position: absolute; top: 4rpx; left: 9rpx; width: 2rpx; height: 6rpx; background: currentColor; content: ""; }
.clock-icon::after { position: absolute; top: 9rpx; left: 9rpx; width: 5rpx; height: 2rpx; background: currentColor; content: ""; }
.task-title, .task-subtitle { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-title { margin-top: 22rpx; color: #182230; font-size: 29rpx; font-weight: 700; line-height: 40rpx; }
.task-subtitle { margin-top: 6rpx; color: #667085; font-size: 22rpx; line-height: 34rpx; }
.task-plan { display: flex; min-width: 0; align-items: center; gap: 12rpx; overflow: hidden; margin-top: 24rpx; color: #5f6d80; font-size: 21rpx; text-overflow: ellipsis; white-space: nowrap; }
.calendar-icon { position: relative; width: 24rpx; height: 22rpx; flex: 0 0 auto; border: 2rpx solid #7d8da2; border-radius: 3rpx; }
.calendar-icon::before { position: absolute; top: 5rpx; right: 0; left: 0; border-top: 2rpx solid #7d8da2; content: ""; }
.task-arrow { position: absolute; top: 50%; right: 18rpx; width: 15rpx; height: 15rpx; border-top: 3rpx solid #98a2b3; border-right: 3rpx solid #98a2b3; transform: translateY(-50%) rotate(45deg); }
</style>
