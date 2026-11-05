import { computed, onBeforeUnmount, shallowRef, watch } from "vue";
import { readStoredSession } from "@/api/client";
import { fetchMobileRecords, type MobileRecordType } from "@/api/mobile";

export function usePagedRecords<T extends { id: number }>(type: () => MobileRecordType, pageSize = 20) {
  const rows = shallowRef<T[]>([]);
  const total = shallowRef(0);
  const loading = shallowRef(false);
  const error = shallowRef("");
  const hasMore = computed(() => rows.value.length < total.value);
  let page = 0;
  let generation = 0;

  async function load(reset = false): Promise<void> {
    if (loading.value && !reset) return;
    const token = ++generation;
    const userId = readStoredSession()?.user.userId;
    const nextPage = reset ? 1 : page + 1;
    loading.value = true;
    error.value = "";
    try {
      const response = await fetchMobileRecords<T>(type(), nextPage, pageSize);
      if (token !== generation || userId !== readStoredSession()?.user.userId) return;
      rows.value = [...new Map([...(reset ? [] : rows.value), ...response.items].map(item => [item.id, item])).values()];
      page = response.page;
      total.value = response.total;
    } catch (reason) {
      if (token === generation) error.value = reason instanceof Error ? reason.message : "历史记录加载失败，请重试";
    } finally { if (token === generation) loading.value = false; }
  }

  function syncPreview(preview: readonly T[], recordCount?: number): void {
    if (!page || loading.value) return;
    const ids = new Set(preview.map(item => item.id));
    rows.value = [...preview, ...rows.value.filter(item => !ids.has(item.id))];
    if (typeof recordCount === "number") total.value = recordCount;
  }

  watch(type, () => {
    rows.value = []; total.value = 0; page = 0;
    void load(true);
  });
  onBeforeUnmount(() => { generation += 1; });
  return { rows, total, loading, error, hasMore, load, syncPreview };
}
