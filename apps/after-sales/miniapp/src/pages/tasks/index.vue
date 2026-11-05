<script setup lang="ts">
import { onHide, onShow, onUnload } from "@dcloudio/uni-app";
import { computed, shallowRef } from "vue";
import { ApiError, readStoredSession } from "@/api/client";
import FieldPageHeader from "@/components/FieldPageHeader.vue";
import TaskCard from "@/components/TaskCard.vue";
import { taskTiming, useMobileTasks, type TaskGroup } from "@/composables/useMobileTasks";

type ServiceTypeFilter = "all" | "midsales" | "aftersales";

const { workspace, tasks, loading, error, loadMobileTasks } = useMobileTasks();
const serviceType = shallowRef<ServiceTypeFilter>("all");
const taskGroup = shallowRef<TaskGroup>("pending");
let syncTimer: ReturnType<typeof setInterval> | null = null;

const serviceOptions: ReadonlyArray<{ value: ServiceTypeFilter; label: string }> = [
  { value: "all", label: "全部" },
  { value: "midsales", label: "售中" },
  { value: "aftersales", label: "售后" },
];
const groupOptions: ReadonlyArray<{ value: TaskGroup; label: string }> = [
  { value: "pending", label: "待进行" },
  { value: "active", label: "进行中" },
  { value: "completed", label: "已完成" },
];

const serviceTypeTasks = computed(() => (
  serviceType.value === "all"
    ? tasks.value
    : tasks.value.filter((task) => task.serviceType === serviceType.value)
));
const taskGroupCounts = computed<Record<TaskGroup, number>>(() => {
  const counts: Record<TaskGroup, number> = { pending: 0, active: 0, completed: 0 };
  serviceTypeTasks.value.forEach((task) => {
    counts[taskTiming(task).group] += 1;
  });
  return counts;
});
const visibleTasks = computed(() => serviceTypeTasks.value.filter((task) => (
  taskTiming(task).group === taskGroup.value
)));

function setServiceType(value: ServiceTypeFilter): void {
  serviceType.value = value;
}

function setTaskGroup(value: TaskGroup): void {
  taskGroup.value = value;
}

function openTask(id: number): void {
  uni.navigateTo({ url: `/pages/task-detail/index?id=${id}` });
}

function requireLogin(): void {
  uni.reLaunch({ url: "/pages/login/index" });
}

async function load(force = false, silent = false): Promise<void> {
  if (!readStoredSession()) {
    requireLogin();
    return;
  }
  try {
    await loadMobileTasks({ force, silent });
  } catch (reason) {
    if (reason instanceof ApiError && reason.status === 401) requireLogin();
    else if (reason instanceof ApiError && ["SERVICE_PROVIDER_REQUIRED", "SERVICE_PROVIDER_NOT_CERTIFIED"].includes(reason.code)) {
      uni.reLaunch({ url: "/pages/pending/index" });
    }
  }
}

function stopSync(): void {
  if (syncTimer) clearInterval(syncTimer);
  syncTimer = null;
}

onShow(() => {
  void load(true);
  stopSync();
  syncTimer = setInterval(() => { void load(true, true); }, 5000);
});
onHide(stopSync);
onUnload(stopSync);
</script>

<template>
  <view class="page-shell task-page">
    <FieldPageHeader :profile="workspace?.profile" />
    <view class="page-content field-main">
      <view class="field-summary">
        <text class="eyebrow">我的现场任务</text>
        <text class="summary-title">{{ visibleTasks.length }} 项服务任务</text>
      <text class="summary-copy">只展示已分派给当前账号的售中和售后节点。</text>
      </view>

      <view class="task-filters">
        <view class="task-service-tabs" role="tablist" aria-label="服务类型筛选">
          <view
            v-for="option in serviceOptions"
            :key="option.value"
            class="task-service-tab"
            :class="{ active: serviceType === option.value }"
            role="tab"
            :aria-selected="serviceType === option.value"
            hover-class="task-filter-item--pressed"
            @tap.stop="setServiceType(option.value)"
          >{{ option.label }}</view>
        </view>
        <view class="task-status-tabs" role="tablist" aria-label="任务状态筛选">
          <view
            v-for="option in groupOptions"
            :key="option.value"
            class="task-status-tab"
            :class="{ active: taskGroup === option.value }"
            role="tab"
            :aria-selected="taskGroup === option.value"
            :aria-label="`${option.label}，${taskGroupCounts[option.value]}项`"
            hover-class="task-filter-item--pressed"
            @tap.stop="setTaskGroup(option.value)"
          >
            <text>{{ option.label }}</text>
            <text class="task-status-count">{{ taskGroupCounts[option.value] }}</text>
          </view>
        </view>
      </view>

      <view v-if="error" class="error-banner">{{ error }}</view>
      <view v-if="loading && !tasks.length" class="task-empty">正在同步现场任务...</view>
      <view v-else-if="!visibleTasks.length" class="task-empty">
        <image src="/static/tabbar/tasks.png" mode="aspectFit" />
        <text>当前筛选没有任务</text>
      </view>
      <view v-else class="task-list">
        <TaskCard v-for="task in visibleTasks" :key="task.id" :task="task" @open="openTask" />
      </view>
    </view>
  </view>
</template>

<style scoped>
.field-main { min-width: 0; }
.field-summary { border-bottom: 1rpx solid #dfe3e8; background: #fff; padding: 30rpx 32rpx 32rpx; }
.eyebrow, .summary-title, .summary-copy { display: block; }
.eyebrow { color: #3e5d86; font-size: 21rpx; font-weight: 800; line-height: 32rpx; }
.summary-title { margin-top: 4rpx; color: #111827; font-size: 38rpx; font-weight: 800; line-height: 54rpx; }
.summary-copy { margin-top: 6rpx; color: #667085; font-size: 24rpx; line-height: 40rpx; }
.task-filters { display: grid; grid-template-columns: 236rpx minmax(0, 1fr); align-items: center; gap: 12rpx; margin: 20rpx 0; }
.task-service-tabs, .task-status-tabs { display: flex; min-width: 0; min-height: 72rpx; align-items: center; border: 1rpx solid #cfd5dd; border-radius: 12rpx; background: #f7f8fa; padding: 4rpx; }
.task-service-tab, .task-status-tab { display: flex; min-width: 0; min-height: 64rpx; flex: 1 1 0; align-items: center; justify-content: center; border-radius: 9rpx; color: #5a6577; font-size: 22rpx; font-weight: 700; white-space: nowrap; }
.task-status-tab { gap: 5rpx; }
.task-service-tab.active, .task-status-tab.active { background: #fff; color: #155eef; box-shadow: 0 2rpx 6rpx rgba(16, 24, 40, .13); }
.task-filter-item--pressed { opacity: .72; }
.task-status-count { display: inline-flex; min-width: 28rpx; height: 28rpx; align-items: center; justify-content: center; border-radius: 14rpx; background: #e5e9ef; padding: 0 6rpx; color: #596579; font-size: 17rpx; font-weight: 800; line-height: 28rpx; }
.task-status-tab.active .task-status-count { background: #e8f0ff; color: #155eef; }
.task-list { display: grid; gap: 20rpx; }
.task-empty { display: flex; min-height: 520rpx; flex-direction: column; align-items: center; justify-content: center; gap: 14rpx; padding: 36rpx; color: #8490a2; font-size: 24rpx; text-align: center; }
.task-empty image { width: 56rpx; height: 56rpx; opacity: .52; }
</style>
