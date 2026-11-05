<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from "vue";
import {
  ArrowLeft,
  CalendarDays,
  Check,
  ChevronRight,
  CircleAlert,
  Clock3,
  Gift,
  Headphones,
  Home,
  LoaderCircle,
  PackageCheck,
  Paperclip,
  Phone,
  Plus,
  Send,
  ShieldCheck,
  TicketCheck,
  UserRound,
  UserRoundCheck,
} from "@lucide/vue";
import { collectionRows, normalizeDatabaseId, serviceApi } from "@/serviceApi";
import { MAX_ATTACHMENT_MB, MAX_ATTACHMENT_SIZE } from "@/attachmentLimits";
import AttachmentPanel from "@/components/AttachmentPanel.vue";
import DateField from "@/components/DateField.vue";
import FileSelectionPanel from "@/components/FileSelectionPanel.vue";
import GlobalNotice from "@/components/GlobalNotice.vue";
import MobileSubmissionHistory from "@/components/MobileSubmissionHistory.vue";
import MobileTaskMaterials from "@/components/MobileTaskMaterials.vue";
import { useDebouncedAutosave } from "@/composables/useDebouncedAutosave";

const props = defineProps({ session: { type: Object, default: null } });
const TASK_DRAFT_STORAGE_PREFIX = "mj.afterSales.fieldTaskDraft";

const loading = ref(true);
const saving = ref(false);
const error = ref("");
const success = ref("");
const workspace = ref({});
const activeTab = ref("tasks");
const taskGroup = ref("pending");
const taskServiceType = shallowRef("all");
const selectedTaskId = ref("");
const taskProofs = ref([]);
const taskProofLoading = ref(false);
const feedbackMode = ref("feedback");
const feedbackView = ref("history");
const profileEditing = ref(false);
const now = ref(Date.now());
const taskSubmitting = shallowRef(false);
const presalesProgressSubmitting = shallowRef(false);
let timer = null;
let workspaceSyncTimer = null;
let workspaceSyncInFlight = false;
let touchStart = null;

const providerForm = reactive({ name: "", role: "installer", phone: "", city: "", regions: "", skills: "", bio: "", files: [] });
const taskForm = reactive({ actualEndAt: "", actualFee: "", actualFeeNote: "", note: "", progressRounds: [], progressSubmitted: false, progressSubmittedAt: "" });
const form = reactive({ task_id: "", type: "issue", project_id: "", node_key: "", title: "", content: "", priority: "medium", files: [] });
const {
  reset: resetTaskDraftAutosave,
  schedule: scheduleTaskDraftAutosave,
  flush: flushTaskDraftAutosave,
} = useDebouncedAutosave(
  (draft) => {
    const values = { ...draft.values };
    delete values.schemeRounds;
    delete values.progressSubmittedAt;
    return serviceApi.updateMobileTask(draft.assignmentId, { draft: true, ...values });
  },
  {
    delay: 700,
    onError: (reason) => {
      error.value = reason instanceof Error ? reason.message : "现场资料同步失败，已保留本机草稿";
    },
  },
);
const MIDSALES_PROOF_NODE_KEYS = new Set([
  "construction-work",
  "furniture-install",
  "device-install",
  "device-debug",
  "school-support",
]);
const MIDSALES_RELATED_PRODUCT_NODE_KEYS = new Set([
  "construction-work",
  "furniture-install",
  "device-install",
  "device-debug",
  "school-support",
  "project-acceptance",
]);
const AFTERSALES_ATTACHMENT_GROUPS = [
  ["package", "包装照片"],
  ["model_label", "型号标签"],
  ["appearance", "产品外观"],
  ["installation", "安装完成"],
  ["debugging", "调试完成"],
  ["other", "其他附件"],
];
const FEEDBACK_TYPE_OPTIONS = [
  { value: "issue", label: "现场问题" },
  { value: "resource_suggestion", label: "资料建议" },
  { value: "reward_application", label: "奖励申请" },
];
const TICKET_TYPE_OPTIONS = [
  { value: "现场问题", label: "现场问题" },
  { value: "设备故障", label: "设备故障" },
  { value: "客户协调", label: "客户协调" },
];
const TASK_SERVICE_TYPE_OPTIONS = Object.freeze([
  { value: "all", label: "全部" },
  { value: "midsales", label: "售中" },
  { value: "aftersales", label: "售后" },
]);
const tasks = computed(() => collectionRows(workspace.value.tasks || workspace.value.assignments).map((task) => {
  if (!task?.assignment && !task?.project && !task?.node) return task;
  const assignment = task.assignment || {};
  const project = task.project || {};
  const node = task.node || {};
  return {
    ...project,
    ...assignment,
    id: assignment.id || task.id,
    project,
    assignment,
    node,
    nodes: Array.isArray(task.nodes) && task.nodes.length
      ? task.nodes
      : Array.isArray(project.nodes) && project.nodes.length ? project.nodes : [node],
    projectId: project.id,
    projectName: project.name,
    projectStatus: project.status,
    currentNodeKey: project.currentNodeKey || project.current_node_key || "",
    serviceType: project.serviceType,
    serviceTypeLabel: project.serviceTypeLabel,
    nodeId: node.id,
    nodeKey: node.nodeKey,
    nodeName: node.name,
    status: node.status || assignment.status,
    statusLabel: node.statusLabel || assignment.statusLabel,
    assignmentStatus: assignment.status,
    assignmentStatusLabel: assignment.statusLabel,
    plannedStartDate: assignment.plannedStartDate || assignment.planned_start_date || "",
    standardDuration: assignment.standardDuration || assignment.standard_duration || "",
    plannedStartAt: node.plannedStartAt || node.planned_start_at
      || assignment.plannedStartDate || assignment.planned_start_date || "",
    plannedEndAt: node.plannedEndAt,
    address: project.address,
    managerName: assignment.providerName || assignment.provider?.name || project.ownerName,
  };
}).filter((task) => task.serviceType !== "presales"));
const productManuals = computed(() => collectionRows(workspace.value.productManuals));
const rewards = computed(() => collectionRows(workspace.value.rewards));
const profile = computed(() => workspace.value.profile || workspace.value.member || props.session?.serviceProvider || {});
const submittedFeedback = computed(() => collectionRows(workspace.value.feedback));
const submittedTickets = computed(() => {
  const currentUserId = String(profile.value?.authUserId || props.session?.userId || "");
  if (!currentUserId) return [];
  return collectionRows(workspace.value.tickets).filter((ticket) => (
    String(ticket.reporterUserId || "") === currentUserId
  ));
});
const records = computed(() => {
  const direct = collectionRows(workspace.value.service_records || workspace.value.serviceRecords || workspace.value.history);
  if (direct.length) return direct;
  return [...collectionRows(workspace.value.feedback), ...collectionRows(workspace.value.tickets)];
});
const providerCertified = computed(() => profile.value?.certificationStatus === "certified");
const selectedTask = computed(() => tasks.value.find((item) => String(item.id) === String(selectedTaskId.value)) || null);
const selectedTaskMaterials = computed(() => {
  if (!selectedTask.value) return [];
  const projectId = String(selectedTask.value.projectId || selectedTask.value.project_id || "").trim();
  const nodeKey = taskNodeKey(selectedTask.value);
  return productManuals.value.filter((material) => {
    const materialProjectId = String(material?.projectId || material?.project_id || "").trim();
    const materialNodeKey = String(material?.nodeKey || material?.node_key || "").trim();
    return Boolean(projectId && materialProjectId === projectId && materialNodeKey === nodeKey);
  });
});
const selectedTaskUsesProofs = computed(() => MIDSALES_PROOF_NODE_KEYS.has(taskNodeKey(selectedTask.value)));
const selectedTaskIsPresales = computed(() => selectedTask.value?.serviceType === "presales");
const selectedTaskIsAftersales = computed(() => selectedTask.value?.serviceType === "aftersales");
const selectedTaskSupportsRelatedProducts = computed(() => (
  selectedTaskIsAftersales.value
  || (
    selectedTask.value?.serviceType === "midsales"
    && MIDSALES_RELATED_PRODUCT_NODE_KEYS.has(taskNodeKey(selectedTask.value))
  )
));
const selectedTaskSubmitted = computed(() => Boolean(taskSubmission(selectedTask.value).submitted));
const selectedTaskEditable = computed(() => taskCanOperate(selectedTask.value) && !selectedTaskSubmitted.value);
const taskActualStartAt = computed(() => {
  return taskActualStart(selectedTask.value);
});
const calculatedActualDuration = computed(() => actualDurationText(taskActualStartAt.value, taskForm.actualEndAt));
const uploadedTaskProofs = computed(() => taskProofs.value.filter((proof) => (
  Array.isArray(proof?.attachments) && proof.attachments.length > 0
)).length);
const feedbackTasks = computed(() => tasks.value.filter(taskCanOperate));
const feedbackTask = computed(() => feedbackTasks.value.find((item) => String(item.id) === String(form.task_id)) || null);
const feedbackTypeOptions = computed(() => feedbackMode.value === "feedback" ? FEEDBACK_TYPE_OPTIONS : TICKET_TYPE_OPTIONS);
const visibleTasks = computed(() => tasks.value.filter((task) => {
  return taskTiming(task).group === taskGroup.value
    && (taskServiceType.value === "all" || task.serviceType === taskServiceType.value);
}));

const navItems = [
  { id: "tasks", label: "任务", icon: Home },
  { id: "feedback", label: "反馈", icon: CircleAlert },
  { id: "profile", label: "我的", icon: UserRound },
];

function display(item, ...keys) {
  for (const key of keys) {
    const value = item?.[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return "-";
}

function taskStatus(task) {
  return taskTiming(task).label;
}

function timeValue(raw) {
  const value = raw ? new Date(raw).getTime() : NaN;
  return Number.isFinite(value) ? value : null;
}

function durationText(delta) {
  const absolute = Math.abs(delta);
  const days = Math.floor(absolute / 86400000);
  const hours = Math.floor((absolute % 86400000) / 3600000);
  const minutes = Math.floor((absolute % 3600000) / 60000);
  return days ? `${days}天 ${hours}小时` : `${hours}小时 ${minutes}分`;
}

function actualDurationText(startValue, endValue) {
  if (!startValue || !endValue) return "";
  const start = Math.floor(new Date(startValue).getTime() / 60000) * 60000;
  const end = Math.floor(new Date(endValue).getTime() / 60000) * 60000;
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "";
  const totalMinutes = Math.floor((end - start) / 60000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  return `${days}天${hours}小时${minutes}分钟`;
}

function taskTiming(task) {
  const nodeState = task?.status_code || task?.status || task?.state;
  const done = task?.assignmentStatus === "completed" || taskSubmission(task).submitted || ["completed", "closed", "已完成"].includes(nodeState);
  if (done) return { group: "completed", label: "已完成", countdown: "任务已完成", overdue: false };
  const current = ["active", "进行中"].includes(nodeState) && Boolean(
    task?.actualStartAt
    || task?.actual_start_at
    || task?.node?.actualStartAt
    || task?.node?.actual_start_at,
  );
  if (!current) return { group: "pending", label: "待进行", countdown: "等待管理端确认开始", overdue: false };
  const end = timeValue(taskPlannedEndValue(task) || taskPlannedEnd(task));
  if (end && end < now.value) {
    return { group: "active", label: "已超时", countdown: `已超时 ${durationText(end - now.value)}`, overdue: true };
  }
  if (end) return { group: "active", label: "进行中", countdown: `还有 ${durationText(end - now.value)} 结束`, overdue: false };
  return { group: "active", label: "进行中", countdown: "未设置计划完成时间", overdue: false };
}

function countdown(task) {
  return taskTiming(task).countdown;
}

function taskNodes(task) {
  const nodes = task?.nodes || task?.workflow?.nodes || task?.project?.nodes;
  return Array.isArray(nodes) ? nodes : [];
}

function nodeStatus(node) {
  const labels = { pending: "未开始", active: "进行中", completed: "已完成", skipped: "不包含" };
  return display(node, "statusLabel", "status_display", "statusDisplay") !== "-"
    ? display(node, "statusLabel", "status_display", "statusDisplay")
    : labels[node?.status] || node?.status || "-";
}

function taskPlan(task) {
  const start = taskPlannedStart(task);
  const end = taskPlannedEnd(task);
  if (!start && !end) return "-";
  return [start, end].filter(Boolean).join(" 至 ");
}

function taskInstruction(task) {
  const nodeData = currentNode(task)?.businessData || currentNode(task)?.business_data || {};
  return String(
    nodeData.deliveryNote
    || nodeData.delivery_note
    || task?.assignment?.note
    || task?.note
    || task?.project?.summary
    || task?.project?.description
    || task?.summary
    || "",
  ).trim() || "管理端尚未填写任务说明";
}

function taskProjectData(task) {
  return task?.project?.businessData
    || task?.project?.business_data
    || task?.businessData
    || task?.business_data
    || {};
}

function taskRelatedProducts(task) {
  const source = task?.serviceType === "aftersales"
    ? taskProjectData(task)
    : currentNode(task)?.businessData || currentNode(task)?.business_data || {};
  const products = source.relatedProducts;
  return Array.isArray(products) ? products : [];
}

function taskProductLabel(product) {
  if (typeof product === "string") return product;
  return [
    product?.name,
    product?.brand,
    product?.model,
  ].filter(Boolean).join(" · ") || "相关产品";
}

function taskFeeValue(value) {
  if (value === undefined || value === null || value === "") return "未填写";
  const amount = Number(value);
  return Number.isFinite(amount) ? `${amount.toFixed(2)} 元` : String(value);
}

function dateOnly(value) {
  const match = String(value || "").match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDateOnly(value) {
  const date = value instanceof Date ? value : dateOnly(value);
  if (!date) return "";
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function taskPlannedStart(task) {
  return formatDateOnly(
    task?.plannedStartAt
    || task?.planned_start_at
    || task?.plannedStartDate
    || task?.planned_start_date
    || task?.assignment?.plannedStartDate
    || task?.assignment?.planned_start_date
    || task?.node?.plannedStartAt
    || task?.node?.planned_start_at,
  );
}

function taskStandardDurationDays(task) {
  const raw = task?.standardDuration
    || task?.standard_duration
    || task?.assignment?.standardDuration
    || task?.assignment?.standard_duration;
  const match = String(raw || "").match(/\d+(?:\.\d+)?/);
  return match ? Math.max(1, Math.ceil(Number(match[0]))) : 0;
}

function taskPlannedEnd(task) {
  const explicit = task?.plannedEndAt
    || task?.planned_end_at
    || task?.node?.plannedEndAt
    || task?.node?.planned_end_at;
  if (task?.serviceType === "midsales") {
    return explicit ? formatDateOnly(explicit) : "";
  }
  if (explicit) return formatDateOnly(explicit);
  const start = dateOnly(taskPlannedStart(task));
  const duration = taskStandardDurationDays(task);
  if (!start || !duration) return "";
  start.setDate(start.getDate() + duration - 1);
  return formatDateOnly(start);
}

function taskActualStart(task) {
  const node = currentNode(task);
  return task?.actualStartAt
    || task?.actual_start_at
    || node?.actualStartAt
    || node?.actual_start_at
    || "";
}

function taskPlannedEndValue(task) {
  return task?.plannedEndAt
    || task?.planned_end_at
    || task?.node?.plannedEndAt
    || task?.node?.planned_end_at
    || "";
}

function taskPlannedStartLabel(task) {
  const start = taskPlannedStart(task);
  return start ? `计划开始时间：${start}` : "未设置计划开始时间";
}

function currentNode(task) {
  return task?.node || taskNodes(task).find((node) => [node.id, node.node_id, node.nodeId].includes(task.node_id || task.nodeId || task.current_node_id || task.currentNodeId)) || {};
}

function taskNodeKey(task) {
  return String(task?.nodeKey || task?.node_key || task?.node?.nodeKey || task?.node?.node_key || "");
}

function taskCanOperate(task) {
  return Boolean(
    task
    && ["assigned", "accepted", "in_progress"].includes(task.assignmentStatus)
    && ["active", "进行中"].includes(task.status)
    && Boolean(taskActualStart(task))
    && !["completed", "closed"].includes(task.status)
    && !["completed", "cancelled"].includes(task.projectStatus)
  );
}

function proofStatus(proof) {
  return proof?.status || "pending";
}

function proofStatusLabel(proof) {
  const labels = { pending: "未处理", approved: "通过", rejected: "驳回" };
  return proof?.statusLabel || proof?.status_label || labels[proofStatus(proof)] || proofStatus(proof);
}

function taskNodeAttachmentId(task = selectedTask.value) {
  return normalizeDatabaseId(task?.nodeId)
    || normalizeDatabaseId(task?.node_id)
    || normalizeDatabaseId(task?.node?.id);
}

function canUploadProof(proof) {
  return Boolean(proof?.canUpload ?? proof?.can_upload);
}

async function loadTaskProofs(task = selectedTask.value) {
  taskProofs.value = [];
  const projectId = task?.projectId || task?.project_id || task?.project?.id;
  const requestedNodeKey = taskNodeKey(task);
  const requestedTaskId = task?.id;
  if (!projectId || !MIDSALES_PROOF_NODE_KEYS.has(requestedNodeKey)) return;
  taskProofLoading.value = true;
  try {
    const rows = collectionRows(await serviceApi.listMidsalesProofs(projectId, requestedNodeKey, { source: "mobile" }));
    if (String(selectedTask.value?.id) !== String(requestedTaskId)) return;
    taskProofs.value = rows;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "证明材料加载失败";
  } finally {
    if (String(selectedTask.value?.id) === String(requestedTaskId)) taskProofLoading.value = false;
  }
}

function datetimeLocalValue(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function dateTimeLabel(value) {
  return value ? String(value).replace("T", " ").slice(0, 16) : "等待管理端确认开始";
}

function taskSubmission(task) {
  const data = currentNode(task)?.businessData || currentNode(task)?.business_data || {};
  return data.fieldSubmissions?.[String(task?.id)] || {};
}

function emptyPresalesProgressRound() {
  return { designDate: "", submitDate: "", note: "", attachmentIds: [], submittedAt: "" };
}

function normalizePresalesProgressRound(item = {}) {
  const round = {
    ...emptyPresalesProgressRound(),
    ...item,
    attachmentIds: Array.isArray(item.attachmentIds) ? item.attachmentIds.map(String) : [],
  };
  delete round.result;
  return round;
}

function mergePresalesProgressRounds(serverRounds, draftRounds) {
  const server = Array.isArray(serverRounds) ? serverRounds.map(normalizePresalesProgressRound) : [];
  const draft = Array.isArray(draftRounds) ? draftRounds.map(normalizePresalesProgressRound) : [];
  const length = Math.max(server.length, draft.length);
  return Array.from({ length }, (_, index) => {
    const serverRound = server[index] || {};
    const draftRound = draft[index] || {};
    return {
      ...emptyPresalesProgressRound(),
      ...serverRound,
      ...draftRound,
      attachmentIds: Array.isArray(draftRound.attachmentIds) && draftRound.attachmentIds.length
        ? [...draftRound.attachmentIds]
        : [...(serverRound.attachmentIds || [])],
      submittedAt: serverRound.submittedAt || draftRound.submittedAt || "",
      submitDate: serverRound.submitDate || draftRound.submitDate || "",
    };
  });
}

function taskDraftSnapshot(task = selectedTask.value) {
  if (!task?.id) return null;
  const values = {
    actualEndAt: taskForm.actualEndAt || null,
    actualDuration: calculatedActualDuration.value,
    note: taskForm.note.trim(),
    progressSubmittedAt: taskForm.progressSubmittedAt || "",
  };
  if (task.serviceType !== "presales") {
    values.actualFee = taskForm.actualFee === "" ? null : taskForm.actualFee;
  }
  if (MIDSALES_PROOF_NODE_KEYS.has(taskNodeKey(task)) || task.serviceType === "aftersales") {
    values.actualFeeNote = taskForm.actualFeeNote.trim();
  }
  if (task?.serviceType === "presales") {
    values.schemeRounds = taskForm.progressRounds.map((item) => ({ ...item, attachmentIds: [...item.attachmentIds] }));
  }
  return { assignmentId: task.id, values };
}

function taskDraftStorageKey(task) {
  const userId = props.session?.userId || props.session?.user_id || props.session?.id || "current";
  return `${TASK_DRAFT_STORAGE_PREFIX}:${userId}:${task?.id || ""}`;
}

function readTaskDraft(task) {
  if (!task?.id) return null;
  try {
    const value = JSON.parse(window.localStorage.getItem(taskDraftStorageKey(task)) || "null");
    return value && typeof value === "object" ? value : null;
  } catch {
    return null;
  }
}

function saveTaskDraft(draft) {
  if (!draft?.assignmentId) return;
  try {
    window.localStorage.setItem(
      taskDraftStorageKey({ id: draft.assignmentId }),
      JSON.stringify({ ...draft.values, savedAt: new Date().toISOString() }),
    );
  } catch {
    error.value = "现场草稿保存失败，请确认浏览器允许本地存储";
  }
}

function clearTaskDraft(task) {
  if (!task?.id) return;
  try { window.localStorage.removeItem(taskDraftStorageKey(task)); } catch { /* submitted data is already on the server */ }
}

function applyTaskUpdate(assignmentId, response) {
  const updated = response?.item || response;
  const row = collectionRows(workspace.value.tasks || workspace.value.assignments).find((item) => (
    String(item?.assignment?.id || item?.id) === String(assignmentId)
  ));
  if (!row || !updated) return;
  if (row.assignment && updated.assignment) Object.assign(row.assignment, updated.assignment);
  else if (updated.assignment) Object.assign(row, updated.assignment);
  if (row.node && updated.node) Object.assign(row.node, updated.node);
  else if (updated.node) Object.assign(row, updated.node);
}

let hydratingTaskForm = true;

function fillTaskForm(task = selectedTask.value) {
  hydratingTaskForm = true;
  const node = currentNode(task);
  const data = node?.businessData || node?.business_data || {};
  const submission = taskSubmission(task);
  const draft = submission.submitted ? null : readTaskDraft(task);
  const source = submission.submitted ? submission : draft || submission;
  const serverProgressRounds = Array.isArray(data.schemeRounds) ? data.schemeRounds : [];
  const serverProgressSubmittedAt = String(data.schemeProgressSubmittedAt || "");
  // Management owns the round list; a local draft cannot recreate cleared rounds.
  const draftProgressRounds = serverProgressRounds.length > 0
    && !(draft?.progressSubmittedAt && !serverProgressSubmittedAt)
    ? draft?.schemeRounds
    : null;
  const progressRounds = mergePresalesProgressRounds(serverProgressRounds, draftProgressRounds);
  const displayedProgressRounds = progressRounds.length || task?.serviceType !== "presales"
    ? progressRounds
    : [emptyPresalesProgressRound()];
  const draftProgressSubmittedAt = String(draft?.progressSubmittedAt || "");
  const rawSubmittedRoundCount = data.schemeProgressSubmittedRoundCount;
  const submittedRoundCount = rawSubmittedRoundCount === "" || rawSubmittedRoundCount === null || rawSubmittedRoundCount === undefined
    ? null
    : Number(rawSubmittedRoundCount);
  const allRoundsSubmitted = submittedRoundCount === null
    ? displayedProgressRounds.length > 0 && displayedProgressRounds.every((round) => round?.submittedAt)
    : Number.isFinite(submittedRoundCount) && submittedRoundCount >= displayedProgressRounds.length;
  Object.assign(taskForm, {
    actualEndAt: datetimeLocalValue(source.actualEndAt || node?.actualEndAt || node?.actual_end_at),
    actualFee: source.actualFee ?? node?.actualFee ?? node?.actual_fee ?? "",
    actualFeeNote: source.actualFeeNote ?? data.feeActualNote ?? data.fee_actual_note ?? "",
    note: source.note ?? "",
    progressRounds: displayedProgressRounds,
    progressSubmittedAt: serverProgressSubmittedAt,
    progressSubmitted: Boolean(
      serverProgressSubmittedAt
      && allRoundsSubmitted
      && (!draft || draftProgressSubmittedAt === serverProgressSubmittedAt),
    ),
  });
  if (submission.submitted) clearTaskDraft(task);
  hydratingTaskForm = false;
  resetTaskDraftAutosave(taskDraftSnapshot(task));
}

watch(
  () => ({
    assignmentId: selectedTaskId.value,
    actualEndAt: taskForm.actualEndAt,
    actualFee: taskForm.actualFee,
    actualFeeNote: taskForm.actualFeeNote,
    note: taskForm.note,
    progressRounds: taskForm.progressRounds.map((item) => ({ ...item, attachmentIds: [...item.attachmentIds] })),
    progressSubmittedAt: taskForm.progressSubmittedAt,
  }),
  () => {
    const draft = taskDraftSnapshot();
    if (!draft || hydratingTaskForm || !selectedTaskEditable.value) return;
    saveTaskDraft(draft);
    scheduleTaskDraftAutosave(draft);
  },
  { deep: true },
);

function showSuccess(message) {
  success.value = message;
  window.setTimeout(() => { if (success.value === message) success.value = ""; }, 2600);
}

async function confirmTaskCompletion() {
  const task = selectedTask.value;
  const draft = taskDraftSnapshot(task);
  if (!task || !draft || taskSubmitting.value) return;
  if (!taskActualStartAt.value) {
    error.value = "管理端尚未确认实际开始时间，请等待节点开始";
    return;
  }
  if (!taskForm.actualEndAt) {
    error.value = "请填写实际结束时间";
    return;
  }
  if (!calculatedActualDuration.value) {
    error.value = "实际结束时间不能早于实际开始时间";
    return;
  }
  if (selectedTaskIsPresales.value) {
    if (!taskForm.progressSubmitted) {
      error.value = "请先提交方案推进记录";
      return;
    }
    if (!taskForm.progressRounds.length) {
      error.value = "请至少填写一轮推进记录";
      return;
    }
    const incompleteIndex = taskForm.progressRounds.findIndex((item) => !item.designDate);
    if (incompleteIndex >= 0) {
      error.value = `请补全第 ${incompleteIndex + 1} 轮工作日期`;
      return;
    }
  }
  taskSubmitting.value = true;
  error.value = "";
  try {
    await flushTaskDraftAutosave();
    const response = await serviceApi.updateMobileTask(task.id, { ...draft.values, submitted: true });
    applyTaskUpdate(task.id, response);
    clearTaskDraft(task);
    taskGroup.value = "completed";
    await load();
    showSuccess("完工资料已提交，请等待管理端确认节点通过");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "确认完工失败";
  } finally {
    taskSubmitting.value = false;
  }
}

async function submitPresalesProgress(rounds) {
  const task = selectedTask.value;
  const normalizedRounds = Array.isArray(rounds) ? rounds.map(normalizePresalesProgressRound) : [];
  if (!task || !selectedTaskIsPresales.value || !selectedTaskEditable.value || presalesProgressSubmitting.value) return;
  if (!normalizedRounds.length) {
    error.value = "请至少填写一轮推进记录";
    return;
  }
  const incompleteIndex = normalizedRounds.findIndex((item) => !item.designDate);
  if (incompleteIndex >= 0) {
    error.value = `请补全第 ${incompleteIndex + 1} 轮工作日期`;
    return;
  }
  presalesProgressSubmitting.value = true;
  error.value = "";
  try {
    const response = await serviceApi.updateMobileTask(task.id, {
      progressOnly: true,
      schemeRounds: normalizedRounds,
    });
    applyTaskUpdate(task.id, response);
    const savedNode = response?.item?.node || response?.node;
    const savedData = savedNode?.businessData || savedNode?.business_data || {};
    taskForm.progressRounds = Array.isArray(savedData.schemeRounds)
      ? savedData.schemeRounds.map(normalizePresalesProgressRound)
      : normalizedRounds;
    taskForm.progressSubmittedAt = String(savedData.schemeProgressSubmittedAt || new Date().toISOString());
    taskForm.progressSubmitted = true;
    showSuccess("方案推进已提交管理端");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "方案推进提交失败";
  } finally {
    presalesProgressSubmitting.value = false;
  }
}

function leaveTask() {
  void flushTaskDraftAutosave().catch(() => {});
  selectedTaskId.value = "";
}

function handleTouchStart(event) {
  if (event.touches.length !== 1) return;
  const target = event.target;
  if (target instanceof Element && target.closest("input, textarea, select, button, a, [data-no-swipe]")) {
    touchStart = null;
    return;
  }
  const touch = event.touches[0];
  touchStart = { x: touch.clientX, y: touch.clientY, time: Date.now() };
}

function handleTouchEnd(event) {
  if (!touchStart || event.changedTouches.length !== 1) return;
  const start = touchStart;
  touchStart = null;
  const touch = event.changedTouches[0];
  const deltaX = touch.clientX - start.x;
  const deltaY = touch.clientY - start.y;
  if (Date.now() - start.time > 650 || deltaX > -72 || Math.abs(deltaX) < Math.abs(deltaY) * 1.25) return;
  if (selectedTask.value) {
    leaveTask();
  }
}

function openTab(tab) {
  activeTab.value = tab;
  selectedTaskId.value = "";
  if (tab === "feedback") feedbackView.value = "history";
}

async function load({ silent = false } = {}) {
  if (!silent) loading.value = true;
  error.value = "";
  try {
    const providerResponse = await serviceApi.providerMe();
    const provider = providerResponse?.item || null;
    if (provider?.certificationStatus === "certified") {
      workspace.value = { ...(await serviceApi.mobileWorkspace()), profile: provider };
    } else {
      workspace.value = { profile: provider };
      activeTab.value = "profile";
      profileEditing.value = true;
    }
    fillProviderForm(provider);
    if (selectedTaskId.value && !tasks.value.some((item) => String(item.id) === String(selectedTaskId.value))) selectedTaskId.value = "";
    if (selectedTask.value) {
      fillTaskForm(selectedTask.value);
      await loadTaskProofs(selectedTask.value);
    }
    if (form.task_id && !feedbackTasks.value.some((item) => String(item.id) === String(form.task_id))) {
      Object.assign(form, { task_id: "", project_id: "", node_key: "" });
    }
  } catch (reason) {
    if (!silent) error.value = reason instanceof Error ? reason.message : "现场工作台加载失败";
  } finally {
    if (!silent) loading.value = false;
  }
}

async function syncWorkspace() {
  if (
    workspaceSyncInFlight
    || loading.value
    || saving.value
    || taskSubmitting.value
    || presalesProgressSubmitting.value
    || profileEditing.value
  ) return;
  workspaceSyncInFlight = true;
  try {
    await load({ silent: true });
  } finally {
    workspaceSyncInFlight = false;
  }
}

function splitList(value) {
  return String(value || "").split(/[，,、\n]/).map((item) => item.trim()).filter(Boolean);
}

function fillProviderForm(provider = profile.value) {
  Object.assign(providerForm, {
    name: provider?.name || props.session?.nick || props.session?.name || "",
    role: provider?.role || "installer",
    phone: provider?.phone || "",
    city: provider?.city || "",
    regions: (provider?.regions || []).join("、"),
    skills: (provider?.skills || []).join("、"),
    bio: provider?.bio || "",
    files: [],
  });
}

function selectProviderFiles(incoming) {
  const tooLarge = incoming.find((file) => file.size > MAX_ATTACHMENT_SIZE);
  if (tooLarge) {
    error.value = `${tooLarge.name} 超过 ${MAX_ATTACHMENT_MB}MB`;
    return;
  }
  providerForm.files.push(...incoming);
}

async function submitProvider() {
  if (!providerForm.name.trim() || !providerForm.phone.trim() || !providerForm.city.trim()) {
    error.value = "请填写姓名、联系电话和所在城市";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const response = await serviceApi.applyProvider({
      name: providerForm.name.trim(),
      role: providerForm.role,
      phone: providerForm.phone.trim(),
      city: providerForm.city.trim(),
      regions: splitList(providerForm.regions),
      skills: splitList(providerForm.skills),
      bio: providerForm.bio.trim(),
    });
    const provider = response?.item || response;
    const providerId = normalizeDatabaseId(provider?.id);
    if (providerForm.files.length && !providerId) throw new Error("服务档案记录无效");
    for (const file of providerForm.files) {
      await serviceApi.uploadAttachment("provider_application", providerId, file, "qualification");
    }
    workspace.value = { ...workspace.value, profile: provider };
    providerForm.files = [];
    profileEditing.value = false;
    showSuccess("服务档案已提交审核");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "服务档案提交失败";
  } finally { saving.value = false; }
}

function selectTask(task) {
  selectedTaskId.value = task.id;
  form.project_id = task.project_id || task.projectId || task.project?.id || "";
  form.node_key = task.nodeKey || task.node_key || task.node?.nodeKey || "";
  fillTaskForm(task);
  loadTaskProofs(task);
}

function updateMobilePresalesProgressRounds(rounds) {
  taskForm.progressRounds = Array.isArray(rounds) ? rounds.map(normalizePresalesProgressRound) : [];
  taskForm.progressSubmitted = false;
  taskForm.progressSubmittedAt = "";
}

function setFeedbackMode(mode) {
  feedbackMode.value = mode;
  form.type = mode === "feedback" ? FEEDBACK_TYPE_OPTIONS[0].value : TICKET_TYPE_OPTIONS[0].value;
}

function openSubmissionForm() {
  Object.assign(form, {
    task_id: "",
    type: feedbackMode.value === "feedback" ? FEEDBACK_TYPE_OPTIONS[0].value : TICKET_TYPE_OPTIONS[0].value,
    project_id: "",
    node_key: "",
    title: "",
    content: "",
    priority: "medium",
    files: [],
  });
  feedbackView.value = "submit";
}

function selectFeedbackTask(task = feedbackTask.value) {
  form.project_id = task?.projectId || task?.project_id || task?.project?.id || "";
  form.node_key = taskNodeKey(task);
  if (task) form.title = `${display(task, "projectName", "project_name")} - ${display(task, "nodeName", "node_name")}`;
}

function openFeedbackForTask(task, mode = "feedback") {
  selectedTaskId.value = "";
  activeTab.value = "feedback";
  setFeedbackMode(mode);
  feedbackView.value = "submit";
  form.task_id = String(task?.id || "");
  selectFeedbackTask(task);
}

function selectFiles(incoming) {
  const tooLarge = incoming.find((file) => file.size > MAX_ATTACHMENT_SIZE);
  if (tooLarge) {
    error.value = `${tooLarge.name} 超过 ${MAX_ATTACHMENT_MB}MB`;
    return;
  }
  form.files.push(...incoming);
}

function removeFile(index) {
  form.files.splice(index, 1);
}

async function submit() {
  const task = feedbackTask.value;
  if (!task) {
    error.value = "请选择已指派的关联任务";
    return;
  }
  if (!form.title.trim() || !form.content.trim()) {
    error.value = "请填写标题和详细内容";
    return;
  }
  const projectId = task.projectId || task.project_id || task.project?.id;
  const nodeKey = taskNodeKey(task);
  saving.value = true;
  error.value = "";
  try {
    if (feedbackMode.value === "feedback") {
      const response = await serviceApi.createFeedback({ project_id: projectId, node_key: nodeKey, title: form.title.trim(), type: form.type, content: form.content.trim(), source: "mobile" });
      const item = response?.item || response;
      const feedbackId = normalizeDatabaseId(item?.id);
      if (form.files.length && !feedbackId) throw new Error("反馈记录无效");
      for (const file of form.files) await serviceApi.uploadAttachment("feedback", feedbackId, file);
      showSuccess("反馈已提交，审核结果会同步到反馈记录");
    } else {
      const response = await serviceApi.createTicket({ project_id: projectId, node_key: nodeKey, title: form.title.trim(), type: form.type, priority: form.priority, description: form.content.trim(), source: "mobile" });
      const item = response?.item || response;
      const ticketId = normalizeDatabaseId(item?.id);
      if (form.files.length && !ticketId) throw new Error("工单记录无效");
      for (const file of form.files) await serviceApi.uploadAttachment("ticket", ticketId, file);
      showSuccess("支持工单已提交");
    }
    form.content = "";
    form.files = [];
    await load();
    feedbackView.value = "history";
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "提交失败";
  } finally { saving.value = false; }
}

async function openMaterial(material) {
  const url = material.externalUrl || material.external_url || material.download_url || material.downloadUrl || material.url;
  if (url) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  error.value = "";
  try {
    const materialId = normalizeDatabaseId(material?.id);
    if (!materialId) throw new Error("资料记录无效");
    const attachments = collectionRows(await serviceApi.listAttachments("resource", materialId));
    if (!attachments.length) throw new Error("该资料暂未上传文件");
    window.location.assign(attachments[0].downloadUrl);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "资料打开失败";
  }
}

onMounted(() => {
  load();
  timer = window.setInterval(() => { now.value = Date.now(); }, 30000);
  workspaceSyncTimer = window.setInterval(() => {
    if (document.visibilityState !== "hidden") void syncWorkspace();
  }, 5000);
});
onBeforeUnmount(() => {
  window.clearInterval(timer);
  window.clearInterval(workspaceSyncTimer);
});
</script>

<template>
  <div class="as-field-shell" :class="{ 'as-field-shell--detail': selectedTask }" @touchstart.passive="handleTouchStart" @touchend.passive="handleTouchEnd">
    <header class="as-field-head">
      <div><span class="as-field-head__avatar">{{ String(profile.name || session?.nick || session?.name || '服').slice(0, 1) }}</span><span><small>现场服务工作台</small><strong>{{ profile.name || session?.nick || session?.name || "当前服务人员" }}</strong></span></div>
      <button v-if="selectedTask" type="button" class="as-field-head__back" @click="leaveTask"><ArrowLeft /><span>返回任务</span></button>
    </header>

    <main class="as-field-main" :class="{ 'as-field-main--with-actions': activeTab === 'tasks' && selectedTask && selectedTaskEditable }">
      <GlobalNotice v-model:error="error" v-model:success="success" />
      <div v-if="loading" class="as-empty as-empty--large"><LoaderCircle class="as-spin" /> 正在同步现场任务...</div>

      <template v-else-if="activeTab === 'tasks'">
        <template v-if="selectedTask">
          <section class="as-field-detail-head">
            <div><span class="as-status">{{ taskStatus(selectedTask) }}</span><h1>{{ display(selectedTask, 'projectName', 'project_name') }}</h1><p>{{ display(selectedTask, 'serviceTypeLabel', 'service_type_display', 'serviceTypeDisplay', 'service_type', 'serviceType') }} · {{ display(selectedTask, 'nodeName', 'node_name') }}</p></div>
            <strong><Clock3 />{{ taskPlannedStartLabel(selectedTask) }}</strong>
          </section>
          <details class="as-field-info-band as-mobile-detail-fold" open>
            <summary class="as-mobile-fold-summary"><strong>项目概览</strong></summary>
            <div><CalendarDays /><span><small>{{ selectedTask.serviceType === 'midsales' ? '预计完成时间' : '计划完成时间' }}</small><strong>{{ taskPlannedEnd(selectedTask) || '-' }}</strong></span></div>
            <div><UserRoundCheck /><span><small>项目负责人</small><strong>{{ display(selectedTask, 'manager_name', 'managerName', 'owner_name', 'ownerName') }}</strong></span></div>
            <div v-if="selectedTaskIsPresales || selectedTaskIsAftersales"><Phone /><span><small>负责人联系电话</small><strong>{{ display(taskProjectData(selectedTask), 'managerContact', 'manager_contact', 'contactPhone', 'contact_phone') }}</strong></span></div>
          </details>
          <details class="as-field-section as-mobile-detail-fold" open>
            <summary class="as-field-section__head"><div><h2>{{ display(currentNode(selectedTask), 'name', 'node_name', 'nodeName') }}</h2></div><span class="as-status">{{ nodeStatus(currentNode(selectedTask)) }}</span></summary>
            <dl class="as-field-node-info"><div><dt>现场任务说明</dt><dd>{{ taskInstruction(selectedTask) }}</dd></div><div><dt>计划时间</dt><dd>{{ taskPlan(selectedTask) }}</dd></div><div v-if="!selectedTaskIsPresales"><dt>预计费用</dt><dd>{{ taskFeeValue(currentNode(selectedTask)?.estimatedFee ?? currentNode(selectedTask)?.estimated_fee) }}</dd></div><template v-if="selectedTaskIsAftersales"><div><dt>服务地址</dt><dd>{{ display(selectedTask, 'address', 'projectAddress') }}</dd></div><div><dt>费用约定</dt><dd>{{ display(taskProjectData(selectedTask), 'feeAgreement', 'fee_agreement') }}</dd></div><div><dt>费用备注</dt><dd>{{ display(taskProjectData(selectedTask), 'feeRemark', 'fee_remark') }}</dd></div></template><div v-if="selectedTaskSupportsRelatedProducts" class="as-field-node-info__wide"><dt>相关产品</dt><dd class="as-field-product-list"><span v-for="product in taskRelatedProducts(selectedTask)" :key="product.productId">{{ taskProductLabel(product) }}</span><em v-if="!taskRelatedProducts(selectedTask).length">暂无相关产品</em></dd></div></dl>
          </details>
          <MobileTaskMaterials :materials="selectedTaskMaterials" @open="openMaterial" />
          <details class="as-field-section as-field-execution as-mobile-detail-fold">
            <summary class="as-field-section__head"><div><h2>任务记录</h2></div><span class="as-status" :class="{ 'is-done': selectedTaskSubmitted }">{{ selectedTaskSubmitted ? '已提交管理端' : selectedTaskEditable ? '待确认完工' : '只读' }}</span></summary>
            <div v-if="selectedTaskSubmitted" class="as-mobile-completion-state"><Check /><span><strong>现场完工资料已提交</strong><small>管理端确认节点通过前，本任务保持只读。</small></span></div>
            <div class="as-form-grid">
              <label class="as-field"><span>实际开始时间</span><input :value="dateTimeLabel(taskActualStartAt)" readonly aria-label="管理端确认的实际开始时间"></label>
              <label class="as-field"><span>实际结束时间</span><DateField v-model="taskForm.actualEndAt" type="datetime-local" :disabled="!selectedTaskEditable" aria-label="实际结束时间" /></label>
              <label v-if="!selectedTaskIsPresales" class="as-field"><span>实际费用</span><input v-model="taskForm.actualFee" type="number" min="0" step="0.01" inputmode="decimal" :disabled="!selectedTaskEditable" placeholder="0.00"></label>
              <label v-if="selectedTaskUsesProofs || selectedTaskIsAftersales" class="as-field as-field--wide"><span>实际费用备注</span><textarea v-model="taskForm.actualFeeNote" rows="2" :disabled="!selectedTaskEditable" placeholder="记录交通、人工、辅材或其他实际费用"></textarea></label>
              <label class="as-field as-field--wide"><span>现场备注</span><textarea v-model="taskForm.note" rows="2" :disabled="!selectedTaskEditable" placeholder="记录客户确认、现场差异或后续事项"></textarea></label>
            </div>
            <template v-if="selectedTaskUsesProofs || selectedTaskIsAftersales">
              <div class="as-field-section__subhead"><strong>费用清单附件</strong><Paperclip /></div>
              <div class="as-proof-grid">
                <div class="as-proof-group">
                  <div><strong>预计费用清单</strong><small>管理端提供</small></div>
                  <AttachmentPanel target-type="project_node" :target-id="taskNodeAttachmentId()" :categories="[{ value: 'fee_estimated', label: '预计费用清单' }]" :editable="false" source="mobile" compact @error="error = $event" />
                </div>
                <div class="as-proof-group">
                  <div><strong>实际费用清单</strong><small>现场填写</small></div>
                  <AttachmentPanel target-type="project_node" :target-id="taskNodeAttachmentId()" :categories="[{ value: 'fee_actual', label: '实际费用清单' }]" :editable="selectedTaskEditable" source="mobile" compact upload-label="上传实际费用清单" @uploaded="showSuccess('实际费用清单已上传')" @removed="showSuccess('实际费用清单已删除')" @error="error = $event" />
                </div>
              </div>
            </template>
            <template v-if="selectedTaskIsAftersales">
              <div class="as-field-section__subhead"><strong>售后完工附件</strong><PackageCheck /></div>
              <AttachmentPanel class="as-mobile-task-attachments" target-type="project_node" :target-id="taskNodeAttachmentId()" title="完工附件" :categories="AFTERSALES_ATTACHMENT_GROUPS" :editable="selectedTaskEditable" source="mobile" @uploaded="showSuccess('完工附件已上传')" @removed="showSuccess('完工附件已删除')" @error="error = $event" />
            </template>
          </details>
          <details v-if="selectedTaskUsesProofs" class="as-field-section as-mobile-proof-section as-mobile-detail-fold">
            <summary class="as-field-section__head"><div><h2>证明材料</h2></div><span class="as-status">已上传 {{ uploadedTaskProofs }}/3</span></summary>
            <div v-if="taskProofLoading" class="as-empty"><LoaderCircle class="as-spin" /> 正在加载证明材料...</div>
            <div v-else class="as-mobile-proof-list">
              <article v-for="proof in taskProofs" :key="proof.id" class="as-proof-review-item">
                <header><strong>{{ proof.proofTypeLabel || proof.proof_type_label }}</strong><span class="as-proof-state" :class="`is-${proofStatus(proof)}`">{{ proofStatusLabel(proof) }}</span></header>
                <AttachmentPanel target-type="midsales_proof" :target-id="proof.id" :categories="[{ value: 'general', label: proof.proofTypeLabel || proof.proof_type_label || '证明附件' }]" :editable="selectedTaskEditable && canUploadProof(proof)" source="mobile" compact upload-label="上传材料" @error="error = $event" />
                <p v-if="proof.reviewOpinion || proof.review_opinion" class="as-proof-opinion-readonly"><strong>审核意见</strong>{{ proof.reviewOpinion || proof.review_opinion }}</p>
              </article>
              <p v-if="!taskProofs.length" class="as-attachment-empty">暂无证明材料记录</p>
            </div>
          </details>
          <details v-if="selectedTask.serviceType === 'midsales' && !selectedTaskUsesProofs" class="as-field-section as-mobile-detail-fold">
            <summary class="as-field-section__head"><div><h2>交付附件</h2></div></summary>
            <AttachmentPanel target-type="project_node" :target-id="taskNodeAttachmentId()" :categories="[{ value: 'general', label: '交付附件' }]" :editable="selectedTaskEditable" source="mobile" compact upload-label="上传交付附件" @uploaded="showSuccess('交付附件已上传')" @removed="showSuccess('交付附件已删除')" @error="error = $event" />
          </details>
          <div v-if="selectedTaskEditable" class="as-field-action-bar"><button type="button" class="as-button as-button--secondary" :disabled="taskSubmitting" @click="openFeedbackForTask(selectedTask, 'ticket')"><Headphones />提交工单</button><button type="button" class="as-button as-button--secondary" :disabled="taskSubmitting" @click="openFeedbackForTask(selectedTask, 'feedback')"><Send />提交反馈</button><button type="button" class="as-button as-button--primary" :disabled="taskSubmitting" @click="confirmTaskCompletion"><LoaderCircle v-if="taskSubmitting" class="as-spin" /><Check v-else />{{ taskSubmitting ? '提交中' : '确认完工' }}</button></div>
        </template>

        <template v-else>
          <section class="as-field-summary"><div><p class="as-eyebrow">我的现场任务</p><h1>{{ visibleTasks.length }} 项服务任务</h1><p>只展示已分派给当前账号的售中和售后节点。</p></div></section>
          <div class="as-mobile-task-filters">
            <div class="as-segmented as-mobile-service-tabs" role="tablist" aria-label="服务类型筛选"><button v-for="item in TASK_SERVICE_TYPE_OPTIONS" :key="item.value" type="button" role="tab" :aria-selected="taskServiceType === item.value" :class="{ active: taskServiceType === item.value }" @click="taskServiceType = item.value">{{ item.label }}</button></div>
            <div class="as-segmented as-mobile-task-tabs" role="tablist" aria-label="任务状态筛选"><button type="button" role="tab" :aria-selected="taskGroup === 'pending'" :class="{ active: taskGroup === 'pending' }" @click="taskGroup = 'pending'">待进行</button><button type="button" role="tab" :aria-selected="taskGroup === 'active'" :class="{ active: taskGroup === 'active' }" @click="taskGroup = 'active'">进行中</button><button type="button" role="tab" :aria-selected="taskGroup === 'completed'" :class="{ active: taskGroup === 'completed' }" @click="taskGroup = 'completed'">已完成</button></div>
          </div>
          <section class="as-mobile-task-list">
            <button v-for="task in visibleTasks" :key="task.id" type="button" class="as-mobile-task" @click="selectTask(task)">
              <span class="as-mobile-task__top"><span class="as-status">{{ taskStatus(task) }}</span><strong :class="{ overdue: countdown(task).includes('超时') }"><Clock3 />{{ countdown(task) }}</strong></span>
              <h2>{{ display(task, 'projectName', 'project_name') }}</h2><p>{{ display(task, 'serviceTypeLabel', 'service_type_display', 'serviceTypeDisplay', 'service_type', 'serviceType') }} · {{ display(task, 'nodeName', 'node_name') }}</p>
              <span class="as-mobile-task__line"><CalendarDays />{{ taskPlan(task) }}</span><ChevronRight class="as-mobile-task__arrow" />
            </button>
            <div v-if="!visibleTasks.length" class="as-empty as-empty--large"><TicketCheck /> 当前筛选没有任务</div>
          </section>
        </template>
      </template>

      <template v-else-if="activeTab === 'feedback'">
        <section class="as-field-page-title"><p class="as-eyebrow">现场协同</p><h1>反馈与支持</h1><p>反馈审核通过后可进入奖励记录；需专人跟进的问题请创建工单。</p></section>
        <div class="as-segmented as-mobile-feedback-tabs"><button :class="{ active: feedbackMode === 'feedback' }" @click="setFeedbackMode('feedback')"><CircleAlert />问题反馈</button><button :class="{ active: feedbackMode === 'ticket' }" @click="setFeedbackMode('ticket')"><Headphones />支持工单</button></div>
        <div class="as-segmented as-mobile-feedback-view-tabs" role="tablist" aria-label="反馈与工单视图"><button type="button" role="tab" :aria-selected="feedbackView === 'history'" :class="{ active: feedbackView === 'history' }" @click="feedbackView = 'history'"><Clock3 />我的记录 <span>{{ feedbackMode === 'ticket' ? submittedTickets.length : submittedFeedback.length }}</span></button><button type="button" role="tab" :aria-selected="feedbackView === 'submit'" :class="{ active: feedbackView === 'submit' }" @click="openSubmissionForm"><Plus />{{ feedbackMode === 'ticket' ? '新建工单' : '新建反馈' }}</button></div>
        <MobileSubmissionHistory v-if="feedbackView === 'history'" :mode="feedbackMode" :records="feedbackMode === 'ticket' ? submittedTickets : submittedFeedback" @error="error = $event" />
        <section v-else class="as-field-form">
          <label class="as-field"><span>关联任务 *</span><select v-model="form.task_id" @change="selectFeedbackTask()"><option value="">请选择已指派任务</option><option v-for="task in feedbackTasks" :key="task.id" :value="String(task.id)">{{ display(task, 'projectName', 'project_name') }} · {{ display(task, 'nodeName', 'node_name') }}</option></select></label>
          <label class="as-field"><span>{{ feedbackMode === 'ticket' ? '工单标题' : '反馈标题' }} *</span><input v-model="form.title" placeholder="简明描述现场事项"></label>
          <label class="as-field"><span>类型</span><select v-model="form.type"><option v-for="option in feedbackTypeOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
          <label v-if="feedbackMode === 'ticket'" class="as-field"><span>优先级</span><select v-model="form.priority"><option value="low">低</option><option value="medium">中</option><option value="high">高</option></select></label>
          <label class="as-field"><span>详细内容 *</span><textarea v-model="form.content" rows="6" placeholder="描述当前现象、已尝试步骤和现场配置差异"></textarea></label>
          <FileSelectionPanel class="as-mobile-file-picker" :files="form.files" button-label="选择现场附件" @change="selectFiles" @remove="removeFile" />
          <button type="button" class="as-button as-button--primary as-button--block" :disabled="saving" @click="submit"><LoaderCircle v-if="saving" class="as-spin" /><Send v-else />{{ feedbackMode === 'ticket' ? '提交工单' : '提交反馈' }}</button>
        </section>
      </template>

      <template v-else>
        <section class="as-mobile-profile-head"><span>{{ String(profile.name || session?.nick || session?.name || '服').slice(0, 1) }}</span><div><h1>{{ profile.name || session?.nick || session?.name || "当前服务人员" }}</h1><p>{{ display(profile, 'roleLabel', 'role_display', 'roleDisplay', 'role') }} · {{ display(profile, 'phone') }}</p></div></section>
        <section class="as-mobile-profile-stats"><div><strong>{{ tasks.length }}</strong><span>服务任务</span></div><div><strong>{{ (profile.skills || profile.abilities || []).length }}</strong><span>节点能力</span></div><div><strong>{{ rewards.length }}</strong><span>奖励记录</span></div></section>
        <section v-if="profileEditing || !profile.id" class="as-field-section as-provider-application">
          <div class="as-field-section__head"><div><p class="as-eyebrow">服务人员认证</p><h2>{{ profile.id ? '更新服务档案' : '提交服务档案' }}</h2></div><ShieldCheck /></div>
          <div class="as-form-grid">
            <label class="as-field"><span>姓名 *</span><input v-model="providerForm.name" autocomplete="name"></label>
            <label class="as-field"><span>服务角色</span><select v-model="providerForm.role"><option value="installer">安装 / 调试人员</option><option value="maintenance">售后维修人员</option><option value="support">技术支持人员</option><option value="partner">第三方合作资源</option></select></label>
            <label class="as-field"><span>联系电话 *</span><input v-model="providerForm.phone" type="tel" autocomplete="tel"></label>
            <label class="as-field"><span>所在城市 *</span><input v-model="providerForm.city" autocomplete="address-level2"></label>
            <label class="as-field"><span>服务地区</span><input v-model="providerForm.regions" placeholder="杭州、宁波、绍兴"></label>
            <label class="as-field"><span>服务技能</span><input v-model="providerForm.skills" placeholder="设备安装、平台接入"></label>
            <label class="as-field as-field--wide"><span>人员简介</span><textarea v-model="providerForm.bio" rows="3"></textarea></label>
          </div>
          <FileSelectionPanel class="as-mobile-file-picker" :files="providerForm.files" button-label="选择资质附件" @change="selectProviderFiles" @remove="providerForm.files.splice($event, 1)" />
          <div class="as-node-actions"><button v-if="profile.id" type="button" class="as-button as-button--secondary" @click="profileEditing = false; fillProviderForm()">取消</button><button type="button" class="as-button as-button--primary" :disabled="saving" @click="submitProvider"><LoaderCircle v-if="saving" class="as-spin" /><Send v-else />提交审核</button></div>
        </section>
        <section v-else class="as-field-section"><div class="as-field-section__head"><div><p class="as-eyebrow">服务档案</p><h2>能力与地区</h2></div><span class="as-status">{{ display(profile, 'certificationStatusLabel', 'status_display', 'statusDisplay', 'status') }}</span></div><div class="as-tag-list"><span v-for="item in (profile.regions || [profile.city]).filter(Boolean)" :key="item">{{ item }}</span><span v-for="item in (profile.skills || profile.abilities || [])" :key="item" class="is-skill">{{ item }}</span></div><button type="button" class="as-button as-button--secondary as-profile-edit" @click="fillProviderForm(); profileEditing = true"><UserRoundCheck />修改档案并重审</button></section>
        <section class="as-field-section"><div class="as-field-section__head"><div><p class="as-eyebrow">最近记录</p><h2>我的服务</h2></div></div><div v-for="item in records.slice(0, 5)" :key="item.id" class="as-simple-row"><strong>{{ display(item, 'project_name', 'projectName', 'title') }}</strong><span>{{ display(item, 'node_name', 'nodeName', 'time') }}</span></div><div v-if="!records.length" class="as-empty as-empty--compact">暂无服务记录</div></section>
        <section class="as-field-section"><div class="as-field-section__head"><div><p class="as-eyebrow">奖励记录</p><h2>我的奖励</h2></div><Gift /></div><div v-for="item in rewards.slice(0, 5)" :key="item.id" class="as-simple-row"><strong>{{ display(item, 'prize', 'title', 'prize_name', 'prizeName') }}</strong><span>{{ display(item, 'statusLabel', 'status_display', 'statusDisplay', 'status') }}</span></div><div v-if="!rewards.length" class="as-empty as-empty--compact">暂无奖励记录</div></section>
      </template>
    </main>

    <nav class="as-field-nav" aria-label="现场端导航"><button v-for="item in navItems" :key="item.id" type="button" :class="{ active: activeTab === item.id }" :disabled="item.id !== 'profile' && !providerCertified" @click="openTab(item.id)"><component :is="item.icon" /><span>{{ item.label }}</span></button></nav>
  </div>
</template>
