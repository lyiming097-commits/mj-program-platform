import { computed, onBeforeUnmount, onMounted, shallowRef, watch } from "vue";
import { loginSessionIdentityKey } from "@platform-ui";
import { CRM_SYNC_POLL_DELAYS, projectListIdentity } from "@/projectListCache";
import { serviceApi } from "@/serviceApi";
import { PRESALES_STATISTIC_DIMENSIONS } from "@/presalesStatistics";

export function usePresalesStatistics(props) {
  const groupBy = shallowRef("all");
  const groupKey = shallowRef("");
  const search = shallowRef("");
  const appliedSearch = shallowRef("");
  const status = shallowRef("");
  const page = shallowRef(1);
  const pageSize = shallowRef(20);
  const data = shallowRef(null);
  const loading = shallowRef(false);
  const error = shallowRef("");
  const identity = computed(() => `${loginSessionIdentityKey(props.session)}:${projectListIdentity(props.session)}`);
  const params = computed(() => ({ groupBy: groupBy.value, groupKey: groupKey.value,
    search: appliedSearch.value, status: status.value, page: page.value, pageSize: pageSize.value }));
  let requestSequence = 0;
  let disposed = false;
  let searchTimer;
  let pollTimer;
  let scopeTimer;
  let syncAttempt = 0;
  let inFlight = 0;
  let restoringLocation = false;

  // Keep statistics state separate from the retained project's list filters.
  function restoreLocation() {
    if (!window.location.pathname.includes("/presales/")) return;
    restoringLocation = true;
    const query = new URLSearchParams(window.location.search);
    groupBy.value = PRESALES_STATISTIC_DIMENSIONS.some(row => row.value === query.get("statView")) ? query.get("statView") : "all";
    groupKey.value = query.get("statGroup") || "";
    search.value = query.get("statSearch") || "";
    appliedSearch.value = search.value.trim();
    status.value = ["in_progress", "completed", "blocked", "draft", "cancelled"].includes(query.get("statStatus")) ? query.get("statStatus") : "";
    page.value = Math.min(100000, Math.max(1, Number.parseInt(query.get("statPage"), 10) || 1));
    const size = Number(query.get("statPageSize"));
    pageSize.value = [20, 50, 100].includes(size) ? size : 20;
    restoringLocation = false;
  }
  function writeLocation() {
    const url = new URL(window.location.href);
    const values = { statView: groupBy.value === "all" ? "" : groupBy.value,
      statGroup: groupKey.value, statSearch: appliedSearch.value, statStatus: status.value,
      statPage: page.value === 1 ? "" : page.value, statPageSize: pageSize.value === 20 ? "" : pageSize.value };
    for (const [key, value] of Object.entries(values)) {
      if (value === "") url.searchParams.delete(key);
      else url.searchParams.set(key, String(value));
    }
    window.history.replaceState(window.history.state, "", url);
  }
  restoreLocation();

  function schedulePoll() {
    window.clearTimeout(pollTimer);
    if (disposed || !props.active) return;
    const pending = data.value?.crmSyncing || (data.value?.crmScopeReady === false && !data.value?.crmSyncError);
    const delay = pending ? CRM_SYNC_POLL_DELAYS[Math.min(syncAttempt++, CRM_SYNC_POLL_DELAYS.length - 1)] : 30000;
    if (!pending) syncAttempt = 0;
    pollTimer = window.setTimeout(() => {
      if (document.hidden || inFlight) schedulePoll();
      else void load({ silent: true });
    }, delay);
  }

  async function load({ silent = false } = {}) {
    if (!props.active || disposed) return;
    window.clearTimeout(pollTimer);
    const sequence = ++requestSequence;
    const requestedIdentity = identity.value;
    inFlight += 1;
    if (!silent) loading.value = true;
    error.value = "";
    try {
      const response = await serviceApi.presalesStatistics(params.value);
      if (disposed || sequence !== requestSequence || requestedIdentity !== identity.value || !props.active) return;
      window.clearTimeout(scopeTimer);
      data.value = response;
      const expiresAt = Date.parse(response.crmScopeExpiresAt || "");
      if (response.crmScopeReady && Number.isFinite(expiresAt)) {
        scopeTimer = window.setTimeout(() => {
          requestSequence += 1;
          data.value = null;
          void load();
        }, Math.max(0, expiresAt - Date.now()));
      }
      if (groupKey.value && !response.groups.some(row => row.key === groupKey.value)) {
        groupKey.value = "";
        page.value = 1;
      }
    } catch (reason) {
      if (disposed || sequence !== requestSequence || requestedIdentity !== identity.value) return;
      error.value = reason instanceof Error ? reason.message : "售前统计加载失败";
      // A failed scope check must never leave another account's figures visible.
      data.value = null;
    } finally {
      inFlight -= 1;
      if (sequence === requestSequence) { loading.value = false; schedulePoll(); }
    }
  }

  function selectDimension(value) {
    groupBy.value = value;
    groupKey.value = "";
    page.value = 1;
  }
  function selectGroup(value) { groupKey.value = value; page.value = 1; }
  function focusRefresh() { if (document.visibilityState === "visible" && !inFlight) void load({ silent: true }); }

  watch(search, value => {
    window.clearTimeout(searchTimer);
    if (restoringLocation) return;
    searchTimer = window.setTimeout(() => { appliedSearch.value = value.trim(); page.value = 1; }, 300);
  }, { flush: "sync" });
  watch([status, pageSize], () => { if (!restoringLocation) { groupKey.value = ""; page.value = 1; } }, { flush: "sync" });
  watch(identity, () => {
    requestSequence += 1;
    window.clearTimeout(scopeTimer);
    data.value = null;
    error.value = "";
  }, { flush: "sync" });
  watch(() => JSON.stringify([props.active, identity.value, params.value, props.refreshKey]), () => {
    if (props.active) { writeLocation(); void load(); }
    else { requestSequence += 1; loading.value = false; window.clearTimeout(pollTimer); }
  }, { immediate: true });
  onMounted(() => {
    window.addEventListener("focus", focusRefresh);
    window.addEventListener("popstate", restoreLocation);
    document.addEventListener("visibilitychange", focusRefresh);
  });
  onBeforeUnmount(() => {
    disposed = true;
    window.clearTimeout(searchTimer);
    window.clearTimeout(pollTimer);
    window.clearTimeout(scopeTimer);
    window.removeEventListener("focus", focusRefresh);
    window.removeEventListener("popstate", restoreLocation);
    document.removeEventListener("visibilitychange", focusRefresh);
  });

  return { groupBy, groupKey, search, status, page, pageSize, data, loading, error,
    load, selectDimension, selectGroup };
}
