<script setup>
import { computed, useId } from "vue";
import { ChevronDown, ChevronRight, Layers3 } from "@lucide/vue";
import { statisticNumber } from "@/presalesStatistics";

const props = defineProps({
  groups: { type: Array, default: () => [] },
  selectedKey: { type: String, default: "" },
  total: { type: Number, default: 0 },
  field: { type: String, default: "项目性质" },
  loading: { type: Boolean, default: false },
  collapsed: { type: Boolean, default: false },
});
const emit = defineEmits(["select", "update:collapsed"]);
const tableId = useId();
const selectedGroup = computed(() => props.groups.find(group => group.key === props.selectedKey));
function percent(count) { return props.total ? (count / props.total * 100).toFixed(1) : "0.0"; }
</script>

<template>
  <section class="as-panel as-stat-groups" aria-label="售前分组统计" :aria-busy="loading">
    <header class="as-panel-head" :class="{ 'is-collapsed': collapsed }">
      <div class="as-stat-group-heading"><h2><Layers3 />分组统计</h2><p :title="selectedGroup?.label">{{ selectedGroup ? `当前分组：${selectedGroup.label}` : collapsed ? '当前分组：全部分组' : '点击分组，查看对应项目明细' }}</p></div>
      <div class="as-stat-group-actions">
        <button type="button" class="as-stat-all" :class="{ active: !selectedKey }" :aria-pressed="!selectedKey" :disabled="loading" @click="emit('select', '')">全部分组</button>
        <button type="button" class="as-stat-all as-stat-toggle" :aria-label="collapsed ? '展开分组统计' : '收起分组统计'" :aria-expanded="!collapsed" :aria-controls="tableId" @click="emit('update:collapsed', !collapsed)">{{ collapsed ? '展开' : '收起' }}<ChevronDown aria-hidden="true" /></button>
      </div>
    </header>
    <div v-show="!collapsed" :id="tableId" class="as-project-table-scroll as-stat-group-scroll" tabindex="0" role="region" aria-label="售前分组表格，可滚动查看">
      <table class="as-project-table as-template-table as-stat-group-table" aria-label="售前分组统计">
        <thead><tr><th scope="col">{{ field }}</th><th scope="col">项目数 / 占比</th><th scope="col">项目金额</th><th scope="col">进行中</th><th scope="col">已完成</th></tr></thead>
        <tbody>
          <tr v-if="!groups.length"><td colspan="5" class="as-stat-empty">{{ loading ? '正在汇总项目...' : '暂无可统计的项目' }}</td></tr>
          <tr v-for="group in groups" :key="group.key" :class="{ selected: selectedKey === group.key }">
            <td><button type="button" class="as-stat-group-name" :disabled="loading" :aria-pressed="selectedKey === group.key" @click="emit('select', group.key)"><span>{{ group.label }}</span><ChevronRight /></button></td>
            <td><div class="as-stat-count"><strong>{{ group.count }}</strong><span>{{ percent(group.count) }}%</span></div><span class="as-stat-bar" aria-hidden="true"><span :style="{ width: `${percent(group.count)}%` }"></span></span></td>
            <td><strong class="as-stat-money">{{ statisticNumber(group.amount, { currency: true }) }}</strong><small v-if="group.knownAmountCount < group.count">{{ group.count - group.knownAmountCount }} 项未填金额</small></td>
            <td>{{ group.activeCount }}</td><td>{{ group.completedCount }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.as-stat-groups { display: flex; min-width: 0; min-height: 0; flex-direction: column; }
.as-stat-group-scroll { max-height: var(--as-stat-group-max-height); }
.as-panel-head { flex-shrink: 0; }
.as-panel-head.is-collapsed { border-bottom: 0; }
.as-stat-group-heading { min-width: 0; }
.as-stat-group-heading p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.as-stat-group-actions { display: flex; flex-shrink: 0; align-items: center; gap: 8px; }
.as-panel-head h2 { display: flex; align-items: center; gap: 7px; }
.as-panel-head h2 svg { width: 16px; height: 16px; color: #64748b; }
.as-stat-all { min-height: 32px; flex-shrink: 0; border: 1px solid #dce4ed; border-radius: 6px; background: #fff; padding: 0 10px; color: #536276; font-size: 12px; }
.as-stat-all.active { border-color: #c6d9fb; background: #edf4ff; color: #245acc; }
.as-stat-toggle { display: inline-flex; align-items: center; gap: 6px; border-color: transparent; background: transparent; color: var(--as-muted); }
.as-stat-toggle:hover { background: var(--as-soft); color: var(--as-primary); }
.as-stat-toggle svg { width: 14px; height: 14px; }
.as-stat-toggle[aria-expanded="false"] svg { transform: rotate(-90deg); }
.as-stat-group-table { min-width: 660px; }
.as-stat-group-table th:first-child { width: 28%; }
.as-stat-group-table th:nth-child(2) { width: 25%; }
.as-stat-group-table th:nth-child(3) { width: 25%; }
.as-stat-group-name { display: inline-flex; max-width: 100%; align-items: center; justify-content: center; gap: 8px; border: 0; background: none; padding: 4px 0; color: var(--as-primary); font: inherit; }
.as-stat-group-name > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.as-stat-group-name svg { width: 14px; height: 14px; flex-shrink: 0; color: #9aa8ba; }
.as-stat-count { display: flex; justify-content: center; align-items: baseline; gap: 12px; font-variant-numeric: tabular-nums; }
.as-stat-count > span { color: var(--as-muted); font-size: 10px; }
.as-stat-bar { display: block; max-width: 112px; height: 4px; margin: 5px auto 0; overflow: hidden; border-radius: 2px; background: var(--as-soft); }
.as-stat-bar > span { display: block; max-width: 100%; height: 100%; border-radius: inherit; background: #6e96de; }
.as-stat-money { font-weight: 600; font-variant-numeric: tabular-nums; }
.as-stat-group-table small { display: block; margin-top: 2px; color: var(--as-muted); font-size: 10px; }
.as-stat-empty { text-align: center; color: var(--as-muted); }
</style>
