<script setup>
import { computed } from "vue";
import { Activity, Building2, CalendarDays, Clock3, FileText, Fingerprint, UserRound } from "@lucide/vue";

const props = defineProps({ company: { type: Object, required: true } });
function dateLabel(value) {
  return /^\d{8}$/.test(value || "") ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value || "—";
}
function timeLabel(value) {
  return value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "—";
}
const fields = computed(() => [
  { label: "企业名称", value: props.company.companyName, icon: Building2, wide: true },
  { label: "统一社会信用代码", value: props.company.creditNo, icon: Fingerprint, wide: true, identifier: true },
  { label: "注册号", value: props.company.companyCode, icon: FileText, identifier: true },
  { label: "法定代表人", value: props.company.legalPerson, icon: UserRound },
  { label: "经营状态", value: props.company.companyStatus, icon: Activity },
  { label: "成立日期", value: dateLabel(props.company.establishDate), icon: CalendarDays },
  { label: "首次查询（北京时间）", value: timeLabel(props.company.firstQueriedAt), icon: Clock3 },
  { label: "最近查询（北京时间）", value: timeLabel(props.company.lastQueriedAt), icon: Clock3 },
]);
</script>

<template>
  <section class="rounded-lg border border-slate-200 bg-white p-4" aria-label="企业工商资料">
    <h3 class="border-l-4 border-blue-600 pl-2 text-sm font-semibold">基本信息</h3>
    <dl class="mt-4 grid grid-cols-2 gap-4">
      <div v-for="field in fields" :key="field.label" class="min-w-0" :class="{ 'col-span-2': field.wide }">
        <dt class="flex items-center gap-1.5 text-xs text-slate-500"><component :is="field.icon" class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />{{ field.label }}</dt>
        <dd class="mt-1 break-words text-sm font-medium text-slate-900" :class="{ 'font-mono tabular-nums': field.identifier }">{{ field.value || '—' }}</dd>
      </div>
    </dl>
  </section>
</template>
