<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from "vue";
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleDollarSign,
  Clock3,
  FileText,
  LoaderCircle,
  Paperclip,
  Play,
  Plus,
  RotateCcw,
  Save,
  Search,
  Star,
  Trash2,
  Upload,
  UserRoundCheck,
  Users,
  X,
} from "@lucide/vue";
import { collectionRows, allCollectionRows, normalizeDatabaseId, serviceApi } from "@/serviceApi";
import { clearProjectListCache, CRM_SYNC_POLL_DELAYS, projectListIdentity, readProjectListCache, writeProjectListCache } from "@/projectListCache";
import { loginSessionIdentityKey, matchesDirectorySearchKeyword } from "@platform-ui";
import { matchesSearch } from "@/productSearch";
import { projectActiveNodes, projectIsCompleted } from "@/projectActiveNodes";
import { personnelAssignmentMembers, personnelAssignmentSelection, personnelMembers, personnelSelection } from "@/projectPersonnel";
import { ElOption, ElSelect } from "element-plus/es/components/select/index.mjs";
import "element-plus/es/components/select/style/css";
import ModalShell from "@/components/ModalShell.vue";
import PresalesProgressPanel from "@/components/PresalesProgressPanel.vue";
import PresalesMaterialsPanel from "@/components/PresalesMaterialsPanel.vue";
import PresalesProjectFees from "@/components/PresalesProjectFees.vue";
import PresalesProjectInfo from "@/components/PresalesProjectInfo.vue";
import MidsalesNodeSelection from "@/components/MidsalesNodeSelection.vue";
import { MIDSALES_PROJECT_STAGES, MIDSALES_REQUIRED_HANDOVER_NODES } from "@/midsalesNodes";
import { emptyPresalesProgressRound, normalizePresalesProgressRound } from "@/components/presalesProgressRounds";
import AttachmentPanel from "@/components/AttachmentPanel.vue";
import DateField from "@/components/DateField.vue";
import FileSelectionPanel from "@/components/FileSelectionPanel.vue";
import MidsalesProjectGantt from "@/components/MidsalesProjectGantt.vue";
import ProjectDetailDrawer from "@/components/ProjectDetailDrawer.vue";
import ProjectMaterialGroup from "@/components/ProjectMaterialGroup.vue";
import ProjectNodeSummary from "@/components/ProjectNodeSummary.vue";
import PersonnelSelectButton from "@/components/PersonnelSelectButton.vue";
import PresalesPersonnelTable from "@/components/PresalesPersonnelTable.vue";
import RelatedProductDetailDrawer from "@/components/RelatedProductDetailDrawer.vue";
import RelatedProductPicker from "@/components/RelatedProductPicker.vue";
import RelatedProductsPanel from "@/components/RelatedProductsPanel.vue";
import GlobalNotice from "@/components/GlobalNotice.vue";
import UnsavedChangesDialog from "@/components/UnsavedChangesDialog.vue";
import ListPagination from "@/components/ListPagination.vue";
import ProjectName from "@/components/ProjectName.vue";
import { useDebouncedAutosave } from "@/composables/useDebouncedAutosave";
import { usePresalesProjectInfo } from "@/composables/usePresalesProjectInfo";
import {
  MIDSALES_SCHEDULE_DEPENDENCIES,
  PRESALES_SCHEDULE_DEPENDENCIES,
  inheritedScheduleStart,
  schedulePredecessorKeys,
} from "@/workflowSchedule";

const props = defineProps({
  active: { type: Boolean, default: true },
  serviceType: { type: String, required: true },
  session: { type: Object, default: null },
  focusProjectId: { type: [String, Number], default: "" },
  focusNodeKey: { type: String, default: "" },
  focusRoundId: { type: String, default: "" },
});
const emit = defineEmits(["open-settlement", "dirty-change", "busy-change", "project-detail-closed"]);
const desktopQuery = window.matchMedia("(min-width: 841px)");
const isDesktop = shallowRef(desktopQuery.matches);
function updateDesktop() {
  isDesktop.value = desktopQuery.matches;
  if (!isDesktop.value && detailTab.value === "info") detailTab.value = "overview";
  else if (isDesktop.value && detailTab.value === "fees") detailTab.value = "info";
}

const CONFIG = {
  presales: {
    title: "售前服务",
    subtitle: "从项目立项到中标后施工图，保留每次提交和节点变更记录。",
    createLabel: "新增售前项目",
    apiType: "presales",
    stages: [
      ["early-approval", "前期立项"], ["early-plan", "前期方案"], ["budget-match", "预算匹配"],
      ["project-filing", "项目申报"], ["early-plan-result", "前期方案结果"], ["late-approval", "后期立项"],
      ["late-plan", "后期方案"], ["device-plan", "设备方案"], ["budget", "工程预算"],
      ["device-budget", "设备预算"], ["cost-control", "成本管控"], ["device-cost-control", "成本管控"],
      ["rendering", "效果图"], ["tender-plan", "招标方案"], ["layout", "平面设计"],
      ["bid-prep", "投标准备"], ["construction-result", "投标结果"], ["construction", "施工图"],
      ["project-end", "售前项目结束"],
    ],
  },
  midsales: {
    title: "售中服务",
    subtitle: "按项目实际范围启用节点，安排服务人员并跟进现场交付。",
    createLabel: "新增售中项目",
    apiType: "midsales",
    stages: MIDSALES_PROJECT_STAGES,
  },
  aftersales: {
    title: "售后服务",
    subtitle: "每个服务单只执行一种服务类型：上门售后、寄件售后或开学巡检。",
    createLabel: "新增售后服务",
    apiType: "aftersales",
    stages: [["onsite-service", "上门售后"], ["mail-service", "寄件售后"], ["school-inspection", "开学巡检"]],
  },
};

const FEE_ATTACHMENT_CATEGORIES = Object.freeze({
  estimated: Object.freeze([{ value: "fee_estimated", label: "预计费用清单" }]),
  actual: Object.freeze([{ value: "fee_actual", label: "实际费用清单" }]),
});
const PRESALES_SUPPLEMENTAL_ATTACHMENT_CATEGORIES = Object.freeze([
  Object.freeze({ value: "general", label: "节点附件" }),
]);
const PRESALES_FLOW_LAYOUT = Object.freeze({
  "early-approval": { column: 1, lane: "bridge" },
  "early-plan": { column: 2, lane: "upper" },
  "budget-match": { column: 2, lane: "lower" },
  "project-filing": { column: 3, lane: "lower" },
  "early-plan-result": { column: 4, lane: "bridge" },
  "late-approval": { column: 5, lane: "bridge" },
  "late-plan": { column: 6, lane: "upper" },
  "device-plan": { column: 6, lane: "lower" },
  budget: { column: 7, lane: "upper" },
  "device-budget": { column: 7, lane: "lower" },
  "cost-control": { column: 8, lane: "upper" },
  "device-cost-control": { column: 8, lane: "lower" },
  rendering: { column: 9, lane: "upper" },
  "tender-plan": { column: 9, lane: "lower" },
  layout: { column: 10, lane: "upper" },
  "bid-prep": { column: 10, lane: "lower" },
  "construction-result": { column: 11, lane: "bridge" },
  construction: { column: 12, lane: "bridge" },
  "project-end": { column: 13, lane: "bridge" },
});

const config = computed(() => CONFIG[props.serviceType]);
const currentUserId = computed(() => String(props.session?.userId || "").trim());
const currentUserName = computed(() => String(
  props.session?.nick || props.session?.name || props.session?.userId || "当前用户",
).trim());
const loading = ref(false);
const detailLoading = ref(false);
const saving = ref(false);
const error = ref("");
const success = ref("");
const projects = ref([]);
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const totalPages = ref(1);
const crmSyncing = ref(false);
const crmSyncError = ref("");
const crmScopeReady = ref(false);
const projectListBusy = ref(false);
const selectedId = ref("");
const projectDetail = ref(null);
const drawerOpen = ref(false);
let detailRequestToken = 0;
const detailTab = ref("overview");
const presalesProgressPanel = ref(null);
const presalesRoundDraft = ref({ dirty: false, busy: false });
const handoverNodeKeys = ref(MIDSALES_PROJECT_STAGES.map(([key]) => key));
const projectChartOpen = ref(false);
const projectChartProject = ref(null);
const selectedNodeId = ref("");
const stageFilter = ref("all");
const crmStageFilter = ref("");
const availableCrmStages = ref([]);
const crmStageOptions = computed(() => [...new Set([
  ...availableCrmStages.value,
  ...(crmStageFilter.value && crmStageFilter.value !== "__empty__" ? [crmStageFilter.value] : []),
])]);
const keyword = ref("");
const customerKeyword = ref("");
const ownerKeyword = ref("");
const designOwnerKeyword = ref("");
const solutionOwnerKeyword = ref("");
const createOpen = ref(false);
const projectDeleteOpen = ref(false);
const projectDeleting = shallowRef(false);
const projectDeleteTarget = ref(null);
const relatedProductPickerOpen = ref(false);
const relatedProductSaving = shallowRef(false);
const relatedProductTargetNodeKey = shallowRef("");
const relatedProductDetailOpen = shallowRef(false);
const relatedProductDetail = ref(null);
const relatedProductDetailLoading = shallowRef(false);
const relatedProductDetailError = shallowRef("");
let relatedProductDetailRequestToken = 0;
const teamOpen = ref(false);
const teamLoading = ref(false);
const teamMembers = ref([]);
const managementEmployees = ref([]);
const teamKeyword = ref("");
const teamRegion = ref("");
const teamSkill = ref("");
const teamTargetMode = ref("direct");
const teamTargetNodeKey = ref("");
const managementPicker = computed(() => ["management", "management-direct", "project-lead"].includes(teamTargetMode.value));
const projectLeadPicker = computed(() => teamTargetMode.value === "project-lead");
const teamSelectedMembers = ref([]);
const teamSelectedIds = computed(() => new Set(teamSelectedMembers.value.map(member => member.userId)));
const teamSearchInput = ref(null);
let teamPickerTrigger = null;
const presalesFlowScroll = ref(null);
const personnelForm = reactive({});
const actionNote = ref("");
const noteModalOpen = ref(false);
const noteModalSource = ref("admin");
const noteModalDraft = ref("");
const selectedOutcome = ref("");
const nodeAttachments = ref([]);
const nodeAttachmentsVersion = ref(0);
const attachmentBusy = ref("");
const nodeProofs = ref([]);
const openedMidsalesProofType = ref("");
const midsalesProofModalOpen = ref(false);
const proofLoading = ref(false);
const proofReviewSaving = ref(false);
const proofReviewOpinion = ref("");
const aftersalesCompletionOpen = ref(false);
const completionForm = reactive({ actualStartTime: "", actualDuration: "" });
const completionRejectNote = ref("");
const completionRejectOpen = ref(false);
const presalesProjectInfoOpen = ref(false);
const presalesDenialOpen = ref(false);
const presalesDenialReason = ref("");
const presalesProjectInfo = reactive({ customer: "", owner: "", name: "", info: "", reason: "" });
const workerRatingOpen = ref(false);
const workerRatingSaving = ref(false);
const workerRatingForm = reactive({ providerId: "", providerName: "", projectId: "", nodeKey: "", nodeName: "", rating: 5 });
const presalesSchemeRounds = ref([]);
const presalesSchemeSaving = shallowRef(false);
const presalesPersonnelForm = reactive({});
const presalesProjectLeadRoles = Object.freeze([
  { key: "design", label: "设计负责人" },
  { key: "solution", label: "方案负责人" },
]);
const PRESALES_DELIVERY_LABELS = Object.freeze({
  "early-plan": ["前期方案推进", "前期方案设计"],
  "budget-match": ["预算匹配推进", "预算匹配"],
  "project-filing": ["项目申报推进", "项目申报"],
  "late-plan": ["后期方案推进", "后期方案设计"],
  "device-plan": ["设备方案推进", "设备方案设计"],
  budget: ["工程预算推进", "工程预算"],
  "device-budget": ["设备预算推进", "设备预算"],
  "cost-control": ["工程成本管控推进", "工程成本管控"],
  "device-cost-control": ["设备成本管控推进", "设备成本管控"],
  rendering: ["效果图推进", "效果图设计"],
  "tender-plan": ["招标方案推进", "招标方案设计"],
  layout: ["平面设计推进", "平面设计"],
  "bid-prep": ["投标准备推进", "投标准备"],
  construction: ["施工图推进", "施工图设计"],
});
const deliveryForm = reactive({
  plannedStartAt: "",
  plannedEndAt: "",
  actualStartAt: "",
  actualEndAt: "",
  estimatedFee: "",
  actualFee: "",
  externalQuote: "",
});
const currentTimestamp = ref(Date.now());
let deliveryClockTimer = 0;
let projectSyncTimer = 0;
let projectSyncInFlight = false;
let projectSyncAttempt = 0;
let projectScopeExpiryTimer = 0;
let disposed = false;

const AFTERSALES_ATTACHMENT_GROUPS = [
  ["package", "包装照片"],
  ["model_label", "型号标签"],
  ["appearance", "产品外观"],
  ["installation", "安装完成"],
  ["debugging", "调试完成"],
  ["other", "其他附件"],
];

const MIDSALES_PROOF_NODE_KEYS = new Set([
  "construction-work",
  "furniture-install",
  "device-install",
  "device-debug",
  "school-support",
]);
const MIDSALES_PROOF_TYPES = [
  { key: "process", label: "过程证明照片" },
  { key: "completion", label: "完工证明照片" },
  { key: "evaluation", label: "用户评价文件" },
];
const MIDSALES_PROOF_ATTACHMENT_CATEGORIES = Object.freeze([{ value: "general", label: "附件" }]);
const midsalesFeeDetail = reactive({ estimatedNote: "", actualNote: "" });
const aftersalesFeeDetail = reactive({ estimatedNote: "", actualNote: "" });
const midsalesFeeModalOpen = ref(false);
const midsalesFeeModalPhase = ref("");
const midsalesFeeModalKind = ref("");
const midsalesFeeNoteDraft = ref("");
const aftersalesFeeModalOpen = ref(false);
const aftersalesFeeModalPhase = ref("");
const aftersalesFeeModalKind = ref("note");
const aftersalesFeeNoteDraft = ref("");

const MIDSALES_ASSIGNMENT_NODE_KEYS = new Set([
  "construction-work",
  "furniture-install",
  "device-install",
  "device-debug",
  "school-support",
  "project-acceptance",
]);
const MIDSALES_FLOW_ORDER = [
  "midsales-project",
  "construction-work",
  "furniture-install",
  "device-install",
  "device-debug",
  "school-support",
  "project-acceptance",
  "midsales-project-end",
];
const MIDSALES_FLOW_LABELS = {
  "midsales-project": "启动",
  "construction-work": "施工",
  "furniture-install": "家具",
  "device-install": "安装",
  "device-debug": "调试",
  "school-support": "保障",
  "project-acceptance": "验收",
  "midsales-project-end": "结束",
};

const createForm = reactive({
  name: "",
  customer_name: "",
  owner_name: "",
  description: "",
  application_reason: "",
  original_files: [],
  address: "",
  service_node_id: "onsite-service",
  enabled_node_ids: [],
  manager_contact: "",
  expected_duration: "1天",
  fee_agreement: "客户承担",
  fee_remark: "",
});
const stageOptions = computed(() => config.value.stages.map(([id, name]) => ({ id, name })));
// All filters run on the server before pagination, so later pages remain searchable.
const filteredProjects = computed(() => projects.value);

const currentProject = computed(() => projectDetail.value || projects.value.find((item) => String(item.id) === String(selectedId.value)) || null);
const isCrmProject = computed(() => projectHasCrmSource(currentProject.value));
const nodes = computed(() => {
  const raw = currentProject.value?.nodes || currentProject.value?.workflow?.nodes || currentProject.value?.process_nodes || currentProject.value?.processNodes;
  if (Array.isArray(raw) && raw.length) return raw;
  const currentId = currentProject.value?.currentNodeKey || currentProject.value?.current_node_key
    || currentProject.value?.current_node_id || currentProject.value?.currentNodeId;
  const currentIndex = stageOptions.value.findIndex((node) => node.id === currentId);
  return stageOptions.value.map((node, index) => ({
    ...node,
    name: node.name,
    status: index < currentIndex ? "已完成" : index === currentIndex ? "进行中" : "未开始",
    done: index < currentIndex,
    enabled: true,
  }));
});
const selectedNode = computed(() => nodes.value.find((node) => nodeKey(node) === selectedNodeId.value) || nodes.value[0] || null);
const selectedNodeAttachmentId = computed(() => normalizeDatabaseId(selectedNode.value?.id));
const presalesFlowNodes = computed(() => nodes.value.map((node, index) => {
  const key = nodeKey(node);
  const placement = PRESALES_FLOW_LAYOUT[key];
  if (!placement) return null;
  return {
    node,
    key,
    sequence: index + 1,
    column: placement.column,
    lane: placement.lane,
    gridRow: placement.lane === "bridge" ? "1 / span 2" : placement.lane === "lower" ? "2" : "1",
  };
}).filter(Boolean));
const midsalesFlowNodes = computed(() => MIDSALES_FLOW_ORDER
  .map((key) => nodes.value.find((node) => nodeKey(node) === key))
  .filter(Boolean));
const isMidsalesProofNode = computed(() => (
  props.serviceType === "midsales" && MIDSALES_PROOF_NODE_KEYS.has(nodeKey(selectedNode.value))
));
const openedMidsalesProof = computed(() => nodeProofs.value.find((item) => proofType(item) === openedMidsalesProofType.value) || null);
const currentNodeKey = computed(() => currentProject.value?.currentNodeKey || currentProject.value?.current_node_key || currentProject.value?.currentNodeId || currentProject.value?.current_node_id || "");
const pendingSettlementItems = computed(() => (
  props.serviceType === "presales" ? [] : Array.isArray(currentProject.value?.settlementItems)
    ? currentProject.value.settlementItems
    : Array.isArray(currentProject.value?.settlement_items)
      ? currentProject.value.settlement_items
      : []
));
const selectedSettlementItems = computed(() => pendingSettlementItems.value.filter((item) => (
  String(item?.nodeId || item?.node_id || "") === String(selectedNode.value?.id || "")
  || String(item?.nodeKey || item?.node_key || "") === nodeKey(selectedNode.value)
)));
const isAftersales = computed(() => props.serviceType === "aftersales");
const aftersalesProjectData = computed(() => currentProject.value?.businessData || currentProject.value?.business_data || {});
const aftersalesExpectedDuration = computed(() => display(aftersalesProjectData.value, "expectedDuration", "expected_duration"));
const aftersalesRelatedProducts = computed(() => (
  Array.isArray(aftersalesProjectData.value.relatedProducts)
    ? aftersalesProjectData.value.relatedProducts
    : []
));
const midsalesRelatedProducts = computed(() => {
  const data = selectedNode.value?.businessData || selectedNode.value?.business_data || {};
  return Array.isArray(data.relatedProducts) ? data.relatedProducts : [];
});
const relatedProductPickerProducts = computed(() => {
  if (!relatedProductTargetNodeKey.value) return aftersalesRelatedProducts.value;
  const target = nodes.value.find((node) => nodeKey(node) === relatedProductTargetNodeKey.value);
  const data = target?.businessData || target?.business_data || {};
  return Array.isArray(data.relatedProducts) ? data.relatedProducts : [];
});
const aftersalesCurrentNode = computed(() => selectedNode.value);
const enabledNodes = computed(() => nodes.value.filter((node) => node.enabled !== false));
const completedNodes = computed(() => enabledNodes.value.filter((node) => node.done || ["completed", "已完成", "通过", "中标"].includes(node.status)).length);
const progress = computed(() => enabledNodes.value.length ? Math.round((completedNodes.value / enabledNodes.value.length) * 100) : 0);
const timeline = computed(() => currentProject.value?.events || []);

function projectHistoryScope(item) {
  if (!item.nodeId) return "项目";
  const node = nodes.value.find((node) => String(node.id) === String(item.nodeId));
  return node ? nodeName(node) : "历史节点";
}
const selectedAssignment = computed(() => (currentProject.value?.assignments || []).find((item) => (
  item.status !== "cancelled"
  && (
    nodeKey(item) === nodeKey(selectedNode.value)
    || String(item.nodeId || item.node_id || "") === String(selectedNode.value?.id || "")
  )
)) || null);
const selectedFieldSubmission = computed(() => {
  const data = selectedNode.value?.businessData || selectedNode.value?.business_data || {};
  const assignmentId = selectedAssignment.value?.id;
  const submissions = data.fieldSubmissions || data.field_submissions || {};
  return assignmentId ? submissions[String(assignmentId)] || null : null;
});
const selectedFieldDraft = computed(() => {
  const data = selectedNode.value?.businessData || selectedNode.value?.business_data || {};
  const assignmentId = selectedAssignment.value?.id;
  const drafts = data.fieldDrafts || data.field_drafts || {};
  return assignmentId ? drafts[String(assignmentId)] || null : null;
});
const selectedFieldRecord = computed(() => ({
  ...(selectedFieldSubmission.value || {}),
  ...(selectedFieldDraft.value || {}),
}));
const selectedNodeData = computed(() => selectedNode.value?.businessData || selectedNode.value?.business_data || {});
const fieldCompletionRequired = computed(() => Boolean(
  selectedNode.value
  && (
    (props.serviceType === "midsales" && MIDSALES_ASSIGNMENT_NODE_KEYS.has(nodeKey(selectedNode.value)))
    || (props.serviceType === "aftersales" && nodeKey(selectedNode.value) !== "mail-service")
  )
));
const fieldCompletionSubmitted = computed(() => selectedFieldSubmission.value?.submitted === true);
const fieldCompletionRejected = computed(() => selectedNodeData.value.managerReviewStatus === "rejected");
const fieldNodeStarted = computed(() => Boolean(
  selectedNode.value?.actualStartAt || selectedNode.value?.actual_start_at,
));
const selectedSettlementState = computed(() => {
  const node = selectedNode.value;
  if (!node || props.serviceType === "presales") return null;

  const key = nodeKey(node);
  const chargeable = props.serviceType === "midsales"
    ? MIDSALES_PROOF_NODE_KEYS.has(key)
    : ["onsite-service", "mail-service", "school-inspection"].includes(key);
  if (!chargeable) {
    return { label: "无需结算", detail: "当前节点不是收费节点", tone: "neutral" };
  }

  const rawActualFee = deliveryForm.actualFee;
  if (rawActualFee === "" || rawActualFee === null || rawActualFee === undefined) {
    return { label: "等待实际费用", detail: "实际费用提交后由系统自动判断", tone: "pending" };
  }
  const actualFee = Number(rawActualFee);
  if (!Number.isFinite(actualFee) || actualFee <= 0) {
    return { label: "无需结算", detail: "实际费用为 0，不生成结算记录", tone: "neutral" };
  }
  if (fieldCompletionRequired.value && !fieldCompletionSubmitted.value) {
    return { label: "等待小程序完工", detail: "小程序确认完工后进入结算中心", tone: "pending" };
  }

  const item = selectedSettlementItems.value[0];
  const status = String(item?.settlementStatus || item?.settlement_status || "");
  if (["draft", "pending"].includes(status)) {
    return { label: "结算处理中", detail: item?.settlementStatusLabel || "结算中心已有未完成记录", tone: "processing" };
  }
  if (item) {
    return { label: "待结算", detail: "已满足条件，请前往结算中心确认结清", tone: "pending" };
  }

  const ready = isCompleted(node)
    || (fieldCompletionRequired.value && fieldCompletionSubmitted.value);
  return ready
    ? { label: "已结算", detail: "结算中心已确认结清", tone: "settled" }
    : { label: "等待节点完成", detail: "节点完成后自动进入结算中心", tone: "pending" };
});
const fieldNote = computed(() => selectedFieldSubmission.value?.note || selectedFieldDraft.value?.note || "");
const mobileActualDuration = computed(() => (
  selectedFieldSubmission.value?.actualDuration
  || selectedFieldDraft.value?.actualDuration
  || selectedNodeData.value.actualDuration
  || selectedNodeData.value.actual_duration
  || formatElapsedDuration(
    selectedNode.value?.actualStartAt || selectedNode.value?.actual_start_at,
    selectedNode.value?.actualEndAt || selectedNode.value?.actual_end_at,
  )
));
const materialNodeAttachments = computed(() => nodeAttachments.value.filter((item) => (
  !["fee_estimated", "fee_actual"].includes(item.category)
)));
const proofAttachmentRows = computed(() => nodeProofs.value.flatMap((proof) => proofAttachments(proof)));
const materialCount = computed(() => materialNodeAttachments.value.length + proofAttachmentRows.value.length);
const supplementalNodeAttachments = computed(() => materialNodeAttachments.value.filter((item) => (
  (item.category || "general") === "general"
)));
const latestMobileSyncAt = computed(() => {
  if (!fieldCompletionRequired.value) return "";
  const providerUserId = String(selectedAssignment.value?.provider?.authUserId || selectedAssignment.value?.provider?.auth_user_id || "");
  const attachmentTimes = [...materialNodeAttachments.value, ...proofAttachmentRows.value]
    .filter((item) => !providerUserId || !item.uploadedBy || String(item.uploadedBy) === providerUserId)
    .map((item) => item.createdAt || item.created_at);
  const values = [
    selectedFieldSubmission.value?.submittedAt || selectedFieldSubmission.value?.submitted_at,
    selectedFieldDraft.value?.updatedAt || selectedFieldDraft.value?.updated_at,
    ...attachmentTimes,
  ].filter(Boolean);
  if (!values.length) return "";
  return values.sort((left, right) => new Date(right).getTime() - new Date(left).getTime())[0];
});
const mobileSyncLabel = computed(() => {
  if (!fieldCompletionRequired.value) return "仅管理端维护";
  if (fieldCompletionSubmitted.value) return "小程序已提交";
  if (selectedFieldDraft.value || materialCount.value) return "小程序同步中";
  return "尚未提交";
});
const mobileSyncTone = computed(() => (
  !fieldCompletionRequired.value
    ? "admin"
    : fieldCompletionSubmitted.value
      ? "mobile"
      : selectedFieldDraft.value || materialCount.value
        ? "admin"
        : "pending"
));
const fieldSubmissionSummaryItems = computed(() => {
  const record = selectedFieldRecord.value;
  const status = fieldCompletionSubmitted.value
    ? { value: "已提交", tone: "mobile" }
    : fieldCompletionRejected.value
      ? { value: "已驳回，待重新提交", tone: "rejected" }
      : selectedFieldDraft.value
        ? { value: "编辑中", tone: "pending" }
        : { value: "尚未提交", tone: "pending" };
  return [
    { label: "提交状态", ...status },
    { label: "服务人员", value: record.providerName || selectedAssignment.value?.provider?.name || "-" },
    { label: "实际开始", value: formatDateTimeLabel(record.actualStartAt || selectedNode.value?.actualStartAt || selectedNode.value?.actual_start_at) },
    { label: "实际完成", value: formatDateTimeLabel(record.actualEndAt || selectedNode.value?.actualEndAt || selectedNode.value?.actual_end_at) },
    { label: "实际工期", value: mobileActualDuration.value || "-" },
    { label: "实际费用", value: moneyLabel(record.actualFee ?? deliveryForm.actualFee) },
    { label: "实际费用备注", value: record.actualFeeNote || selectedNodeData.value.feeActualNote || "-", wide: true },
    { label: "现场备注", value: record.note || "-", wide: true },
    {
      label: fieldCompletionSubmitted.value ? "提交时间" : "最近同步",
      value: formatDateTimeLabel(
        fieldCompletionSubmitted.value
          ? record.submittedAt || record.updatedAt
          : selectedFieldDraft.value?.updatedAt || latestMobileSyncAt.value,
      ),
    },
  ];
});
const nodeSummaryItems = computed(() => {
  const assignment = selectedAssignment.value || {};
  const node = selectedNode.value || {};
  const managementAssignment = presalesManagementAssignment(node);
  const actualStart = deliveryForm.actualStartAt || node.actualStartAt || node.actual_start_at;
  const actualEnd = deliveryForm.actualEndAt || node.actualEndAt || node.actual_end_at;
  const plannedStart = deliveryForm.plannedStartAt || node.plannedStartAt || node.planned_start_at || assignment.plannedStartDate || assignment.planned_start_date;
  const plannedEnd = deliveryForm.plannedEndAt || node.plannedEndAt || node.planned_end_at;
  const mobileSource = !fieldCompletionRequired.value
    ? { source: "管理端填写", tone: "admin" }
    : fieldCompletionSubmitted.value
      ? { source: "小程序已提交", tone: "mobile" }
      : actualStart || actualEnd || selectedFieldDraft.value
        ? { source: "小程序同步中", tone: "mobile" }
      : { source: "尚未提交", tone: "pending" };
  return [
    { label: "节点状态", value: isPresales.value ? presalesFlowStatus(node) : display(node, "statusLabel", "status_display", "statusDisplay", "status"), source: "系统状态" },
    { label: "项目人员", value: isPresales.value ? managementAssignment?.name || display(currentProject.value, "ownerName", "owner_name", "owner") : display(assignment.provider, "name") !== "-" ? display(assignment.provider, "name") : display(currentProject.value, "ownerName", "owner_name", "owner"), source: isPresales.value ? "钉钉人员" : "管理端配置", tone: "admin" },
    ...(!isPresales.value ? [
      { label: "计划开始", value: formatDateTimeLabel(plannedStart), source: "管理端填写", tone: "admin" },
      { label: "计划完成", value: formatDateTimeLabel(plannedEnd), source: "管理端填写", tone: "admin" },
    ] : []),
    { label: "实际开始", value: formatDateTimeLabel(actualStart), ...mobileSource },
    { label: "实际完成", value: formatDateTimeLabel(actualEnd), ...mobileSource },
    ...(!isPresales.value ? [{
      label: isAftersales.value ? "预计服务时长" : "计划周期",
      value: isAftersales.value
        ? assignment.standardDuration || assignment.standard_duration || "-"
        : formatElapsedDuration(plannedStart, plannedEnd),
      source: isAftersales.value ? "管理端填写" : "自动计算",
      tone: "admin",
    }] : []),
    { label: "实际工期", value: mobileActualDuration.value || "-", ...mobileSource },
    ...(!isPresales.value ? [
      { label: "预计费用", value: moneyLabel(deliveryForm.estimatedFee), source: "管理端填写", tone: "admin" },
      { label: "实际费用", value: moneyLabel(deliveryForm.actualFee), ...mobileSource },
    ] : []),
  ];
});
const midsalesPlannedStartDate = computed(() => String(
  selectedNode.value?.plannedStartAt
    || selectedNode.value?.planned_start_at
    || selectedAssignment.value?.plannedStartDate
    || selectedAssignment.value?.planned_start_date
    || "",
).slice(0, 10));
const midsalesPlannedEndDate = computed(() => String(
  selectedNode.value?.plannedEndAt || selectedNode.value?.planned_end_at || "",
).slice(0, 10));
const midsalesActualStartTime = computed(() => formatDateTimeLabel(
  selectedNode.value?.actualStartAt || selectedNode.value?.actual_start_at,
));
const personnelRows = computed(() => MIDSALES_FLOW_ORDER
  .map((key) => nodes.value.find((node) => nodeKey(node) === key))
  .filter((node) => node?.enabled !== false && MIDSALES_ASSIGNMENT_NODE_KEYS.has(nodeKey(node)))
  .map((node) => personnelForm[nodeKey(node)])
  .filter(Boolean));
const configuredPersonnelCount = computed(() => personnelRows.value.filter((row) => (
  row.providerId && row.plannedStartDate && row.plannedEndDate
)).length);
const personnelLocked = computed(() => Boolean(
  currentProject.value?.deleted
  || ["completed", "cancelled"].includes(currentProject.value?.status)
));
const canAssignSelectedNode = computed(() => Boolean(
  currentProject.value?.permissions?.canManage
  && selectedNode.value
  && selectedNode.value.enabled !== false
  && !isCompleted(selectedNode.value)
  && (
    props.serviceType !== "midsales"
    || MIDSALES_ASSIGNMENT_NODE_KEYS.has(nodeKey(selectedNode.value))
  )
  && props.serviceType !== "presales"
));
const canReturn = computed(() => {
  if (!currentProject.value?.permissions?.canManage || !selectedNode.value) return false;
  if (props.serviceType === "midsales") return isCompleted(selectedNode.value);
  if (
    props.serviceType === "presales"
    && ["cancelled", "blocked"].includes(currentProject.value.status)
  ) return nodeKey(selectedNode.value) === currentNodeKey.value;
  if (props.serviceType === "presales") {
    if (isCompleted(selectedNode.value)) return true;
    if (selectedNode.value.status !== "active") return false;
    return (PRESALES_SCHEDULE_DEPENDENCIES[nodeKey(selectedNode.value)] || []).some((key) => (
      nodes.value.some((node) => nodeKey(node) === key && node.enabled !== false && isCompleted(node))
    ));
  }
  if (currentProject.value.status === "completed") return isCompleted(selectedNode.value);
  const currentIndex = nodes.value.findIndex((node) => nodeKey(node) === currentNodeKey.value);
  const selectedIndex = nodes.value.findIndex((node) => nodeKey(node) === nodeKey(selectedNode.value));
  return currentIndex > 0 && selectedIndex >= 0 && selectedIndex <= currentIndex;
});
const canAdvance = computed(() => Boolean(
  selectedNode.value?.permissions?.canEdit
  && currentProject.value
  && selectedNode.value
  && (!fieldCompletionRequired.value || fieldCompletionSubmitted.value)
  && ["active", "进行中"].includes(selectedNode.value.status)
  && (
    props.serviceType !== "aftersales"
    || nodeKey(selectedNode.value) === currentNodeKey.value
  )
  && (!decisionOptions.value.length || selectedOutcome.value)
));
const canStart = computed(() => Boolean(
  selectedNode.value?.permissions?.canEdit
  && ["midsales", "aftersales"].includes(props.serviceType)
  && currentProject.value
  && selectedNode.value
  && selectedNode.value.enabled !== false
  && !fieldNodeStarted.value
  && (
    selectedNode.value.status === "pending" && nodeKey(selectedNode.value) === currentNodeKey.value
  )
  && (
    props.serviceType === "aftersales"
      ? nodeKey(selectedNode.value) === "mail-service" || selectedAssignment.value
      : !MIDSALES_ASSIGNMENT_NODE_KEYS.has(nodeKey(selectedNode.value)) || selectedAssignment.value
  )
));
function projectNodeEditable(node) {
  return Boolean(
    node
    && node.permissions?.canEdit
    && currentProject.value
    && !currentProject.value.deleted
    && !["completed", "cancelled", "blocked"].includes(currentProject.value.status)
    && node.enabled !== false
    && !isCompleted(node)
    && (
      ["active", "进行中"].includes(node.status)
      || (
        ["midsales", "aftersales"].includes(props.serviceType)
        && node.status === "pending"
        && nodeKey(node) === currentNodeKey.value
      )
    )
  );
}
const nodeEditable = computed(() => projectNodeEditable(selectedNode.value));
const projectInfoEditable = computed(() => nodeEditable.value && currentProject.value?.permissions?.canManage);
const decisionOptions = computed(() => {
  const key = nodeKey(selectedNode.value);
  if (key === "early-approval" || key === "late-approval") return [
    { value: "approved", label: "立项成功" },
    { value: "denied", label: "立项否决", danger: true },
  ];
  if (key === "early-plan-result") return [
    { value: "passed", label: "通过" },
    { value: "failed", label: "失败", danger: true },
    { value: "abandoned", label: "放弃", danger: true },
    { value: "suspended", label: "挂起" },
  ];
  if (key === "construction-result") return [
    { value: "won", label: "中标" },
    { value: "failed", label: "失败", danger: true },
    { value: "abandoned", label: "放弃", danger: true },
    { value: "suspended", label: "挂起" },
  ];
  return [];
});
const isPresales = computed(() => props.serviceType === "presales");
const isPresalesApproval = computed(() => isPresales.value && selectedNode.value?.kind === "approval");
const presalesApprovalOutcome = computed(() => String(selectedNode.value?.businessData?.outcome || selectedNode.value?.business_data?.outcome || "").toLowerCase());
const isPresalesApprovalDenied = computed(() => isPresalesApproval.value && presalesApprovalOutcome.value === "denied");
const isPresalesDelivery = computed(() => isPresales.value && selectedNode.value?.kind === "delivery");
const isPresalesResult = computed(() => isPresales.value && selectedNode.value?.kind === "result");
const isPresalesEnd = computed(() => isPresales.value && selectedNode.value?.kind === "end");
const presalesDeliveryMeta = computed(() => PRESALES_DELIVERY_LABELS[nodeKey(selectedNode.value)] || [`${nodeName(selectedNode.value)}推进`, nodeName(selectedNode.value)]);
const presalesApprovalTargets = computed(() => {
  if (!isPresalesApproval.value) return [];
  if (nodeKey(selectedNode.value) === "late-approval") {
    return [
      ["late-plan", "后期方案"],
      ["device-plan", "设备方案"],
      ["budget", "工程预算"],
      ["device-budget", "设备预算"],
      ["cost-control", "工程成本管控"],
      ["device-cost-control", "设备成本管控"],
      ["rendering", "效果图"],
      ["tender-plan", "招标方案"],
      ["layout", "平面设计"],
      ["bid-prep", "投标准备"],
    ].map(([nodeKey, name]) => ({ nodeKey, name }));
  }
  const phase = ["early-plan", "前期方案"];
  return [
    { nodeKey: phase[0], name: phase[1] },
    { nodeKey: "budget-match", name: "预算匹配" },
    { nodeKey: "project-filing", name: "项目申报" },
  ];
});
const presalesPersonnelMissing = computed(() => {
  if (!isPresalesApproval.value) return [];
  const missing = [];
  presalesApprovalTargets.value.forEach((target) => {
    const node = nodes.value.find((item) => nodeKey(item) === target.nodeKey);
    if (!node || node.enabled === false) return;
    const plan = presalesPersonnelForm[target.nodeKey] || {};
    if (!plan.members?.length) missing.push(`${target.name}未分派项目人员`);
  });
  return missing;
});
const presalesPersonnelComplete = computed(() => (
  !isPresalesApproval.value || presalesPersonnelMissing.value.length === 0
));
const presalesPersonnelRows = computed(() => {
  const targets = isPresalesApproval.value ? presalesApprovalTargets.value : isPresalesDelivery.value
    ? [{ nodeKey: nodeKey(selectedNode.value), name: nodeName(selectedNode.value) }] : [];
  return targets.map(target => ({ ...target,
    members: presalesPersonnelForm[target.nodeKey]?.members || [],
    disabled: saving.value || !presalesPersonnelEditable(target),
  }));
});
const midsalesFeeModalTitle = computed(() => `${midsalesFeeModalPhase.value === "estimated" ? "预计" : "实际"}费用${midsalesFeeModalKind.value === "note" ? "备注" : "清单附件"}`);
const midsalesFeeModalEditable = computed(() => midsalesFeeModalPhase.value === "estimated" && nodeEditable.value);
const aftersalesFeeModalTitle = computed(() => `${aftersalesFeeModalPhase.value === "estimated" ? "预计" : "实际"}费用${aftersalesFeeModalKind.value === "attachment" ? "清单附件" : "备注"}`);
const aftersalesFeeModalEditable = computed(() => aftersalesFeeModalPhase.value === "estimated" && nodeEditable.value);
const aftersalesServiceDuration = computed(() => formatElapsedDuration(deliveryForm.actualStartAt, deliveryForm.actualEndAt));
const presalesProjectInfoRecord = computed(() => {
  const data = currentProject.value?.businessData || currentProject.value?.business_data || {};
  const records = data.projectInfoRecords || data.project_info_records || {};
  const nodeData = selectedNode.value?.businessData || selectedNode.value?.business_data || {};
  const nodeRecords = nodeData.projectInfoRecords || nodeData.project_info_records || {};
  const record = records[nodeKey(selectedNode.value)] || data.projectInfo || data.project_info || records["early-approval"] || nodeRecords[nodeKey(selectedNode.value)] || {};
  return isCrmProject.value ? { ...record, ...(data.projectInfo || {}) } : record;
});
function projectNodeDraftSnapshot() {
  const projectId = currentProject.value?.id;
  const activeNodeKey = nodeKey(selectedNode.value);
  if (!projectId || !activeNodeKey) return null;
  const projectData = currentProject.value?.businessData || currentProject.value?.business_data || {};
  const businessData = {
    deliveryNote: actionNote.value,
    ...(!isPresales.value ? { externalQuote: deliveryForm.externalQuote } : {}),
  };
  if (props.serviceType === "presales") {
    if (isPresalesEnd.value) businessData.midsalesNodeKeys = [...handoverNodeKeys.value];
    if (isPresalesDelivery.value) {
      businessData.schemeRounds = presalesSchemeRounds.value.map((item) => ({ ...item }));
      const members = presalesPersonnelForm[activeNodeKey]?.members;
      if (members) businessData.managementAssignment = {
        ...presalesManagementAssignment(selectedNode.value), ...personnelSelection(members), note: members[0]?.note || "",
      };
    }
    if (isPresalesApproval.value) {
      businessData.projectInfoRecords = {
        ...(projectData.projectInfoRecords || projectData.project_info_records || {}),
        [activeNodeKey]: { ...presalesProjectInfo },
      };
    }
  }
  if (props.serviceType === "midsales") {
    businessData.feeEstimatedNote = midsalesFeeDetail.estimatedNote;
  }
  if (props.serviceType === "aftersales") {
    businessData.feeEstimatedNote = aftersalesFeeDetail.estimatedNote;
  }
  return {
    projectId,
    nodeKey: activeNodeKey,
    values: {
      ...(props.serviceType === "aftersales" ? {
        plannedStartAt: deliveryForm.plannedStartAt,
        plannedEndAt: deliveryForm.plannedEndAt,
      } : props.serviceType === "midsales" && activeNodeKey === "midsales-project" ? {
        plannedEndAt: deliveryForm.plannedEndAt,
      } : {}),
      ...(!isPresales.value ? { estimatedFee: deliveryForm.estimatedFee } : {}),
      businessData,
    },
  };
}

let hydratingNodeDraft = true;
const persistedNodeVersions = new Map();
const discardDraftOpen = ref(false);
function expectedNodeVersion(key) {
  const node = nodes.value.find(item => nodeKey(item) === key);
  return (key === nodeKey(selectedNode.value) && persistedNodeVersions.get(`${currentProject.value?.id}:${key}`))
    || node?.updatedAt || node?.updated_at || "";
}
function nodeDraftPayload(draft) {
  return {
    ...draft.values,
    expectedUpdatedAt: persistedNodeVersions.get(`${draft.projectId}:${draft.nodeKey}`) || "",
  };
}
const {
  reset: resetNodeAutosave,
  schedule: scheduleNodeAutosave,
  flush: flushNodeAutosave,
  pending: nodeAutosavePending,
  saving: nodeAutosaveSaving,
} = useDebouncedAutosave(
  async (draft) => {
    const response = await serviceApi.updateProjectNode(draft.projectId, draft.nodeKey, nodeDraftPayload(draft));
    error.value = "";
    const updatedProject = unwrapProject(response);
    const node = updatedProject?.nodes?.find(item => nodeKey(item) === draft.nodeKey);
    persistedNodeVersions.set(`${draft.projectId}:${draft.nodeKey}`, node?.updatedAt || node?.updated_at || "");
    if (String(currentProject.value?.id) === String(draft.projectId) && nodeKey(selectedNode.value) === draft.nodeKey) {
      if (draft.values.businessData.managementAssignment && node) {
        selectedNode.value.businessData = { ...selectedNode.value.businessData, managementAssignment: node.businessData.managementAssignment };
        selectedNode.value.updatedAt = node.updatedAt;
      }
      Object.assign(currentProject.value, { updatedAt: updatedProject.updatedAt });
    }
    return response;
  },
  {
    delay: 700,
    onError: (reason) => {
      error.value = reason instanceof Error ? reason.message : "项目详情自动保存失败";
    },
  },
);

function presalesProjectInfoSnapshot() {
  const projectId = currentProject.value?.id;
  if (!projectId || !projectInfoEditable.value) return null;
  const values = {
    customer: presalesProjectInfo.customer.trim(),
    owner: presalesProjectInfo.owner.trim(),
    name: presalesProjectInfo.name.trim(),
    info: presalesProjectInfo.info.trim(),
    reason: presalesProjectInfo.reason.trim(),
  };
  const projectData = currentProject.value?.businessData || currentProject.value?.business_data || {};
  const records = projectData.projectInfoRecords || projectData.project_info_records || {};
  const record = { ...presalesProjectInfoRecord.value, ...values };
  return {
    projectId,
    values,
    crmSource: isCrmProject.value,
    businessData: {
      ...projectData,
      projectInfo: {
        ...record,
        totalArea: projectData.projectInfo?.totalArea ?? null,
        designArea: projectData.projectInfo?.designArea ?? null,
        projectLevel: projectData.projectInfo?.projectLevel || "",
        urgency: projectData.projectInfo?.urgency || "",
        expectedBidAt: projectData.projectInfo?.expectedBidAt || "",
      },
      projectInfoRecords: { ...records, [nodeKey(selectedNode.value)]: record },
      applicationReason: values.reason,
    },
  };
}

const {
  saving: presalesProjectInfoSaving,
  pending: presalesProjectInfoPending,
  reset: resetPresalesProjectInfoAutosave,
  schedule: schedulePresalesProjectInfoAutosave,
  flush: flushPresalesProjectInfoAutosave,
} = useDebouncedAutosave(
  async (draft) => {
    if (!draft.crmSource && (!draft.values.customer || !draft.values.name)) {
      throw new Error("请填写客户单位和项目名称，当前填写已保留");
    }
    await flushNodeAutosave();
    const projectInfo = currentProject.value?.businessData?.projectInfo || {};
    const businessData = {
      ...draft.businessData,
      projectInfo: {
        ...draft.businessData.projectInfo,
        totalArea: projectInfo.totalArea ?? null,
        designArea: projectInfo.designArea ?? null,
        projectLevel: projectInfo.projectLevel || "",
        urgency: projectInfo.urgency || "",
        expectedBidAt: projectInfo.expectedBidAt || "",
      },
    };
    const response = await serviceApi.updateProject(draft.projectId, {
      expectedDraftVersion: currentProject.value?.draftVersion || "",
      ...(draft.crmSource ? {} : {
        name: draft.values.name,
        customer_name: draft.values.customer,
        owner_name: draft.values.owner,
        description: draft.values.info,
      }),
      business_data: businessData,
    });
    if (String(currentProject.value?.id) !== String(draft.projectId)) return;
    error.value = "";
    const localValues = {
      updatedAt: unwrapProject(response)?.updatedAt,
      draftVersion: unwrapProject(response)?.draftVersion,
      name: draft.values.name,
      customer: draft.values.customer,
      customerName: draft.values.customer,
      customer_name: draft.values.customer,
      ownerName: draft.values.owner,
      owner_name: draft.values.owner,
      summary: draft.values.info,
      description: draft.values.info,
      businessData,
      business_data: businessData,
    };
    Object.assign(currentProject.value, localValues);
    const listProject = projects.value.find((item) => String(item.id) === String(draft.projectId));
    if (listProject) Object.assign(listProject, localValues);
  },
  {
    delay: 700,
    onError: (reason) => {
      error.value = reason instanceof Error ? reason.message : "项目信息自动保存失败";
    },
  },
);

function presalesPersonnelSnapshot() {
  if (!currentProject.value?.id || !nodeEditable.value || !isPresalesApproval.value) return null;
  return { projectId: currentProject.value.id,
    assignments: presalesPersonnelRows.value.filter(row => presalesPersonnelEditable(row))
      .map(row => ({ nodeKey: row.nodeKey, members: row.members.map(member => ({ ...member })) })),
  };
}

const {
  saving: presalesPersonnelSaving,
  pending: presalesPersonnelPending,
  reset: resetPresalesPersonnelAutosave,
  schedule: schedulePresalesPersonnelAutosave,
  flush: flushPresalesPersonnelAutosave,
} = useDebouncedAutosave(async (draft) => {
  await flushNodeAutosave();
  await flushPresalesProjectInfoAutosave();
  for (const row of draft.assignments) {
    if (String(currentProject.value?.id) !== String(draft.projectId)) return;
    const target = nodes.value.find(node => nodeKey(node) === row.nodeKey);
    const existing = presalesManagementAssignment(target);
    if (JSON.stringify(personnelAssignmentMembers(existing)) === JSON.stringify(row.members)) continue;
    const selection = { ...personnelSelection(row.members), note: row.members[0]?.note || "" };
    const response = await serviceApi.updateProjectNode(draft.projectId, row.nodeKey, {
      expectedUpdatedAt: expectedNodeVersion(row.nodeKey),
      businessData: { managementAssignment: { ...existing, ...selection } },
    });
    if (String(currentProject.value?.id) !== String(draft.projectId)) return;
    const updated = unwrapProject(response);
    const savedNode = updated.nodes?.find(node => nodeKey(node) === row.nodeKey);
    if (!savedNode) throw new Error("项目人员保存结果不完整，请重试");
    // Merge the saved assignment only. Other people may already have a newer
    // note draft, which replacing the entire detail would otherwise erase.
    target.businessData = { ...target.businessData, managementAssignment: savedNode.businessData.managementAssignment };
    target.updatedAt = savedNode.updatedAt;
    persistedNodeVersions.set(`${draft.projectId}:${row.nodeKey}`, savedNode.updatedAt);
    currentProject.value.updatedAt = updated.updatedAt;
  }
  error.value = "";
}, { onError: reason => { error.value = reason instanceof Error ? reason.message : "工作说明自动保存失败"; } });

const {
  values: presalesMetadata, editable: presalesMetadataEditable, errors: presalesMetadataErrors,
  saving: presalesMetadataSaving, pending: presalesMetadataPending,
  flush: flushPresalesMetadata, discard: discardPresalesMetadata,
} = usePresalesProjectInfo({
  project: () => currentProject.value,
  enabled: () => isPresales.value,
  beforeSave: async () => { await flushNodeAutosave(); await flushPresalesProjectInfoAutosave(); },
  onSaved: (updated) => {
    const localValues = {
      updatedAt: updated.updatedAt, draftVersion: updated.draftVersion,
      businessData: updated.businessData, business_data: updated.businessData, events: updated.events,
    };
    Object.assign(currentProject.value, localValues);
    const listed = projects.value.find(item => String(item.id) === String(updated.id));
    if (listed) Object.assign(listed, localValues);
    error.value = "";
  },
  onError: reason => { error.value = reason instanceof Error ? reason.message : "项目信息自动保存失败"; },
});

const presalesDocumentsBusy = ref(false);
const autosaveDirty = computed(() => presalesMetadataPending.value || presalesRoundDraft.value.dirty || nodeAutosavePending.value || presalesProjectInfoPending.value || presalesPersonnelPending.value || personnelRows.value.some(row => row.dirty));
const autosaveBusy = computed(() => presalesDocumentsBusy.value || presalesMetadataSaving.value || presalesRoundDraft.value.busy || nodeAutosaveSaving.value || presalesProjectInfoSaving.value || presalesPersonnelSaving.value || saving.value || presalesSchemeSaving.value || personnelRows.value.some(row => row.saving));
watch(autosaveDirty, value => emit("dirty-change", value), { immediate: true });
watch(autosaveBusy, value => emit("busy-change", value), { immediate: true });

async function flushProjectDrafts({ personnel = true } = {}) {
  if (presalesDocumentsBusy.value) throw new Error("正在处理项目需求文档，请稍候");
  if (presalesRoundDraft.value.busy) throw new Error("正在保存轮次，请稍候");
  if (presalesRoundDraft.value.dirty && !await presalesProgressPanel.value?.requestCloseReason()) {
    throw new Error("新增原因和附件尚未提交");
  }
  await flushNodeAutosave();
  await flushPresalesProjectInfoAutosave();
  await flushPresalesMetadata();
  await flushPresalesPersonnelAutosave();
  if (!personnel) return;
  for (const row of personnelRows.value) {
    if (row.saving || (row.dirty && !await savePersonnelRow(row, { showNotice: false, flushDrafts: false }))) {
      throw new Error(error.value || "项目人员配置正在保存，请稍后再试");
    }
  }
}

async function selectProjectNode(key) {
  if (key === selectedNodeId.value) return true;
  try {
    await flushProjectDrafts();
    selectedNodeId.value = key;
    return true;
  } catch { return false; }
}

async function selectDetailTab(tab) {
  if (tab === detailTab.value) return;
  if (tab === "info" || detailTab.value === "info") {
    try { await flushProjectDrafts(); } catch { return; }
  }
  detailTab.value = tab;
}

function discardDrafts() {
  presalesProgressPanel.value?.discardReasonDraft();
  presalesRoundDraft.value = { dirty: false, busy: false };
  resetNodeAutosave(null);
  resetPresalesProjectInfoAutosave(null);
  resetPresalesPersonnelAutosave(null);
  discardPresalesMetadata();
  resetPersonnelForm();
  presalesProjectInfoOpen.value = false;
  discardDraftOpen.value = false;
}

defineExpose({ discard: discardDrafts, openProject: loadDetail });

async function reloadSavedProject() {
  discardDrafts();
  await loadDetail(selectedId.value, { open: false, focusNodeKey: selectedNodeId.value });
}

function presalesNodeData(node = selectedNode.value) {
  return node?.businessData || node?.business_data || {};
}

function resetPresalesDraft(node = selectedNode.value) {
  const data = presalesNodeData(node);
  const key = nodeKey(node);
  const projectData = currentProject.value?.businessData || currentProject.value?.business_data || {};
  const records = projectData.projectInfoRecords || projectData.project_info_records || {};
  const nodeRecords = data.projectInfoRecords || data.project_info_records || {};
  const canonical = projectData.projectInfo || projectData.project_info || records["early-approval"] || nodeRecords[key] || {};
  const historicInfo = nodeRecords[key] || records[key] || canonical;
  const info = isCrmProject.value ? { ...historicInfo, ...canonical } : historicInfo;
  Object.assign(presalesProjectInfo, {
    customer: info.customer || display(currentProject.value, "customer", "customerName", "customer_name"),
    owner: info.owner || display(currentProject.value, "ownerName", "owner_name", "owner"),
    name: info.name || display(currentProject.value, "name", "projectName", "project_name"),
    info: info.info || display(currentProject.value, "summary", "description"),
    reason: info.reason || projectData.applicationReason || projectData.application_reason || "",
  });
  const serverSchemeRounds = Array.isArray(data.schemeRounds)
    ? data.schemeRounds.map(normalizePresalesProgressRound)
    : [];
  presalesSchemeRounds.value = serverSchemeRounds.length || !isPresales.value || node?.kind !== "delivery"
    ? serverSchemeRounds
    : [emptyPresalesProgressRound()];
  Object.assign(midsalesFeeDetail, { estimatedNote: data.feeEstimatedNote || data.fee_estimated_note || "", actualNote: data.feeActualNote || data.fee_actual_note || "" });
  Object.assign(aftersalesFeeDetail, {
    estimatedNote: data.feeEstimatedNote || data.fee_estimated_note || "",
    actualNote: data.feeActualNote || data.fee_actual_note || "",
  });
  Object.keys(presalesPersonnelForm).forEach((item) => delete presalesPersonnelForm[item]);
  presalesPersonnelRows.value.forEach((target) => {
    const targetNode = nodes.value.find((item) => nodeKey(item) === target.nodeKey);
    const assignment = presalesManagementAssignment(targetNode);
    presalesPersonnelForm[target.nodeKey] = {
      members: personnelAssignmentMembers(assignment),
    };
  });
}

let roundSaveCompletion = Promise.resolve();
async function updatePresalesSchemeRounds(rounds) {
  const normalizedRounds = Array.isArray(rounds)
    ? rounds.map(normalizePresalesProgressRound)
    : [];
  presalesSchemeRounds.value = normalizedRounds;
  if (!drawerOpen.value || !nodeEditable.value || presalesSchemeSaving.value) return;

  const draft = projectNodeDraftSnapshot();
  if (!draft) return;
  presalesSchemeSaving.value = true;
  let finishSave;
  roundSaveCompletion = new Promise(resolve => { finishSave = resolve; });
  error.value = "";
  try {
    // Flush edits already queued for this node before persisting the round change.
    await flushNodeAutosave();
    const response = await serviceApi.updateProjectNode(draft.projectId, draft.nodeKey, nodeDraftPayload(draft));
    if (String(currentProject.value?.id) === String(draft.projectId)) {
      projectDetail.value = unwrapProject(response);
    }
    const latestDraft = projectNodeDraftSnapshot();
    if (JSON.stringify(latestDraft) === JSON.stringify(draft)) {
      resetNodeAutosave(latestDraft);
    } else if (latestDraft && drawerOpen.value && nodeEditable.value) {
      scheduleNodeAutosave(latestDraft);
    }
    showSuccess("方案推进轮次已保存");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "方案推进轮次保存失败";
  } finally {
    presalesSchemeSaving.value = false;
    finishSave();
  }
}

async function preparePresalesRound({ index }) {
  const projectId = currentProject.value?.id;
  const key = nodeKey(selectedNode.value);
  const roundId = presalesSchemeRounds.value[index]?.roundId || "";
  if (!projectId || !nodeEditable.value || saving.value) throw new Error("当前节点无法处理，请稍后重试");
  await roundSaveCompletion;
  await nextTick();
  scheduleNodeAutosave(projectNodeDraftSnapshot());
  await flushNodeAutosave();
  if (String(currentProject.value?.id) !== String(projectId) || nodeKey(selectedNode.value) !== key) {
    throw new Error("项目已切换，请在当前项目重新操作");
  }
  // Use the version actually displayed or returned by our own save, never a
  // fresh GET stamp that could silently approve another person's unseen edits.
  const expectedUpdatedAt = persistedNodeVersions.get(`${projectId}:${key}`) || "";
  const response = await serviceApi.projectRoundAction(projectId, key, "prepare-forward", {
    roundIndex: index, roundId, expectedUpdatedAt,
  });
  if (String(currentProject.value?.id) !== String(projectId) || nodeKey(selectedNode.value) !== key) {
    throw new Error("项目已切换，请在当前项目重新操作");
  }
  projectDetail.value = unwrapProject(response);
  await nextTick();
  const savedNode = projectDetail.value.nodes.find(item => nodeKey(item) === key);
  return {
    projectId, projectName: projectDetail.value.name, nodeKey: key, nodeName: nodeName(savedNode),
    roundId: response.roundId, roundIndex: index,
    expectedUpdatedAt: savedNode.updatedAt || savedNode.updated_at || "",
  };
}

async function processPresalesRound({ index, action, reason = "", reasonFiles = [], attachmentId }) {
  const prepared = await preparePresalesRound({ index });
  saving.value = true;
  try {
    const response = await serviceApi.projectRoundAction(prepared.projectId, prepared.nodeKey, "process", {
      roundId: prepared.roundId, expectedUpdatedAt: prepared.expectedUpdatedAt, action, reason,
      ...(attachmentId != null ? { attachmentId } : {}),
    }, { reasonFiles });
    if (String(currentProject.value?.id) === String(prepared.projectId)) projectDetail.value = unwrapProject(response);
    await nextTick();
    void loadProjects({ silent: true });
    return action === "add_round" ? presalesSchemeRounds.value.length - 1 : index;
  } finally {
    saving.value = false;
  }
}

function openPresalesProjectInfoModal() {
  resetPresalesDraft(selectedNode.value);
  presalesProjectInfoOpen.value = true;
  nextTick(() => resetPresalesProjectInfoAutosave(presalesProjectInfoSnapshot()));
}

async function closePresalesProjectInfoModal() {
  const draft = presalesProjectInfoSnapshot();
  if (draft) {
    schedulePresalesProjectInfoAutosave(draft);
    try { await flushPresalesProjectInfoAutosave(); } catch { return false; }
  }
  presalesProjectInfoOpen.value = false;
  return true;
}

function openPresalesDenial() {
  presalesDenialReason.value = "";
  presalesDenialOpen.value = true;
}

function closePresalesDenial() {
  presalesDenialOpen.value = false;
  presalesDenialReason.value = "";
}

async function confirmPresalesDenial() {
  if (!presalesDenialReason.value.trim()) {
    error.value = "请填写立项否决原因";
    return;
  }
  const denied = await runAction("advance", {
    outcome: "denied",
    note: presalesDenialReason.value.trim(),
  });
  if (denied) closePresalesDenial();
}

async function restorePresalesApproval() {
  await runAction("return", { note: "恢复已否决的售前立项" });
}

function openWorkerRatingModal(assignment, node) {
  const providerId = assignment?.providerId || assignment?.provider_id || assignment?.provider?.id;
  if (!providerId || (!node?.nodeKey && !node?.node_key)) return;
  Object.assign(workerRatingForm, {
    providerId: String(providerId),
    providerName: assignment?.provider?.name || "服务人员",
    projectId: String(currentProject.value?.id || ""),
    nodeKey: nodeKey(node),
    nodeName: nodeName(node),
    rating: 5,
  });
  workerRatingOpen.value = true;
}

function closeWorkerRatingModal() {
  if (workerRatingSaving.value) return;
  workerRatingOpen.value = false;
}

async function submitWorkerRating() {
  if (workerRatingSaving.value || !workerRatingForm.projectId || !workerRatingForm.nodeKey) return;
  workerRatingSaving.value = true;
  error.value = "";
  try {
    await serviceApi.createRating({
      projectId: workerRatingForm.projectId,
      nodeKey: workerRatingForm.nodeKey,
      providerId: workerRatingForm.providerId,
      rating: Number(workerRatingForm.rating),
    });
    workerRatingOpen.value = false;
    showSuccess("服务人员评分已记录");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "服务人员评分保存失败";
  } finally {
    workerRatingSaving.value = false;
  }
}

async function savePresalesProjectInfo() {
  if (!currentProject.value?.id || !nodeEditable.value || presalesProjectInfoSaving.value) return;
  const draft = presalesProjectInfoSnapshot();
  if (!draft) {
    error.value = "请补全客户和项目名称";
    return;
  }
  error.value = "";
  schedulePresalesProjectInfoAutosave(draft);
  try {
    await flushPresalesProjectInfoAutosave();
    presalesProjectInfoOpen.value = false;
    showSuccess("项目信息已保存");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "项目信息保存失败";
  }
}

function updatePresalesPersonnelMembers(targetNodeKey, members) {
  if (!presalesPersonnelEditable({ nodeKey: targetNodeKey }) || saving.value) return;
  const plan = presalesPersonnelForm[targetNodeKey];
  if (!plan) return;
  plan.members = members;
  if (isPresalesDelivery.value) scheduleNodeAutosave(projectNodeDraftSnapshot());
  else schedulePresalesPersonnelAutosave(presalesPersonnelSnapshot());
}

const regions = computed(() => [...new Set(teamMembers.value.flatMap((item) => item.regions || [item.city]).filter(Boolean))]);
const skills = computed(() => [...new Set(teamMembers.value.flatMap((item) => item.skills || item.abilities || []).filter(Boolean))]);

function managementEmployeeDepartments(member) {
  const departments = Array.isArray(member?.departments)
    ? member.departments
    : Array.isArray(member?.departmentIds)
      ? member.departmentIds
      : [];
  return departments.map((department) => (
    typeof department === "object" && department !== null
      ? {
          id: department.deptId || department.dept_id || department.id || "",
          name: department.name || department.departmentName || department.department_name || "",
          pinyin: department.pinyin || "",
          pinyinInitials: department.pinyinInitials || department.pinyin_initials || "",
          path: department.departmentPathText || department.department_path_text || "",
        }
      : { id: department, name: "", pinyin: "", pinyinInitials: "", path: "" }
  ));
}

function managementEmployeeDepartmentText(member) {
  const names = managementEmployeeDepartments(member)
    .map((department) => department.name || department.path || department.id)
    .filter(Boolean);
  return names.length ? names.join(" / ") : "未分配部门";
}

const filteredTeam = computed(() => {
  const members = managementPicker.value ? managementEmployees.value : teamMembers.value;
  return members.filter((member) => {
    if (managementPicker.value) {
      const departments = managementEmployeeDepartments(member);
      return matchesDirectorySearchKeyword(teamKeyword.value, {
        names: [member.name, ...departments.flatMap(department => [department.name, department.path])],
        ids: [member.userId, member.user_id, ...departments.map(department => department.id)],
        pinyin: [member.pinyin, ...departments.map(department => department.pinyin)],
        pinyinInitials: [member.pinyinInitials || member.pinyin_initials, ...departments.map(department => department.pinyinInitials)],
      });
    }
    const memberSkills = member.skills || member.abilities || [];
    const memberRegions = member.regions || [member.city];
    return matchesSearch(teamKeyword.value, member.name, member.role, member.phone, memberSkills, memberRegions)
      && (!teamRegion.value || memberRegions.includes(teamRegion.value))
      && (!teamSkill.value || memberSkills.includes(teamSkill.value));
  });
});
const teamTargetNodeName = computed(() => {
  if (teamTargetMode.value === "project-lead") return presalesProjectLeadRoles.find(role => role.key === teamTargetNodeKey.value)?.label || "项目负责人";
  if (isPresalesApproval.value) return presalesApprovalTargets.value.find((item) => item.nodeKey === teamTargetNodeKey.value)?.name || nodeName(selectedNode.value);
  const target = personnelForm[teamTargetNodeKey.value];
  return target?.nodeName || nodeName(selectedNode.value);
});

function unwrapProject(payload) {
  return payload?.item || payload?.project || payload?.data || payload;
}

function presalesProjectLead(role, project = currentProject.value) {
  const earlyNode = project?.nodes?.find(node => nodeKey(node) === "early-approval");
  return project?.projectLeads?.[role] || earlyNode?.businessData?.projectLeads?.[role] || null;
}

const presalesProjectLeadsEditable = computed(() => isPresales.value
  && nodeKey(selectedNode.value) === "early-approval" && nodeEditable.value
  && currentProject.value?.permissions?.canManage);

function mergeAssignment(assignment, { syncPersonnel = true } = {}) {
  if (!projectDetail.value || !assignment?.id) return;
  const assignmentNodeKey = nodeKey(assignment);
  const assignedNode = projectDetail.value.nodes?.find(node => nodeKey(node) === assignmentNodeKey);
  if (assignedNode && assignment.nodeUpdatedAt) {
    assignedNode.updatedAt = assignment.nodeUpdatedAt;
    persistedNodeVersions.set(`${projectDetail.value.id}:${assignmentNodeKey}`, assignment.nodeUpdatedAt);
  }
  const currentAssignments = Array.isArray(projectDetail.value.assignments)
    ? projectDetail.value.assignments
    : [];
  projectDetail.value = {
    ...projectDetail.value,
    assignments: [
      ...currentAssignments.filter((item) => nodeKey(item) !== assignmentNodeKey),
      assignment,
    ],
  };
  if (syncPersonnel) syncPersonnelForm();
}

function nodeKey(node) {
  return String(node?.nodeKey || node?.node_key || node?.key || node?.node_id || node?.nodeId || node?.id || "");
}

function nodeName(node) {
  const key = nodeKey(node);
  const prototypeName = props.serviceType === "presales" ? {
    "early-plan-result": "前期方案结果",
    "cost-control": "成本管控",
    "device-cost-control": "成本管控",
    "construction-result": "投标结果",
    "project-end": "售前项目结束",
  }[key] : "";
  const serviceName = props.serviceType === "midsales" && key === "midsales-project-end"
    ? "售中项目结束"
    : "";
  return prototypeName || serviceName || node?.name || node?.label || node?.node_name || node?.nodeName || "未命名节点";
}

function presalesFlowStatus(node) {
  const data = node?.businessData || node?.business_data || {};
  if (node?.kind === "result") {
    const resultLabels = { passed: "通过", won: "中标", failed: "失败", abandoned: "放弃", suspended: "挂起" };
    return resultLabels[String(data.outcome || "").toLowerCase()] || "未判定";
  }
  if (node?.kind === "approval" && !data.outcome && !data.outcomeLabel && !data.outcome_label) return "立项中";
  return data.outcomeLabel || data.outcome_label
    || display(node, "statusLabel", "status_display", "statusDisplay", "status");
}

function presalesResultOptions(node) {
  return nodeKey(node) === "construction-result"
    ? ["未判定", "中标", "失败", "放弃", "挂起"]
    : ["未判定", "通过", "失败", "放弃", "挂起"];
}

async function updatePresalesResult(node, label) {
  if (!projectNodeEditable(node) || saving.value) return;
  if (!await selectProjectNode(nodeKey(node))) return;
  if (label === "未判定") return;
  const outcomeMap = { 通过: "passed", 中标: "won", 失败: "failed", 放弃: "abandoned", 挂起: "suspended" };
  selectedOutcome.value = outcomeMap[label] || "";
  await runAction("advance", { outcome: selectedOutcome.value });
}

function presalesFlowNodeDone(node) {
  const data = node?.businessData || node?.business_data || {};
  const outcome = String(data.outcome || "").toLowerCase();
  if (node?.kind === "approval" && outcome) return outcome === "approved";
  if (node?.kind === "result" && outcome) return ["passed", "won"].includes(outcome);
  return isCompleted(node);
}

function presalesFlowStateClass(node) {
  const data = node?.businessData || node?.business_data || {};
  const outcome = String(data.outcome || "").toLowerCase();
  const status = String(node?.status || "").toLowerCase();
  if (node?.enabled === false || ["skipped", "disabled"].includes(status)) return "is-disabled";
  if (["denied", "failed", "abandoned"].includes(outcome) || ["rejected", "failed", "cancelled"].includes(status)) return "is-failed";
  if (outcome === "suspended" || ["suspended", "blocked"].includes(status)) return "is-paused";
  if (presalesFlowNodeDone(node)) return "is-complete";
  if (node?.kind === "delivery" && activeAssignmentFor(node) && !(node?.actualStartAt || node?.actual_start_at)) return "is-pending";
  if (nodeKey(node) === currentNodeKey.value || ["active", "in_progress"].includes(status)) return "is-current";
  return "is-pending";
}

function scrollPresalesFlowToSelection() {
  if (props.serviceType !== "presales" || !selectedNodeId.value) return;
  nextTick(() => {
    const area = presalesFlowScroll.value;
    if (!area) return;
    const target = Array.from(area.querySelectorAll("[data-presales-node-key]")).find(
      (item) => item.dataset.presalesNodeKey === selectedNodeId.value,
    );
    if (!target) return;
    const left = Math.max(0, target.offsetLeft + (target.offsetWidth / 2) - (area.clientWidth / 2));
    area.scrollTo({ left, behavior: "smooth" });
  });
}

function activeAssignmentFor(node) {
  const requestedKey = nodeKey(node);
  const requestedId = String(node?.id || "");
  return (currentProject.value?.assignments || []).find((assignment) => (
    assignment.status !== "cancelled"
    && (
      nodeKey(assignment) === requestedKey
      || String(assignment.nodeId || assignment.node_id || "") === requestedId
    )
  )) || null;
}

function presalesManagementAssignment(node) {
  const data = node?.businessData || node?.business_data || {};
  const assignment = data.managementAssignment || data.management_assignment;
  return assignment && typeof assignment === "object" ? assignment : null;
}

function presalesPersonnelEditable(target) {
  const node = nodes.value.find(item => nodeKey(item) === target.nodeKey);
  return currentProject.value?.permissions?.canManage && nodeEditable.value && node && node.enabled !== false && !isCompleted(node) && node.status !== "skipped";
}

function resetPersonnelForm() {
  Object.keys(personnelForm).forEach((key) => delete personnelForm[key]);
}

function syncPersonnelForm() {
  resetPersonnelForm();
  if (props.serviceType !== "midsales" || !currentProject.value) return;
  const nodesByKey = new Map(nodes.value.map((node) => [nodeKey(node), node]));
  const targetKeys = new Set(MIDSALES_FLOW_ORDER.filter((key) => {
    const node = nodesByKey.get(key);
    return node?.enabled !== false && MIDSALES_ASSIGNMENT_NODE_KEYS.has(key);
  }));
  MIDSALES_FLOW_ORDER
    .map((key) => nodesByKey.get(key))
    .filter((node) => node?.enabled !== false && MIDSALES_ASSIGNMENT_NODE_KEYS.has(nodeKey(node)))
    .forEach((node) => {
      const key = nodeKey(node);
      const assignment = activeAssignmentFor(node);
      const provider = assignment?.provider || null;
      const data = node.businessData || node.business_data || {};
      const plannedStartDate = String(node.plannedStartAt || node.planned_start_at || "").slice(0, 10)
        || assignment?.plannedStartDate
        || assignment?.planned_start_date
        || "";
      const savedStartDateMode = data.plannedStartMode || data.planned_start_mode;
      const canInheritStart = schedulePredecessorKeys(
        key,
        MIDSALES_SCHEDULE_DEPENDENCIES,
        targetKeys,
      ).length > 0;
      personnelForm[key] = {
        nodeKey: key,
        nodeName: nodeName(node),
        nodeStatus: node.status,
        providerId: assignment?.providerId || assignment?.provider_id || provider?.id || "",
        provider,
        plannedStartDate,
        plannedStartMode: canInheritStart && ["auto", "manual"].includes(savedStartDateMode)
          ? savedStartDateMode
          : canInheritStart ? "auto" : "manual",
        plannedEndDate: String(node.plannedEndAt || node.planned_end_at || "").slice(0, 10),
        role: assignment?.role || "节点负责人",
        note: assignment?.note || "",
        dirty: false,
        saving: false,
      };
    });
  recalculatePersonnelStartDates({ markDirty: false });
}

function recalculatePersonnelStartDates({ markDirty = true } = {}) {
  const changedRows = [];
  for (const row of personnelRows.value) {
    if (row.plannedStartMode === "manual" || personnelRowLocked(row)) continue;
    const inherited = inheritedScheduleStart(
      row.nodeKey,
      MIDSALES_SCHEDULE_DEPENDENCIES,
      personnelForm,
    );
    if (!inherited.predecessorKeys.length || row.plannedStartDate === inherited.startDate) continue;
    row.plannedStartDate = inherited.startDate;
    if (markDirty) row.dirty = true;
    changedRows.push(row);
  }
  return changedRows;
}

function personnelRowLocked(row) {
  return !currentProject.value?.permissions?.canManage || !nodeEditable.value || personnelLocked.value || ["completed", "skipped"].includes(row.nodeStatus);
}

function markPersonnelDirty(row) {
  row.dirty = true;
}

function isCompleted(node) {
  return Boolean(node?.done || ["completed", "closed", "已完成", "通过", "中标"].includes(node?.status));
}

function display(item, ...keys) {
  for (const key of keys) {
    const value = item?.[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return "-";
}

function projectCurrentNodeKey(project) {
  const rawKey = project?.currentNodeKey
    || project?.current_node_key
    || project?.currentNodeId
    || project?.current_node_id
    || "";
  const directKey = String(rawKey).trim();
  if (stageOptions.value.some((stage) => stage.id === directKey)) return directKey;
  const directLabel = project?.currentNodeName
    || project?.current_node_name
    || project?.stage
    || "";
  const matched = stageOptions.value.find((stage) => stage.name === directLabel || stage.id === String(directLabel).trim());
  return matched?.id || directKey;
}

function currentStageName(project) {
  return currentStageNames(project).join("、");
}

function currentStageNames(project) {
  const active = projectActiveNodes(project);
  if (active.length) return active.map(node => stageOptions.value.find(stage => stage.id === node.nodeKey)?.name || node.name);
  const key = projectCurrentNodeKey(project);
  const direct = display(project, "currentNodeName", "current_node_name", "stage");
  return [stageOptions.value.find((item) => item.id === key)?.name
    || (direct !== "-" ? direct : props.serviceType === "presales" ? "售前项目结束" : props.serviceType === "midsales" ? "售中项目结束" : "已完成")];
}

function midsalesFlowNodeDate(node, index) {
  const explicitStart = node?.plannedStartAt || node?.planned_start_at;
  const explicitEnd = node?.plannedEndAt || node?.planned_end_at;
  if (!explicitStart && !explicitEnd && node?.status === "pending") return "-";
  if (explicitStart || explicitEnd) {
    const format = (value) => value ? `${new Date(value).getMonth() + 1}/${new Date(value).getDate()}` : "-";
    const start = format(explicitStart);
    const end = format(explicitEnd);
    return explicitStart && explicitEnd ? `${start}-${end}` : start !== "-" ? start : end;
  }
  const projectStart = new Date(currentProject.value?.plannedStartDate || currentProject.value?.planned_start_date || Date.now());
  const projectEnd = new Date(currentProject.value?.plannedEndDate || currentProject.value?.planned_end_date || projectStart.getTime() + (MIDSALES_FLOW_ORDER.length * 2 * 86400000));
  const span = Math.max(86400000, projectEnd.getTime() - projectStart.getTime());
  const start = new Date(projectStart.getTime() + (span * index / MIDSALES_FLOW_ORDER.length));
  const end = new Date(projectStart.getTime() + (span * (index + 1) / MIDSALES_FLOW_ORDER.length));
  return `${start.getMonth() + 1}/${start.getDate()}-${end.getMonth() + 1}/${end.getDate()}`;
}

function midsalesFlowNodeStatus(node) {
  if (node?.enabled === false) return "不包含";
  if (isCompleted(node)) return "已完成";
  if (["active", "进行中"].includes(node?.status)) return "进行中";
  return "未开始";
}

function hasPendingSettlement(node) {
  return pendingSettlementItems.value.some((item) => (
    String(item?.nodeId || item?.node_id || "") === String(node?.id || "")
    || String(item?.nodeKey || item?.node_key || "") === nodeKey(node)
  ));
}

function midsalesFlowNodeState(node) {
  if (node?.enabled === false) return "is-disabled";
  if (isCompleted(node)) return "is-done";
  if (["active", "进行中"].includes(node?.status)) return "is-current";
  return "is-pending";
}

function timeRange(node, prefix) {
  const start = node?.[`${prefix}StartAt`] || node?.[`${prefix}_start_at`];
  const end = node?.[`${prefix}EndAt`] || node?.[`${prefix}_end_at`];
  if (!start && !end) return "-";
  return [start, end].filter(Boolean).map((item) => String(item).replace("T", " ").slice(0, 16)).join(" 至 ");
}

function aftersalesNodeDate(node, index) {
  const start = node?.plannedStartAt || node?.planned_start_at || currentProject.value?.plannedStartDate;
  const end = node?.plannedEndAt || node?.planned_end_at || currentProject.value?.plannedEndDate;
  if (!start && !end) return "-";
  const format = (value) => value ? `${new Date(value).getMonth() + 1}/${new Date(value).getDate()}` : "-";
  if (start && end) return `${format(start)}-${format(end)}`;
  return format(start || end);
}

function aftersalesNodeState(node) {
  if (node?.enabled === false) return "不包含";
  if (isCompleted(node)) return "已完成";
  if (["active", "进行中"].includes(node?.status)) return "进行中";
  return "未开始";
}

function openRelatedProductPicker(targetNodeKey = "") {
  if (!nodeEditable.value) return;
  relatedProductTargetNodeKey.value = String(targetNodeKey || "");
  relatedProductPickerOpen.value = true;
}

function closeRelatedProductPicker() {
  if (relatedProductSaving.value) return;
  relatedProductPickerOpen.value = false;
  relatedProductTargetNodeKey.value = "";
}

function openRelatedProductDetail(product) {
  relatedProductDetail.value = product;
  relatedProductDetailOpen.value = true;
  void loadRelatedProductDetail();
}

async function loadRelatedProductDetail() {
  const productId = Number(relatedProductDetail.value?.productId || 0);
  const requestToken = ++relatedProductDetailRequestToken;
  relatedProductDetailLoading.value = true;
  relatedProductDetailError.value = "";
  if (!Number.isSafeInteger(productId) || productId < 1) {
    relatedProductDetailError.value = "产品编号无效，无法读取详情";
    relatedProductDetailLoading.value = false;
    return;
  }
  try {
    const response = await serviceApi.getProductCatalogItem(productId);
    if (requestToken !== relatedProductDetailRequestToken || !relatedProductDetailOpen.value) return;
    if (Number(response?.item?.productId) !== productId) throw new Error("产品档案未返回该产品");
    relatedProductDetail.value = response.item;
  } catch (reason) {
    if (requestToken === relatedProductDetailRequestToken && relatedProductDetailOpen.value) {
      relatedProductDetailError.value = reason instanceof Error ? reason.message : "产品详情读取失败";
    }
  } finally {
    if (requestToken === relatedProductDetailRequestToken) relatedProductDetailLoading.value = false;
  }
}

function closeRelatedProductDetail() {
  relatedProductDetailRequestToken += 1;
  relatedProductDetailOpen.value = false;
  relatedProductDetail.value = null;
  relatedProductDetailLoading.value = false;
  relatedProductDetailError.value = "";
}

async function saveRelatedProducts(productIds) {
  if (!currentProject.value?.id || !nodeEditable.value) return;
  relatedProductSaving.value = true;
  error.value = "";
  try {
    const targetNodeKey = relatedProductTargetNodeKey.value;
    const response = targetNodeKey
      ? await serviceApi.updateNodeRelatedProducts(currentProject.value.id, targetNodeKey, productIds)
      : await serviceApi.updateRelatedProducts(currentProject.value.id, productIds);
    const updated = unwrapProject(response);
    projectDetail.value = updated;
    const listProject = projects.value.find((item) => String(item.id) === String(updated.id));
    if (listProject) Object.assign(listProject, updated);
    relatedProductPickerOpen.value = false;
    relatedProductTargetNodeKey.value = "";
    showSuccess(targetNodeKey ? "节点相关产品已保存，说明书已同步到对应现场任务" : "相关产品已保存，产品说明书已同步到对应现场人员的资料页");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "相关产品保存失败";
  } finally {
    relatedProductSaving.value = false;
  }
}

function datetimeInputValue(value) {
  return value ? String(value).slice(0, 16) : "";
}

function formatDateTimeLabel(value) {
  return value ? String(value).replace("T", " ").slice(0, 16) : "-";
}

function moneyLabel(value) {
  if (value === "" || value === null || value === undefined) return "-";
  const amount = Number(value);
  return Number.isFinite(amount) ? `￥${amount.toFixed(2)}` : String(value);
}

function openNoteModal(source = "admin") {
  noteModalSource.value = source;
  noteModalDraft.value = source === "mobile" ? fieldNote.value : actionNote.value;
  noteModalOpen.value = true;
}

function closeNoteModal() {
  noteModalOpen.value = false;
  noteModalDraft.value = "";
}

function saveNoteModal() {
  if (noteModalSource.value !== "admin") return closeNoteModal();
  actionNote.value = noteModalDraft.value.trim();
  closeNoteModal();
  showSuccess("管理端处理说明已更新");
}

function minuteTimestamp(value) {
  const timestamp = new Date(value || "").getTime();
  return Number.isFinite(timestamp) ? Math.floor(timestamp / 60000) * 60000 : NaN;
}

function plannedCompletionDate(startValue, durationValue) {
  const start = String(startValue || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  const duration = Math.max(1, Math.ceil(Number.parseFloat(String(durationValue || "").replace(/[^\d.]/g, "")) || 0));
  if (!start || !duration) return "-";
  const date = new Date(Number(start[1]), Number(start[2]) - 1, Number(start[3]));
  date.setDate(date.getDate() + duration);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function plannedCompletionDateTime(startValue, durationValue) {
  const start = new Date(startValue || "");
  const rawDuration = String(durationValue || "");
  const amount = Number.parseFloat(rawDuration.match(/[\d.]+/)?.[0] || "");
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(amount) || amount <= 0) return "";
  const multiplier = rawDuration.includes("分钟") ? 60_000 : rawDuration.includes("小时") || rawDuration.includes("时") ? 3_600_000 : 86_400_000;
  const end = new Date(start.getTime() + amount * multiplier);
  const pad = (value) => String(value).padStart(2, "0");
  return `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}T${pad(end.getHours())}:${pad(end.getMinutes())}`;
}

function durationDays(value) {
  const parsed = Number.parseFloat(String(value ?? "").replace(/[^\d.]/g, ""));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : "";
}

function formatElapsedDuration(startValue, endValue) {
  const start = new Date(startValue).getTime();
  const end = new Date(endValue).getTime();
  if (!startValue || !endValue || !Number.isFinite(start) || !Number.isFinite(end) || end < start) return "-";
  const minutes = Math.round((end - start) / 60000);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const remainingMinutes = minutes % 60;
  return `${days}天${hours}小时${remainingMinutes}分钟`;
}

function attachmentsFor(category) {
  return nodeAttachments.value.filter((item) => item.category === category);
}

function syncNodeAttachments(items) {
  nodeAttachments.value = collectionRows(items);
  void loadNodeAttachments();
}

function openAftersalesCompletion() {
  if (!currentProject.value?.id || !selectedNode.value) return;
  if (deliveryForm.actualStartAt) completionForm.actualStartTime = deliveryForm.actualStartAt;
  completionForm.actualDuration = aftersalesServiceDuration.value === "-" ? "" : aftersalesServiceDuration.value;
  completionRejectNote.value = "";
  aftersalesCompletionOpen.value = true;
}

function openCompletionRejectModal() {
  completionRejectNote.value = "";
  completionRejectOpen.value = true;
}

function closeCompletionRejectModal() {
  completionRejectOpen.value = false;
  completionRejectNote.value = "";
}

async function confirmAftersalesCompletion() {
  if (deliveryForm.actualStartAt) completionForm.actualStartTime = deliveryForm.actualStartAt;
  completionForm.actualDuration = aftersalesServiceDuration.value === "-" ? "" : aftersalesServiceDuration.value;
  const completed = await runAction("advance");
  if (completed) aftersalesCompletionOpen.value = false;
}

async function rejectAftersalesCompletion() {
  const note = completionRejectNote.value.trim();
  if (!note) {
    error.value = "请填写完工驳回原因";
    return;
  }
  actionNote.value = note;
  const rejected = await runAction("reject_completion");
  if (rejected) {
    closeCompletionRejectModal();
    aftersalesCompletionOpen.value = false;
  }
}

function proofType(proof) {
  return proof?.proofType || proof?.proof_type || "";
}

function proofStatus(proof) {
  return proof?.status || "pending";
}

function proofStatusLabel(proof) {
  return proof?.statusLabel || proof?.status_label || ({
    pending: "待审核",
    approved: "已通过",
    rejected: "已驳回",
  }[proofStatus(proof)] || "待审核");
}

function proofAttachments(proof) {
  return Array.isArray(proof?.attachments) ? proof.attachments : [];
}

function midsalesProofFor(type) {
  return nodeProofs.value.find((item) => proofType(item) === type) || null;
}

function openMidsalesProofModal(type = "") {
  if (!isMidsalesProofNode.value) return;
  midsalesProofModalOpen.value = true;
  openedMidsalesProofType.value = type || openedMidsalesProofType.value || proofType(nodeProofs.value[0]) || MIDSALES_PROOF_TYPES[0]?.key || "";
  const proof = nodeProofs.value.find((item) => proofType(item) === openedMidsalesProofType.value);
  proofReviewOpinion.value = proof?.reviewOpinion || proof?.review_opinion || "";
}

function closeMidsalesProofModal() {
  if (proofReviewSaving.value) return;
  midsalesProofModalOpen.value = false;
  openedMidsalesProofType.value = "";
  proofReviewOpinion.value = "";
}

async function saveMidsalesProofReview(status) {
  const proof = openedMidsalesProof.value;
  const projectId = currentProject.value?.id;
  const currentNodeKey = nodeKey(selectedNode.value);
  if (!proof || !projectId || !currentNodeKey || proofReviewSaving.value) return;
  const opinion = proofReviewOpinion.value.trim();
  if (status === "rejected" && !opinion) {
    error.value = "驳回材料时请填写审核意见";
    return;
  }
  if (status === "approved" && !proofAttachments(proof).length) {
    error.value = "没有上传材料，不能审核通过";
    return;
  }
  proofReviewSaving.value = true;
  error.value = "";
  try {
    const response = await serviceApi.reviewMidsalesProof(
      projectId,
      currentNodeKey,
      proofType(proof),
      status,
      opinion,
    );
    const updated = response?.item || response;
    nodeProofs.value = nodeProofs.value.map((item) => (
      proofType(item) === proofType(proof) ? { ...item, ...updated } : item
    ));
    proofReviewOpinion.value = updated?.reviewOpinion || opinion;
    showSuccess(status === "approved" ? "交付材料已审核通过" : "交付材料已驳回，小程序将显示审核意见");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "交付材料审核失败";
  } finally {
    proofReviewSaving.value = false;
  }
}

function openMidsalesFeeModal(phase, kind) {
  if (props.serviceType !== "midsales") return;
  midsalesFeeModalPhase.value = phase;
  midsalesFeeModalKind.value = kind;
  midsalesFeeNoteDraft.value = kind === "note" ? midsalesFeeDetail[`${phase}Note`] || "" : "";
  midsalesFeeModalOpen.value = true;
}

function closeMidsalesFeeModal(commit = true) {
  const phase = midsalesFeeModalPhase.value;
  if (commit && midsalesFeeModalKind.value === "note" && midsalesFeeModalEditable.value) {
    midsalesFeeDetail[`${phase}Note`] = midsalesFeeNoteDraft.value.trim();
  }
  midsalesFeeModalOpen.value = false;
  midsalesFeeModalPhase.value = "";
  midsalesFeeModalKind.value = "";
  midsalesFeeNoteDraft.value = "";
}

function saveMidsalesFeeNote() {
  const phase = midsalesFeeModalPhase.value;
  if (midsalesFeeModalKind.value !== "note" || !midsalesFeeModalEditable.value) return;
  showSuccess(`${phase === "estimated" ? "预计" : "实际"}费用备注已更新`);
  closeMidsalesFeeModal();
}

function openAftersalesFeeModal(phase, kind = "note") {
  if (props.serviceType !== "aftersales") return;
  aftersalesFeeModalPhase.value = phase;
  aftersalesFeeModalKind.value = kind;
  aftersalesFeeNoteDraft.value = kind === "note"
    ? aftersalesFeeDetail[phase === "estimated" ? "estimatedNote" : "actualNote"] || ""
    : "";
  aftersalesFeeModalOpen.value = true;
}

function closeAftersalesFeeModal(commit = true) {
  if (commit && aftersalesFeeModalEditable.value) {
    aftersalesFeeDetail.estimatedNote = aftersalesFeeNoteDraft.value.trim();
  }
  aftersalesFeeModalOpen.value = false;
  aftersalesFeeModalPhase.value = "";
  aftersalesFeeModalKind.value = "note";
  aftersalesFeeNoteDraft.value = "";
}

function saveAftersalesFeeNote() {
  if (!aftersalesFeeModalEditable.value) return;
  showSuccess(`${aftersalesFeeModalPhase.value === "estimated" ? "预计" : "实际"}费用备注已更新`);
  closeAftersalesFeeModal();
}

function syncMidsalesProofAttachments(items) {
  if (openedMidsalesProof.value) openedMidsalesProof.value.attachments = items;
}

function toggleMidsalesProof(type) {
  openMidsalesProofModal(type);
}

async function loadNodeProofs(node = selectedNode.value) {
  nodeProofs.value = [];
  openedMidsalesProofType.value = "";
  const projectId = currentProject.value?.id;
  const requestedNodeKey = nodeKey(node);
  if (!projectId || props.serviceType !== "midsales" || !MIDSALES_PROOF_NODE_KEYS.has(requestedNodeKey)) return;
  proofLoading.value = true;
  try {
    const rows = collectionRows(await serviceApi.listMidsalesProofs(projectId, requestedNodeKey));
    const proofs = await Promise.all(rows.map(async (proof) => {
      const embedded = collectionRows(proof?.attachments);
      const proofId = normalizeDatabaseId(proof?.id);
      const attachments = embedded.length
        ? embedded
        : proofId
          ? collectionRows(await serviceApi.listAttachments("midsales_proof", proofId))
          : [];
      return { ...proof, attachments };
    }));
    if (String(currentProject.value?.id) !== String(projectId) || nodeKey(selectedNode.value) !== requestedNodeKey) return;
    nodeProofs.value = proofs;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "证明材料加载失败";
  } finally {
    if (nodeKey(selectedNode.value) === requestedNodeKey) proofLoading.value = false;
  }
}

async function loadNodeAttachments(node = selectedNode.value) {
  const nodeId = normalizeDatabaseId(node?.id);
  if (!nodeId) {
    nodeAttachments.value = [];
    return;
  }
  try {
    const items = collectionRows(await serviceApi.listAttachments("project_node", nodeId));
    if (selectedNodeAttachmentId.value === nodeId) {
      nodeAttachments.value = items;
      nodeAttachmentsVersion.value += 1;
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "节点附件加载失败";
  }
}

async function uploadNodeAttachment(category, event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  const nodeId = selectedNodeAttachmentId.value;
  if (!file || !nodeId) return;
  attachmentBusy.value = category;
  error.value = "";
  try {
    await serviceApi.uploadAttachment("project_node", nodeId, file, category);
    await loadNodeAttachments();
    showSuccess("附件已上传");
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "附件上传失败";
  } finally { attachmentBusy.value = ""; }
}

async function deleteNodeAttachment(item) {
  const attachmentId = normalizeDatabaseId(item?.id);
  if (!attachmentId) return;
  attachmentBusy.value = attachmentId;
  error.value = "";
  try {
    await serviceApi.deleteAttachment(attachmentId);
    await loadNodeAttachments();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "附件删除失败";
  } finally { attachmentBusy.value = ""; }
}

function showSuccess(message) {
  success.value = message;
  window.setTimeout(() => { if (success.value === message) success.value = ""; }, 2600);
}

async function openSettlementCenter(item = selectedSettlementItems.value[0] || pendingSettlementItems.value[0]) {
  if (!currentProject.value?.id) return;
  try {
    await flushNodeAutosave();
  } catch {
    return;
  }
  emit("open-settlement", {
    projectId: currentProject.value.id,
    sourceNodeId: item?.nodeId || item?.node_id || "",
  });
}

let projectListRequest = 0;
let projectFilterTimer = 0;
let changingListState = false;
let lastListRefresh = 0;

function readListLocation() {
  const params = new URLSearchParams(window.location.search);
  changingListState = true;
  page.value = Math.max(1, Number(params.get("page")) || 1);
  const size = Number(params.get("pageSize"));
  pageSize.value = [20, 50, 100].includes(size) ? size : 20;
  keyword.value = params.get("search") || "";
  customerKeyword.value = params.get("customerSearch") || "";
  ownerKeyword.value = params.get("ownerSearch") || "";
  designOwnerKeyword.value = props.serviceType === "presales" ? params.get("designOwnerSearch") || "" : "";
  solutionOwnerKeyword.value = props.serviceType === "presales" ? params.get("solutionOwnerSearch") || "" : "";
  crmStageFilter.value = props.serviceType === "presales" ? params.get("crmStage") || "" : "";
  stageFilter.value = ["all", "completed", ...config.value.stages.map(([key]) => key)].includes(params.get("stage")) ? params.get("stage") : "all";
  changingListState = false;
}

function writeListLocation() {
  const url = new URL(window.location.href);
  const state = { page: page.value === 1 ? "" : page.value, pageSize: pageSize.value === 20 ? "" : pageSize.value,
    search: keyword.value.trim(), customerSearch: customerKeyword.value.trim(), ownerSearch: ownerKeyword.value.trim(),
    designOwnerSearch: props.serviceType === "presales" ? designOwnerKeyword.value.trim() : "",
    solutionOwnerSearch: props.serviceType === "presales" ? solutionOwnerKeyword.value.trim() : "",
    stage: stageFilter.value === "all" ? "" : stageFilter.value, completion: "",
    crmStage: props.serviceType === "presales" ? crmStageFilter.value : "" };
  for (const [key, value] of Object.entries(state)) {
    if (value === "") url.searchParams.delete(key);
    else url.searchParams.set(key, String(value));
  }
  window.history.replaceState(window.history.state, "", url);
}

function applyProjectFilters() {
  window.clearTimeout(projectFilterTimer);
  page.value = 1;
  void loadProjects();
}

function changeProjectPage(value) {
  if (loading.value || value < 1 || value > totalPages.value) return;
  window.clearTimeout(projectFilterTimer);
  page.value = value;
  void loadProjects();
}

function restoreListLocation() {
  if (!window.location.pathname.includes(`/${props.serviceType}/`)) return;
  window.clearTimeout(projectFilterTimer);
  readListLocation();
  void loadProjects();
}

function projectListParams() {
  return {
    service_type: config.value.apiType,
    nodeKey: stageFilter.value === "all" ? "" : stageFilter.value,
    nameSearch: keyword.value.trim(),
    customerSearch: customerKeyword.value.trim(), ownerSearch: ownerKeyword.value.trim(),
    designOwnerSearch: props.serviceType === "presales" ? designOwnerKeyword.value.trim() : "",
    solutionOwnerSearch: props.serviceType === "presales" ? solutionOwnerKeyword.value.trim() : "",
    crmStage: props.serviceType === "presales" ? crmStageFilter.value : "",
    page: page.value, page_size: pageSize.value,
  };
}

function acceptProjectList(response) {
  projects.value = [...new Map(collectionRows(response).map((item) => [String(item.id), item])).values()];
  page.value = Number(response.page) || page.value;
  total.value = Number(response.total) || 0;
  totalPages.value = Number(response.totalPages) || 1;
  crmSyncing.value = Boolean(response.crmSyncing);
  crmSyncError.value = response.crmSyncError || "";
  crmScopeReady.value = response.crmScopeReady !== false;
  availableCrmStages.value = Array.isArray(response.crmStageOptions) ? response.crmStageOptions : [];
  window.clearTimeout(projectScopeExpiryTimer);
  const expiresAt = Date.parse(response.crmScopeExpiresAt || "");
  if (props.serviceType === "presales" && expiresAt > Date.now()) {
    projectScopeExpiryTimer = window.setTimeout(() => {
      clearProjectListCache();
      projects.value = projects.value.filter((item) => !projectHasCrmSource(item));
      availableCrmStages.value = [];
      total.value = projects.value.length;
      totalPages.value = 1;
      crmScopeReady.value = false;
      void loadProjects({ silent: true });
    }, Math.max(0, expiresAt - Date.now()));
  }
}

function scheduleProjectSync() {
  window.clearTimeout(projectSyncTimer);
  if (disposed || (!props.active && !drawerOpen.value)) return;
  const pending = props.serviceType === "presales" && (crmSyncing.value || (!crmScopeReady.value && !crmSyncError.value));
  const delay = drawerOpen.value ? 5_000 : pending ? CRM_SYNC_POLL_DELAYS[Math.min(projectSyncAttempt, CRM_SYNC_POLL_DELAYS.length - 1)]
    : props.serviceType === "presales" ? 30_000 : 5_000;
  projectSyncTimer = window.setTimeout(async () => {
    if (document.hidden || projectSyncInFlight || projectListBusy.value || loading.value) { scheduleProjectSync(); return; }
    if (pending) projectSyncAttempt += 1;
    projectSyncInFlight = true;
    try {
      if (drawerOpen.value) await syncOpenProject();
      else await loadProjects({ silent: true });
    } finally { projectSyncInFlight = false; scheduleProjectSync(); }
  }, delay);
}

function refreshVisibleProjects() {
  if (props.active && !document.hidden && !projectListBusy.value && !loading.value && !drawerOpen.value && Date.now() - lastListRefresh > 15_000) {
    void loadProjects({ silent: true });
  }
}

async function loadProjects({ silent = false } = {}) {
  if (!props.active) return;
  window.clearTimeout(projectFilterTimer);
  window.clearTimeout(projectSyncTimer);
  const requestId = ++projectListRequest;
  projectListBusy.value = true;
  const params = projectListParams();
  const identity = projectListIdentity(props.session);
  const requestSession = loginSessionIdentityKey(props.session);
  const cached = props.serviceType === "presales" ? readProjectListCache(identity, params) : null;
  if (!silent) {
    projectSyncAttempt = 0;
    if (cached) acceptProjectList(cached);
    loading.value = !cached;
  }
  if (!silent) error.value = "";
  writeListLocation();
  try {
    const response = await serviceApi.listProjects(params);
    if (disposed || requestId !== projectListRequest || identity !== projectListIdentity(props.session) || requestSession !== loginSessionIdentityKey(props.session)) return;
    acceptProjectList(response);
    if (props.serviceType === "presales") writeProjectListCache(identity, params, response);
    lastListRefresh = Date.now();
    writeListLocation();
  } catch (reason) {
    if (disposed || requestId !== projectListRequest || identity !== projectListIdentity(props.session) || requestSession !== loginSessionIdentityKey(props.session)) return;
    if (!silent || props.serviceType === "presales") error.value = reason instanceof Error ? reason.message : "项目列表加载失败";
    if (reason?.code === "CRM_PERMISSION_DENIED" || [401, 403].includes(reason?.status)) {
      clearProjectListCache();
      window.clearTimeout(projectScopeExpiryTimer);
      projects.value = [];
      availableCrmStages.value = [];
      total.value = 0;
      totalPages.value = 1;
      crmSyncing.value = false;
      closeProjectDetail();
    }
  } finally {
    if (!disposed && requestId === projectListRequest) {
      loading.value = false;
      projectListBusy.value = false;
      scheduleProjectSync();
    }
  }
}

async function syncOpenProject() {
  if (
    !drawerOpen.value
    || autosaveDirty.value
    || autosaveBusy.value
    || !selectedId.value
    || detailLoading.value
    || loading.value
    || saving.value
    || nodeAutosavePending.value
    || nodeAutosaveSaving.value
    || presalesSchemeSaving.value
    || presalesProjectInfoPending.value
    || presalesProjectInfoOpen.value
    || projectDeleteOpen.value
    || teamOpen.value
    || relatedProductPickerOpen.value
    || createOpen.value
    || projectChartOpen.value
  ) return;
  const projectId = selectedId.value;
  const identity = projectListIdentity(props.session);
  const projectAtRequest = currentProject.value;
  const stampAtRequest = projectAtRequest?.updatedAt;
  try {
    const latest = unwrapProject(await serviceApi.getProject(projectId));
    if (!latest || !drawerOpen.value || String(selectedId.value) !== String(projectId)
      || identity !== projectListIdentity(props.session)
      || currentProject.value !== projectAtRequest || currentProject.value?.updatedAt !== stampAtRequest
      || autosaveDirty.value || autosaveBusy.value || presalesProjectInfoOpen.value) return;
    const selectedKey = nodeKey(selectedNode.value);
    const latestNode = (latest.nodes || []).find((node) => nodeKey(node) === selectedKey);
    const currentNodeStamp = selectedNode.value?.updatedAt || selectedNode.value?.updated_at || "";
    const latestNodeStamp = latestNode?.updatedAt || latestNode?.updated_at || "";
    const projectStamp = latest.updatedAt || latest.updated_at || "";
    const currentProjectStamp = currentProject.value?.updatedAt || currentProject.value?.updated_at || "";
    const permissionState = (project) => JSON.stringify([
      project?.permissions, (project?.nodes || []).map((node) => [nodeKey(node), node.permissions]),
    ]);
    if (
      latest.currentNodeKey === currentProject.value?.currentNodeKey
      && latestNodeStamp
      && latestNodeStamp === currentNodeStamp
      && (!projectStamp || projectStamp === currentProjectStamp)
      && permissionState(latest) === permissionState(currentProject.value)
    ) return;
    projectDetail.value = latest;
    syncPersonnelForm();
    const listProject = projects.value.find((item) => String(item.id) === String(projectId));
    if (listProject) Object.assign(listProject, latest);
  } catch (reason) {
    if ([401, 403, 404].includes(reason?.status) && drawerOpen.value
      && String(selectedId.value) === String(projectId) && identity === projectListIdentity(props.session)) {
      clearProjectListCache();
      closeProjectDetail();
      projects.value = projects.value.filter((item) => String(item.id) !== String(projectId));
      error.value = reason instanceof Error ? reason.message : "项目已不可访问，请核对当前权限";
    }
    // Polling is best effort; the next cycle retries without interrupting editing.
  }
}

async function loadDetail(id, { open = true, focusNodeKey = "" } = {}) {
  if (!id) return;
  try {
    await flushProjectDrafts();
  } catch {
    return;
  }
  const openingNewProject = open && (!drawerOpen.value || String(selectedId.value) !== String(id));
  if (openingNewProject) closeRelatedProductDetail();
  const requestToken = ++detailRequestToken;
  selectedId.value = id;
  if (open) {
    drawerOpen.value = true;
    scheduleProjectSync();
    if (openingNewProject) detailTab.value = "overview";
  }
  detailLoading.value = true;
  error.value = "";
  try {
    const detail = unwrapProject(await serviceApi.getProject(id));
    if (requestToken !== detailRequestToken) return;
    projectDetail.value = detail;
    syncPersonnelForm();
    const requestedNode = (projectDetail.value?.nodes || []).find((node) => nodeKey(node) === String(focusNodeKey));
    selectedNodeId.value = nodeKey(requestedNode)
      || projectDetail.value?.currentNodeKey
      || projectDetail.value?.current_node_key
      || projectDetail.value?.current_node_id
      || projectDetail.value?.currentNodeId
      || nodeKey(nodes.value.find((node) => ["active", "进行中"].includes(node.status)))
      || nodeKey(nodes.value[0]);
    if (props.focusRoundId && focusNodeKey && !requestedNode) {
      error.value = "转发对应的节点已不存在，请查看当前项目流程";
    }
  } catch (reason) {
    if (requestToken !== detailRequestToken) return;
    projectDetail.value = projects.value.find((item) => String(item.id) === String(id)) || null;
    syncPersonnelForm();
    error.value = reason instanceof Error ? reason.message : "项目详情加载失败";
  } finally {
    if (requestToken === detailRequestToken) detailLoading.value = false;
  }
}

async function openFocusedProject() {
  const projectId = String(props.focusProjectId || "").trim();
  if (!projectId) return;
  await loadDetail(projectId, { focusNodeKey: props.focusNodeKey });
}

async function closeProjectDetail() {
  try { await flushProjectDrafts(); } catch { return; }
  closeRelatedProductDetail();
  if (presalesProjectInfoOpen.value && !await closePresalesProjectInfoModal()) return;
  detailRequestToken += 1;
  closePresalesDenial();
  closeNoteModal();
  relatedProductPickerOpen.value = false;
  relatedProductTargetNodeKey.value = "";
  drawerOpen.value = false;
  detailTab.value = "overview";
  detailLoading.value = false;
  projectDetail.value = null;
  selectedId.value = "";
  selectedNodeId.value = "";
  emit("project-detail-closed");
  scheduleProjectSync();
}

function projectHasCrmSource(project) {
  return Boolean(project?.sourceCrmId || project?.source_crm_id || project?.source === "crm");
}

function openProjectDelete(project) {
  if (!project?.id || projectHasCrmSource(project)) return;
  projectDeleteTarget.value = project;
  projectDeleteOpen.value = true;
}

function closeProjectDelete() {
  if (projectDeleting.value) return;
  projectDeleteOpen.value = false;
  projectDeleteTarget.value = null;
}

async function confirmProjectDelete() {
  const projectId = projectDeleteTarget.value?.id;
  if (!projectId || projectDeleting.value || projectHasCrmSource(projectDeleteTarget.value)) return;
  projectDeleting.value = true;
  error.value = "";
  try {
    const deletingOpenProject = String(selectedId.value || "") === String(projectId);
    if (deletingOpenProject) await flushNodeAutosave();
    await serviceApi.deleteProject(projectId);
    projectDeleteOpen.value = false;
    projectDeleteTarget.value = null;
    if (deletingOpenProject) {
      resetNodeAutosave(null);
      closeProjectDetail();
    }
    await loadProjects();
    showSuccess(`${config.value.title}已删除`);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "服务删除失败";
  } finally {
    projectDeleting.value = false;
  }
}

function openProjectChart(project) {
  projectChartProject.value = project;
  projectChartOpen.value = true;
}

function closeProjectChart() {
  projectChartOpen.value = false;
  projectChartProject.value = null;
}

function openCreate() {
  Object.assign(createForm, {
    name: "",
    customer_name: "",
    owner_name: currentUserName.value,
    description: "",
    application_reason: "",
    original_files: [],
    address: "",
    service_node_id: "onsite-service",
    enabled_node_ids: props.serviceType === "midsales" ? stageOptions.value.map((item) => item.id) : [],
    manager_contact: "",
    expected_duration: "1天",
    fee_agreement: "客户承担",
    fee_remark: "",
  });
  createOpen.value = true;
}

function selectCreatePresalesFiles(files) {
  createForm.original_files = files;
}

function removeCreatePresalesFile(index) { createForm.original_files.splice(index, 1); }

async function createProject() {
  if (!createForm.name.trim() || !createForm.customer_name.trim()) {
    error.value = "请填写项目名称和客户名称";
    return;
  }
  if (props.serviceType === "presales" && (
    !createForm.owner_name.trim()
  )) {
    error.value = "请填写负责人";
    return;
  }
  if (props.serviceType === "midsales" && !createForm.manager_contact.trim()) {
    error.value = "请填写申请人联系电话";
    return;
  }
  if (props.serviceType === "aftersales" && (
    !createForm.address.trim()
    || !createForm.manager_contact.trim()
    || !createForm.expected_duration.trim()
    || !createForm.fee_agreement.trim()
    || !createForm.fee_remark.trim()
  )) {
    error.value = "请完整填写售后派单和费用信息";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const payload = {
      service_type: config.value.apiType,
      name: createForm.name.trim(),
      customer_name: createForm.customer_name.trim(),
      owner_user_id: currentUserId.value,
      owner_name: currentUserName.value,
      description: createForm.description.trim(),
      address: createForm.address.trim(),
    };
    if (props.serviceType === "presales") {
      const projectInfo = {
        customer: createForm.customer_name.trim(),
        owner: createForm.owner_name.trim(),
        name: createForm.name.trim(),
        info: createForm.description.trim(),
        reason: createForm.application_reason.trim(),
        files: createForm.original_files.map((file) => file.name),
      };
      payload.business_data = {
        projectInfo,
        projectInfoRecords: { "early-approval": projectInfo },
        applicationReason: projectInfo.reason,
      };
    }
    if (props.serviceType === "midsales") {
      payload.enabled_node_ids = [...createForm.enabled_node_ids];
      payload.business_data = { managerContact: createForm.manager_contact.trim() };
    }
    if (props.serviceType === "aftersales") {
      payload.service_node_id = createForm.service_node_id;
      payload.business_data = {
        managerContact: createForm.manager_contact.trim(),
        expectedDuration: createForm.expected_duration.trim(),
        feeAgreement: createForm.fee_agreement.trim(),
        feeRemark: createForm.fee_remark.trim(),
        relatedProducts: [],
      };
    }
    const created = unwrapProject(await serviceApi.createProject(payload));
    let attachmentWarning = "";
    if (props.serviceType === "presales" && createForm.original_files.length) {
      const initialNode = (created?.nodes || []).find((node) => nodeKey(node) === "early-approval");
      const initialNodeId = normalizeDatabaseId(initialNode?.id);
      if (initialNodeId) {
        try {
          await Promise.all(createForm.original_files.map((file) => (
            serviceApi.uploadAttachment("project_node", initialNodeId, file, "general")
          )));
        } catch (_reason) {
          attachmentWarning = "，但部分原始附件上传失败，请在项目信息中补传";
        }
      }
    }
    createOpen.value = false;
    showSuccess("项目已创建" + attachmentWarning);
    await loadProjects();
    if (created?.id) await loadDetail(created.id);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "项目创建失败";
  } finally {
    saving.value = false;
  }
}

async function runAction(actionName, extra = {}) {
  if (!currentProject.value?.id || saving.value) return;
  try {
    await flushProjectDrafts();
  } catch {
    return;
  }
  const actedNodeKey = nodeKey(selectedNode.value);
  const actedNodeKind = selectedNode.value?.kind;
  const completedWorkerAssignment = actionName === "advance" && props.serviceType !== "presales"
    ? selectedAssignment.value
    : null;
  const completedWorkerNode = completedWorkerAssignment ? selectedNode.value : null;
  const outcome = extra.outcome ?? selectedOutcome.value;
  if (
    actionName === "advance"
    && isPresalesApproval.value
    && outcome === "approved"
    && !presalesPersonnelComplete.value
  ) {
    error.value = `立项成功前请补齐项目人员配置：${presalesPersonnelMissing.value.join("；")}`;
    return;
  }
  if (actionName === "advance" && decisionOptions.value.length && !outcome) {
    error.value = "请选择本节点的处理结果";
    return;
  }
  if (actionName === "advance" && !isPresalesResult.value && !isPresalesApproval.value && ["denied", "failed", "abandoned", "suspended"].includes(outcome) && !actionNote.value.trim()) {
    error.value = "否决、失败、放弃或挂起时必须填写原因";
    return;
  }
  if (["advance", "submit_version"].includes(actionName)) {
    const actualStartAt = props.serviceType === "aftersales"
      ? deliveryForm.actualStartAt || completionForm.actualStartTime
      : deliveryForm.actualStartAt;
    const timePairs = [
      ...(!isPresales.value ? [[deliveryForm.plannedStartAt, deliveryForm.plannedEndAt, "计划结束时间不能早于计划开始时间"]] : []),
      ...(props.serviceType === "aftersales"
        ? [[actualStartAt, deliveryForm.actualEndAt, "实际结束时间不能早于实际开始时间"]]
        : []),
    ];
    const invalidRange = timePairs.find(([start, end]) => (
      start
      && end
      && minuteTimestamp(end) < minuteTimestamp(start)
    ));
    if (invalidRange) {
      error.value = invalidRange[2];
      return;
    }
  }
  if (props.serviceType === "aftersales" && actionName === "advance") {
    if (!completionForm.actualStartTime || !completionForm.actualDuration.trim()) {
      error.value = "请完整填写实际服务时间";
      return;
    }
  }
  if (actionName === "reject_completion" && !actionNote.value.trim()) {
    error.value = "请填写完工驳回原因";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const businessData = {
      ...(!isPresales.value && deliveryForm.externalQuote !== "" ? { externalQuote: deliveryForm.externalQuote } : {}),
      ...(props.serviceType === "presales" ? {
        deliveryNote: actionNote.value.trim(),
        ...(isPresalesEnd.value ? { midsalesNodeKeys: [...handoverNodeKeys.value] } : {}),
        ...(isPresalesDelivery.value ? { schemeRounds: presalesSchemeRounds.value.map((item) => ({ ...item })) } : {}),
        ...(isPresalesApproval.value ? {
          projectInfoRecords: {
            ...((currentProject.value.businessData || currentProject.value.business_data || {}).projectInfoRecords || (currentProject.value.businessData || currentProject.value.business_data || {}).project_info_records || {}),
            [nodeKey(selectedNode.value)]: { ...presalesProjectInfo },
          },
        } : {}),
      } : {}),
      ...(props.serviceType === "midsales" ? {
        feeEstimatedNote: midsalesFeeDetail.estimatedNote,
      } : {}),
      ...(props.serviceType === "aftersales" ? {
        feeEstimatedNote: aftersalesFeeDetail.estimatedNote,
      } : {}),
    };
    const response = await serviceApi.projectAction(currentProject.value.id, actionName, {
      node_id: actedNodeKey,
      node_key: actedNodeKey,
      note: actionNote.value.trim(),
      outcome,
      plannedStartAt: props.serviceType === "aftersales" ? deliveryForm.plannedStartAt : undefined,
      plannedEndAt: props.serviceType === "aftersales" || (props.serviceType === "midsales" && actedNodeKey === "midsales-project") ? deliveryForm.plannedEndAt : undefined,
      ...(!isPresales.value ? { estimatedFee: deliveryForm.estimatedFee } : {}),
      businessData,
      expectedUpdatedAt: expectedNodeVersion(actedNodeKey),
      ...extra,
    });
    const updatedProject = unwrapProject(response);
    if (actionName === "assign") mergeAssignment(updatedProject);
    else projectDetail.value = updatedProject;
    const completedSequentialProject = (
      actionName === "advance"
      && ["presales", "midsales"].includes(props.serviceType)
      && actedNodeKind === "end"
      && projectIsCompleted(updatedProject)
    );
    if (completedSequentialProject) {
      stageFilter.value = "completed";
    }
    actionNote.value = "";
    selectedOutcome.value = "";
    const messages = {
      start: "节点已开始",
      return: "节点已回退",
      submit_version: "当前版本已提交并留痕",
      reject_completion: "现场完工资料已驳回",
      assign: "服务人员已分派",
      advance: actedNodeKind === "end" ? (updatedProject?.midsalesProjectId ? "售前已结束，已转入售中服务" : "项目已结束") : "节点已通过",
    };
    showSuccess(messages[actionName] || "操作已提交");
    if (actionName !== "assign") await loadProjects({ silent: true });
    if (completedSequentialProject) selectedNodeId.value = actedNodeKey;
    if (completedWorkerAssignment && completedWorkerNode) {
      openWorkerRatingModal(completedWorkerAssignment, completedWorkerNode);
    }
    return true;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "节点操作失败";
    return false;
  } finally {
    saving.value = false;
  }
}

async function selectAfterSalesNode(node) {
  if (!await selectProjectNode(nodeKey(node))) return;
  if (!currentProject.value?.permissions?.canManage) {
    selectedNodeId.value = nodeKey(node);
    return;
  }
  try {
    await flushNodeAutosave();
  } catch {
    return;
  }
  selectedNodeId.value = nodeKey(node);
  if (props.serviceType !== "aftersales" || nodeKey(node) === (
    currentProject.value?.currentNodeKey || currentProject.value?.current_node_key
    || currentProject.value?.current_node_id || currentProject.value?.currentNodeId
  )) return;
  await runAction("select_service_type", { service_node_id: nodeKey(node) });
}

async function loadCertifiedTeamMembers() {
  if (teamMembers.value.length) return;
  teamLoading.value = true;
  try {
    const response = await allCollectionRows(serviceApi.listTeamMembers, { status: "certified" });
    teamMembers.value = collectionRows(response);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "服务团队加载失败";
  } finally {
    teamLoading.value = false;
  }
}

async function loadManagementEmployees() {
  if (managementEmployees.value.length) return;
  teamLoading.value = true;
  try {
    managementEmployees.value = collectionRows(await serviceApi.employeeDirectory());
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "钉钉人员目录加载失败";
  } finally {
    teamLoading.value = false;
  }
}

async function showTeamPicker(mode, targetNodeKey) {
  if (!currentProject.value?.permissions?.canManage || saving.value || teamLoading.value) return;
  if (mode === "management" && !presalesPersonnelEditable({ nodeKey: targetNodeKey })) return;
  if (mode === "management-direct" && (!nodeEditable.value || !currentProject.value?.permissions?.canManage)) return;
  if (mode === "project-lead" && (!presalesProjectLeadsEditable.value || !presalesProjectLeadRoles.some(role => role.key === targetNodeKey))) return;
  teamPickerTrigger = document.activeElement;
  teamTargetMode.value = mode;
  teamTargetNodeKey.value = targetNodeKey;
  teamKeyword.value = "";
  error.value = "";
  const selected = mode === "project-lead" ? presalesProjectLead(targetNodeKey)
    : mode === "management" ? presalesPersonnelForm[targetNodeKey]
    : presalesManagementAssignment(nodes.value.find(node => nodeKey(node) === targetNodeKey));
  teamSelectedMembers.value = mode === "project-lead" ? personnelMembers(selected).slice(0, 1) : personnelMembers(selected);
  teamOpen.value = true;
  await nextTick();
  teamSearchInput.value?.focus();
  if (managementPicker.value) await loadManagementEmployees();
  else await loadCertifiedTeamMembers();
}

async function openTeamPicker() {
  if (!canAssignSelectedNode.value || personnelLocked.value) return;
  await showTeamPicker("direct", nodeKey(selectedNode.value));
}

async function openPersonnelPicker(row) {
  if (!row || personnelRowLocked(row) || row.saving) return;
  await showTeamPicker("personnel", row.nodeKey);
}

watch(teamOpen, (open) => {
  if (!open) nextTick(() => {
    if (teamPickerTrigger?.isConnected) teamPickerTrigger.focus();
  });
});

function toggleTeamMember(member) {
  if (saving.value || teamLoading.value) return;
  const userId = String(member.userId || member.user_id || member.id || "");
  if (teamSelectedIds.value.has(userId)) teamSelectedMembers.value = teamSelectedMembers.value.filter(row => row.userId !== userId);
  else if (projectLeadPicker.value) teamSelectedMembers.value = [{ userId, name: member.name || userId }];
  else teamSelectedMembers.value.push({ userId, name: member.name || userId });
}

async function confirmManagementMembers() {
  if (!managementPicker.value || saving.value || teamLoading.value || !currentProject.value?.id) return;
  const mode = teamTargetMode.value;
  const targetKey = teamTargetNodeKey.value;
  const role = mode === "project-lead" ? presalesProjectLeadRoles.find(item => item.key === targetKey) : null;
  if (mode === "project-lead" ? !role || !presalesProjectLeadsEditable.value
    : mode === "management" ? !presalesPersonnelEditable({ nodeKey: targetKey }) : !nodeEditable.value) return;
  const projectId = currentProject.value.id;
  const nodeTargetKey = role ? "early-approval" : targetKey;
  saving.value = true;
  error.value = "";
  try {
    await flushProjectDrafts();
    const target = nodes.value.find(node => nodeKey(node) === nodeTargetKey);
    const previous = presalesManagementAssignment(target);
    const selection = role ? personnelSelection(teamSelectedMembers.value)
      : personnelAssignmentSelection(teamSelectedMembers.value, previous);
    const businessData = role ? { projectLeads: { [role.key]: selection } } : {
      managementAssignment: { ...previous, ...selection },
    };
    const response = await serviceApi.updateProjectNode(projectId, nodeTargetKey, {
      expectedUpdatedAt: expectedNodeVersion(nodeTargetKey), businessData,
    });
    const updated = unwrapProject(response);
    if (String(currentProject.value?.id) === String(projectId)) projectDetail.value = updated;
    if (role) {
      projects.value = projects.value.map(project => String(project.id) === String(projectId)
        ? { ...project, projectLeads: updated.projectLeads || updated.nodes?.find(node => nodeKey(node) === "early-approval")?.businessData?.projectLeads || {} } : project);
      clearProjectListCache();
    }
    teamOpen.value = false;
    showSuccess(`${role?.label || nodeName(target) + '项目人员'}已保存`);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "项目人员保存失败";
  } finally {
    saving.value = false;
  }
}

async function assignMember(member) {
  if (saving.value || teamLoading.value) return;
  if (teamTargetMode.value === "personnel") {
    const row = personnelForm[teamTargetNodeKey.value];
    if (!row) return;
    row.providerId = member.id;
    row.provider = member;
    row.dirty = true;
    teamOpen.value = false;
    await savePersonnelRow(row);
    return;
  }
  const personnelRow = props.serviceType === "midsales"
    ? personnelForm[nodeKey(selectedNode.value)]
    : null;
  const targetNodeKey = nodeKey(selectedNode.value);
  await runAction("assign", {
    node_id: targetNodeKey,
    node_key: targetNodeKey,
    member_id: member.id,
    assignee_id: member.id,
    assignee_name: member.name,
    ...(personnelRow ? {
      role: personnelRow.role,
      plannedStartDate: personnelRow.plannedStartDate,
      standardDuration: "",
    } : {}),
  });
  teamOpen.value = false;
}

async function savePersonnelRow(row, { showNotice = true, flushDrafts = true } = {}) {
  if (!currentProject.value?.id || row.saving || personnelRowLocked(row)) return false;
  if (row.plannedStartDate && row.plannedEndDate && row.plannedEndDate < row.plannedStartDate) {
    error.value = `${row.nodeName}计划结束日期不能早于计划开始日期`;
    return false;
  }
  row.saving = true;
  error.value = "";
  const projectId = currentProject.value.id;
  try {
    if (flushDrafts) await flushProjectDrafts({ personnel: false });
    let expectedUpdatedAt = row.expectedUpdatedAt || expectedNodeVersion(row.nodeKey);
    let assignment = null;
    if (row.providerId) {
      const assignmentResponse = await serviceApi.projectAction(projectId, "assign", {
        expectedUpdatedAt,
        nodeKey: row.nodeKey,
        providerId: row.providerId,
        role: row.role,
        plannedStartDate: row.plannedStartDate,
        standardDuration: "",
        note: row.note.trim(),
      });
      assignment = unwrapProject(assignmentResponse);
      expectedUpdatedAt = assignment.nodeUpdatedAt || expectedUpdatedAt;
      row.expectedUpdatedAt = expectedUpdatedAt;
      mergeAssignment(assignment, { syncPersonnel: false });
    }
    const projectResponse = await serviceApi.updateProjectNode(projectId, row.nodeKey, {
      expectedUpdatedAt,
      plannedStartAt: row.plannedStartDate ? `${row.plannedStartDate}T00:00:00` : "",
      plannedEndAt: row.plannedEndDate ? `${row.plannedEndDate}T23:59:00` : "",
      businessData: {
        plannedStartMode: row.plannedStartMode || "manual",
      },
    });
    if (String(currentProject.value?.id || "") === String(projectId)) {
      projectDetail.value = unwrapProject(projectResponse);
    }
    const savedNode = unwrapProject(projectResponse)?.nodes?.find(node => nodeKey(node) === row.nodeKey);
    row.expectedUpdatedAt = savedNode?.updatedAt || savedNode?.updated_at || "";
    if (assignment) {
      row.providerId = assignment.providerId || assignment.provider_id || assignment.provider?.id || row.providerId;
      row.provider = assignment.provider || row.provider;
      row.role = assignment.role || row.role;
      row.note = assignment.note ?? row.note;
    }
    row.dirty = false;
    row.saving = false;
    if (showNotice) showSuccess(`${row.nodeName}配置已保存`);
    return true;
  } catch (reason) {
    row.saving = false;
    error.value = reason instanceof Error ? reason.message : "项目人员配置保存失败";
    return false;
  }
}

async function savePersonnelSchedule(row) {
  markPersonnelDirty(row);
  recalculatePersonnelStartDates();
  let saved = false;
  for (const target of personnelRows.value) {
    if (!target.dirty) continue;
    const success = await savePersonnelRow(target, { showNotice: false });
    if (!success) return;
    saved ||= success;
  }
  if (saved) showSuccess("项目计划时间已保存");
}

function savePersonnelStartDate(row) {
  const canInheritStart = schedulePredecessorKeys(
    row.nodeKey,
    MIDSALES_SCHEDULE_DEPENDENCIES,
    Object.keys(personnelForm),
  ).length > 0;
  row.plannedStartMode = canInheritStart && !row.plannedStartDate ? "auto" : "manual";
  return savePersonnelSchedule(row);
}

function collapseNodeSections() {
  nextTick(() => {
    document.querySelector(".module-route-drawer")
      ?.querySelectorAll(".as-node-main details")
      .forEach((section) => { section.open = false; });
  });
}

watch(() => props.active, (active) => {
  if (active) void loadProjects();
  else scheduleProjectSync();
});
watch(() => props.serviceType, () => {
  window.clearTimeout(projectFilterTimer);
  projectListRequest += 1;
  changingListState = true;
  closeProjectDetail();
  closeProjectChart();
  closeMidsalesFeeModal();
  closeAftersalesFeeModal();
  stageFilter.value = "all";
  crmStageFilter.value = "";
  availableCrmStages.value = [];
  customerKeyword.value = "";
  ownerKeyword.value = "";
  designOwnerKeyword.value = "";
  solutionOwnerKeyword.value = "";
  keyword.value = "";
  page.value = 1;
  projects.value = [];
  total.value = 0;
  crmSyncing.value = false;
  crmSyncError.value = "";
  crmScopeReady.value = false;
  changingListState = false;
  loadProjects();
});
watch([keyword, customerKeyword, ownerKeyword, designOwnerKeyword, solutionOwnerKeyword, stageFilter, crmStageFilter, pageSize], () => {
  if (changingListState) return;
  window.clearTimeout(projectFilterTimer);
  projectListRequest += 1;
  loading.value = true;
  page.value = 1;
  projectFilterTimer = window.setTimeout(() => { void loadProjects(); }, 300);
}, { flush: "sync" });
watch(
  () => [props.focusProjectId, props.focusNodeKey, props.focusRoundId],
  ([projectId]) => {
    if (projectId) void openFocusedProject();
  },
);
watch([() => props.serviceType, selectedNodeId], scrollPresalesFlowToSelection);
watch([drawerOpen, detailLoading, selectedNodeId], ([open, loading]) => {
  if (open && !loading) collapseNodeSections();
});
watch(nodes, (value) => {
  if (value.length && !value.some((node) => nodeKey(node) === selectedNodeId.value)) {
    selectedNodeId.value = nodeKey(value[0]);
  }
});
watch(selectedNodeId, (value, previousValue) => {
  if (previousValue && value !== previousValue) {
    closeRelatedProductDetail();
  }
});
watch(selectedNode, async (node, previousNode) => {
  hydratingNodeDraft = true;
  persistedNodeVersions.set(`${currentProject.value?.id}:${nodeKey(node)}`, node?.updatedAt || node?.updated_at || "");
  const nodeChanged = nodeKey(node) !== nodeKey(previousNode);
  midsalesProofModalOpen.value = false;
  closeMidsalesFeeModal(false);
  closeAftersalesFeeModal(false);
  aftersalesCompletionOpen.value = false;
  completionRejectOpen.value = false;
  selectedOutcome.value = node?.businessData?.outcome || node?.business_data?.outcome || "";
  const data = node?.businessData || node?.business_data || {};
  handoverNodeKeys.value = Array.isArray(data.midsalesNodeKeys)
    ? [...data.midsalesNodeKeys] : MIDSALES_PROJECT_STAGES.map(([key]) => key);
  actionNote.value = data.deliveryNote || data.delivery_note || "";
  completionForm.actualStartTime = data.actualStartTime || datetimeInputValue(node?.actualStartAt || node?.actual_start_at);
  completionForm.actualDuration = data.actualDuration || "";
  deliveryForm.plannedStartAt = datetimeInputValue(node?.plannedStartAt || node?.planned_start_at);
  deliveryForm.plannedEndAt = datetimeInputValue(node?.plannedEndAt || node?.planned_end_at);
  deliveryForm.actualStartAt = datetimeInputValue(node?.actualStartAt || node?.actual_start_at);
  deliveryForm.actualEndAt = datetimeInputValue(node?.actualEndAt || node?.actual_end_at);
  deliveryForm.estimatedFee = node?.estimatedFee ?? node?.estimated_fee ?? "";
  deliveryForm.actualFee = node?.actualFee ?? node?.actual_fee ?? "";
  deliveryForm.externalQuote = data.externalQuote ?? data.external_quote ?? "";
  resetPresalesDraft(node);
  if (node?.id !== previousNode?.id) nodeAttachments.value = [];
  loadNodeAttachments(node);
  loadNodeProofs(node);
  if (nodeChanged) collapseNodeSections();
  await nextTick();
  const initialDraft = projectNodeDraftSnapshot();
  if (initialDraft && isPresalesDelivery.value && !data.schemeRounds?.length) {
    // The first empty row is a display default, not yet a persisted round.
    // Forwarding must flush it even when attachments/notes/dates stay optional.
    initialDraft.values.businessData.schemeRounds = [];
  }
  resetNodeAutosave(initialDraft);
  resetPresalesPersonnelAutosave(presalesPersonnelSnapshot());
  hydratingNodeDraft = false;
});
watch(
  [() => deliveryForm.plannedStartAt, aftersalesExpectedDuration],
  ([startAt, expectedDuration]) => {
    if (!isAftersales.value || hydratingNodeDraft || !startAt) return;
    const plannedEndAt = plannedCompletionDateTime(startAt, expectedDuration);
    if (plannedEndAt && plannedEndAt !== deliveryForm.plannedEndAt) deliveryForm.plannedEndAt = plannedEndAt;
  },
);
watch(
  () => projectNodeDraftSnapshot(),
  (draft) => {
    if (!draft || hydratingNodeDraft || !drawerOpen.value || detailLoading.value || !nodeEditable.value) return;
    scheduleNodeAutosave(draft);
  },
  { deep: true },
);
watch(
  () => ({ ...presalesProjectInfo }),
  () => {
    if (!presalesProjectInfoOpen.value || !nodeEditable.value) return;
    const draft = presalesProjectInfoSnapshot();
    if (draft) schedulePresalesProjectInfoAutosave(draft);
  },
  { deep: true },
);
watch([() => deliveryForm.actualStartAt, () => deliveryForm.actualEndAt], () => {
  if (!isAftersales.value) return;
  completionForm.actualStartTime = deliveryForm.actualStartAt;
  completionForm.actualDuration = aftersalesServiceDuration.value === "-" ? "" : aftersalesServiceDuration.value;
});
watch(nodeProofs, (proofs) => {
  if (!midsalesProofModalOpen.value || openedMidsalesProofType.value || !proofs.length) return;
  openedMidsalesProofType.value = proofType(proofs[0]) || MIDSALES_PROOF_TYPES[0]?.key || "";
});
onMounted(async () => {
  desktopQuery.addEventListener("change", updateDesktop);
  readListLocation();
  window.addEventListener("popstate", restoreListLocation);
  window.addEventListener("focus", refreshVisibleProjects);
  document.addEventListener("visibilitychange", refreshVisibleProjects);
  await loadProjects();
  if (disposed) return;
  await openFocusedProject();
  if (disposed) return;
  deliveryClockTimer = window.setInterval(() => {
    currentTimestamp.value = Date.now();
  }, 60_000);
});
onBeforeUnmount(() => {
  desktopQuery.removeEventListener("change", updateDesktop);
  emit("dirty-change", false);
  emit("busy-change", false);
  disposed = true;
  window.clearInterval(deliveryClockTimer);
  window.clearTimeout(projectSyncTimer);
  window.clearTimeout(projectScopeExpiryTimer);
  window.clearTimeout(projectFilterTimer);
  window.removeEventListener("popstate", restoreListLocation);
  window.removeEventListener("focus", refreshVisibleProjects);
  document.removeEventListener("visibilitychange", refreshVisibleProjects);
  projectListRequest += 1;
});
</script>

<template>
  <div class="as-page as-project-page">
    <GlobalNotice v-model:error="error" v-model:success="success" />
    <UnsavedChangesDialog :open="discardDraftOpen" :layer="3400" message="重新加载会放弃当前未保存的填写，并读取最新已保存资料。" @cancel="discardDraftOpen = false" @confirm="reloadSavedProject" />

    <div class="as-project-layout as-project-layout--list-only">
      <section class="as-panel as-project-list-panel">
         <div class="as-panel-head">
           <div><h2>{{ isAftersales ? '售后服务订单列表' : '项目列表' }}</h2><p>{{ isAftersales ? '显示售后服务订单，点击订单查看对应流程。' : isPresales ? `${total} 个项目 · CRM 同步与本地新增` : `${total} 个项目` }}</p><p v-if="isPresales && crmSyncing" role="status">{{ crmScopeReady ? '正在后台更新 CRM 项目，当前列表仍可使用。' : '正在后台同步 CRM 项目，完成后自动更新列表...' }}</p><p v-if="isPresales && crmSyncError" role="alert">{{ crmSyncError }}；{{ crmScopeReady ? '当前显示已有同步数据，稍后自动重试。' : '本地项目仍可正常使用，稍后自动重试。' }}</p></div>
           <div class="as-project-list-actions">
             <button type="button" class="as-button as-button--primary as-project-create-button" @click="openCreate"><Plus />{{ config.createLabel }}</button>
           </div>
         </div>
        <div class="as-project-table-scroll" :aria-busy="loading">
          <table class="as-project-table as-template-table" :class="{ 'is-presales': isPresales, 'is-midsales': serviceType === 'midsales' }">
            <colgroup>
              <col class="as-project-col-name">
              <col class="as-project-col-customer">
              <col class="as-project-col-stage">
              <col v-if="!isPresales" class="as-project-col-owner">
              <col class="as-project-col-date">
              <col v-if="isPresales" class="as-project-col-owner">
              <col v-if="isPresales" class="as-project-col-lead">
              <col v-if="isPresales" class="as-project-col-lead">
              <col v-if="serviceType === 'midsales'" class="as-project-col-progress">
              <col class="as-project-col-operation">
            </colgroup>
            <thead>
              <tr>
                <th>{{ isAftersales ? '服务订单' : '项目名称' }}</th>
                <th>客户名称</th>
                <th>当前节点</th>
                <th v-if="!isPresales">负责人</th>
                <th>{{ isPresales ? 'CRM 阶段' : '计划完成' }}</th>
                <th v-if="isPresales">销售负责人</th>
                <th v-if="isPresales">设计负责人</th>
                <th v-if="isPresales">方案负责人</th>
                <th v-if="serviceType === 'midsales'">节点进度</th>
                <th class="as-project-operation-column">操作</th>
              </tr>
              <tr class="as-project-table-filter-row">
                <th><label class="as-search"><Search /><input v-model="keyword" type="search" :placeholder="isAftersales ? '搜索服务订单' : '搜索项目名称'" aria-label="搜索项目名称" @keyup.enter="applyProjectFilters"></label></th>
                <th><label class="as-search"><Search /><input v-model="customerKeyword" type="search" placeholder="搜索客户" aria-label="搜索客户"></label></th>
                <th><ElSelect v-model="stageFilter" class="as-table-select" popper-class="as-table-select-popper" placeholder="全部节点" aria-label="筛选节点阶段"><ElOption label="全部节点" value="all" /><ElOption label="已完成项目" value="completed" /><ElOption v-for="stage in stageOptions" :key="stage.id" :label="stage.name" :value="stage.id" /></ElSelect></th>
                <th v-if="!isPresales"><label class="as-search"><Search /><input v-model="ownerKeyword" type="search" placeholder="搜索负责人" aria-label="搜索负责人"></label></th>
                <th><ElSelect v-if="isPresales" v-model="crmStageFilter" class="as-table-select" popper-class="as-table-select-popper" filterable placeholder="全部阶段" aria-label="筛选 CRM 阶段"><ElOption label="全部阶段" value="" /><ElOption v-for="stage in crmStageOptions" :key="stage" :label="stage" :value="stage" /><ElOption label="无 CRM 阶段" value="__empty__" /></ElSelect></th>
                <th v-if="isPresales"><label class="as-search"><Search /><input v-model="ownerKeyword" type="search" placeholder="搜索销售负责人" aria-label="搜索销售负责人"></label></th>
                <th v-if="isPresales"><label class="as-search"><Search /><input v-model="designOwnerKeyword" type="search" placeholder="搜索设计负责人" aria-label="搜索设计负责人"></label></th>
                <th v-if="isPresales"><label class="as-search"><Search /><input v-model="solutionOwnerKeyword" type="search" placeholder="搜索方案负责人" aria-label="搜索方案负责人"></label></th>
                <th v-if="serviceType === 'midsales'"></th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="loading" class="as-project-empty-row"><td :colspan="isPresales ? 8 : serviceType === 'midsales' ? 7 : 6"><LoaderCircle class="as-spin" /> 正在加载项目...</td></tr>
              <tr v-else-if="!filteredProjects.length" class="as-project-empty-row"><td :colspan="isPresales ? 8 : serviceType === 'midsales' ? 7 : 6">{{ crmSyncing ? '正在同步 CRM 项目，请稍候...' : crmSyncError ? '项目同步失败，稍后自动重试' : '没有符合条件的项目' }}</td></tr>
              <template v-for="project in loading ? [] : filteredProjects" :key="project.id">
                <tr
                  tabindex="0"
                  class="as-project-data-row"
                  :class="{ active: String(project.id) === String(selectedId) }"
                  @click="loadDetail(project.id)"
                  @keydown.enter="loadDetail(project.id)"
                  @keydown.space.prevent="loadDetail(project.id)"
                >
                  <td class="as-project-identity">
                    <ProjectName :name="display(project, 'name', 'project_name', 'projectName')" :created-at="project.crmCreatedAt || ''" :now="currentTimestamp" />
                  </td>
                  <td class="as-project-customer">{{ display(project, 'customer_name', 'customerName', 'customer') }}</td>
                  <td><span class="as-project-active-stages"><span v-for="(stage, index) in currentStageNames(project)" :key="index" class="as-project-stage">{{ stage }}</span></span></td>
                  <td v-if="!isPresales"><span class="as-project-person">{{ display(project, 'owner_name', 'ownerName', 'owner') }}</span></td>
                  <td v-if="isPresales"><span class="as-project-person" :title="projectHasCrmSource(project) ? project.crmStage || '' : ''">{{ projectHasCrmSource(project) ? project.crmStage || '—' : '—' }}</span></td>
                  <td v-else><span class="as-project-date">{{ display(project, 'plannedEndDate', 'planned_end_date', 'due_text', 'dueText', 'due') }}</span></td>
                  <td v-if="isPresales"><span class="as-project-person">{{ display(project, 'owner_name', 'ownerName', 'owner') }}</span></td>
                  <td v-for="role in isPresales ? presalesProjectLeadRoles : []" :key="role.key"><span class="as-project-person" :title="presalesProjectLead(role.key, project)?.name || ''">{{ presalesProjectLead(role.key, project)?.name || '—' }}</span></td>
                  <td v-if="serviceType === 'midsales'" class="as-project-progress-cell">
                    <MidsalesProjectGantt compact :project="project" @open="openProjectChart(project)" />
                  </td>
                  <td class="as-project-operation-cell"><button v-if="project.permissions?.canDelete" type="button" class="as-icon-button as-project-delete-button" :title="`删除${display(project, 'name', 'project_name', 'projectName')}`" :aria-label="`删除${display(project, 'name', 'project_name', 'projectName')}`" @click.stop="openProjectDelete(project)" @keydown.stop><Trash2 /></button><span v-else class="as-muted" title="CRM 同步项目不能在售后系统删除">—</span></td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <ListPagination v-model:page-size="pageSize" :page="page" :total="total" :total-pages="totalPages" :loading="loading" label="项目分页" size-label="每页项目数" @change="changeProjectPage" />
      </section>

      <ModalShell :open="projectChartOpen" title="项目节点进度" description="查看本项目已包含节点的计划与实际进度。" wide @close="closeProjectChart">
        <MidsalesProjectGantt v-if="projectChartProject" :project="projectChartProject" />
      </ModalShell>

      <ProjectDetailDrawer
        :open="drawerOpen"
        :title="config.title + ' · 项目详情'"
        @close="closeProjectDetail"
      >
      <template #header="{ close }">
        <div v-if="currentProject" class="as-project-drawer-context">
          <span class="as-project-drawer-context__mark" aria-hidden="true"></span>
          <div class="as-project-drawer-context__copy">
            <p>{{ config.title }}</p>
            <h2>{{ display(currentProject, 'name', 'project_name', 'projectName') }}</h2>
            <div class="as-project-drawer-context__meta">
              <span><small>客户</small>{{ display(currentProject, 'customer_name', 'customerName', 'customer') }}</span>
              <span><small>服务类型</small>{{ config.title }}</span>
              <span v-if="isCrmProject"><small>CRM 阶段</small>{{ currentProject.crmStage || '未填写' }}</span>
              <span><small>当前节点</small>{{ isPresales ? currentStageName(currentProject) : nodeName(selectedNode) }}</span>
              <span><small>当前状态</small><em class="as-status" :class="{ 'is-done': isPresales ? projectIsCompleted(currentProject) : isCompleted(selectedNode) }">{{ isPresales ? display(currentProject, 'statusLabel', 'status_display', 'statusDisplay', 'status') : display(selectedNode, 'statusLabel', 'status_display', 'statusDisplay', 'status') }}</em></span>
            </div>
          </div>
          <div class="as-project-drawer-context__right">
            <div class="as-detail-sync" :class="`is-${mobileSyncTone}`"><span>{{ mobileSyncLabel }}</span><strong>{{ latestMobileSyncAt ? `最近同步 ${formatDateTimeLabel(latestMobileSyncAt)}` : fieldCompletionRequired ? '等待小程序提交节点资料' : '当前节点由管理端维护' }}</strong></div>
            <button type="button" class="as-project-drawer-close" aria-label="关闭" title="关闭" @click="close"><X /></button>
          </div>
        </div>
        <div v-else class="as-project-drawer-context as-project-drawer-context--loading"><div class="as-project-drawer-context__copy"><p>{{ config.title }}</p><h2>项目详情</h2></div><button type="button" class="as-project-drawer-close" aria-label="关闭" title="关闭" @click="close"><X /></button></div>
      </template>
      <section class="as-panel as-project-detail-panel">
        <div v-if="autosaveDirty" class="as-alert" role="status"><span>{{ autosaveBusy ? '正在保存…' : '有尚未保存的修改，填写内容已保留。' }}</span><template v-if="!autosaveBusy"><button type="button" class="as-button as-button--secondary" @click="flushProjectDrafts().catch(() => {})">重试保存</button><button type="button" class="as-button as-button--secondary" @click="discardDraftOpen = true">放弃修改并重新加载</button></template></div>
        <div v-if="detailLoading" class="as-empty"><LoaderCircle class="as-spin" /> 正在读取详情...</div>
        <div v-else-if="!currentProject" class="as-empty as-empty--large"><FileText /> 选择一个项目查看节点详情</div>
        <template v-else>
          <div class="as-project-sticky-tabs">
            <nav class="as-project-detail-tabs as-mall-tabbar" role="tablist" aria-label="项目详情视图">
              <button type="button" role="tab" :aria-selected="detailTab === 'overview'" :class="{ active: detailTab === 'overview' }" @click="selectDetailTab('overview')"><FileText />节点详情<span>{{ nodeSummaryItems.length }}</span></button>
              <button v-if="isPresales && isDesktop" type="button" role="tab" :aria-selected="detailTab === 'info'" :class="{ active: detailTab === 'info' }" @click="selectDetailTab('info')"><FileText />项目信息</button>
              <button v-if="isPresales && !isDesktop" type="button" role="tab" :aria-selected="detailTab === 'fees'" :class="{ active: detailTab === 'fees' }" @click="selectDetailTab('fees')"><CircleDollarSign />费用信息</button>
              <button type="button" role="tab" :aria-selected="detailTab === 'history'" :class="{ active: detailTab === 'history' }" @click="selectDetailTab('history')"><Clock3 />版本与留痕<span>{{ timeline.length }}</span></button>
              <button v-if="serviceType === 'midsales'" type="button" role="tab" :aria-selected="detailTab === 'presales-materials'" :class="{ active: detailTab === 'presales-materials' }" @click="selectDetailTab('presales-materials')"><Paperclip />售前资料</button>
            </nav>
          </div>

          <section v-if="detailTab === 'overview' && selectedSettlementItems.length" class="as-settlement-gate" aria-live="polite">
            <div class="as-settlement-gate__icon"><CircleDollarSign /></div>
            <div class="as-settlement-gate__content">
              <strong>当前节点有费用待结算</strong>
              <span>{{ selectedSettlementItems.map((item) => `${item.nodeName || '收费节点'}（￥${item.actualFee || 0}）`).join('、') }}。费用可在结算中心继续处理，不影响节点通过。</span>
            </div>
          </section>

          <details v-if="detailTab === 'overview' && serviceType === 'presales'" class="as-project-flow-fold" open>
            <summary><span><strong>售前项目流程</strong><small>{{ currentStageName(currentProject) }} · {{ progress }}%</small></span><ChevronDown /></summary>
          <nav ref="presalesFlowScroll" class="as-presales-flow-scroll" aria-label="售前项目流程">
            <div class="as-presales-flow-canvas">
              <svg class="as-presales-flow-connectors" viewBox="0 0 1752 274" preserveAspectRatio="none" aria-hidden="true">
                <path d="M84 137 H216 M216 72 V202 M216 72 H480 M216 202 H480 M480 72 V202 M480 137 H612" />
                <path d="M612 137 H744 M744 72 V202 M744 72 H1404 M744 202 H1404 M1404 72 V202 M1404 137 H1668" />
                <circle cx="216" cy="137" r="5" />
                <circle cx="480" cy="137" r="5" />
                <circle cx="744" cy="137" r="5" />
                <circle cx="1404" cy="137" r="5" />
              </svg>
              <template v-for="item in presalesFlowNodes" :key="item.key">
              <button
                v-if="item.node.kind !== 'result'"
                type="button"
                class="as-presales-flow-node"
                :class="[
                  presalesFlowStateClass(item.node),
                  {
                    active: item.key === selectedNodeId,
                    done: presalesFlowNodeDone(item.node),
                    disabled: item.node.enabled === false,
                    'is-bridge': item.lane === 'bridge',
                    'is-result': item.node.kind === 'result',
                    'is-end': item.node.kind === 'end',
                  },
                ]"
                :style="{ gridColumn: item.column, gridRow: item.gridRow }"
                :data-presales-node-key="item.key"
                :aria-current="item.key === selectedNodeId ? 'step' : undefined"
                :aria-label="`${nodeName(item.node)}，${presalesFlowStatus(item.node)}`"
                @click="selectProjectNode(item.key)"
              >
                <span class="as-presales-flow-node__index"><Check v-if="presalesFlowNodeDone(item.node)" /><template v-else>{{ item.sequence }}</template></span>
                <strong>{{ nodeName(item.node) }}</strong>
                <span class="as-presales-flow-node__status">{{ presalesFlowStatus(item.node) }}</span>
              </button>
              <div
                v-else
                class="as-presales-flow-node as-presales-flow-node--result"
                :class="[
                  presalesFlowStateClass(item.node),
                  {
                    active: item.key === selectedNodeId,
                    done: presalesFlowNodeDone(item.node),
                    disabled: item.node.enabled === false,
                    'is-bridge': item.lane === 'bridge',
                    'is-result': true,
                  },
                ]"
                :style="{ gridColumn: item.column, gridRow: item.gridRow }"
                :data-presales-node-key="item.key"
                @click="selectProjectNode(item.key)"
              >
                <span class="as-presales-flow-node__index"><Check v-if="presalesFlowNodeDone(item.node)" /><template v-else>{{ item.sequence }}</template></span>
                <strong>{{ nodeName(item.node) }}</strong>
                <ElSelect :model-value="presalesFlowStatus(item.node)" class="as-presales-flow-result-select" popper-class="as-presales-flow-result-popper" placeholder="未判定" teleported :disabled="!projectNodeEditable(item.node) || saving" :aria-label="`${nodeName(item.node)}处理结果`" @click.stop="selectProjectNode(item.key)" @update:model-value="updatePresalesResult(item.node, $event)"><ElOption v-for="option in presalesResultOptions(item.node)" :key="option" :label="option" :value="option" /></ElSelect>
              </div>
              </template>
            </div>
          </nav>
          </details>

          <details v-else-if="detailTab === 'overview' && serviceType === 'midsales'" class="as-project-flow-fold" open>
            <summary><span><strong>售中项目流程</strong><small>{{ currentStageName(currentProject) }} · {{ progress }}%</small></span><ChevronDown /></summary>
          <section class="as-midsales-flow-shell">
            <nav class="as-midsales-flow-scroll" aria-label="售中项目流程">
              <div class="as-midsales-flow-track">
                <span class="as-midsales-flow-line" aria-hidden="true"></span>
                <button v-for="(node, index) in midsalesFlowNodes" :key="nodeKey(node)" type="button" class="as-midsales-flow-node" :class="[midsalesFlowNodeState(node), { active: nodeKey(node) === selectedNodeId }]" :disabled="node.enabled === false" @click="selectProjectNode(nodeKey(node))">
                  <span class="as-midsales-flow-included"><Check v-if="node.enabled !== false" />{{ node.enabled === false ? '不包含' : '有' }}</span>
                  <span class="as-midsales-flow-date">{{ midsalesFlowNodeDate(node, index) }}</span>
                  <span class="as-midsales-flow-chip">{{ MIDSALES_FLOW_LABELS[nodeKey(node)] }}</span>
                  <span class="as-midsales-flow-status-chip">{{ midsalesFlowNodeStatus(node) }}</span>
                  <span class="as-midsales-flow-dot" aria-hidden="true"></span>
                  <strong>{{ nodeName(node) }}</strong>
                  <small>{{ midsalesFlowNodeStatus(node) }}</small>
                  <small v-if="hasPendingSettlement(node)" class="as-flow-settlement-hint">待结算</small>
                </button>
              </div>
            </nav>
          </section>
          </details>
          <details v-else-if="detailTab === 'overview' && serviceType === 'aftersales'" class="as-project-flow-fold" open>
            <summary><span><strong>售后服务流程</strong><small>当前：{{ nodeName(aftersalesCurrentNode) }}<template v-if="isCompleted(aftersalesCurrentNode)"> · 100%</template></small></span><ChevronDown /></summary>
          <section class="as-aftersales-flow-shell">
            <div class="as-aftersales-process-card" :class="{ 'is-done': isCompleted(aftersalesCurrentNode), 'is-alert': aftersalesCurrentNode?.status === '异常跟进' }"><span class="as-aftersales-process-date">{{ aftersalesNodeDate(aftersalesCurrentNode, 0) }}</span><span class="as-aftersales-process-chip">{{ nodeName(aftersalesCurrentNode) }}</span><span class="as-aftersales-process-state">{{ aftersalesNodeState(aftersalesCurrentNode) }}</span><span class="as-aftersales-process-dot"></span><strong>{{ nodeName(aftersalesCurrentNode) }}</strong></div>
           </section>
          </details>
          <div v-else-if="detailTab === 'overview'" class="as-flow">
            <button v-for="(node, index) in nodes" :key="nodeKey(node)" type="button" class="as-flow-node" :class="{ active: nodeKey(node) === selectedNodeId, done: isCompleted(node), disabled: node.enabled === false }" @click="serviceType === 'aftersales' ? selectAfterSalesNode(node) : selectProjectNode(nodeKey(node))">
              <span class="as-flow-node__index"><Check v-if="isCompleted(node)" /><template v-else>{{ index + 1 }}</template></span>
              <span><strong>{{ nodeName(node) }}</strong><small>{{ node.enabled === false ? '不包含' : display(node, 'statusLabel', 'status_display', 'statusDisplay', 'status') }}</small></span>
              <ChevronRight />
            </button>
          </div>

          <div v-if="selectedNode" v-show="detailTab === 'overview'" class="as-node-workspace is-overview-tab">
            <div class="as-node-main">
              <section v-if="isPresalesEnd" class="as-presales-handover" aria-label="转入售中服务">
                <header class="as-panel-head"><h3>转入售中服务</h3></header>
                <div class="as-node-fold-body">
                  <p class="as-node-fold-description">{{ currentProject.midsalesProjectId ? '已创建关联售中项目，售前资料已保留，可在售中详情的“售前资料”中查看。' : '选择售中需要开展的节点，结束售前后自动创建售中项目。项目立项和售中项目结束保留，其余节点可调整。' }}</p>
                  <MidsalesNodeSelection v-model="handoverNodeKeys" :disabled="!nodeEditable || saving || Boolean(currentProject.midsalesProjectId)" :required-nodes="MIDSALES_REQUIRED_HANDOVER_NODES" />
                  <a v-if="currentProject.midsalesProjectId" class="as-button as-button--secondary" :href="`/after-sales/midsales/?projectId=${currentProject.midsalesProjectId}`">查看售中项目<ArrowRight /></a>
                </div>
              </section>
              <details class="as-presales-fold as-node-overview-fold">
                <summary class="as-node-head">
                  <div class="as-node-head__copy"><h3>节点概览</h3><small>{{ nodeName(selectedNode) }} · {{ display(selectedNode, 'description', 'desc') }}</small></div>
                  <div class="as-node-head__actions"><button v-if="isPresalesApproval" type="button" class="as-button as-button--secondary" @click.stop.prevent="openPresalesProjectInfoModal"><FileText />项目信息</button><span class="as-status" :class="{ 'is-done': isCompleted(selectedNode) }">{{ isPresales ? presalesFlowStatus(selectedNode) : display(selectedNode, 'statusLabel', 'status_display', 'statusDisplay', 'status') }}</span></div>
                </summary>
                <div class="as-node-overview-fold__body"><ProjectNodeSummary :items="nodeSummaryItems" /></div>
              </details>
              <section v-if="fieldCompletionRequired" class="as-field-completion-gate" :class="{ 'is-submitted': fieldCompletionSubmitted, 'is-rejected': fieldCompletionRejected }" aria-live="polite"><span class="as-field-completion-gate__icon"><Check v-if="fieldCompletionSubmitted" /><CircleAlert v-else-if="fieldCompletionRejected" /><Clock3 v-else /></span><div><strong>{{ !fieldNodeStarted ? '等待管理端确认开始' : fieldCompletionSubmitted ? '小程序已提交完工' : fieldCompletionRejected ? '完工资料已驳回，等待重新提交' : '等待小程序确认完工' }}</strong><small v-if="!fieldNodeStarted">点击下方“开始节点”后，任务会同步到 {{ display(selectedAssignment?.provider, 'name') }} 的小程序。</small><small v-else-if="fieldCompletionSubmitted">{{ display(selectedAssignment?.provider, 'name') }} 已于 {{ formatDateTimeLabel(selectedFieldSubmission?.submittedAt) }} 提交小程序资料，可核对后点击“节点通过”。</small><small v-else-if="fieldCompletionRejected">驳回原因：{{ selectedNodeData.managerReviewNote || '未填写' }}。小程序已同步显示该原因。</small><small v-else-if="selectedAssignment">{{ display(selectedAssignment?.provider, 'name') }} 尚未在小程序任务底部点击“确认完工”，当前节点不能通过。</small><small v-else>当前节点尚未分派小程序服务人员，分派并完成小程序任务后才能通过。</small></div></section>
              <details v-if="serviceType === 'midsales' && nodeKey(selectedNode) === 'midsales-project'" class="as-presales-fold as-midsales-inline-personnel">
                <summary>项目人员 <small>{{ configuredPersonnelCount }}/{{ personnelRows.length }} 个节点已配置</small></summary>
                <div class="as-midsales-inline-personnel__body">
                  <div v-if="!personnelRows.length" class="as-empty as-empty--compact">当前售中项目没有可指派的后续节点</div>
                  <template v-else>
                    <div class="as-personnel-table-head" aria-hidden="true"><span>执行节点</span><span>服务团队人员</span><span>计划开始日期</span><span>计划结束日期</span><span>现场任务说明</span></div>
                    <div v-for="row in personnelRows" :key="row.nodeKey" class="as-personnel-row" :class="{ 'is-dirty': row.dirty, 'is-locked': personnelRowLocked(row) }">
                      <div class="as-personnel-node"><strong>{{ row.nodeName }}</strong><small>{{ personnelRowLocked(row) ? '已结束' : row.saving ? '自动保存中' : row.dirty ? '待补全' : '已同步' }}</small></div>
                      <div><PersonnelSelectButton :name="row.provider?.name || ''" :detail="row.provider ? `${display(row.provider, 'roleLabel', 'role')} · ${row.provider.city || '服务团队'}` : '未配置'" placeholder="选择服务人员" :label="`${row.nodeName}服务人员`" :disabled="personnelRowLocked(row) || saving" :busy="row.saving" @select="openPersonnelPicker(row)" /></div>
                      <label class="as-personnel-field"><DateField v-model="row.plannedStartDate" :disabled="personnelRowLocked(row) || row.saving" aria-label="计划开始日期" @change="savePersonnelStartDate(row)" /></label>
                      <label class="as-personnel-field"><DateField v-model="row.plannedEndDate" :disabled="personnelRowLocked(row) || row.saving" aria-label="计划结束日期" @change="savePersonnelSchedule(row)" /></label>
                      <label class="as-personnel-field as-personnel-task-note"><input v-model="row.note" maxlength="5000" placeholder="填写本项目该节点的现场任务说明" :disabled="personnelRowLocked(row) || row.saving" @input="markPersonnelDirty(row)" @blur="savePersonnelRow(row)"></label>
                    </div>
                  </template>
                </div>
              </details>
              <section v-if="serviceType === 'midsales' && selectedNode.kind !== 'end'" class="as-midsales-node-sections" :class="{ 'is-proof-modal-open': midsalesProofModalOpen }">
                <RelatedProductsPanel v-if="MIDSALES_ASSIGNMENT_NODE_KEYS.has(nodeKey(selectedNode))" :products="midsalesRelatedProducts" :editable="nodeEditable" description="关联后，产品说明书会同步到本节点对应的现场任务。" @add="openRelatedProductPicker(nodeKey(selectedNode))" @open="openRelatedProductDetail" />
                <details class="as-presales-fold"><summary>交付时间</summary><div v-if="nodeKey(selectedNode) === 'midsales-project'" class="as-form-grid"><label class="as-field"><span>负责人</span><input :value="display(currentProject, 'owner_name', 'ownerName', 'owner')" readonly></label><label class="as-field"><span>计划完成时间</span><DateField v-model="deliveryForm.plannedEndAt" type="datetime-local" :disabled="!nodeEditable" aria-label="计划完成时间" /></label></div><div v-else class="as-form-grid"><div class="as-field"><span>服务人员</span><PersonnelSelectButton :name="selectedAssignment?.provider?.name || ''" placeholder="选择服务人员" :label="`${nodeName(selectedNode)}服务人员`" :disabled="!canAssignSelectedNode || personnelLocked || saving" :busy="Boolean(personnelForm[nodeKey(selectedNode)]?.saving)" @select="openPersonnelPicker(personnelForm[nodeKey(selectedNode)])" /></div><label class="as-field"><span>计划开始日期</span><input :value="midsalesPlannedStartDate || '-'" readonly></label><label class="as-field"><span>实际开始时间</span><input :value="midsalesActualStartTime" readonly></label><label class="as-field"><span>预计完成时间</span><input :value="midsalesPlannedEndDate" readonly></label></div></details>
              </section>
              <section v-if="isAftersales" class="as-aftersales-node-sections">
                <details open class="as-presales-fold as-aftersales-order-info"><summary>服务订单信息</summary><div class="as-aftersales-order-grid"><div><span>服务地址</span><strong>{{ display(currentProject, 'address') }}</strong></div><div><span>费用约定</span><strong>{{ display(aftersalesProjectData, 'feeAgreement', 'fee_agreement') }}</strong></div><div><span>费用备注</span><strong>{{ display(aftersalesProjectData, 'feeRemark', 'fee_remark') }}</strong></div><div class="as-aftersales-order-grid__wide"><span>项目说明</span><p>{{ display(currentProject, 'summary', 'description') }}</p></div></div></details>
                <RelatedProductsPanel :products="aftersalesRelatedProducts" :editable="nodeEditable" @add="openRelatedProductPicker()" @open="openRelatedProductDetail" />
                <details open class="as-presales-fold"><summary>交付时间</summary><div class="as-form-grid"><div class="as-field as-field--wide"><span>项目人员</span><PersonnelSelectButton :name="selectedAssignment?.provider?.name || ''" :detail="selectedAssignment?.provider?.roleLabel || ''" :label="`${nodeName(selectedNode)}项目人员`" :disabled="!canAssignSelectedNode || personnelLocked" :busy="saving" @select="openTeamPicker" /></div><label class="as-field"><span>节点状态</span><select :value="aftersalesNodeState(selectedNode)" disabled><option>未开始</option><option>进行中</option><option>异常跟进</option><option>已完成</option></select></label><label class="as-field"><span>计划开始时间</span><DateField v-model="deliveryForm.plannedStartAt" type="datetime-local" :disabled="!nodeEditable" aria-label="计划开始时间" /></label><label class="as-field"><span>实际开始时间</span><input :value="formatDateTimeLabel(deliveryForm.actualStartAt)" readonly aria-label="现场实际开始时间" /></label><label class="as-field"><span>计划完成时间</span><DateField v-model="deliveryForm.plannedEndAt" type="datetime-local" disabled aria-label="根据预计服务时长自动计算的计划完成时间" /></label><label class="as-field"><span>实际完成时间</span><input :value="formatDateTimeLabel(deliveryForm.actualEndAt)" readonly aria-label="现场实际完成时间" /></label></div></details>
                <!-- 完工确认按原型通过右侧快捷操作打开独立浮窗。 -->
              </section>
              <section v-if="isPresalesApproval" class="as-presales-detail">
                <details open class="as-presales-fold">
                  <summary>项目人员</summary>
                  <div v-if="nodeKey(selectedNode) === 'early-approval'" class="as-form-grid as-presales-project-leads">
                    <div v-for="role in presalesProjectLeadRoles" :key="role.key" class="as-field">
                      <span>{{ role.label }}</span>
                      <PersonnelSelectButton :name="presalesProjectLead(role.key)?.name || ''" detail="钉钉组织人员" :label="role.label" :disabled="saving || !presalesProjectLeadsEditable" :busy="saving && teamTargetMode === 'project-lead' && teamTargetNodeKey === role.key" @select="showTeamPicker('project-lead', role.key)" />
                    </div>
                  </div>
                  <PresalesPersonnelTable :rows="presalesPersonnelRows" @select="showTeamPicker('management', $event)" @change="updatePresalesPersonnelMembers" @commit="flushProjectDrafts().catch(() => {})" />
                </details>
              </section>
              <section v-if="isPresalesDelivery" class="as-presales-detail">
                <details open class="as-presales-fold">
                  <summary>项目人员</summary>
                  <PresalesPersonnelTable :rows="presalesPersonnelRows" @select="showTeamPicker('management-direct', $event)" @change="updatePresalesPersonnelMembers" @commit="flushProjectDrafts().catch(() => {})" />
                </details>
                <details open class="as-presales-fold">
                  <summary>{{ presalesDeliveryMeta[0] }} <small>{{ nodeEditable ? '管理端填写 · 自动保存' : '只读 · 可查看历史资料' }}</small></summary>
                  <PresalesProgressPanel ref="presalesProgressPanel" :node-key="nodeKey(selectedNode)" :node-name="nodeName(selectedNode)" :target-id="selectedNodeAttachmentId" :source-crm-id="currentProject.sourceCrmId || currentProject.source_crm_id || ''" :rounds="presalesSchemeRounds" :editable="nodeEditable" :now="currentTimestamp" :completed="isCompleted(selectedNode)" :completed-at="selectedNode.completedAt || selectedNode.completed_at || ''" :focus-round-id="!detailLoading && String(currentProject.id) === String(focusProjectId) && nodeKey(selectedNode) === focusNodeKey ? focusRoundId : ''" :prepare-forward="preparePresalesRound" :process-round="processPresalesRound" managed :allow-add-round="nodeEditable" :submitting="presalesSchemeSaving || saving" @draft-change="presalesRoundDraft = $event" @update:rounds="updatePresalesSchemeRounds" @changed="syncNodeAttachments" @error="error = $event" @success="showSuccess" />
                </details>
              </section>
              <section v-if="serviceType === 'midsales' && selectedNode.kind === 'end'" class="as-presales-detail"><details class="as-presales-fold"><summary>售中项目结束</summary><div class="as-form-grid"><label class="as-field"><span>节点类型</span><input :value="nodeName(selectedNode)" readonly></label><label class="as-field"><span>结束后状态</span><input value="已完成售中项目" readonly></label></div></details></section>
              <section v-if="isPresalesEnd" class="as-presales-detail"><details class="as-presales-fold"><summary>售前项目结束</summary><div class="as-form-grid"><label class="as-field"><span>节点类型</span><input :value="nodeName(selectedNode)" readonly></label><label class="as-field"><span>结束后去向</span><input value="已完成售前项目" readonly></label></div></details></section>

              <details v-if="!isPresales || supplementalNodeAttachments.length" class="as-presales-fold as-node-materials-fold">
                <summary>{{ isPresales ? '节点补充附件' : '交付资料' }} <small>{{ isPresales ? supplementalNodeAttachments.length : materialCount }} 个文件</small></summary>
                <div class="as-node-fold-body">

                  <section v-if="fieldCompletionRequired" class="as-field-submission-summary" aria-label="现场提交记录">
                    <header><div><h4>现场提交记录</h4><p>小程序填写的数据集中展示，附件按下方资料分组核对。</p></div><span :class="`is-${fieldSubmissionSummaryItems[0].tone}`">{{ fieldSubmissionSummaryItems[0].value }}</span></header>
                    <dl><div v-for="item in fieldSubmissionSummaryItems.slice(1)" :key="item.label" :class="{ 'is-wide': item.wide }"><dt>{{ item.label }}</dt><dd :class="{ 'is-empty': !item.value || item.value === '-' }">{{ item.value || '-' }}</dd></div></dl>
                    <div v-if="fieldCompletionRejected" class="as-field-submission-rejection"><CircleAlert /><span><strong>管理端驳回原因</strong><small>{{ selectedNodeData.managerReviewNote || '未填写驳回原因' }}<template v-if="selectedNodeData.managerReviewedAt"> · {{ formatDateTimeLabel(selectedNodeData.managerReviewedAt) }}</template></small></span></div>
                  </section>
                  <article v-else-if="!isPresales" class="as-note-summary"><div><span>管理端处理说明</span><strong>{{ actionNote || '尚未填写处理说明' }}</strong><small>修改后自动保存到当前节点</small></div><button type="button" class="as-button as-button--secondary" @click="openNoteModal('admin')"><FileText />{{ nodeEditable ? '查看/编辑' : '查看详情' }}</button></article>

                  <div v-if="serviceType === 'midsales' && isMidsalesProofNode" class="as-material-groups">
                    <ProjectMaterialGroup v-for="type in MIDSALES_PROOF_TYPES" :key="type.key" :title="type.label" :count="proofAttachments(midsalesProofFor(type.key)).length" source-label="小程序上传" :synced-at="formatDateTimeLabel(proofAttachments(midsalesProofFor(type.key)).at(-1)?.createdAt || '')" :status="midsalesProofFor(type.key) ? proofStatusLabel(midsalesProofFor(type.key)) : '待提交'" :tone="proofAttachments(midsalesProofFor(type.key)).length ? 'mobile' : 'pending'">
                      <AttachmentPanel v-if="midsalesProofFor(type.key)" target-type="midsales_proof" :target-id="midsalesProofFor(type.key).id" :categories="MIDSALES_PROOF_ATTACHMENT_CATEGORIES" :editable="false" source-label="小程序上传" :uploader-label="selectedAssignment?.provider?.name || ''" compact @error="error = $event" />
                      <div v-else class="as-empty as-empty--compact">当前证明材料尚未建立</div>
                      <div v-if="midsalesProofFor(type.key)" class="as-proof-review-summary"><span class="as-proof-state" :class="`is-${proofStatus(midsalesProofFor(type.key))}`">{{ proofStatusLabel(midsalesProofFor(type.key)) }}</span><p>{{ midsalesProofFor(type.key).reviewOpinion || '尚未填写审核意见' }}</p><button type="button" class="as-button as-button--secondary" @click="openMidsalesProofModal(type.key)"><FileText />审核材料</button></div>
                    </ProjectMaterialGroup>
                  </div>

                  <ProjectMaterialGroup v-else-if="isAftersales" title="售后完工附件" :count="materialNodeAttachments.length" source-label="小程序上传" :synced-at="latestMobileSyncAt ? formatDateTimeLabel(latestMobileSyncAt) : ''" :status="materialNodeAttachments.length ? '已同步' : '待提交'" :tone="materialNodeAttachments.length ? 'mobile' : 'pending'">
                    <AttachmentPanel :key="selectedNodeAttachmentId + ':materials:' + nodeAttachmentsVersion" target-type="project_node" :target-id="selectedNodeAttachmentId" :categories="AFTERSALES_ATTACHMENT_GROUPS" :editable="false" source-label="小程序上传" :uploader-label="selectedAssignment?.provider?.name || ''" compact @changed="syncNodeAttachments" @error="error = $event" />
                  </ProjectMaterialGroup>

                  <ProjectMaterialGroup v-else :title="fieldCompletionRequired ? '小程序交付附件' : '管理端节点附件'" :count="isPresales ? supplementalNodeAttachments.length : materialNodeAttachments.length" :source-label="fieldCompletionRequired ? '小程序上传' : '管理端上传'" :synced-at="fieldCompletionRequired ? latestMobileSyncAt ? formatDateTimeLabel(latestMobileSyncAt) : '' : formatDateTimeLabel(selectedNode.updatedAt || selectedNode.updated_at)" :status="materialNodeAttachments.length ? '已有资料' : '暂无资料'" :tone="fieldCompletionRequired ? materialNodeAttachments.length ? 'mobile' : 'pending' : 'admin'">
                    <AttachmentPanel :key="selectedNodeAttachmentId + ':materials:' + nodeAttachmentsVersion" target-type="project_node" :target-id="selectedNodeAttachmentId" :categories="isPresales ? PRESALES_SUPPLEMENTAL_ATTACHMENT_CATEGORIES : undefined" :editable="!fieldCompletionRequired && nodeEditable" :source-label="fieldCompletionRequired ? '小程序上传' : '管理端上传'" :uploader-label="fieldCompletionRequired ? selectedAssignment?.provider?.name || '' : ''" compact @changed="syncNodeAttachments" @error="error = $event" />
                  </ProjectMaterialGroup>
                </div>
              </details>

              <details v-if="!isPresales" class="as-presales-fold as-node-fees-fold">
                <summary>费用信息 <small>{{ nodeName(selectedNode) }}</small></summary>
                <div class="as-node-fold-body">
                  <p class="as-node-fold-description">{{ isPresales ? '当前节点的预计费用、实际费用和对外报价由管理端维护。' : '当前节点的预计费用和对外报价由管理端维护，实际费用由小程序提交后只读展示。' }}</p>
                  <div class="as-fee-summary-table">
                    <div class="as-fee-summary-head"><span>费用类型</span><span>金额</span><span>来源</span><span>资料</span></div>
                    <div class="as-fee-summary-row"><strong>预计费用</strong><label :class="{ 'is-readonly': !nodeEditable }"><input v-model="deliveryForm.estimatedFee" type="number" min="0" step="0.01" :disabled="!nodeEditable" placeholder="0.00" aria-label="当前节点预计费用"><span>元</span></label><em class="is-admin">管理端</em><button v-if="serviceType === 'midsales'" type="button" @click="openMidsalesFeeModal('estimated', 'note')">备注</button><button v-else-if="isAftersales" type="button" @click="openAftersalesFeeModal('estimated')">备注</button><span v-else>-</span></div>
                    <div class="as-fee-summary-row"><strong>实际费用</strong><label v-if="isPresales" :class="{ 'is-readonly': !nodeEditable }"><input v-model="deliveryForm.actualFee" type="number" min="0" step="0.01" :disabled="!nodeEditable" placeholder="0.00" aria-label="当前节点实际费用"><span>元</span></label><div v-else class="as-fee-readonly">{{ deliveryForm.actualFee !== '' ? moneyLabel(deliveryForm.actualFee) : '尚未提交' }}</div><em :class="serviceType === 'presales' ? 'is-admin' : 'is-mobile'">{{ serviceType === 'presales' ? '管理端' : '小程序' }}</em><button v-if="serviceType === 'midsales'" type="button" @click="openMidsalesFeeModal('actual', 'note')">查看备注</button><button v-else-if="isAftersales" type="button" @click="openAftersalesFeeModal('actual')">查看备注</button><span v-else>-</span></div>
                    <div class="as-fee-summary-row"><strong>对外报价</strong><label :class="{ 'is-readonly': !nodeEditable }"><input v-model="deliveryForm.externalQuote" type="number" min="0" step="0.01" :disabled="!nodeEditable" placeholder="0.00" aria-label="当前节点对外报价"><span>元</span></label><em class="is-admin">管理端</em><span>订单金额</span></div>
                  </div>
                  <ProjectMaterialGroup v-if="!isPresales" title="费用清单附件" :count="attachmentsFor('fee_estimated').length + attachmentsFor('fee_actual').length" source-label="管理端 / 小程序" :status="attachmentsFor('fee_estimated').length + attachmentsFor('fee_actual').length ? '已有资料' : '暂无资料'" tone="admin">
                    <AttachmentPanel target-type="project_node" :target-id="selectedNodeAttachmentId" :categories="[...FEE_ATTACHMENT_CATEGORIES.estimated, ...FEE_ATTACHMENT_CATEGORIES.actual]" :editable="false" source-label="按来源只读核对" :uploader-labels="{ fee_actual: selectedAssignment?.provider?.name || '' }" compact @changed="syncNodeAttachments" @error="error = $event" />
                    <div class="as-fee-attachment-actions"><button v-if="serviceType === 'midsales'" type="button" class="as-button as-button--secondary" @click="openMidsalesFeeModal('estimated', 'attachment')"><Paperclip />维护预计费用附件</button><button v-else-if="isAftersales" type="button" class="as-button as-button--secondary" @click="openAftersalesFeeModal('estimated', 'attachment')"><Paperclip />维护预计费用附件</button></div>
                  </ProjectMaterialGroup>
                  <section v-if="selectedSettlementState" class="as-settlement-state-summary" :class="`is-${selectedSettlementState.tone}`">
                    <span class="as-settlement-state-summary__icon"><Check v-if="selectedSettlementState.tone === 'settled'" /><Clock3 v-else-if="selectedSettlementState.tone === 'pending' || selectedSettlementState.tone === 'processing'" /><CircleDollarSign v-else /></span>
                    <div><small>结算状态</small><strong>{{ selectedSettlementState.label }}</strong><p>{{ selectedSettlementState.detail }}</p></div>
                    <em>系统自动判断</em>
                  </section>
                </div>
              </details>
            </div>
          </div>

          <PresalesProjectFees v-if="detailTab === 'fees' && isPresales" :source-crm-id="currentProject.sourceCrmId || ''" :identity-key="`${loginSessionIdentityKey(session)}:${projectListIdentity(session)}`" />
          <PresalesProjectInfo v-if="detailTab === 'info' && isPresales && isDesktop" :project-id="currentProject.id" :values="presalesMetadata" :editable="presalesMetadataEditable" :errors="presalesMetadataErrors" :source-crm-id="currentProject.sourceCrmId || currentProject.source_crm_id || ''" :identity-key="`${loginSessionIdentityKey(session)}:${projectListIdentity(session)}`" @change="(key, value) => presalesMetadata[key] = value" @documents-busy-change="presalesDocumentsBusy = $event" />
          <PresalesMaterialsPanel v-if="detailTab === 'presales-materials' && serviceType === 'midsales'" :project-id="currentProject.id" />

          <section v-if="detailTab === 'history'" class="as-node-workspace as-node-history is-history-tab" aria-label="项目版本与留痕">
              <div class="as-panel-head"><div><h3>项目版本与留痕</h3><p>整个项目 · 包含全部节点 · 共 {{ timeline.length }} 条记录</p></div></div>
              <div v-if="!timeline.length" class="as-empty as-empty--compact">暂无项目记录</div>
              <div v-for="(item, index) in timeline" v-else :key="item.id || `${item.time}-${index}`" class="as-history-item">
                <span></span><div><strong>{{ display(item, 'title', 'action_display', 'actionDisplay', 'eventType', 'type', 'action') }}</strong><small>{{ projectHistoryScope(item) }} · {{ formatDateTimeLabel(item.createdAt) }} · {{ item.actorName || item.authUserName || '-' }}<template v-if="item.authUserId && item.actorUserId && item.authUserId !== item.actorUserId">（代 {{ item.authUserName || item.authUserId }} 操作）</template></small><p>{{ display(item, 'detail', 'note', 'content', 'description') }}</p></div>
              </div>
          </section>
        </template>
      </section>
      <template v-if="currentProject && selectedNode && detailTab === 'overview'" #footer>
        <footer class="as-node-actionbar">
          <div class="as-node-actionbar__context"><span>{{ nodeName(selectedNode) }}</span><strong><LoaderCircle v-if="saving || nodeAutosavePending" class="as-spin" /><Check v-else />{{ saving ? '正在执行操作' : nodeAutosavePending ? '正在自动保存' : '内容已自动保存' }}</strong></div>
          <div class="as-node-actionbar__actions">
            <button v-if="selectedSettlementItems.length && currentProject.permissions?.canSettle" type="button" class="as-button as-button--warning" @click="openSettlementCenter()"><CircleDollarSign />结算中心</button>
            <template v-if="isPresalesResult"><button type="button" class="as-button as-button--secondary" :disabled="saving || !canReturn" @click="runAction('return')"><RotateCcw />节点回退</button><button type="button" class="as-button as-button--primary" :disabled="saving || !canAdvance" @click="runAction('advance')"><Check />节点通过</button></template>
            <button v-else-if="isPresalesEnd" type="button" class="as-button as-button--primary" :disabled="!canAdvance || saving" @click="runAction('advance')"><Check />结束售前并转入售中</button>
            <template v-else-if="serviceType === 'aftersales'"><button v-if="selectedNode.status === 'pending' && nodeKey(selectedNode) === currentNodeKey" type="button" class="as-button as-button--primary" :disabled="saving || !canStart" @click="runAction('start')"><Play />开始节点</button><button type="button" class="as-button as-button--secondary" :disabled="!canReturn || saving" @click="runAction('return')"><RotateCcw />节点回退</button><button type="button" class="as-button as-button--primary" :disabled="!canAdvance || saving" @click="openAftersalesCompletion"><LoaderCircle v-if="saving" class="as-spin" /><Check v-else />节点通过</button></template>
            <template v-else-if="isPresalesApproval"><button v-if="isPresalesApprovalDenied" type="button" class="as-button as-button--primary" :disabled="saving || !canReturn" @click="restorePresalesApproval"><LoaderCircle v-if="saving" class="as-spin" /><RotateCcw v-else />恢复立项</button><template v-else><button type="button" class="as-button as-button--danger" :disabled="saving || !nodeEditable" @click="openPresalesDenial"><CircleAlert />立项否决</button><button type="button" class="as-button as-button--primary" :disabled="saving || !nodeEditable || !presalesPersonnelComplete" @click="runAction('advance', { outcome: 'approved' })"><Check />立项成功</button></template></template>
            <template v-else-if="isPresalesDelivery"><button type="button" class="as-button as-button--secondary" :disabled="!canReturn || saving" @click="runAction('return')"><RotateCcw />节点回退</button><button type="button" class="as-button as-button--primary" :disabled="!canAdvance || saving" @click="runAction('advance')"><Check />节点通过</button></template>
            <template v-else-if="serviceType === 'midsales' && selectedNode.kind !== 'end'"><button v-if="selectedNode.status === 'pending' && nodeKey(selectedNode) === currentNodeKey" type="button" class="as-button as-button--primary" :disabled="saving || !canStart" @click="runAction('start')"><Play />开始节点</button><button type="button" class="as-button as-button--secondary" :disabled="saving || !canReturn" @click="runAction('return')"><RotateCcw />节点回退</button><button type="button" class="as-button as-button--primary" :disabled="saving || !canAdvance" @click="runAction('advance')"><Check />节点通过</button></template>
            <template v-else-if="serviceType === 'midsales' && selectedNode.kind === 'end'"><button v-if="selectedNode.status === 'pending' && nodeKey(selectedNode) === currentNodeKey" type="button" class="as-button as-button--primary" :disabled="saving || !canStart" @click="runAction('start')"><Play />开始节点</button><button type="button" class="as-button as-button--primary" :disabled="saving || !canAdvance" @click="runAction('advance')"><Check />本节点结束</button></template>
          </div>
        </footer>
      </template>
      </ProjectDetailDrawer>

      <RelatedProductPicker
        :open="relatedProductPickerOpen"
        :project-name="display(currentProject, 'name', 'project_name', 'projectName')"
        :selected-products="relatedProductPickerProducts"
        :saving="relatedProductSaving"
        @close="closeRelatedProductPicker"
        @confirm="saveRelatedProducts"
      />
      <RelatedProductDetailDrawer
        :open="relatedProductDetailOpen && drawerOpen"
        :product="relatedProductDetail"
        :level="2"
        :loading="relatedProductDetailLoading"
        :error="relatedProductDetailError"
        @retry="loadRelatedProductDetail"
        @close="closeRelatedProductDetail"
      />
    </div>

    <ModalShell :open="projectDeleteOpen" title="确认删除服务" :description="projectDeleteTarget ? `删除“${display(projectDeleteTarget, 'name', 'project_name', 'projectName')}”后，管理端列表和小程序关联任务将不再显示。` : '确认删除当前服务。'" @close="closeProjectDelete">
      <div class="as-alert as-alert--error"><CircleAlert /><span>该操作会停止当前服务及其现场任务，请确认无需继续处理。</span></div>
      <template #footer><button type="button" class="as-button as-button--secondary" :disabled="projectDeleting" @click="closeProjectDelete">取消</button><button type="button" class="as-button as-button--danger" :disabled="projectDeleting" @click="confirmProjectDelete"><LoaderCircle v-if="projectDeleting" class="as-spin" /><Trash2 v-else />确认删除</button></template>
    </ModalShell>

    <ModalShell :open="noteModalOpen" :title="noteModalSource === 'mobile' ? '小程序提交说明' : '管理端处理说明'" :description="`${nodeName(selectedNode)} · ${noteModalSource === 'mobile' ? '小程序提交，管理端只读' : '管理端记录，修改后自动保存'}`" @close="closeNoteModal">
      <div class="as-note-modal">
        <div class="as-note-modal__meta"><span :class="noteModalSource === 'mobile' ? 'is-mobile' : 'is-admin'">{{ noteModalSource === 'mobile' ? '小程序提交' : '管理端记录' }}</span><strong>{{ noteModalSource === 'mobile' ? latestMobileSyncAt ? `更新时间 ${formatDateTimeLabel(latestMobileSyncAt)}` : '尚未收到小程序数据' : nodeAutosavePending ? '正在自动保存' : '内容自动保存' }}</strong></div>
        <label class="as-field"><span>说明内容</span><textarea v-model="noteModalDraft" rows="8" :readonly="noteModalSource === 'mobile' || !nodeEditable" :placeholder="noteModalSource === 'mobile' ? '小程序端尚未填写现场说明' : '填写当前节点的处理说明、判断和下一步安排'"></textarea></label>
      </div>
      <template #footer><button type="button" class="as-button as-button--secondary" @click="closeNoteModal">关闭</button><button v-if="noteModalSource === 'admin' && nodeEditable" type="button" class="as-button as-button--primary" @click="saveNoteModal"><Save />保存说明</button></template>
    </ModalShell>

    <ModalShell :open="aftersalesCompletionOpen" title="完工确认" description="联系负责人确认无误后，提交当前售后节点的完工申请。" wide @close="aftersalesCompletionOpen = false">
      <div class="as-completion-summary"><div class="as-info-grid"><div><span>预计服务开始时间</span><strong>{{ formatDateTimeLabel(deliveryForm.plannedStartAt) }}</strong></div><div><span>预计服务总时长</span><strong>{{ display(aftersalesProjectData, 'expectedDuration', 'expected_duration') }}</strong></div><div><span>实际费用</span><strong>{{ deliveryForm.actualFee !== '' ? deliveryForm.actualFee + ' 元' : '-' }}</strong></div><div><span>费用备注</span><strong>{{ aftersalesFeeDetail.actualNote || aftersalesFeeDetail.estimatedNote || '-' }}</strong></div></div></div>
      <div class="as-completion-form-grid"><label class="as-field"><span>实际服务开始时间 *</span><DateField v-model="deliveryForm.actualStartAt" type="datetime-local" aria-label="实际服务开始时间" /></label><label class="as-field"><span>实际服务时长 *</span><input :value="aftersalesServiceDuration" readonly placeholder="需先填写实际完成时间"></label></div>
      <details open class="as-presales-fold"><summary>完工附件检查</summary><AttachmentPanel :key="selectedNodeAttachmentId + ':' + nodeAttachmentsVersion" target-type="project_node" :target-id="selectedNodeAttachmentId" title="完工附件" :categories="AFTERSALES_ATTACHMENT_GROUPS" :editable="false" @changed="syncNodeAttachments" @error="error = $event" /></details>
      <template #footer><button type="button" class="as-button as-button--secondary" @click="aftersalesCompletionOpen = false">返回</button><button type="button" class="as-button as-button--danger" :disabled="saving" @click="openCompletionRejectModal">驳回</button><button type="button" class="as-button as-button--primary" :disabled="saving" @click="confirmAftersalesCompletion"><LoaderCircle v-if="saving" class="as-spin" /><Check v-else />完工确认</button></template>
    </ModalShell>

    <ModalShell :open="completionRejectOpen" title="驳回完工确认" description="填写需要补充或重新处理的内容，确认后当前完工申请将被驳回。" @close="closeCompletionRejectModal">
      <label class="as-field"><span>驳回原因 *</span><textarea v-model="completionRejectNote" rows="7" placeholder="填写资料缺失、现场问题、验收未通过项或需要补充处理的要求"></textarea></label>
      <template #footer><button type="button" class="as-button as-button--secondary" :disabled="saving" @click="closeCompletionRejectModal">取消</button><button type="button" class="as-button as-button--danger" :disabled="saving || !completionRejectNote.trim()" @click="rejectAftersalesCompletion"><LoaderCircle v-if="saving" class="as-spin" /><CircleAlert v-else />确认驳回</button></template>
    </ModalShell>

    <ModalShell :open="midsalesProofModalOpen" title="交付内容" :description="selectedNode ? nodeName(selectedNode) + ' · 查看现场证明材料。' : '查看现场证明材料。'" wide @close="closeMidsalesProofModal">
      <div class="as-midsales-proof-modal">
        <div v-if="proofLoading" class="as-empty as-empty--compact"><LoaderCircle class="as-spin" /> 正在加载证明材料...</div>
        <article v-if="openedMidsalesProof" class="as-midsales-proof-modal__editor">
          <div class="as-midsales-proof-modal__editor-head"><div><strong>{{ MIDSALES_PROOF_TYPES.find((type) => type.key === proofType(openedMidsalesProof))?.label || '证明材料' }}</strong><small>支持任意类型附件 · {{ proofAttachments(openedMidsalesProof).length }} 个文件</small></div></div>
          <AttachmentPanel target-type="midsales_proof" :target-id="openedMidsalesProof.id" title="现场材料附件" :categories="MIDSALES_PROOF_ATTACHMENT_CATEGORIES" :editable="false" compact @changed="syncMidsalesProofAttachments" @error="error = $event" />
          <label class="as-field"><span>审核意见</span><textarea v-model="proofReviewOpinion" rows="5" maxlength="20000" placeholder="通过时可填写确认意见；驳回时必须说明需要补充或修改的内容"></textarea></label>
        </article>
        <div v-else-if="!proofLoading" class="as-empty as-empty--compact">暂无证明材料记录</div>
      </div>
      <template #footer><button type="button" class="as-button as-button--secondary" :disabled="proofReviewSaving" @click="closeMidsalesProofModal">关闭</button><button type="button" class="as-button as-button--danger" :disabled="proofReviewSaving || !openedMidsalesProof?.canReview" @click="saveMidsalesProofReview('rejected')"><LoaderCircle v-if="proofReviewSaving" class="as-spin" /><CircleAlert v-else />驳回</button><button type="button" class="as-button as-button--primary" :disabled="proofReviewSaving || !openedMidsalesProof?.canReview || !proofAttachments(openedMidsalesProof).length" @click="saveMidsalesProofReview('approved')"><LoaderCircle v-if="proofReviewSaving" class="as-spin" /><Check v-else />审核通过</button></template>
    </ModalShell>

    <ModalShell :open="midsalesFeeModalOpen" :title="midsalesFeeModalTitle" :description="midsalesFeeModalPhase === 'estimated' ? '预计费用资料由管理端维护。' : '实际费用资料由小程序端填写，管理端仅查看。'" @close="closeMidsalesFeeModal">
      <div class="as-midsales-fee-modal">
        <label v-if="midsalesFeeModalKind === 'note'" class="as-field"><span>{{ midsalesFeeModalTitle }}</span><textarea v-model="midsalesFeeNoteDraft" rows="7" :readonly="!midsalesFeeModalEditable" :placeholder="midsalesFeeModalEditable ? '填写费用说明、计费口径或结算差异' : '小程序端尚未填写实际费用备注'"></textarea></label>
        <AttachmentPanel v-else target-type="project_node" :target-id="selectedNodeAttachmentId" :categories="FEE_ATTACHMENT_CATEGORIES[midsalesFeeModalPhase]" :editable="midsalesFeeModalEditable" compact upload-label="上传附件" @changed="syncNodeAttachments" @error="error = $event" />
      </div>
      <template #footer><button type="button" class="as-button as-button--secondary" @click="closeMidsalesFeeModal">关闭</button><button v-if="midsalesFeeModalKind === 'note' && midsalesFeeModalEditable" type="button" class="as-button as-button--primary" @click="saveMidsalesFeeNote"><Save />保存备注</button></template>
    </ModalShell>

    <ModalShell :open="aftersalesFeeModalOpen" :title="aftersalesFeeModalTitle" description="查看或编辑当前售后节点的费用备注。" @close="closeAftersalesFeeModal">
      <div class="as-aftersales-fee-modal">
        <label v-if="aftersalesFeeModalKind === 'note'" class="as-field"><span>{{ aftersalesFeeModalTitle }}</span><textarea v-model="aftersalesFeeNoteDraft" rows="7" :readonly="!aftersalesFeeModalEditable" :placeholder="aftersalesFeeModalPhase === 'actual' ? '小程序端尚未填写实际费用备注' : '填写预计费用口径和预算说明'"></textarea></label>
        <AttachmentPanel v-else target-type="project_node" :target-id="selectedNodeAttachmentId" :categories="FEE_ATTACHMENT_CATEGORIES[aftersalesFeeModalPhase]" :editable="aftersalesFeeModalEditable" compact upload-label="上传附件" @changed="syncNodeAttachments" @error="error = $event" />
      </div>
      <template #footer><button type="button" class="as-button as-button--secondary" @click="closeAftersalesFeeModal">关闭</button><button v-if="aftersalesFeeModalKind === 'note' && aftersalesFeeModalEditable" type="button" class="as-button as-button--primary" @click="saveAftersalesFeeNote"><Save />保存备注</button></template>
    </ModalShell>

    <ModalShell :open="workerRatingOpen" title="服务人员评分" description="当前节点已完成，请为本次服务记录评分。" @close="closeWorkerRatingModal">
      <div class="as-worker-rating-context">
        <div><span>服务人员</span><strong>{{ workerRatingForm.providerName || '-' }}</strong></div>
        <div><span>完成节点</span><strong>{{ workerRatingForm.nodeName || '-' }}</strong></div>
      </div>
      <fieldset class="as-worker-rating-fieldset">
        <legend>本次服务评分 *</legend>
        <div class="as-worker-rating-options" role="radiogroup" aria-label="本次服务评分">
          <button v-for="score in [1, 2, 3, 4, 5]" :key="score" type="button" role="radio" :aria-checked="workerRatingForm.rating === score" :class="{ active: workerRatingForm.rating === score }" @click="workerRatingForm.rating = score"><Star />{{ score }} 分</button>
        </div>
      </fieldset>
      <template #footer><button type="button" class="as-button as-button--secondary" :disabled="workerRatingSaving" @click="closeWorkerRatingModal">暂不评分</button><button type="button" class="as-button as-button--primary" :disabled="workerRatingSaving" @click="submitWorkerRating"><LoaderCircle v-if="workerRatingSaving" class="as-spin" /><Star v-else />确认评分</button></template>
    </ModalShell>

    <ModalShell :open="presalesProjectInfoOpen" title="项目信息" :description="!nodeEditable ? '当前节点资料只读，可查看项目信息和附件。' : isCrmProject ? '项目基础资料来自 CRM；申请理由和补充附件可在此维护。' : '查看或编辑项目信息。'" wide @close="closePresalesProjectInfoModal">
      <div v-if="error" class="as-alert as-alert--error" role="alert">{{ error }}</div>
      <div v-if="presalesProjectInfoPending && !presalesProjectInfoSaving" class="as-alert" role="status"><span>填写内容尚未保存，可以重试或放弃修改后重新加载。</span><button type="button" class="as-button as-button--secondary" @click="discardDraftOpen = true">放弃修改并重新加载</button></div>
      <div class="as-form-grid">
        <label v-if="isCrmProject" class="as-field"><span>CRM 项目编号</span><input :value="currentProject.sourceCrmId" readonly></label>
        <label v-if="isCrmProject" class="as-field"><span>销售类型</span><input :value="currentProject.crmOrderType || '未填写'" readonly></label>
        <label v-if="isCrmProject" class="as-field"><span>CRM 阶段</span><input :value="currentProject.crmStage || '未填写'" readonly></label>
        <label v-if="isCrmProject" class="as-field"><span>CRM 状态</span><input :value="currentProject.crmStatus || '未填写'" readonly></label>
        <label class="as-field"><span>客户单位</span><input v-model="presalesProjectInfo.customer" :readonly="isCrmProject || !projectInfoEditable" placeholder="填写客户单位"></label>
        <label class="as-field"><span>{{ isCrmProject ? 'CRM 负责人' : '负责人' }}</span><input v-model="presalesProjectInfo.owner" :readonly="isCrmProject || !projectInfoEditable" placeholder="填写负责人"></label>
        <label class="as-field as-field--wide"><span>项目名称</span><input v-model="presalesProjectInfo.name" :readonly="isCrmProject || !projectInfoEditable" placeholder="填写项目名称"></label>
        <label class="as-field as-field--wide"><span>项目信息</span><textarea v-model="presalesProjectInfo.info" :readonly="isCrmProject || !projectInfoEditable" rows="4" :placeholder="isCrmProject ? 'CRM 暂未填写项目说明或采购需求' : '填写客户需求、建设范围、预计规模、关键时间要求。'"></textarea></label>
        <label class="as-field as-field--wide"><span>申请理由（选填）</span><textarea v-model="presalesProjectInfo.reason" :readonly="!projectInfoEditable" rows="4" placeholder="按需补充售前服务说明，可留空。"></textarea></label>
        <div class="as-field as-field--wide"><span>补充原始附件</span><AttachmentPanel target-type="project_node" :target-id="selectedNodeAttachmentId" :editable="nodeEditable" compact upload-label="选择文件" @error="error = $event" /></div>
      </div>
      <template #footer><button type="button" class="as-button as-button--secondary" @click="closePresalesProjectInfoModal">关闭</button><button v-if="projectInfoEditable" type="button" class="as-button as-button--primary" :disabled="presalesProjectInfoSaving" @click="savePresalesProjectInfo"><LoaderCircle v-if="presalesProjectInfoSaving" class="as-spin" /><Save v-else />立即保存</button></template>
    </ModalShell>

    <ModalShell :open="presalesDenialOpen" title="确认立项否决" description="否决后项目会停止推进，但可以从当前节点恢复立项。" @close="closePresalesDenial">
      <div class="as-alert as-alert--error"><CircleAlert /><span>请确认项目确实不应继续推进，并填写具体原因。</span></div>
      <label class="as-field"><span>否决原因 *</span><textarea v-model="presalesDenialReason" rows="5" placeholder="填写客户反馈、预算原因、项目风险或其他否决依据"></textarea></label>
      <template #footer><button type="button" class="as-button as-button--secondary" @click="closePresalesDenial">取消</button><button type="button" class="as-button as-button--danger" :disabled="saving" @click="confirmPresalesDenial"><LoaderCircle v-if="saving" class="as-spin" /><CircleAlert v-else />确认否决</button></template>
    </ModalShell>

    <ModalShell :open="createOpen" :title="config.createLabel" :description="serviceType === 'presales' ? '在服务中心独立维护，不关联 CRM；创建后进入前期立项流程。' : '建立项目后从首个节点开始推进。'" wide @close="createOpen = false">
      <div class="as-form-grid">
        <template v-if="serviceType === 'presales'">
          <label class="as-field"><span>客户单位 *</span><input v-model="createForm.customer_name" placeholder="例如：新锐客户"></label>
          <label class="as-field"><span>申请人</span><input :value="currentUserName" readonly></label>
          <label class="as-field as-field--wide"><span>项目名称 *</span><input v-model="createForm.name" placeholder="例如：新锐客户-2026年-智慧教室项目"></label>
          <label class="as-field as-field--wide"><span>项目信息（选填）</span><textarea v-model="createForm.description" rows="4" placeholder="填写客户需求、建设范围、预计规模、关键时间要求。"></textarea></label>
          <label class="as-field as-field--wide"><span>申请理由（选填）</span><textarea v-model="createForm.application_reason" rows="4" placeholder="按需补充售前服务说明，可留空。"></textarea></label>
          <div class="as-field as-field--wide"><span>原始附件</span><FileSelectionPanel :files="createForm.original_files" preview-enabled @change="selectCreatePresalesFiles" @remove="removeCreatePresalesFile" /></div>
        </template>
        <template v-else>
          <label class="as-field as-field--wide"><span>项目名称 *</span><input v-model="createForm.name" placeholder="客户-年份-项目名称"></label>
          <label class="as-field"><span>客户名称 *</span><input v-model="createForm.customer_name" placeholder="客户单位"></label>
          <label class="as-field"><span>申请人</span><input :value="currentUserName" readonly></label>
          <label class="as-field"><span>申请人联系电话 *</span><input v-model="createForm.manager_contact" type="tel" placeholder="用于项目沟通"></label>
          <label class="as-field as-field--wide"><span>项目 / 服务地址</span><input v-model="createForm.address" placeholder="现场详细地址"></label>
          <label class="as-field as-field--wide"><span>项目说明</span><textarea v-model="createForm.description" rows="3" placeholder="记录项目范围、关键时间与交付要求"></textarea></label>
        </template>
        <MidsalesNodeSelection v-if="serviceType === 'midsales'" v-model="createForm.enabled_node_ids" />
        <fieldset v-if="serviceType === 'aftersales'" class="as-fieldset as-field--wide"><legend>服务类型（单选）</legend><div class="as-radio-grid"><label v-for="stage in stageOptions" :key="stage.id" :class="{ active: createForm.service_node_id === stage.id }"><input v-model="createForm.service_node_id" type="radio" :value="stage.id"><span>{{ stage.name }}</span></label></div></fieldset>
        <template v-if="serviceType === 'aftersales'">
          <label class="as-field"><span>预计服务时长 *</span><input v-model="createForm.expected_duration" placeholder="例如：1天"></label>
          <label class="as-field"><span>费用约定 *</span><select v-model="createForm.fee_agreement"><option>客户承担</option><option>公司承担</option><option>保内免费</option></select></label>
          <label class="as-field"><span>费用备注 *</span><input v-model="createForm.fee_remark" placeholder="金额、报销或核销说明"></label>
        </template>
      </div>
      <template #footer><button type="button" class="as-button as-button--secondary" @click="createOpen = false">取消</button><button type="button" class="as-button as-button--primary" :disabled="saving" @click="createProject"><LoaderCircle v-if="saving" class="as-spin" /><Plus v-else />{{ serviceType === 'presales' ? '确认新增' : '创建项目' }}</button></template>
    </ModalShell>

    <ModalShell :open="teamOpen" :title="managementPicker ? '选择钉钉项目人员' : '选择服务人员'" :description="`为 ${teamTargetNodeName} 选择${projectLeadPicker ? '一位负责人' : managementPicker ? '管理端人员' : '现场工人'}`" wide @close="!saving && (teamOpen = false)">
      <div v-if="managementPicker && error" class="as-alert as-alert--error" role="alert">{{ error }}<button v-if="!managementEmployees.length && !teamLoading" type="button" class="as-button as-button--secondary" @click="loadManagementEmployees">重试加载人员</button></div>
      <div v-if="managementPicker" class="as-filter-row as-filter-row--single"><label class="as-search"><Search /><input ref="teamSearchInput" v-model="teamKeyword" type="search" placeholder="搜索姓名、部门或用户ID" aria-label="搜索钉钉人员姓名、部门或用户ID"></label></div>
      <div v-else class="as-filter-row as-filter-row--three"><label class="as-search"><Search /><input ref="teamSearchInput" v-model="teamKeyword" type="search" placeholder="姓名、电话或能力" aria-label="搜索服务人员"></label><select v-model="teamRegion" class="as-select"><option value="">全部地区</option><option v-for="region in regions" :key="region">{{ region }}</option></select><select v-model="teamSkill" class="as-select"><option value="">全部能力</option><option v-for="skill in skills" :key="skill">{{ skill }}</option></select></div>
      <div v-if="managementPicker && teamSelectedMembers.length" class="as-management-selected" aria-label="已选项目人员">
        <button v-for="member in teamSelectedMembers" :key="member.userId" type="button" class="as-button as-button--secondary" :disabled="saving" :aria-label="`移除${member.name}`" @click="toggleTeamMember(member)">{{ member.name }}<X aria-hidden="true" /></button>
      </div>
      <div v-if="teamLoading" class="as-empty"><LoaderCircle class="as-spin" /> 正在读取{{ managementPicker ? '钉钉人员' : '服务团队' }}...</div>
      <div v-else-if="managementPicker" class="as-management-member-picker">
        <div class="as-management-member-picker__head" aria-hidden="true"><span>人员</span><span>部门</span><span /></div>
        <label v-for="member in filteredTeam" :key="member.userId" class="as-management-member-choice" :class="{ 'is-selected': teamSelectedIds.has(String(member.userId)) }"><span class="as-avatar" aria-hidden="true">{{ String(member.name || '人').slice(0, 1) }}</span><span class="as-management-member-picker__identity"><strong>{{ member.name }}</strong><small>钉钉用户ID · {{ member.userId }}</small></span><span class="as-management-member-picker__department" :title="managementEmployeeDepartmentText(member)">{{ managementEmployeeDepartmentText(member) }}</span><input :type="projectLeadPicker ? 'radio' : 'checkbox'" :name="projectLeadPicker ? 'presales-project-lead' : undefined" :aria-label="`选择${member.name}`" :checked="teamSelectedIds.has(String(member.userId))" :disabled="saving" @change="toggleTeamMember(member)"></label>
        <div v-if="!filteredTeam.length" class="as-empty">没有符合条件的人员</div>
      </div>
      <div v-else class="as-member-picker">
        <button v-for="member in filteredTeam" :key="member.id || member.userId" type="button" :disabled="saving" @click="assignMember(member)"><span class="as-avatar">{{ String(member.name || '人').slice(0, 1) }}</span><span><strong>{{ member.name }}</strong><small>{{ display(member, 'roleLabel', 'role_display', 'roleDisplay', 'role') }} · {{ (member.regions || [member.city]).filter(Boolean).join('、') }}</small><em>{{ (member.skills || member.abilities || []).slice(0, 3).join(' · ') }}</em></span><ChevronRight /></button>
        <div v-if="!filteredTeam.length" class="as-empty">没有符合条件的人员</div>
      </div>
      <template v-if="managementPicker" #footer><span class="as-management-selection-count" role="status">已选择 {{ teamSelectedMembers.length }} 人</span><button type="button" class="as-button as-button--secondary" :disabled="saving || !teamSelectedMembers.length" @click="teamSelectedMembers = []">清空</button><button type="button" class="as-button as-button--secondary" :disabled="saving" @click="teamOpen = false">取消</button><button type="button" class="as-button as-button--primary" :disabled="saving || teamLoading" @click="confirmManagementMembers"><LoaderCircle v-if="saving" class="as-spin" />确认选择</button></template>
    </ModalShell>
  </div>
</template>
