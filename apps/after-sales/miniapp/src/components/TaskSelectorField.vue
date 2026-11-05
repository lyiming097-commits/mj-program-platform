<script setup lang="ts">
import { computed, getCurrentInstance, onBeforeUnmount, shallowRef, watch } from "vue";
import type { MobileTask } from "@/api/types";
import { createBackdropTapHandlers } from "@/composables/backdropTap";
import { taskTiming, type TaskGroup } from "@/composables/useMobileTasks";

type TaskFilter = "all" | "active" | "completed";

const props = withDefaults(defineProps<{
  tasks: readonly MobileTask[];
  modelValue: number;
  disabled?: boolean;
}>(), {
  disabled: false,
});

const emit = defineEmits<{
  "update:modelValue": [taskId: number];
  "open-change": [open: boolean];
}>();
const open = shallowRef(false);
const query = shallowRef("");
const filter = shallowRef<TaskFilter>("all");
const pageInstance = getCurrentInstance();

const selectedTask = computed(() => props.tasks.find((task) => task.id === props.modelValue) || null);
const taskRows = computed(() => props.tasks.map((task) => ({
  task,
  timing: taskTiming(task),
})).sort((left, right) => {
  const rank: Record<TaskGroup, number> = { active: 0, completed: 1, pending: 2 };
  const groupDifference = rank[left.timing.group] - rank[right.timing.group];
  if (groupDifference) return groupDifference;
  const leftTime = Date.parse(String(left.task.assignment.updatedAt || left.task.node.updatedAt || "")) || 0;
  const rightTime = Date.parse(String(right.task.assignment.updatedAt || right.task.node.updatedAt || "")) || 0;
  return rightTime - leftTime;
}));
const counts = computed(() => ({
  all: taskRows.value.length,
  active: taskRows.value.filter((row) => row.timing.group === "active").length,
  completed: taskRows.value.filter((row) => row.timing.group === "completed").length,
}));
const filteredRows = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase();
  return taskRows.value.filter((row) => {
    if (filter.value !== "all" && row.timing.group !== filter.value) return false;
    if (!keyword) return true;
    return [
      row.task.projectName,
      row.task.project.customer,
      row.task.nodeName,
      row.task.serviceTypeLabel,
    ].some((value) => String(value || "").toLocaleLowerCase().includes(keyword));
  });
});
const filterOptions: ReadonlyArray<{ value: TaskFilter; label: string }> = [
  { value: "all", label: "全部" },
  { value: "active", label: "进行中" },
  { value: "completed", label: "已完成" },
];

const backdrop = createBackdropTapHandlers("task-selector-mask", (point) => new Promise<boolean>((resolve) => {
  const selector = uni.createSelectorQuery();
  if (pageInstance?.proxy) selector.in(pageInstance.proxy);
  selector.select("#task-selector-mask").boundingClientRect();
  selector.select(".task-selector-sheet").boundingClientRect();
  selector.exec((rects) => {
    const [mask, panel] = rects;
    const inside = (rect: UniApp.NodeInfo) => point.clientX >= Number(rect.left) && point.clientX <= Number(rect.right)
      && point.clientY >= Number(rect.top) && point.clientY <= Number(rect.bottom);
    resolve(Boolean(mask && panel && inside(mask) && !inside(panel)));
  });
}), closeSelector);

function openSelector(): void {
  if (props.disabled || !props.tasks.length) return;
  backdrop.reset();
  query.value = "";
  filter.value = "all";
  open.value = true;
  emit("open-change", true);
}

function closeSelector(): void {
  backdrop.reset();
  if (!open.value) return;
  open.value = false;
  emit("open-change", false);
}

function chooseTask(taskId: number): void {
  emit("update:modelValue", taskId);
  closeSelector();
}

watch(() => props.disabled, (disabled) => {
  if (disabled) closeSelector();
});
onBeforeUnmount(backdrop.reset);
</script>

<template>
  <view
    class="task-selector-trigger"
    :class="{ disabled }"
    role="button"
    aria-haspopup="dialog"
    :aria-expanded="open"
    :aria-label="selectedTask ? `已选择任务：${selectedTask.projectName}，${selectedTask.nodeName}` : '选择关联任务'"
    hover-class="task-selector-trigger--pressed"
    @tap.stop="openSelector"
  >
    <view v-if="selectedTask" class="task-selector-value">
      <text class="task-selector-status" :class="`is-${taskTiming(selectedTask).group}`">{{ taskTiming(selectedTask).label }}</text>
      <view class="task-selector-copy">
        <text class="task-selector-project">{{ selectedTask.projectName }}</text>
        <text class="task-selector-node">{{ selectedTask.nodeName }} · {{ selectedTask.serviceTypeLabel }}</text>
      </view>
    </view>
    <text v-else class="task-selector-placeholder">{{ modelValue && tasks.length ? "所选任务已不可用，请重新选择" : "暂无进行中或已完成任务" }}</text>
    <view class="task-selector-chevron" />
  </view>

  <view
    v-if="open"
    id="task-selector-mask"
    class="task-selector-mask"
    @touchstart="backdrop.touchstart"
    @touchmove.stop.prevent="backdrop.reset"
    @touchend="backdrop.touchend"
    @touchcancel="backdrop.reset"
    @tap="backdrop.tap"
  >
    <view class="task-selector-sheet" role="dialog" aria-modal="true" aria-label="选择关联任务">
      <view class="task-selector-head">
        <view><text class="task-selector-eyebrow">关联服务任务</text><text class="task-selector-title">选择项目与节点</text></view>
        <button class="task-selector-close" aria-label="关闭任务选择" hover-class="task-selector-control--pressed" @tap.stop="closeSelector">×</button>
      </view>

      <view class="task-selector-search">
        <view class="task-selector-search-icon" />
        <input v-model="query" aria-label="搜索项目或节点" placeholder="搜索项目、客户或节点" confirm-type="search" />
        <button v-if="query" class="task-selector-clear" aria-label="清空搜索" hover-class="task-selector-control--pressed" @tap.stop="query = ''">×</button>
      </view>

      <view class="task-selector-filters" role="tablist" aria-label="任务状态筛选">
        <button
          v-for="option in filterOptions"
          :key="option.value"
          class="task-selector-filter"
          :class="{ active: filter === option.value }"
          role="tab"
          :aria-selected="filter === option.value"
          hover-class="task-selector-control--pressed"
          @tap.stop="filter = option.value"
        >{{ option.label }} {{ counts[option.value] }}</button>
      </view>

      <text class="task-selector-summary">{{ filteredRows.length }} 个可选任务</text>
      <scroll-view class="task-selector-list" scroll-y enhanced :bounces="false">
        <button
          v-for="row in filteredRows"
          :key="row.task.id"
          class="task-selector-row"
          :class="{ selected: row.task.id === modelValue }"
          :aria-label="`${row.timing.label}，${row.task.projectName}，${row.task.nodeName}`"
          :aria-selected="row.task.id === modelValue"
          hover-class="task-selector-row--pressed"
          @tap.stop="chooseTask(row.task.id)"
        >
          <text class="task-selector-row-status" :class="`is-${row.timing.group}`">{{ row.timing.label }}</text>
          <view class="task-selector-row-copy">
            <text class="task-selector-row-project">{{ row.task.projectName }}</text>
            <text class="task-selector-row-node">{{ row.task.nodeName }} · {{ row.task.serviceTypeLabel }}</text>
            <text v-if="row.task.project.customer" class="task-selector-row-customer">客户：{{ row.task.project.customer }}</text>
          </view>
          <text v-if="row.task.id === modelValue" class="task-selector-check">✓</text>
          <view v-else class="task-selector-row-arrow" />
        </button>
        <view v-if="!filteredRows.length" class="task-selector-empty">
          <text class="task-selector-empty-title">没有匹配的任务</text>
          <text class="task-selector-empty-copy">请调整搜索内容或任务状态</text>
          <button v-if="query || filter !== 'all'" hover-class="task-selector-control--pressed" @tap.stop="query = ''; filter = 'all'">清除筛选</button>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<style scoped>
.task-selector-trigger { display: grid; min-height: 92rpx; grid-template-columns: minmax(0, 1fr) 24rpx; align-items: center; gap: 16rpx; overflow: hidden; border: 1rpx solid #d5dee9; border-radius: 12rpx; background: #fff; padding: 14rpx 20rpx; box-shadow: inset 0 1rpx 0 rgba(255, 255, 255, .9); }
.task-selector-trigger--pressed { border-color: #9bb8ed; background: #f7faff; }
.task-selector-trigger.disabled { background: #f4f6f8; color: #7b8798; }
.task-selector-value { display: flex; min-width: 0; align-items: center; gap: 14rpx; }
.task-selector-status, .task-selector-row-status { display: inline-flex; min-height: 40rpx; flex: 0 0 auto; align-items: center; border: 1rpx solid #bfd2f7; border-radius: 9rpx; background: #edf4ff; padding: 3rpx 10rpx; color: #155eef; font-size: 18rpx; font-weight: 750; line-height: 28rpx; }
.task-selector-status.is-completed, .task-selector-row-status.is-completed { border-color: #b7decf; background: #eef9f4; color: #087550; }
.task-selector-copy, .task-selector-row-copy { min-width: 0; }
.task-selector-project, .task-selector-node, .task-selector-placeholder, .task-selector-row-project, .task-selector-row-node, .task-selector-row-customer { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-selector-project { color: #27364a; font-size: 23rpx; font-weight: 750; line-height: 32rpx; }
.task-selector-node { margin-top: 3rpx; color: #7b8798; font-size: 19rpx; line-height: 28rpx; }
.task-selector-placeholder { color: #8a96a7; font-size: 23rpx; }
.task-selector-chevron, .task-selector-row-arrow { width: 14rpx; height: 14rpx; border-top: 3rpx solid #8a98aa; border-right: 3rpx solid #8a98aa; transform: rotate(45deg); }

.task-selector-mask { position: fixed; inset: 0; z-index: 1100; display: flex; align-items: flex-end; background: rgba(16, 24, 40, .52); }
.task-selector-sheet { display: flex; width: 100%; max-height: 84vh; max-height: 84dvh; flex-direction: column; overflow: hidden; border-radius: 20rpx 20rpx 0 0; background: #fff; padding-bottom: env(safe-area-inset-bottom); box-shadow: 0 -20rpx 60rpx rgba(16, 24, 40, .2); }
.task-selector-head { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; gap: 24rpx; border-bottom: 1rpx solid #e4e7ec; padding: 26rpx 28rpx 22rpx; }
.task-selector-eyebrow, .task-selector-title { display: block; }
.task-selector-eyebrow { color: #3e5d86; font-size: 19rpx; font-weight: 800; line-height: 28rpx; }
.task-selector-title { margin-top: 3rpx; color: #182230; font-size: 30rpx; font-weight: 800; line-height: 40rpx; }
.task-selector-close, .task-selector-clear { display: grid; place-items: center; margin: 0; border: 0; background: transparent; color: #526174; }
.task-selector-close { width: 64rpx; height: 64rpx; flex: 0 0 auto; border: 1rpx solid #d5dbe4; border-radius: 11rpx; background: #f8fafc; font-size: 40rpx; font-weight: 400; line-height: 60rpx; }
.task-selector-close::after, .task-selector-clear::after, .task-selector-filter::after, .task-selector-row::after, .task-selector-empty button::after { border: 0; }
.task-selector-search { display: grid; min-height: 76rpx; grid-template-columns: 34rpx minmax(0, 1fr) 52rpx; align-items: center; gap: 10rpx; margin: 24rpx 28rpx 0; border: 1rpx solid #cfd9e5; border-radius: 12rpx; background: #f8fafc; padding: 0 10rpx 0 20rpx; }
.task-selector-search:focus-within { border-color: #7aa7ef; background: #fff; box-shadow: 0 0 0 4rpx rgba(21, 94, 239, .1); }
.task-selector-search-icon { position: relative; width: 24rpx; height: 24rpx; border: 3rpx solid #7b8798; border-radius: 50%; }
.task-selector-search-icon::after { position: absolute; right: -9rpx; bottom: -6rpx; width: 11rpx; border-top: 3rpx solid #7b8798; content: ""; transform: rotate(45deg); }
.task-selector-search input { height: 72rpx; color: #27364a; font-size: 23rpx; }
.task-selector-clear { width: 52rpx; height: 52rpx; border-radius: 9rpx; background: #e9eef5; font-size: 30rpx; line-height: 50rpx; }
.task-selector-filters { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8rpx; margin: 18rpx 28rpx 0; border: 1rpx solid #dce3eb; border-radius: 12rpx; background: #f1f4f7; padding: 6rpx; }
.task-selector-filter { min-width: 0; min-height: 60rpx; margin: 0; border: 0; border-radius: 9rpx; background: transparent; padding: 0 8rpx; color: #5b687a; font-size: 20rpx; font-weight: 700; line-height: 60rpx; white-space: nowrap; }
.task-selector-filter.active { background: #fff; color: #155eef; box-shadow: 0 2rpx 6rpx rgba(16, 24, 40, .12); }
.task-selector-control--pressed { opacity: .68; }
.task-selector-summary { display: block; margin: 18rpx 30rpx 10rpx; color: #7b8798; font-size: 19rpx; line-height: 28rpx; }
.task-selector-list { min-height: 320rpx; flex: 1 1 auto; }
.task-selector-row { display: grid; width: auto; min-height: 132rpx; grid-template-columns: auto minmax(0, 1fr) 30rpx; align-items: center; gap: 16rpx; margin: 0 28rpx; border: 0; border-bottom: 1rpx solid #e8ecf1; border-radius: 0; background: #fff; padding: 18rpx 4rpx; color: #27364a; line-height: normal; text-align: left; }
.task-selector-row.selected { background: #f7faff; }
.task-selector-row--pressed { background: #edf4ff; }
.task-selector-row-project { color: #27364a; font-size: 23rpx; font-weight: 750; line-height: 33rpx; }
.task-selector-row-node { margin-top: 4rpx; color: #526174; font-size: 20rpx; line-height: 29rpx; }
.task-selector-row-customer { margin-top: 3rpx; color: #8a96a7; font-size: 18rpx; line-height: 27rpx; }
.task-selector-check { color: #155eef; font-size: 28rpx; font-weight: 800; text-align: center; }
.task-selector-row-arrow { justify-self: center; }
.task-selector-empty { display: flex; min-height: 320rpx; flex-direction: column; align-items: center; justify-content: center; padding: 40rpx; text-align: center; }
.task-selector-empty-title, .task-selector-empty-copy { display: block; }
.task-selector-empty-title { color: #526174; font-size: 24rpx; font-weight: 750; }
.task-selector-empty-copy { margin-top: 8rpx; color: #98a2b3; font-size: 20rpx; }
.task-selector-empty button { min-height: 60rpx; margin: 22rpx 0 0; border: 1rpx solid #bfd2f7; border-radius: 10rpx; background: #f2f6fd; padding: 0 24rpx; color: #155eef; font-size: 21rpx; font-weight: 700; line-height: 58rpx; }

@media (max-width: 360px) {
  .task-selector-sheet { max-height: 88vh; max-height: 88dvh; }
  .task-selector-head { padding-right: 22rpx; padding-left: 22rpx; }
  .task-selector-search, .task-selector-filters { margin-right: 22rpx; margin-left: 22rpx; }
  .task-selector-row { margin-right: 22rpx; margin-left: 22rpx; }
}
</style>
