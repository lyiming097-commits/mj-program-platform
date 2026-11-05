<script setup>
import BusinessRegistryTableFrame from "./BusinessRegistryTableFrame.vue";
import BusinessRegistryColumnFilter from "./BusinessRegistryColumnFilter.vue";
import BusinessRegistryTableState from "./BusinessRegistryTableState.vue";

const props = defineProps({
  items: { type: Array, default: () => [] },
  saved: Boolean,
  filters: { type: Object, default: null },
  statuses: { type: Array, default: () => [] },
  loading: Boolean,
  error: { type: String, default: "" },
  emptyMessage: { type: String, default: "暂无记录。" },
  offset: { type: Number, default: 0 },
  selectedCompanyId: { type: Number, default: null },
});
const emit = defineEmits(["open", "history", "filter", "retry"]);
function openRow(event, item) {
  if (!props.saved || event.target.closest('button, a, input, textarea, select, [contenteditable="true"]')) return;
  event.currentTarget.focus({ preventScroll: true });
  emit("open", item);
}
function rowKeydown(event, item) {
  if (event.target !== event.currentTarget || !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  openRow(event, item);
}
const filterColumns = [
  ["companyName", "企业名称", "search"], ["creditNo", "统一社会信用代码", "search"],
  ["companyCode", "注册号", "search"], ["legalPerson", "法定代表人", "search"],
  ["companyStatus", "经营状态", "select"], ["establishDate", "成立日期", "date"],
  ["lastQueriedOn", "最近查询日期", "date"],
];
function dateLabel(value) {
  return /^\d{8}$/.test(value || "") ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value || "—";
}
function timeLabel(value) {
  return value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "—";
}
function companyStatusClass(value) {
  if (/注销|吊销|撤销/.test(value)) return "registry-badge-muted";
  if (/停业|清算|迁出/.test(value)) return "registry-badge-warning";
  if (/存续|在营|开业|在业/.test(value)) return "registry-badge-success";
  return "registry-badge-muted";
}
</script>

<template>
  <BusinessRegistryTableFrame :label="saved ? '已保存企业表格，可使用左右方向键浏览' : '本次查询企业表格，可使用左右方向键浏览'">
    <table class="registry-grid-table registry-company-table" :class="{ 'registry-saved-table': saved }">
      <caption class="sr-only">{{ saved ? '已保存企业' : '本次查询企业' }}</caption>
      <colgroup>
        <col class="registry-number-column" /><col class="registry-name-column" />
        <col class="registry-credit-column" /><col class="registry-code-column" />
        <col class="registry-person-column" /><col class="registry-status-column" /><col class="registry-date-column" />
        <template v-if="saved"><col class="registry-time-column" /><col class="registry-action-column" /></template>
      </colgroup>
      <thead><tr>
        <th scope="col" class="registry-frozen-number">序号</th><th scope="col" class="registry-frozen-name">企业名称</th>
        <th scope="col">统一社会信用代码</th><th scope="col">注册号</th>
        <th scope="col">法定代表人</th><th scope="col">经营状态</th><th scope="col">成立日期</th>
        <template v-if="saved"><th scope="col">最近查询（北京时间）</th><th scope="col" class="registry-frozen-action">历史查询</th></template>
      </tr>
      <tr v-if="filters" class="registry-filter-row" aria-label="企业列筛选">
        <td class="registry-frozen-number"></td>
        <td v-for="[field, label, type] in filterColumns" :key="field" :class="{ 'registry-frozen-name': field === 'companyName' }">
          <BusinessRegistryColumnFilter :model-value="filters[field]" :label="`筛选${label}`" :type="type" :options="type === 'select' ? statuses : []" @change="(value, immediate) => $emit('filter', field, value, immediate)" />
        </td>
        <td class="registry-frozen-action"></td>
      </tr></thead>
      <tbody>
      <BusinessRegistryTableState :colspan="saved ? 9 : 7" :loading="loading" :error="error" :empty="!items.length" :message="emptyMessage" @retry="$emit('retry')" />
      <tr v-for="(item, index) in loading || error ? [] : items" :key="item.id || index"
        :class="{ 'registry-clickable-row': saved, 'is-detail-open': saved && item.id === selectedCompanyId }"
        :tabindex="saved ? 0 : undefined" :aria-label="saved ? `查看企业：${item.companyName}` : undefined"
        @click="openRow($event, item)" @keydown="rowKeydown($event, item)">
        <td class="registry-frozen-number registry-row-number">{{ offset + index + 1 }}</td>
        <td class="registry-frozen-name registry-company-name">
          <button v-if="saved" type="button" class="registry-company-link" :title="item.companyName" :aria-label="`查看${item.companyName}的工商信息`" @click.stop="$emit('open', item)">{{ item.companyName }}</button>
          <span v-else :title="item.companyName">{{ item.companyName }}</span>
        </td>
        <td class="registry-identifier" :title="item.creditNo">{{ item.creditNo || '—' }}</td>
        <td class="registry-identifier" :title="item.companyCode">{{ item.companyCode || '—' }}</td>
        <td>{{ item.legalPerson || '—' }}</td>
        <td><span class="registry-badge" :class="companyStatusClass(item.companyStatus)">{{ item.companyStatus || '—' }}</span></td>
        <td class="registry-identifier">{{ dateLabel(item.establishDate) }}</td>
        <template v-if="saved">
          <td class="registry-timestamp">{{ timeLabel(item.lastQueriedAt) }}</td>
          <td class="registry-frozen-action"><button type="button" class="org-text-button" :aria-label="`查看${item.companyName}的${item.queryCount ?? 0}次历史查询`" @click.stop="$emit('history', item)">{{ item.queryCount ?? 0 }} 次查询</button></td>
        </template>
      </tr></tbody>
    </table>
  </BusinessRegistryTableFrame>
</template>
