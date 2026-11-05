import { apiGet, apiPost } from "@/api";


function wait(delayMs) {
  return new Promise((resolve) => window.setTimeout(resolve, delayMs));
}

export async function runOrganizationSync({ onProgress = null, isCancelled = null } = {}) {
  const accepted = await apiPost("/api/dingtalk/sync_contacts");
  const runId = String(accepted?.syncRun?.runId || "").trim();
  if (!runId) {
    throw new Error("同步任务未返回 runId");
  }
  onProgress?.(accepted.syncRun);

  const deadline = Date.now() + 25 * 60 * 1000;
  while (Date.now() < deadline) {
    if (isCancelled?.()) {
      return null;
    }
    await wait(1500);
    const data = await apiGet(`/api/dingtalk/sync_contacts/status/${encodeURIComponent(runId)}`);
    const syncRun = data?.syncRun || null;
    onProgress?.(syncRun);
    if (syncRun?.status === "succeeded") {
      return syncRun.summary || {};
    }
    if (syncRun?.status === "failed") {
      throw new Error(syncRun.error || "组织架构同步失败");
    }
  }
  throw new Error("组织架构同步等待超时，任务可能仍在后台运行");
}
