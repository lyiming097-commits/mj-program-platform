<script setup>
import { INACTIVE_EMPLOYEE_PAGE_SIZE } from "./useInactiveEmployeePagination";

defineProps({
  page: { type: Number, required: true },
  totalPages: { type: Number, required: true },
  visiblePages: { type: Array, required: true },
  total: { type: Number, required: true },
});
const emit = defineEmits(["change"]);
</script>

<template>
  <nav class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-slate-200 bg-white px-3 py-2" aria-label="离职人员分页">
    <span class="text-xs text-slate-500">共 {{ total }} 人 · 每页 {{ INACTIVE_EMPLOYEE_PAGE_SIZE }} 人</span>
    <div class="flex items-center gap-1 rounded-md border border-slate-100 bg-slate-50 p-0.5">
      <button type="button" class="rounded px-2.5 py-1 text-xs text-slate-600 hover:bg-white hover:text-blue-600 disabled:cursor-not-allowed disabled:opacity-40" :disabled="page <= 1" @click="emit('change', page - 1)">上一页</button>
      <span class="px-1 text-xs tabular-nums text-slate-700 sm:hidden" aria-live="polite">第 {{ page }} / {{ totalPages }} 页</span>
      <template v-for="item in visiblePages" :key="item">
        <span v-if="typeof item === 'string'" class="hidden px-1 text-xs text-slate-400 sm:inline" aria-hidden="true">...</span>
        <button
          v-else
          type="button"
          class="hidden min-w-7 rounded px-1.5 py-1 text-xs font-medium sm:inline-block"
          :class="item === page ? 'bg-white text-blue-600 shadow-sm ring-1 ring-slate-200/50' : 'text-slate-600 hover:bg-white hover:text-blue-600'"
          :aria-label="`第 ${item} 页`"
          :aria-current="item === page ? 'page' : undefined"
          @click="emit('change', item)"
        >{{ item }}</button>
      </template>
      <button type="button" class="rounded px-2.5 py-1 text-xs text-slate-600 hover:bg-white hover:text-blue-600 disabled:cursor-not-allowed disabled:opacity-40" :disabled="page >= totalPages" @click="emit('change', page + 1)">下一页</button>
    </div>
  </nav>
</template>
