<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { ArrowLeft, Database, History, RefreshCw, RotateCcw, Search, SearchCheck, X } from "@lucide/vue";
import { PlatformDetailDrawer } from "@platform-ui";
import { apiGet } from "@/api";
import BusinessRegistryCompanyTable from "./BusinessRegistryCompanyTable.vue";
import BusinessRegistryTableFrame from "./BusinessRegistryTableFrame.vue";
import BusinessRegistryColumnFilter from "./BusinessRegistryColumnFilter.vue";
import BusinessRegistryTableState from "./BusinessRegistryTableState.vue";
import BusinessRegistryCompanyHistory from "./BusinessRegistryCompanyHistory.vue";
import BusinessRegistryCompanyInfo from "./BusinessRegistryCompanyInfo.vue";
import BusinessRegistryLookup from "./BusinessRegistryLookup.vue";
import { useBusinessRegistryLookup } from "./useBusinessRegistryLookup";
import "./business-registry.css";

const base = "/api/org/business-registry";
const initial = new URLSearchParams(window.location.search);
const view = ref(initial.get("view") === "queries" ? "queries" : "companies");
const companyFilterKeys = ["companyName", "creditNo", "companyCode", "legalPerson", "companyStatus", "establishDate", "lastQueriedOn"];
const queryFilterColumns = [
  { key: "keyword", label: "查询关键词", type: "search" },
  { key: "pageNum", label: "查询页码", type: "number", min: 1, max: 100 },
  { key: "status", label: "查询状态", type: "select", options: [
    { value: "succeeded", label: "已保存" }, { value: "running", label: "处理中" },
    { value: "empty", label: "无结果" }, { value: "failed", label: "查询失败" },
  ] },
  { key: "resultCount", label: "保存数量", type: "number", min: 0, max: 20 },
  { key: "actor", label: "操作人", type: "search" },
  { key: "createdOn", label: "查询日期", type: "date" },
];
const queryFilterKeys = queryFilterColumns.map((column) => column.key);
const filterKeys = () => view.value === "companies" ? companyFilterKeys : queryFilterKeys;
const blankFilters = () => Object.fromEntries(filterKeys().map((key) => [key, ""]));
const filters = ref(Object.fromEntries(filterKeys().map((key) => [key, initial.get(key) || ""])));
if (initial.has("q")) filters.value[view.value === "companies" ? "companyName" : "keyword"] ||= initial.get("q");
const appliedFilters = ref({ ...filters.value });
const companyStatuses = ref([]);
const hasFilters = computed(() => Object.values(filters.value).some((value) => value.trim()));
const page = ref(Math.max(1, Math.min(1000000, Number(initial.get("page")) || 1)));
const items = ref([]);
const total = ref(0);
const configured = ref(null);
const loading = ref(false);
const error = ref("");
const lookupMode = ref(false);
const historyMode = ref(false);
const historyCompany = ref(null);
const companyTab = ref("info");
const companyHistoryVisited = ref(false);
const companyTabs = [{ id: "info", label: "工商信息" }, { id: "history", label: "历史查询" }];
const historyPage = ref(1);
const historyQueryId = ref(null);
const historyBack = ref(null);
const drawerOpen = ref(false);
const detail = ref(null);
const detailLoading = ref(false);
const detailError = ref("");
let detailId = null;
let listSequence = 0;
let detailSequence = 0;
let alive = true;
let filterTimer = null;
const pages = computed(() => Math.max(1, Math.ceil(total.value / 20)));
const visiblePages = computed(() => {
  if (pages.value <= 7) return Array.from({ length: pages.value }, (_, index) => index + 1);
  const candidates = [...new Set([1, page.value - 1, page.value, page.value + 1, pages.value])]
    .filter((value) => value >= 1 && value <= pages.value).sort((a, b) => a - b);
  return candidates.flatMap((value, index) => index && value - candidates[index - 1] > 1 ? [`gap-${value}`, value] : [value]);
});
const lookupFields = [
  { label: "单选企业", multiple: false, session: useBusinessRegistryLookup({ configured, onResults: loadList }) },
  { label: "多选企业", multiple: true, session: useBusinessRegistryLookup({ configured, onResults: loadList }) },
];
const queryBusy = computed(() => lookupFields.some(({ session }) => session.busy));
const statusLabel = (value) => ({ running: "处理中", succeeded: "已保存", empty: "无结果", failed: "查询失败" })[value] || value;
const timeLabel = (value) => value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "—";

function syncUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("view", view.value);
  url.searchParams.delete("q");
  for (const key of new Set([...companyFilterKeys, ...queryFilterKeys])) {
    if (appliedFilters.value[key]) url.searchParams.set(key, appliedFilters.value[key]);
    else url.searchParams.delete(key);
  }
  if (page.value > 1) url.searchParams.set("page", String(page.value)); else url.searchParams.delete("page");
  window.history.replaceState({}, "", url);
}
async function loadList() {
  const sequence = ++listSequence;
  loading.value = true;
  error.value = "";
  try {
    const data = await apiGet(`${base}/${view.value}`, { page: page.value, ...appliedFilters.value });
    if (!alive || sequence !== listSequence) return;
    items.value = data.items;
    total.value = data.total;
    if (Array.isArray(data.filterOptions?.companyStatuses)) companyStatuses.value = data.filterOptions.companyStatuses;
    if (typeof data.configured === "boolean") configured.value = data.configured;
  } catch (reason) {
    if (alive && sequence === listSequence) error.value = reason.message || "记录加载失败";
  } finally {
    if (alive && sequence === listSequence) loading.value = false;
  }
}
function selectView(value) {
  if (value === view.value) return;
  window.clearTimeout(filterTimer);
  filterTimer = null;
  view.value = value;
  filters.value = blankFilters();
  applyFilters();
}
function applyFilters() {
  window.clearTimeout(filterTimer);
  filterTimer = null;
  appliedFilters.value = Object.fromEntries(Object.entries(filters.value).map(([key, value]) => [key, value.trim()]));
  page.value = 1;
  syncUrl();
  void loadList();
}
function updateFilter(field, value, immediate = false) {
  filters.value[field] = String(value);
  ++listSequence;
  loading.value = true;
  window.clearTimeout(filterTimer);
  if (immediate) applyFilters();
  else filterTimer = window.setTimeout(applyFilters, 260);
}
function clearFilters() {
  filters.value = blankFilters();
  applyFilters();
}
function openLookup() {
  lookupFields.forEach(({ session }) => session.reset());
  historyMode.value = false;
  historyCompany.value = null;
  ++detailSequence;
  lookupMode.value = true;
  detail.value = null;
  detailError.value = "";
  detailLoading.value = false;
  drawerOpen.value = true;
}
function goToPage(value) {
  if (loading.value) return;
  const nextPage = Math.max(1, Math.min(pages.value, value));
  if (nextPage === page.value) return;
  page.value = nextPage;
  syncUrl();
  void loadList();
}
function openCompany(company, tab = "info") {
  historyCompany.value = company;
  companyTab.value = tab;
  companyHistoryVisited.value = tab === "history";
  historyPage.value = 1;
  historyQueryId.value = null;
  showCompanyHistory();
  drawerOpen.value = true;
}
function selectCompanyTab(tab) {
  companyTab.value = tab;
  if (tab === "history") companyHistoryVisited.value = true;
}
function companyTabKeydown(event) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const index = companyTabs.findIndex(tab => tab.id === companyTab.value);
  const next = event.key === "Home" ? 0 : event.key === "End" ? companyTabs.length - 1
    : (index + (event.key === "ArrowRight" ? 1 : -1) + companyTabs.length) % companyTabs.length;
  selectCompanyTab(companyTabs[next].id);
  event.currentTarget.querySelectorAll('[role="tab"]')[next]?.focus();
}
function showCompanyHistory() {
  ++detailSequence;
  lookupMode.value = false;
  historyMode.value = true;
  detail.value = null;
  detailError.value = "";
  detailLoading.value = false;
}
async function openDetail(id, fromCompany = false) {
  historyMode.value = false;
  if (!fromCompany) historyCompany.value = null;
  else historyQueryId.value = id;
  lookupMode.value = false;
  detailId = id;
  drawerOpen.value = true;
  detail.value = null;
  detailError.value = "";
  detailLoading.value = true;
  const sequence = ++detailSequence;
  if (fromCompany) {
    await nextTick();
    if (sequence === detailSequence) historyBack.value?.focus();
  }
  try {
    const data = await apiGet(`${base}/queries/${id}`);
    if (alive && sequence === detailSequence) detail.value = data;
  } catch (reason) {
    if (alive && sequence === detailSequence) detailError.value = reason.message || "查询详情加载失败";
  } finally {
    if (alive && sequence === detailSequence) detailLoading.value = false;
  }
}
function closeDetail() {
  if (queryBusy.value) return;
  drawerOpen.value = false;
  ++detailSequence;
}
onMounted(loadList);
onBeforeUnmount(() => { alive = false; ++listSequence; ++detailSequence; window.clearTimeout(filterTimer); });
</script>

<template>
  <section id="auth-business-registry-panel" role="tabpanel" aria-labelledby="auth-business-registry-tab"
    class="registry-surface registry-workspace flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
    <div class="registry-table-toolbar">
      <div class="registry-view-switch" role="group" aria-label="工商信息查询记录类型">
        <button v-for="[key, label, icon] in [['companies', '已保存企业', Database], ['queries', '查询记录', History]]" :key="key" type="button"
          class="registry-view-button" :class="{ 'is-active': view === key }" :aria-pressed="view === key" @click="selectView(key)">
          <component :is="icon" class="h-4 w-4" aria-hidden="true" />{{ label }}
        </button>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <button v-if="hasFilters" class="org-button" type="button" @click="clearFilters"><RotateCcw class="h-4 w-4" aria-hidden="true" />重置筛选</button>
        <button class="org-button" type="button" :disabled="loading" @click="loadList"><RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" aria-hidden="true" />刷新</button>
        <button class="org-button registry-primary" type="button" :disabled="queryBusy" @click="openLookup"><Search class="h-4 w-4" aria-hidden="true" />查询企业</button>
      </div>
    </div>
    <BusinessRegistryCompanyTable v-if="view === 'companies'" :items="items" :offset="(page - 1) * 20" saved :filters="filters" :statuses="companyStatuses" :loading="loading" :error="error" :selected-company-id="drawerOpen ? historyCompany?.id : null"
      :empty-message="hasFilters ? '没有匹配的记录，请调整筛选条件。' : '暂无已保存企业，完成查询后会自动记录在这里。'"
      @open="openCompany" @history="openCompany($event, 'history')" @filter="updateFilter" @retry="loadList" />
    <BusinessRegistryTableFrame v-else label="工商查询记录表格，可使用左右方向键浏览">
      <table class="registry-grid-table registry-query-table"><caption class="sr-only">工商查询记录</caption>
        <colgroup>
          <col class="registry-number-column" /><col class="registry-name-column" /><col class="registry-page-column" />
          <col class="registry-status-column" /><col class="registry-count-column" /><col class="registry-actor-column" />
          <col class="registry-time-column" /><col class="registry-action-column" />
        </colgroup>
        <thead><tr>
          <th scope="col" class="registry-frozen-number">序号</th><th scope="col" class="registry-frozen-name">查询关键词</th><th scope="col">页码</th>
          <th scope="col">查询状态</th><th scope="col">保存数量</th><th scope="col">操作人</th><th scope="col">查询时间（北京时间）</th><th scope="col" class="registry-frozen-action">操作</th>
        </tr>
        <tr class="registry-filter-row" aria-label="查询记录列筛选">
          <td class="registry-frozen-number"></td>
          <td v-for="column in queryFilterColumns" :key="column.key" :class="{ 'registry-frozen-name': column.key === 'keyword' }">
            <BusinessRegistryColumnFilter :model-value="filters[column.key]" :label="`筛选${column.label}`" :type="column.type" :options="column.options" :min="column.min" :max="column.max"
              @change="(value, immediate) => updateFilter(column.key, value, immediate)" />
          </td>
          <td class="registry-frozen-action"></td>
        </tr></thead>
        <tbody>
        <BusinessRegistryTableState :colspan="8" :loading="loading" :error="error" :empty="!items.length" :message="hasFilters ? '没有匹配的记录，请调整筛选条件。' : '暂无查询记录。'" @retry="loadList" />
        <tr v-for="(row, index) in loading || error ? [] : items" :key="row.id" :class="{ 'is-detail-open': drawerOpen && detail?.id === row.id }">
          <td class="registry-frozen-number registry-row-number">{{ (page - 1) * 20 + index + 1 }}</td>
          <td class="registry-frozen-name registry-company-name">{{ row.keyword }}</td><td class="tabular-nums">{{ row.pageNum }}</td>
          <td><span class="registry-badge" :class="{ 'registry-badge-danger': row.status === 'failed', 'registry-badge-success': row.status === 'succeeded', 'registry-badge-warning': row.status === 'running', 'registry-badge-muted': row.status === 'empty' }">{{ statusLabel(row.status) }}</span></td>
          <td class="tabular-nums">{{ row.status === 'running' ? '—' : `${row.resultCount} 条` }}</td>
          <td>{{ row.actorName }}<div v-if="row.actorUserId !== row.effectiveUserId" class="mt-1 text-xs text-slate-500">代理：{{ row.effectiveName }}</div></td>
          <td class="registry-timestamp">{{ timeLabel(row.createdAt) }}</td><td class="registry-frozen-action"><button type="button" class="org-text-button" :aria-label="`查看查询记录：${row.keyword}，第${row.pageNum}页`" @click="openDetail(row.id)">查看详情</button></td>
        </tr></tbody>
      </table>
    </BusinessRegistryTableFrame>
    <footer class="registry-pagination">
      <span class="registry-pagination-total">共 <strong>{{ total }}</strong> 条 · 每页 20 条</span>
      <nav class="registry-page-buttons" aria-label="工商信息查询记录分页">
        <button type="button" :disabled="loading || page <= 1" @click="goToPage(page - 1)">上一页</button>
        <template v-for="item in visiblePages" :key="item">
          <span v-if="typeof item === 'string'" class="px-1 text-xs text-slate-400" aria-hidden="true">…</span>
          <button v-else type="button" class="registry-page-number" :aria-label="`第 ${item} 页`" :aria-current="item === page ? 'page' : undefined" :disabled="loading" @click="goToPage(item)">{{ item }}</button>
        </template>
        <button type="button" :disabled="loading || page >= pages" @click="goToPage(page + 1)">下一页</button>
      </nav>
      <span class="sr-only" aria-live="polite">第 {{ page }} / {{ pages }} 页</span>
    </footer>
  </section>
  <PlatformDetailDrawer :open="drawerOpen" labelled-by="registry-detail-title" :close-on-backdrop="!queryBusy" :close-on-escape="!queryBusy" @close="closeDetail">
    <div class="auth-org-surface registry-surface flex h-full min-h-0 flex-col">
      <header class="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white p-4">
        <div class="flex min-w-0 items-center gap-3"><span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-50 text-blue-600"><SearchCheck class="h-5 w-5" aria-hidden="true" /></span>
          <div><h2 id="registry-detail-title" class="text-base font-semibold">{{ lookupMode ? "企业工商查询" : historyCompany ? "企业详情" : "工商查询详情" }}</h2><p v-if="detail && !historyCompany" class="mt-1 text-xs text-slate-500">记录 #{{ detail.id }} · {{ statusLabel(detail.status) }}</p></div>
        </div><button type="button" class="org-button" aria-label="关闭工商查询详情" :disabled="queryBusy" @click="closeDetail"><X class="h-4 w-4" aria-hidden="true" /></button>
      </header>
      <div v-if="historyCompany" class="registry-view-switch shrink-0 border-b border-slate-200 bg-white px-4 py-2" role="tablist" aria-label="企业详情页签" @keydown="companyTabKeydown">
        <button v-for="tab in companyTabs" :id="`registry-company-${tab.id}-tab`" :key="tab.id" type="button" role="tab"
          class="registry-view-button" :class="{ 'is-active': companyTab === tab.id }"
          :aria-selected="companyTab === tab.id" :aria-controls="`registry-company-${tab.id}-panel`" :tabindex="companyTab === tab.id ? 0 : -1"
          @click="selectCompanyTab(tab.id)">{{ tab.label }}</button>
      </div>
      <div v-if="historyCompany" v-show="companyTab === 'info'" id="registry-company-info-panel" role="tabpanel" aria-labelledby="registry-company-info-tab"
        class="min-h-0 flex-1 overflow-auto bg-slate-100 p-4" tabindex="0">
        <BusinessRegistryCompanyInfo :company="historyCompany" />
      </div>
      <div v-if="!historyCompany || companyHistoryVisited" v-show="!historyCompany || companyTab === 'history'"
        :id="historyCompany ? 'registry-company-history-panel' : undefined" :role="historyCompany ? 'tabpanel' : undefined"
        :aria-labelledby="historyCompany ? 'registry-company-history-tab' : undefined"
        class="min-h-0 flex-1 bg-slate-100 p-4" :class="historyMode ? 'flex flex-col overflow-hidden' : 'space-y-4 overflow-auto'">
        <BusinessRegistryCompanyHistory v-if="historyMode && historyCompany" :company="historyCompany" :page="historyPage" :selected-query-id="historyQueryId" @page="historyPage = $event" @open="openDetail($event, true)" />
        <template v-else-if="lookupMode">
          <BusinessRegistryLookup v-for="field in lookupFields" :key="field.label" v-model="field.session.keyword"
            v-model:selected-companies="field.session.selectedCompanies" :label="field.label" :multiple="field.multiple" :autofocus="!field.multiple"
            :selected-company="field.session.selectedCompany" :result="field.session.result"
            :busy="field.session.searching || field.session.refreshing" :configured="configured" :has-more="field.session.hasMore"
            :loading-more="field.session.loadingMore" :more-error="field.session.moreError" :more-pending="Boolean(field.session.morePending)"
            :end-message="field.session.endMessage" :error="field.session.error" described-by="registry-query-help"
            @select="field.session.selectedCompany = $event" @search="field.session.search()" @refresh="field.session.refresh"
            @load-more="field.session.loadMore()" @refresh-more="field.session.loadMore(true)" />
        </template>
        <button v-if="historyCompany && !historyMode" ref="historyBack" type="button" class="org-button" @click="showCompanyHistory"><ArrowLeft class="h-4 w-4" aria-hidden="true" />返回历史查询</button>
        <p v-if="!historyMode && !lookupMode && detailLoading" role="status" class="text-sm text-slate-500">正在加载查询详情…</p>
        <p v-else-if="detailError" role="alert" class="text-sm text-red-700">{{ detailError }} <button type="button" class="org-text-button" @click="openDetail(detailId, Boolean(historyCompany))">重新加载</button></p>
        <template v-else-if="detail && !lookupMode">
          <section class="rounded-lg border border-slate-200 bg-white p-4">
            <h3 class="border-l-4 border-blue-600 pl-2 text-sm font-semibold">查询信息</h3>
            <dl class="mt-4 grid grid-cols-2 gap-4 text-sm">
              <div class="min-w-0"><dt class="text-xs text-slate-500">查询关键词</dt><dd class="mt-1 break-words font-medium">{{ detail.keyword }}</dd></div>
              <div class="min-w-0"><dt class="text-xs text-slate-500">查询范围</dt><dd class="mt-1">第 {{ detail.pageNum }} 页 · 每页 {{ detail.pageSize }} 条<span v-if="detail.totalRecords != null"> · 共 {{ detail.totalRecords }} 条</span></dd></div>
              <div class="min-w-0"><dt class="text-xs text-slate-500">操作人</dt><dd class="mt-1 break-words">{{ detail.actorName }}<span v-if="detail.actorUserId !== detail.effectiveUserId">（代理 {{ detail.effectiveName }}）</span></dd></div>
              <div class="min-w-0"><dt class="text-xs text-slate-500">查询时间（北京时间）</dt><dd class="mt-1">{{ timeLabel(detail.createdAt) }}</dd></div>
            </dl>
            <p v-if="detail.status !== 'succeeded'" class="mt-4 text-sm" :class="detail.status === 'failed' ? 'text-red-700' : 'text-slate-600'" :role="detail.status === 'failed' ? 'alert' : 'status'">{{ detail.message || '查询仍在处理中，请稍后刷新记录。' }}</p>
            <button v-if="detail.status === 'running'" type="button" class="org-button mt-3" @click="openDetail(detail.id, Boolean(historyCompany))">刷新查询状态</button>
          </section>
          <section class="overflow-hidden rounded-lg border border-slate-200 bg-white">
            <div class="p-4"><h3 class="border-l-4 border-blue-600 pl-2 text-sm font-semibold">查询结果 · {{ detail.resultCount }} 条</h3><p class="mt-2 text-xs text-slate-500">保留查询当时的数据。结果名称可能不包含关键词，请核对企业身份。</p></div>
            <BusinessRegistryCompanyTable v-if="detail.companies?.length" :items="detail.companies" />
            <p v-else class="px-4 pb-4 text-sm text-slate-500">本次没有保存企业信息。</p>
          </section>
        </template>
      </div>
      <footer class="shrink-0 border-t border-slate-200 bg-white p-4">
        <div class="flex flex-wrap justify-center gap-2">
          <button type="button" class="org-button" :disabled="queryBusy" @click="closeDetail">关闭</button>
        </div>
        <p v-if="lookupMode" id="registry-query-help" class="mt-2 text-center text-xs text-slate-500">每页最多 20 条，整页自动保存。滚到底部加载下一页，查询和加载可能消耗服务额度。</p>
      </footer>
    </div>
  </PlatformDetailDrawer>
</template>
