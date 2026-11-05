import { computed, readonly, shallowRef } from "vue";
import { fetchMobileWorkspace, updateMobileTask } from "@/api/mobile";
import type {
  JsonRecord,
  MobileTask,
  MobileTaskUpdate,
  MobileWorkspace,
  ProductManual,
} from "@/api/types";

const workspace = shallowRef<MobileWorkspace | null>(null);
const loading = shallowRef(false);
const error = shallowRef("");
let loadPromise: Promise<MobileWorkspace> | null = null;
let workspaceGeneration = 0;

function normalizeTask(row: MobileWorkspace["tasks"][number]): MobileTask {
  return {
    ...row,
    id: row.assignment.id,
    projectId: row.project.id,
    projectName: row.project.name,
    serviceType: row.project.serviceType,
    serviceTypeLabel: row.project.serviceTypeLabel || row.project.serviceType,
    nodeId: row.node.id,
    nodeKey: row.node.nodeKey,
    nodeName: row.node.name,
    assignmentStatus: row.assignment.status,
  };
}

const tasks = computed(() => (workspace.value?.tasks || [])
  .map(normalizeTask)
  .filter((task) => task.serviceType !== "presales"));

export function taskSubmission(task: MobileTask): JsonRecord {
  const submissions = task.node.businessData?.fieldSubmissions;
  if (!submissions || typeof submissions !== "object") return {};
  const value = (submissions as JsonRecord)[String(task.id)];
  return value && typeof value === "object" ? value as JsonRecord : {};
}

export function taskDraft(task: MobileTask): JsonRecord {
  const drafts = task.node.businessData?.fieldDrafts;
  if (!drafts || typeof drafts !== "object") return {};
  const value = (drafts as JsonRecord)[String(task.id)];
  return value && typeof value === "object" ? value as JsonRecord : {};
}

export type TaskGroup = "pending" | "active" | "completed";

export function taskTiming(task: MobileTask, now = Date.now()): { group: TaskGroup; label: string; detail: string } {
  const submitted = taskSubmission(task).submitted === true;
  const done = task.assignmentStatus === "completed" || submitted || task.node.status === "completed";
  if (done) return { group: "completed", label: "已完成", detail: "已上传管理端" };
  const start = Date.parse(String(task.node.actualStartAt || ""));
  if (task.node.status !== "active" || !Number.isFinite(start)) {
    return { group: "pending", label: "待进行", detail: "等待管理端确认开始" };
  }
  const end = Date.parse(String(task.node.plannedEndAt || ""));
  if (!Number.isFinite(end)) return { group: "active", label: "进行中", detail: "未设置计划完成时间" };
  const difference = end - now;
  const absoluteMinutes = Math.max(0, Math.floor(Math.abs(difference) / 60_000));
  const days = Math.floor(absoluteMinutes / 1440);
  const hours = Math.floor((absoluteMinutes % 1440) / 60);
  const detail = `${days}天${hours}小时`;
  return difference < 0
    ? { group: "active", label: "已超时", detail: `已超时 ${detail}` }
    : { group: "active", label: "进行中", detail: `剩余 ${detail}` };
}

export async function loadMobileTasks(options: { force?: boolean; silent?: boolean } = {}): Promise<MobileWorkspace> {
  if (loadPromise) return loadPromise;
  const requestGeneration = workspaceGeneration;
  if (!options.silent) {
    loading.value = true;
    error.value = "";
  }
  const request = fetchMobileWorkspace()
    .then((data) => {
      if (requestGeneration === workspaceGeneration) {
        workspace.value = data;
        error.value = "";
      }
      return data;
    })
    .catch((reason: unknown) => {
      if (requestGeneration === workspaceGeneration && !options.silent) {
        error.value = reason instanceof Error ? reason.message : "现场任务加载失败";
      }
      throw reason;
    })
    .finally(() => {
      if (requestGeneration === workspaceGeneration && !options.silent) loading.value = false;
      if (loadPromise === request) loadPromise = null;
    });
  loadPromise = request;
  return request;
}

export function resetMobileTasks(): void {
  workspaceGeneration += 1;
  workspace.value = null;
  loading.value = false;
  error.value = "";
  loadPromise = null;
}

export function mergeTaskUpdate(assignmentId: number, response: MobileTaskUpdate): void {
  const current = workspace.value;
  if (!current) return;
  workspace.value = {
    ...current,
    tasks: current.tasks.map((row) => row.assignment.id === assignmentId ? {
      ...row,
      assignment: response.item.assignment || row.assignment,
      node: response.item.node || row.node,
    } : row),
  };
}

export async function saveMobileTask(assignmentId: number, payload: Record<string, unknown>): Promise<MobileTaskUpdate> {
  const requestGeneration = workspaceGeneration;
  const response = await updateMobileTask(assignmentId, payload);
  if (requestGeneration === workspaceGeneration) mergeTaskUpdate(assignmentId, response);
  return response;
}

export function manualsForTask(task: MobileTask): ProductManual[] {
  return (workspace.value?.productManuals || []).filter((manual) => (
    manual.projectId === task.projectId && manual.nodeKey === task.nodeKey
  ));
}

export function useMobileTasks() {
  return {
    workspace: readonly(workspace),
    tasks,
    loading: readonly(loading),
    error: readonly(error),
    loadMobileTasks,
    resetMobileTasks,
    saveMobileTask,
    manualsForTask,
  };
}
