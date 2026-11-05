<script setup>
import { computed, onMounted, reactive, shallowRef, watch } from "vue";
import { Search, Upload } from "lucide-vue-next";

import {
  fetchCompetitors,
} from "@/features/competitiveApi";
import DesktopCompetitorDrawer from "@/desktop/components/DesktopCompetitorDrawer.vue";
import DesktopPagination from "@/desktop/components/DesktopPagination.vue";
import SubmissionCover from "@/shared/SubmissionCover.vue";

const props = defineProps({ access: { type: Object, required: true } });
const emit = defineEmits(["notify"]);
const rows = shallowRef([]);
const selectedId = shallowRef("");
const loading = shallowRef(false);
const filters = reactive({ q: "", page: 1, pageSize: 20 });
const total = shallowRef(0);
const pages = shallowRef(0);
let timer;

const visibleRows = computed(() => rows.value);

function productLabel(item) {
  return item.product?.name || `历史产品（ID: ${item.productId}）`;
}

async function loadRows(force = false) {
  loading.value = true;
  try {
    const result = await fetchCompetitors(filters, { force });
    rows.value = result.items;
    total.value = result.total;
    pages.value = result.pages;
  } catch (reason) {
    rows.value = [];
    total.value = 0;
    pages.value = 0;
    emit("notify", reason.message || "竞品资料加载失败");
  } finally {
    loading.value = false;
  }
}

function openRow(event, id) {
  if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  selectedId.value = id;
}

watch(
  () => filters.q,
  () => {
    filters.page = 1;
    window.clearTimeout(timer);
    timer = window.setTimeout(loadRows, 220);
  },
);
watch(() => filters.page, loadRows);

onMounted(loadRows);
</script>

<template>
  <div class="competitor-library">
    <div class="table-wrap library-table">
      <table class="data-table">
        <colgroup>
          <col class="competitor-column" />
          <col class="product-column" />
          <col class="region-column" />
          <col class="source-column" />
          <col class="date-column" />
          <col class="date-column" />
        </colgroup>
        <thead><tr><th>竞品</th><th>我司产品</th><th>地区覆盖</th><th>来源</th><th>更新时间</th><th>有效期</th></tr><tr class="table-filter-row"><th><label class="table-filter-search"><Search :size="13" /><input v-model="filters.q" class="table-filter-control" placeholder="搜索品牌、名称或型号" /></label></th><th></th><th></th><th></th><th></th><th></th></tr></thead>
        <tbody>
          <tr
            v-for="item in visibleRows"
            :key="item.id"
            role="button"
            tabindex="0"
            @click="openRow($event, item.id)"
            @keydown="openRow($event, item.id)"
          >
            <td>
              <div class="competitor-cell">
                <SubmissionCover class="competitor-cover" :submission="item.coverSubmission">
                  <Upload :size="17" aria-hidden="true" />
                </SubmissionCover>
                <span class="competitor-copy"><strong>{{ item.brand }} · {{ item.model || item.name }}</strong><small>{{ item.name }}</small></span>
              </div>
            </td>
            <td class="product-name">{{ productLabel(item) }}</td>
            <td>{{ item.regions.join('、') || '-' }}</td>
            <td>{{ item.sources }} 条</td>
            <td>{{ item.updated }}</td>
            <td>{{ item.expires }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="loading" class="empty-state">正在查询数据库...</div>
      <div v-else-if="!visibleRows.length" class="empty-state">当前筛选条件下暂无竞品资料</div>
    </div>
    <DesktopPagination :page="filters.page" :pages="pages" :total="total" :page-size="filters.pageSize" @change="filters.page = $event" />
  </div>
  <DesktopCompetitorDrawer
    :id="selectedId"
    :access="props.access"
    @close="selectedId = ''"
    @deleted="loadRows(true)"
    @updated="loadRows(true)"
    @notify="emit('notify', $event)"
  />
</template>

<style scoped>
.competitor-library { display: flex; min-height: 0; flex: 1; flex-direction: column; }
.table-filter-search { position: relative; display: block; }
.table-filter-search svg { position: absolute; z-index: 1; top: 7px; left: 8px; color: #94a3b8; }
.table-filter-search input { padding-left: 28px; }
.library-table { min-height: 0; flex: 1; }
.library-table table { min-width: 960px; table-layout: fixed; }
.competitor-column { width: 31%; }
.product-column { width: 24%; }
.region-column { width: 14%; }
.source-column { width: 8%; }
.date-column { width: 11.5%; }
.library-table tbody tr { cursor: pointer; }
.library-table tbody tr:focus-visible { background: #eff6ff; outline: 2px solid #3b82f6; outline-offset: -2px; }
.library-table td strong, .library-table td small { display: block; }
.library-table td strong { color: #132b50; font-size: 12px; }
.library-table td small { margin-top: 3px; color: #64748b; font-size: 10px; }
.competitor-cell { display: flex; min-width: 0; align-items: center; gap: 11px; }
.competitor-cover { width: 48px; height: 44px; flex: 0 0 auto; border: 1px solid #dce5f0; border-radius: 6px; background: #f1f5f9; color: #155eef; }
.competitor-copy { min-width: 0; }
.competitor-copy strong, .competitor-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.product-name { overflow: hidden; color: #075ff7 !important; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
</style>
