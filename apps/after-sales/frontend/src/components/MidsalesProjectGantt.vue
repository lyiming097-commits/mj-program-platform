<script setup>
import { computed } from "vue";

const props = defineProps({
  project: { type: Object, required: true },
  compact: { type: Boolean, default: false },
});

const emit = defineEmits(["open"]);

const TRACKS = [
  ["construction-work", "工程施工"],
  ["furniture-install", "家具安装"],
  ["device-install", "设备安装"],
  ["device-debug", "设备调试"],
  ["school-support", "开学保障"],
  ["project-acceptance", "项目验收"],
];
const DAY = 24 * 60 * 60 * 1000;

function parseDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function nodeKey(node) {
  return String(node?.nodeKey || node?.node_key || node?.key || node?.nodeId || node?.id || "");
}

function isCompleted(node) {
  return Boolean(node?.done || ["completed", "closed", "已完成"].includes(node?.status));
}

const nodesByKey = computed(() => new Map(
  (props.project?.nodes || props.project?.nodeSummary || []).map((node) => [nodeKey(node), node]),
));

const baseRange = computed(() => {
  const projectStart = parseDate(props.project?.plannedStartDate || props.project?.planned_start_date);
  const projectEnd = parseDate(props.project?.plannedEndDate || props.project?.planned_end_date);
  const nodeDates = [...nodesByKey.value.values()].filter((node) => node.enabled !== false).flatMap((node) => [
    parseDate(node.plannedStartAt || node.planned_start_at),
    parseDate(node.plannedEndAt || node.planned_end_at),
  ].filter(Boolean));
  const start = projectStart || nodeDates.reduce((min, date) => (!min || date < min ? date : min), null) || new Date();
  const end = projectEnd || nodeDates.reduce((max, date) => (!max || date > max ? date : max), null) || new Date(start.getTime() + (TRACKS.length * DAY));
  return end > start ? { start, end } : { start, end: new Date(start.getTime() + (TRACKS.length * DAY)) };
});

const rows = computed(() => TRACKS.map(([key, label], index) => {
  const node = nodesByKey.value.get(key) || {};
  const plannedStart = parseDate(node.plannedStartAt || node.planned_start_at)
    || new Date(baseRange.value.start.getTime() + ((baseRange.value.end - baseRange.value.start) * index / TRACKS.length));
  const plannedEnd = parseDate(node.plannedEndAt || node.planned_end_at)
    || new Date(baseRange.value.start.getTime() + ((baseRange.value.end - baseRange.value.start) * (index + 1) / TRACKS.length));
  const completed = isCompleted(node);
  const current = nodeKey(node) === String(props.project?.currentNodeKey || props.project?.current_node_key || "")
    && ["active", "进行中"].includes(node?.status);
  const actualStart = parseDate(node.actualStartAt || node.actual_start_at) || (completed || current ? plannedStart : null);
  const actualEnd = parseDate(node.actualEndAt || node.actual_end_at) || (completed ? plannedEnd : current ? new Date() : null);
  const lateEnd = actualEnd || (current ? new Date() : null);
  const late = (completed || current) && lateEnd && lateEnd > plannedEnd;
  const state = completed ? (late ? "超时" : "完成") : late ? "超时" : current ? "进行" : "未开";
  return { key, label, node, plannedStart, plannedEnd, actualStart, actualEnd, lateEnd, late, completed, current, state };
}).filter((row) => row.node.enabled !== false));

const chartBounds = computed(() => {
  const today = new Date();
  const dates = rows.value.flatMap((row) => [row.plannedStart, row.plannedEnd, row.actualStart, row.actualEnd, row.lateEnd].filter(Boolean));
  dates.push(today);
  const start = dates.reduce((min, date) => (!min || date < min ? date : min), null) || today;
  const end = dates.reduce((max, date) => (!max || date > max ? date : max), null) || new Date(today.getTime() + DAY);
  return { start, end: end > start ? end : new Date(start.getTime() + DAY), today };
});

function percent(value) {
  const { start, end } = chartBounds.value;
  return Math.max(0, Math.min(100, ((value - start) / (end - start)) * 100));
}

function bar(start, end) {
  if (!start || !end || end <= start) return null;
  return { left: percent(start), width: Math.max(0.8, percent(end) - percent(start)) };
}

const rowsWithBars = computed(() => rows.value.map((row) => ({
  ...row,
  planBar: bar(row.plannedStart, row.plannedEnd),
  actualBar: bar(row.actualStart, row.actualEnd),
  lateBar: row.late ? bar(row.plannedEnd, row.lateEnd) : null,
})));

const todayLeft = computed(() => percent(chartBounds.value.today));
const todayLabel = computed(() => `${chartBounds.value.today.getMonth() + 1}/${chartBounds.value.today.getDate()}`);
</script>

<template>
  <div
    v-if="compact"
    class="as-midsales-gantt as-midsales-gantt--compact"
    role="button"
    tabindex="0"
    aria-label="打开节点进度图"
    @click.stop="emit('open')"
    @keydown.enter.stop="emit('open')"
    @keydown.space.prevent.stop="emit('open')"
  >
    <span v-if="rowsWithBars.length" class="as-midsales-gantt__compact-bars" aria-hidden="true">
      <span v-for="row in rowsWithBars" :key="row.key" class="as-midsales-gantt__compact-track" :class="{ 'is-done': row.completed, 'is-late': row.late }">
        <i v-if="row.planBar" class="as-midsales-gantt__bar is-plan" :style="{ left: row.planBar.left + '%', width: row.planBar.width + '%' }"></i>
        <i v-if="row.actualBar" class="as-midsales-gantt__bar is-actual" :style="{ left: row.actualBar.left + '%', width: row.actualBar.width + '%' }"></i>
        <i v-if="row.lateBar" class="as-midsales-gantt__bar is-late" :style="{ left: row.lateBar.left + '%', width: row.lateBar.width + '%' }"></i>
      </span>
    </span>
    <span class="as-midsales-gantt__compact-label">查看进度</span>
  </div>
  <div v-else class="as-midsales-gantt" aria-label="节点进度甘特图">
    <div class="as-midsales-gantt__head">
      <strong>节点进度</strong>
      <span class="as-midsales-gantt__legend"><span><i class="is-plan"></i>计划</span><span><i class="is-actual"></i>实际</span><span><i class="is-late"></i>超时</span></span>
    </div>
    <div v-if="rowsWithBars.length" class="as-midsales-gantt__chart" :style="{ '--today-left': `${todayLeft}%` }">
      <div class="as-midsales-gantt__timeline">
        <div class="as-midsales-gantt__today"><span>今日 {{ todayLabel }}</span></div>
      </div>
      <div v-for="row in rowsWithBars" :key="row.key" class="as-midsales-gantt__row" :class="{ 'is-late': row.late, 'is-done': row.completed }">
        <span class="as-midsales-gantt__name" :title="row.label">{{ row.label }}</span>
        <span class="as-midsales-gantt__track"><i v-if="row.planBar" class="as-midsales-gantt__bar is-plan" :style="{ left: `${row.planBar.left}%`, width: `${row.planBar.width}%` }"></i><i v-if="row.actualBar" class="as-midsales-gantt__bar is-actual" :style="{ left: `${row.actualBar.left}%`, width: `${row.actualBar.width}%` }"></i><i v-if="row.lateBar" class="as-midsales-gantt__bar is-late" :style="{ left: `${row.lateBar.left}%`, width: `${row.lateBar.width}%` }"></i></span>
        <span class="as-midsales-gantt__state">{{ row.state }}</span>
      </div>
    </div>
    <p v-else class="as-muted">本项目未包含进度节点</p>
  </div>
</template>
