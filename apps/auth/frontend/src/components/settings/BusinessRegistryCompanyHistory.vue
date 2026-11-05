<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { RefreshCw } from "@lucide/vue";
import { apiGet } from "@/api";
import BusinessRegistryTableFrame from "./BusinessRegistryTableFrame.vue";
import BusinessRegistryTableState from "./BusinessRegistryTableState.vue";

const props = defineProps({
  company: { type: Object, required: true },
  page: { type: Number, default: 1 },
  selectedQueryId: { type: Number, default: null },
});
const emit = defineEmits(["open", "page"]);
const root = ref(null);
const items = ref([]);
const total = ref(0);
const loading = ref(true);
const error = ref("");
const pages = computed(() => Math.max(1, Math.ceil(total.value / 20)));
const timeLabel = (value) => new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
let sequence = 0;
async function load() {
  const current = ++sequence;
  loading.value = true;
  error.value = "";
  try {
    const data = await apiGet(`/api/org/business-registry/companies/${props.company.id}/queries`, { page: props.page });
    if (current !== sequence) return;
    items.value = data.items;
    total.value = data.total;
  } catch (reason) {
    if (current === sequence) error.value = reason.message || "历史查询加载失败";
  } finally {
    if (current === sequence) loading.value = false;
  }
}
onMounted(async () => {
  await load();
  await nextTick();
  if (props.selectedQueryId) root.value?.querySelector(`[data-query-id="${props.selectedQueryId}"]`)?.focus();
});
watch(() => props.page, load);
onBeforeUnmount(() => { ++sequence; });
</script>

<template>
  <section ref="root" class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white" aria-label="企业历史查询">
    <header class="flex shrink-0 items-start justify-between gap-3 border-b border-slate-200 p-4">
      <div class="min-w-0">
        <h3 class="break-words border-l-4 border-blue-600 pl-2 text-sm font-semibold">{{ company.companyName }}</h3>
        <p class="mt-2 break-all text-xs text-slate-500">统一社会信用代码：{{ company.creditNo || '—' }}</p>
      </div>
      <button type="button" class="org-button" :disabled="loading" @click="load"><RefreshCw class="h-4 w-4" aria-hidden="true" />刷新</button>
    </header>
    <BusinessRegistryTableFrame label="企业历史查询表格，可使用左右方向键浏览">
      <table class="registry-grid-table registry-company-history-table">
        <caption class="sr-only">企业历史查询</caption>
        <colgroup><col class="registry-number-column" /><col class="registry-history-keyword-column" /><col class="registry-time-column" /><col class="registry-count-column" /><col class="registry-page-column" /><col class="registry-actor-column" /><col class="registry-action-column" /></colgroup>
        <thead><tr><th scope="col" class="registry-frozen-number">序号</th><th scope="col" class="registry-frozen-name">查询关键词</th><th scope="col">查询时间（北京时间）</th><th scope="col">返回企业</th><th scope="col">页码</th><th scope="col">操作人</th><th scope="col" class="registry-frozen-action">操作</th></tr></thead>
        <tbody>
          <BusinessRegistryTableState :colspan="7" :loading="loading" :error="error" :empty="!items.length" message="暂无关联的历史查询。" @retry="load" />
          <tr v-for="(row, index) in loading || error ? [] : items" :key="row.id" :class="{ 'is-detail-open': row.id === selectedQueryId }">
            <td class="registry-frozen-number registry-row-number">{{ (page - 1) * 20 + index + 1 }}</td>
            <td class="registry-frozen-name registry-company-name"><button type="button" class="registry-company-link" :data-query-id="row.id" :aria-label="`查看历史查询：${row.keyword}，第${row.pageNum}页，记录${row.id}`" @click="emit('open', row.id)">{{ row.keyword }}</button></td>
            <td class="registry-timestamp">{{ timeLabel(row.createdAt) }}</td>
            <td class="tabular-nums">{{ row.resultCount }} 家</td><td class="tabular-nums">{{ row.pageNum }}</td>
            <td>{{ row.actorName }}<div v-if="row.actorUserId !== row.effectiveUserId" class="mt-1 text-xs text-slate-500">代理：{{ row.effectiveName }}</div></td>
            <td class="registry-frozen-action"><button type="button" class="org-text-button" :aria-label="`查看记录${row.id}返回的企业`" @click="emit('open', row.id)">查看企业</button></td>
          </tr>
        </tbody>
      </table>
    </BusinessRegistryTableFrame>
    <nav class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-3 py-2" aria-label="企业历史查询分页">
      <span class="text-xs text-slate-500">共 {{ total }} 次查询</span>
      <div class="registry-page-buttons"><button type="button" :disabled="loading || page <= 1" @click="emit('page', page - 1)">上一页</button><span class="px-1 text-xs tabular-nums text-slate-600" aria-live="polite">第 {{ page }} / {{ pages }} 页</span><button type="button" :disabled="loading || page >= pages" @click="emit('page', page + 1)">下一页</button></div>
    </nav>
  </section>
</template>
