<script setup>
import { computed } from "vue";

const props = defineProps({
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  total: { type: Number, default: 0 },
  totalPages: { type: Number, default: 1 },
  loading: { type: Boolean, default: false },
  label: { type: String, default: "列表分页" },
  sizeLabel: { type: String, default: "每页条数" },
});
const emit = defineEmits(["change", "update:pageSize"]);
const selectedPageSize = computed({
  get: () => props.pageSize,
  set: value => emit("update:pageSize", value),
});
const visiblePages = computed(() => {
  const values = [...new Set([1, props.totalPages, props.page - 1, props.page, props.page + 1])]
    .filter(value => value >= 1 && value <= props.totalPages).sort((a, b) => a - b);
  return values.flatMap((value, index) => index && value - values[index - 1] > 1 ? [`gap-${value}`, value] : [value]);
});
function changePage(value) {
  if (props.loading || value < 1 || value > props.totalPages || value === props.page) return;
  emit("change", value);
}
</script>

<template>
  <footer class="as-project-pagination">
    <span role="status">共 {{ total }} 条</span>
    <nav class="as-segmented" :aria-label="label">
      <button type="button" :disabled="loading || page <= 1" @click="changePage(page - 1)">上一页</button>
      <template v-for="value in visiblePages" :key="value">
        <span v-if="typeof value === 'string'" aria-hidden="true">…</span>
        <button v-else type="button" :class="{ active: value === page }" :aria-current="value === page ? 'page' : undefined" :aria-label="`第 ${value} 页`" :disabled="loading" @click="changePage(value)">{{ value }}</button>
      </template>
      <button type="button" :disabled="loading || page >= totalPages" @click="changePage(page + 1)">下一页</button>
    </nav>
    <label class="as-project-page-size">每页<select v-model.number="selectedPageSize" :aria-label="sizeLabel" :disabled="loading"><option :value="20">20 条</option><option :value="50">50 条</option><option :value="100">100 条</option></select></label>
  </footer>
</template>
