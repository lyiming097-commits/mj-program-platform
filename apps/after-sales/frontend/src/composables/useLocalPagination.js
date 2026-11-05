import { computed, reactive, ref, watch } from "vue";

export function useLocalPagination(rows) {
  const page = ref(1);
  const pageSize = ref(20);
  const total = computed(() => rows.value.length);
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)));
  watch([rows, pageSize], () => { page.value = 1; });
  return reactive({
    page, pageSize, total, totalPages,
    rows: computed(() => rows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value)),
  });
}
