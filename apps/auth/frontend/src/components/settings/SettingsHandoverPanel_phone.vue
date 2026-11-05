<script setup>
import { Search } from "@lucide/vue";
import { ref } from "vue";
import { formatOrganizationSyncTime } from "@/organization-sync-time";
import SettingsInactivePagination from "./SettingsInactivePagination.vue";
import { useInactiveEmployeePagination } from "./useInactiveEmployeePagination";

const props = defineProps({
  inactiveKeyword: { type: String, default: "" },
  loadingInactive: Boolean,
  filteredInactiveEmployees: { type: Array, required: true },
});
const emit = defineEmits(["update-inactive-keyword"]);
const listScroll = ref(null);
const { page, pageEmployees, totalPages, visiblePages, goToPage } = useInactiveEmployeePagination(props);

function changePage(value) {
  goToPage(value);
  listScroll.value?.scrollTo({ top: 0 });
}

function formerPaths(employee, field) {
  if (!employee.formerOrganizationRecordedAt) return "未记录";
  return (employee[field] || []).map((item) => item.pathText).filter(Boolean).join("；") || "无归属";
}

function resignationDate(employee) {
  return formatOrganizationSyncTime(employee.formerOrganizationRecordedAt).slice(0, 10) || "未记录";
}
</script>

<template>
  <section class="flex h-[70vh] min-h-[360px] min-w-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white" aria-label="离职人员">
    <div class="shrink-0 border-b border-slate-200 px-4 py-3">
      <div class="flex items-center justify-between text-sm font-medium text-slate-800"><span>离职人员</span><span class="text-slate-500">{{ filteredInactiveEmployees.length }}人</span></div>
      <label class="mt-3 flex h-9 items-center gap-2 rounded-md border border-slate-200 px-3 text-slate-500 focus-within:border-sky-500">
        <Search class="h-4 w-4 shrink-0" />
        <input type="search" :value="inactiveKeyword" aria-label="搜索离职人员" placeholder="搜索姓名或 ID" class="min-w-0 flex-1 bg-transparent text-sm text-slate-900 outline-none" @input="emit('update-inactive-keyword', $event.target.value.trim())" />
      </label>
    </div>
    <div ref="listScroll" class="min-h-0 flex-1 overflow-y-auto">
      <div v-if="loadingInactive" class="px-4 py-8 text-center text-sm text-slate-500" role="status">加载中...</div>
      <div v-else-if="!pageEmployees.length" class="px-4 py-8 text-center text-sm text-slate-500">{{ inactiveKeyword ? "没有匹配的离职人员" : "暂无离职人员" }}</div>
      <div v-else class="divide-y divide-slate-100">
        <article v-for="employee in pageEmployees" :key="employee.userId" class="min-w-0 px-4 py-3">
          <div class="break-words text-sm font-medium text-slate-900">{{ employee.rawName || employee.name }}</div>
          <div class="mt-0.5 break-all text-xs text-slate-500">ID: {{ employee.userId }}</div>
          <dl class="mt-3 space-y-2 text-xs">
            <div><dt class="text-slate-500">离职日期</dt><dd class="mt-1 text-slate-800">{{ resignationDate(employee) }}</dd></div>
            <div><dt class="text-slate-500">离职前钉钉组织架构</dt><dd class="mt-1 break-words leading-5 text-slate-800">{{ formerPaths(employee, "formerDingTalkDepartments") }}</dd></div>
          </dl>
        </article>
      </div>
    </div>
    <SettingsInactivePagination :page="page" :total-pages="totalPages" :visible-pages="visiblePages" :total="filteredInactiveEmployees.length" @change="changePage" />
  </section>
</template>
