import { computed, ref } from "vue";
import { apiGet } from "@/api";
import { formatOrganizationSyncTime } from "@/organization-sync-time";

export function useOrganizationSyncTime() {
  const lastSyncedAt = ref("");
  const status = ref("idle");
  const syncRun = ref(null);
  let requestId = 0;

  const lastSyncLabel = computed(() => {
    if (status.value === "loading") return "上次同步：读取中...";
    if (status.value === "error") return "上次同步：获取失败";
    if (!lastSyncedAt.value) return "上次同步：暂无记录";
    return `上次同步：${formatOrganizationSyncTime(lastSyncedAt.value) || "时间不可用"}`;
  });

  async function refreshLastSyncTime() {
    const currentRequestId = ++requestId;
    status.value = "loading";
    try {
      const response = await apiGet("/api/dingtalk/sync_contacts/status");
      if (currentRequestId !== requestId) return;
      lastSyncedAt.value = typeof response?.lastSyncedAt === "string" ? response.lastSyncedAt : "";
      syncRun.value = response?.syncRun || null;
      status.value = "loaded";
    } catch {
      if (currentRequestId === requestId) status.value = "error";
    }
  }

  return { lastSyncLabel, refreshLastSyncTime, syncRun, status };
}
