<script setup>
import { ref } from "vue";
import { formatOrganizationSyncTime } from "@/organization-sync-time";
import SettingsInactivePagination from "./SettingsInactivePagination.vue";
import { INACTIVE_EMPLOYEE_PAGE_SIZE, useInactiveEmployeePagination } from "./useInactiveEmployeePagination";

const props = defineProps({
  inactiveKeyword: { type: String, default: "" },
  loadingInactive: Boolean,
  filteredInactiveEmployees: { type: Array, required: true },
});
const emit = defineEmits(["update-inactive-keyword"]);
const tableScroll = ref(null);
const { page, pageEmployees, totalPages, visiblePages, goToPage } = useInactiveEmployeePagination(props);

function changePage(value) {
  goToPage(value);
  tableScroll.value?.scrollTo({ top: 0 });
}

function scrollTableByKeyboard(event) {
  if (event.target !== event.currentTarget || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  event.currentTarget.scrollLeft += event.key === "ArrowRight" ? 120 : -120;
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
  <section class="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm" aria-label="离职人员">
    <div class="flex shrink-0 items-center justify-between border-b border-slate-200 bg-slate-50 px-3 py-2">
      <span class="text-sm font-semibold text-slate-800">离职人员</span>
      <span class="text-xs text-slate-500">{{ filteredInactiveEmployees.length }} 人</span>
    </div>
    <div
      ref="tableScroll"
      class="min-h-0 min-w-0 flex-1 overflow-auto"
      tabindex="0"
      role="region"
      aria-label="离职人员表格，可使用方向键横向浏览"
      @keydown="scrollTableByKeyboard"
    >
      <table class="w-full min-w-[760px] table-fixed border-l border-t border-slate-200 text-left text-sm">
        <caption class="sr-only">离职人员</caption>
        <colgroup>
          <col class="w-[48px]" />
          <col class="w-[112px]" />
          <col class="w-[164px]" />
          <col class="w-[112px]" />
          <col class="w-[162px]" />
        </colgroup>
        <thead class="sticky top-0 z-30 bg-slate-50 text-xs text-slate-700">
          <tr>
            <th scope="col" class="sticky left-0 z-40 border-b border-r border-slate-200 bg-slate-50 px-2 py-2 text-center font-semibold">序号</th>
            <th scope="col" class="sticky left-[48px] z-40 border-b border-r border-slate-200 bg-slate-50 px-3 py-2 font-semibold">姓名</th>
            <th scope="col" class="border-b border-r border-slate-200 bg-slate-50 px-3 py-2 font-semibold">ID</th>
            <th scope="col" class="border-b border-r border-slate-200 bg-slate-50 px-3 py-2 font-semibold">离职日期</th>
            <th scope="col" class="border-b border-r border-slate-200 bg-slate-50 px-3 py-2 font-semibold">离职前钉钉组织架构</th>
          </tr>
          <tr class="bg-white">
            <th class="sticky left-0 z-40 border-b border-r border-slate-200 bg-white"></th>
            <th class="sticky left-[48px] z-40 border-b border-r border-slate-200 bg-white px-2 py-1">
              <input
                type="search"
                :value="inactiveKeyword"
                aria-label="搜索离职人员姓名或 ID"
                placeholder="姓名 / ID"
                class="h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-800 outline-none placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                @input="emit('update-inactive-keyword', $event.target.value.trim())"
              />
            </th>
            <th v-for="column in 3" :key="column" class="border-b border-r border-slate-200 bg-white"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loadingInactive"><td colspan="5" class="h-52 border-b border-slate-200 text-center text-sm text-slate-500" role="status">加载中...</td></tr>
          <tr v-else-if="!pageEmployees.length"><td colspan="5" class="h-52 border-b border-slate-200 text-center text-sm text-slate-500">{{ inactiveKeyword ? "没有匹配的离职人员" : "暂无离职人员" }}</td></tr>
          <tr v-for="(employee, index) in !loadingInactive ? pageEmployees : []" :key="employee.userId" class="group text-slate-700">
            <td class="sticky left-0 border-b border-r border-slate-100 bg-white px-2 py-2 text-center text-xs text-slate-400 group-even:bg-slate-50 group-hover:bg-blue-50/40">{{ (page - 1) * INACTIVE_EMPLOYEE_PAGE_SIZE + index + 1 }}</td>
            <td class="sticky left-[48px] border-b border-r border-slate-100 bg-white px-3 py-2 font-semibold text-slate-900 group-even:bg-slate-50 group-hover:bg-blue-50/40"><span class="block break-words">{{ employee.rawName || employee.name }}</span></td>
            <td class="whitespace-nowrap border-b border-r border-slate-100 px-3 py-2 font-mono text-xs text-slate-600 group-even:bg-slate-50 group-hover:bg-blue-50/40">{{ employee.userId }}</td>
            <td class="whitespace-nowrap border-b border-r border-slate-100 px-3 py-2 text-xs tabular-nums group-even:bg-slate-50 group-hover:bg-blue-50/40">{{ resignationDate(employee) }}</td>
            <td class="break-words border-b border-r border-slate-100 px-3 py-2 leading-5 group-even:bg-slate-50 group-hover:bg-blue-50/40">{{ formerPaths(employee, "formerDingTalkDepartments") }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <SettingsInactivePagination :page="page" :total-pages="totalPages" :visible-pages="visiblePages" :total="filteredInactiveEmployees.length" @change="changePage" />
  </section>
</template>
