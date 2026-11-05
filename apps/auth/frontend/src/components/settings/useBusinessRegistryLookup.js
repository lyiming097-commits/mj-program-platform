import { computed, onBeforeUnmount, reactive, ref } from "vue";
import { apiGet, apiPost } from "@/api";

const base = "/api/org/business-registry";

function newRequestId() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  // Local network HTTP supports getRandomValues even when randomUUID is unavailable.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join("-");
}

// Each field owns its query pages and retry IDs; only configuration and the saved list are shared.
export function useBusinessRegistryLookup({ configured, onResults }) {
  const keyword = ref("");
  const selectedCompany = ref(null);
  const selectedCompanies = ref([]);
  const pages = ref([]);
  const latest = ref(null);
  const searching = ref(false);
  const refreshing = ref(false);
  const loadingMore = ref(false);
  const error = ref("");
  const moreError = ref("");
  const morePending = ref(null);
  let pendingRequest = null;
  let moreRequest = null;
  let alive = true;
  const busy = computed(() => searching.value || refreshing.value || loadingMore.value);
  const lastPage = computed(() => pages.value.at(-1));
  const result = computed(() => pages.value.length
    ? { ...pages.value[0], companies: pages.value.flatMap((page) => page.companies || []) }
    : latest.value);
  const hasMoreResults = computed(() => {
    const page = lastPage.value;
    return page?.status === "succeeded" && page.resultCount > 0 && (page.totalRecords == null
      ? page.resultCount === page.pageSize : page.pageNum * page.pageSize < page.totalRecords);
  });
  const hasMore = computed(() => hasMoreResults.value && lastPage.value.pageNum < 100);
  const endMessage = computed(() => hasMoreResults.value && lastPage.value.pageNum >= 100 ? "已达查询上限" : "已全部加载");

  function resetPages() {
    pages.value = [];
    latest.value = null;
    error.value = "";
    moreError.value = "";
    morePending.value = null;
    moreRequest = null;
  }
  function reset() {
    if (busy.value) return;
    resetPages();
    selectedCompany.value = null;
    selectedCompanies.value = [];
  }
  function accept(value) {
    latest.value = value;
    if (["succeeded", "empty"].includes(value.status) && !pages.value.some((page) => page.pageNum === value.pageNum)) pages.value.push(value);
  }
  async function search() {
    if (busy.value || configured.value !== true) return;
    const normalized = keyword.value.trim();
    if (!normalized || normalized.length > 200) {
      error.value = "请输入企业名称、信用代码或注册号，最多 200 字";
      return;
    }
    searching.value = true;
    resetPages();
    selectedCompany.value = null;
    const parameters = { keyword: normalized, pageNum: 1, pageSize: 20 };
    const signature = JSON.stringify(parameters);
    try {
      // A transport retry checks the original saved request instead of billing twice.
      if (pendingRequest?.signature !== signature) pendingRequest = { signature, requestId: newRequestId() };
      const value = await apiPost(`${base}/search`, { ...parameters, requestId: pendingRequest.requestId }, { timeoutMs: 40000 });
      if (!alive) return;
      if (value.status !== "running") pendingRequest = null;
      accept(value);
      if (value.status === "failed") error.value = value.message;
      keyword.value = normalized;
      await onResults();
    } catch (reason) {
      if (!alive) return;
      error.value = `${reason.message || "请求失败"}。可先查看查询记录；相同条件再次提交会检查原请求结果。`;
      if (reason.code === "REGISTRY_NOT_CONFIGURED") configured.value = false;
      void onResults();
    } finally {
      if (alive) searching.value = false;
    }
  }
  async function refresh(id) {
    if (busy.value) return;
    refreshing.value = true;
    error.value = "";
    try {
      const value = await apiGet(`${base}/queries/${id}`);
      if (!alive) return;
      accept(value);
      if (value.status === "failed") error.value = value.message;
      if (value.status !== "running" && pendingRequest?.requestId === value.requestId) pendingRequest = null;
      void onResults();
    } catch (reason) {
      if (alive) error.value = reason.message || "查询状态加载失败";
    } finally {
      if (alive) refreshing.value = false;
    }
  }
  async function loadMore(refresh = false) {
    if (busy.value || !hasMore.value || configured.value !== true) return;
    if (refresh ? !morePending.value : morePending.value) return;
    const previous = lastPage.value;
    const parameters = { keyword: previous.keyword, pageNum: previous.pageNum + 1, pageSize: previous.pageSize };
    loadingMore.value = true;
    moreError.value = "";
    try {
      let value;
      if (refresh) value = await apiGet(`${base}/queries/${morePending.value.id}`);
      else {
        moreRequest ||= { ...parameters, requestId: newRequestId() };
        value = await apiPost(`${base}/search`, moreRequest, { timeoutMs: 40000 });
      }
      if (!alive) return;
      accept(value);
      morePending.value = value.status === "running" ? value : null;
      if (value.status !== "running") moreRequest = null;
      if (value.status === "failed") moreError.value = value.message || "加载失败，请重试。";
      void onResults();
    } catch (reason) {
      if (!alive) return;
      moreError.value = refresh ? (reason.message || "查询状态加载失败，请刷新重试。")
        : `${reason.message || "加载失败"}。点击重试会检查原请求结果。`;
      if (reason.code === "REGISTRY_NOT_CONFIGURED") configured.value = false;
      void onResults();
    } finally {
      if (alive) loadingMore.value = false;
    }
  }
  onBeforeUnmount(() => { alive = false; });
  return reactive({ keyword, selectedCompany, selectedCompanies, result, searching, refreshing, busy,
    error, loadingMore, moreError, morePending, hasMore, endMessage, search, refresh, loadMore, reset });
}
