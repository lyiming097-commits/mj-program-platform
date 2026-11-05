<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  Building2,
  Bot,
  BellRing,
  PanelsTopLeft,
  SearchCheck,
  Landmark,
  MapPinned,
  ShieldCheck,
  UserRoundX,
  UserX,
  X,
} from "@lucide/vue";
import { PlatformActionToast, PlatformSidebar } from "@platform-ui";
import {
  APP_PATH,
  SETTINGS_APPLICATION_TEMPLATE_PATH,
  APPLICATION_TEMPLATE_WORKSPACE_PATH,
  SETTINGS_ADMINISTRATIVE_REGIONS_PATH,
  SETTINGS_BUSINESS_REGISTRY_PATH,
  SETTINGS_ROBOT_MESSAGES_PATH,
  SETTINGS_NOTIFICATIONS_PATH,
  SETTINGS_COMPANY_ENTITIES_LEAVE_EVENT,
  SETTINGS_COMPANY_ENTITIES_PATH,
  SETTINGS_HANDOVER_PATH,
  SETTINGS_ORGANIZATION_PATH,
  SETTINGS_ORGANIZATION_PERMISSIONS_PATH,
} from "@/config";
import { apiGet, apiPost, apiPut } from "@/api";
import { runOrganizationSync } from "@/organization-sync";
import { useOrganizationSyncTime } from "@/use-organization-sync-time";
import { employeeMatchesDirectoryKeyword } from "@/directory-search";
import { sortInactiveEmployeesByDepartureDate } from "@/inactive-employee-sort";
import { navigateTo } from "@/router-lite";
import { openApplicationTemplateTab } from "@/application-template-navigation";
import SettingsHandoverPanel from "@/components/settings/SettingsHandoverPanel_web.vue";
import SettingsCompanyEntitiesPanel from "@/components/settings/SettingsCompanyEntitiesPanel_web.vue";
import SettingsOrganizationPanel from "@/components/settings/SettingsOrganizationPanel_web.vue";
import SettingsOrganizationTabs from "@/components/settings/SettingsOrganizationTabs.vue";
import SettingsOrganizationPermissionsPanel from "@/components/settings/SettingsOrganizationPermissionsPanel.vue";
import SettingsUnsavedChangesDialog from "@/components/settings/SettingsUnsavedChangesDialog.vue";
import SettingsApplicationTemplateEntry from "@/components/settings/SettingsApplicationTemplateEntry_web.vue";
import { clearLoginSession, loadLoginSession, logoutLoginSession, saveLoginSession, validateLoginSession } from "@/session";

import SettingsAccountStatusDialog from "./SettingsAccountStatusDialog_web.vue";
import SettingsOrganizationActivity from "./SettingsOrganizationActivity_web.vue";
import "./organization-workspace.css";
import { useSettingsDialog } from "./useSettingsDialog";
import { provideSettingsFeedback } from "./useSettingsFeedback";

const props = defineProps({
  initialManagementTab: {
    type: String,
    default: "department",
  },
});
const emit = defineEmits(["dirty-change", "saving-change"]);
const SettingsAdministrativeRegionsPanel = defineAsyncComponent(
  () => import("@/components/settings/SettingsAdministrativeRegionsPanel_web.vue"),
);

const SettingsBusinessRegistryPanel = defineAsyncComponent(
  () => import("@/components/settings/SettingsBusinessRegistryPanel_web.vue"),
);

const SettingsRobotMessagesPanel = defineAsyncComponent(() => import("./SettingsRobotMessagesPanel_web.vue"));
const SettingsNotificationsPanel = defineAsyncComponent(() => import("./SettingsNotificationsPanel_web.vue"));
const robotMessagesPanel = ref(null);
const notificationsPanel = ref(null);
const robotSettingsDirty = ref(false), robotSettingsSaving = ref(false);
const managementTab = ref(
  ["department", "permissions", "inactive", "company-entities", "administrative-regions", "business-registry", "application-template", "robot-messages", "notifications"].includes(props.initialManagementTab)
    ? props.initialManagementTab
    : "department",
);
const session = ref(loadLoginSession());
const organizationSettingsPanel = ref(null);
const permissionSettingsDirty = ref(false);
const permissionSettingsSaving = ref(false);
const organizationLeaveConfirmOpen = ref(false);

const loadingTree = ref(false);
const loadingDepartment = ref(false);
const loadingEmployeeDirectory = ref(false);
const loadingInactive = ref(false);
const syncingContacts = ref(false);
const { lastSyncLabel, refreshLastSyncTime, syncRun, status: syncStatus } = useOrganizationSyncTime();
const organizationActionDialogOpen = ref(false);
const organizationActivityOpen = ref(false);
const organizationActionRunning = ref("");
const accountStatusSavingUserId = ref("");
const errorMessage = ref("");
const { feedback, showFeedback, clearFeedback } = provideSettingsFeedback();

const departmentTree = ref([]);
const expandedDeptIds = ref([]);
const selectedDepartment = ref(null);
const departmentDetail = ref(null);
const departmentEmployees = ref([]);
const includeSubDepartments = ref(new URLSearchParams(window.location.search).get("children") !== "0");
const initialDirectoryQuery = new URLSearchParams(window.location.search);
const departmentKeyword = ref(initialDirectoryQuery.get("q") || "");
const treeKeyword = ref(initialDirectoryQuery.get("treeQ") || "");
const departmentError = ref("");
const treeError = ref("");
const accountTarget = ref(null);
const accountSaving = ref(false);
let syncStatusTimer = null;

const enabledDepartmentIds = ref(new Set());
const enabledDepartmentRevision = ref("");
const enabledDepartmentOrgRevision = ref("");
const enabledDepartmentSnapshot = ref("");
const enabledDepartmentsLoaded = ref(false);
const loadingEnabledDepartments = ref(false);
const savingEnabledDepartments = ref(false);
const editingEnabledDepartments = ref(false);
const showDisabledDepartments = ref(false);

const employeeDirectory = ref([]);

const inactiveKeyword = ref("");
const inactiveEmployees = ref([]);
const proxyKeyword = ref("");
const proxyEmployees = ref([]);
const proxyConfirmOpen = ref(false);
const proxyStopConfirmOpen = ref(false);
const selectedProxyEmployee = ref(null);
const loadingProxyEmployees = ref(false);
const proxyActionUserId = ref("");
const employeeActionDialogOpen = ref(false);
const selectedEmployeeActionTarget = ref(null);
const organizationActionPanel = ref(null);
const employeeActionPanel = ref(null);
useSettingsDialog(organizationActionDialogOpen, organizationActionPanel, closeOrganizationActionDialog, () => Boolean(accountTarget.value) || organizationLeaveConfirmOpen.value || organizationActivityOpen.value);
useSettingsDialog(employeeActionDialogOpen, employeeActionPanel, closeEmployeeActionDialog, () => Boolean(accountTarget.value));
const ORGANIZATION_SETTINGS_SAVING_LEAVE_MESSAGE = "组织配置正在保存，请等待保存完成后再离开";

const isProxying = computed(() => Boolean(session.value?.isProxying));
const canManagePlatformSettings = computed(() => Boolean(session.value?.canManagePlatformSettings));
const canConfigurePermissions = computed(() => (
  Boolean(session.value?.canConfigurePermissions) || canManagePlatformSettings.value
));
const canSyncContacts = computed(() => Boolean(session.value?.canSyncContacts));
const canManageEmployeeAccountStatus = computed(() => Boolean(session.value?.canManageEmployeeAccountStatus));
const canAccessInactiveEmployees = computed(() => Boolean(session.value?.canAccessInactiveEmployees));
const canUseProxy = computed(() => Boolean(session.value?.canStartProxy) && !isProxying.value);
const canOpenOrganizationActions = computed(() => canSyncContacts.value || canManageEmployeeAccountStatus.value);
const canManageEnabledDepartments = computed(() => canOpenOrganizationActions.value);
const canOperateDepartmentEmployee = computed(() => canManageEmployeeAccountStatus.value || canUseProxy.value);
const canShowLogout = computed(() => !isDingTalkEnvironment());

const selectedManagers = computed(() => departmentDetail.value?.managers || (departmentDetail.value?.manager ? [departmentDetail.value.manager] : []));
const selectedManager = computed(() => selectedManagers.value[0] || null);
const selectedDepartmentName = computed(() => selectedDepartment.value?.name || "请选择部门");
const sortedDepartmentEmployees = computed(() => {
  const managers = new Set(selectedManagers.value.map(item => item.userId));
  return [...departmentEmployees.value].sort((left, right) =>
    Number(managers.has(right.userId)) - Number(managers.has(left.userId))
    || String(left.name || "").localeCompare(String(right.name || ""), "zh-CN")
    || String(left.userId).localeCompare(String(right.userId)));
});
const departmentIndex = computed(() => {
  const index = new Map();
  function visit(nodes, parents = []) {
    for (const node of nodes || []) {
      const path = [...parents, node];
      index.set(departmentId(node.deptId), { node, path, pathText: path.map(item => item.name).join(" / ") });
      visit(node.children, path);
    }
  }
  visit(departmentTree.value);
  return index;
});
const selectedDepartmentPath = computed(() => (departmentIndex.value.get(departmentId(selectedDepartment.value?.deptId))?.path || []).map(node => ({
  ...node, selectable: showDisabledDepartments.value || enabledDepartmentIds.value.has(departmentId(node.deptId)),
})));
const managementTabs = computed(() => {
  const items = [
    { id: "organization", label: "组织架构", path: SETTINGS_ORGANIZATION_PATH, icon: Building2 },
  ];
  if (canConfigurePermissions.value) {
    items.push({ id: "company-entities", label: "我司主体", path: SETTINGS_COMPANY_ENTITIES_PATH, icon: Landmark });
    items.push({ id: "administrative-regions", label: "省市区域", path: SETTINGS_ADMINISTRATIVE_REGIONS_PATH, icon: MapPinned });
    items.push({ id: "application-template", label: "应用模板", href: APPLICATION_TEMPLATE_WORKSPACE_PATH, target: "_blank", icon: PanelsTopLeft });
    items.push({ id: "business-registry", label: "工商信息查询", path: SETTINGS_BUSINESS_REGISTRY_PATH, icon: SearchCheck });
  }
  items.push({ id: "robot-messages", label: "机器人群发", path: SETTINGS_ROBOT_MESSAGES_PATH, icon: Bot });
  items.push({ id: "notifications", label: "通知", path: SETTINGS_NOTIFICATIONS_PATH, icon: BellRing });
  return items;
});

const managementSections = computed(() => [
  { id: "organization", label: "组织管理", items: managementTabs.value.filter(item => item.id === "organization") },
  ...(canConfigurePermissions.value ? [{ id: "directory", label: "基础资料", items: managementTabs.value.filter(item => ["company-entities", "administrative-regions", "business-registry"].includes(item.id)) }] : []),
  ...(canConfigurePermissions.value ? [{ id: "developer-tools", label: "开发工具", items: managementTabs.value.filter(item => item.id === "application-template") }] : []),
  { id: "messages", label: "消息工具", items: managementTabs.value.filter(item => ["robot-messages", "notifications"].includes(item.id)) },
]);
const activeSidebarItemId = computed(() => {
  return ["company-entities", "administrative-regions", "business-registry", "application-template", "robot-messages", "notifications"].includes(managementTab.value) ? managementTab.value : "organization";
});

const contentClass = computed(() => (
  ["department", "permissions", "inactive", "company-entities", "administrative-regions", "business-registry", "application-template", "robot-messages", "notifications"].includes(managementTab.value) ? "overflow-hidden" : "overflow-y-auto"
));

const standalonePage = computed(() => {
  if (managementTab.value === "application-template") {
    return { label: "应用模板", tabId: "auth-template-entry-tab", panelId: "auth-template-entry-panel" };
  }
  if (managementTab.value === "business-registry") {
    return { label: "工商信息查询", tabId: "auth-business-registry-tab", panelId: "auth-business-registry-panel" };
  }
  if (managementTab.value === "company-entities") {
    return { label: "我司主体", tabId: "auth-company-entities-tab", panelId: "auth-company-entities-panel" };
  }
  if (managementTab.value === "administrative-regions") {
    return { label: "省市区域", tabId: "auth-administrative-regions-tab", panelId: "auth-administrative-regions-panel" };
  }
  return null;
});


const filteredInactiveEmployees = computed(() => {
  return sortInactiveEmployeesByDepartureDate(
    inactiveEmployees.value.filter((employee) => employeeMatchesDirectoryKeyword(employee, inactiveKeyword.value)),
  );
});

const currentProxyUserId = computed(() => (isProxying.value ? session.value?.userId || "" : ""));
const currentSessionUserId = computed(() => session.value?.userId || "");
const actorSessionUserId = computed(() => session.value?.actorUserId || session.value?.userId || "");

function departmentId(value) {
  return String(value ?? "").trim();
}

function serializeEnabledDepartmentIds(ids = enabledDepartmentIds.value) {
  return JSON.stringify([...ids].sort((left, right) => left.localeCompare(right)));
}

function filterEnabledDepartmentTree(nodes) {
  return (nodes || []).flatMap((node) => {
    const children = filterEnabledDepartmentTree(node.children || []);
    if (!enabledDepartmentIds.value.has(departmentId(node.deptId))) return children;
    return [{ ...node, children,
      pathText: departmentIndex.value.get(departmentId(node.deptId))?.pathText,
      parentDisabled: node.parentDeptId != null && !enabledDepartmentIds.value.has(departmentId(node.parentDeptId)),
    }];
  });
}

function findDepartment(nodes, targetId) {
  const normalizedTargetId = departmentId(targetId);
  for (const node of nodes || []) {
    if (departmentId(node.deptId) === normalizedTargetId) return node;
    const child = findDepartment(node.children || [], normalizedTargetId);
    if (child) return child;
  }
  return null;
}

const enabledDepartmentsDirty = computed(() => (
  enabledDepartmentsLoaded.value
  && serializeEnabledDepartmentIds() !== enabledDepartmentSnapshot.value
));
const organizationSettingsSaving = computed(() => (
  savingEnabledDepartments.value || permissionSettingsSaving.value || accountSaving.value
));
const organizationDepartmentTree = computed(() => {
  if (!enabledDepartmentsLoaded.value || showDisabledDepartments.value) return departmentTree.value;
  return filterEnabledDepartmentTree(departmentTree.value);
});
let skipNextDepartmentWatch = false;
let departmentKeywordTimer = null;
let departmentDataRequestSeq = 0;
let workspaceUnmounted = false;
let pendingOrganizationLeaveAction = null;

function getDefaultDept(nodes) {
  return nodes.length ? nodes[0] : null;
}

function toggleExpanded(deptId) {
  const normalizedDeptId = departmentId(deptId);
  if (expandedDeptIds.value.some((item) => departmentId(item) === normalizedDeptId)) {
    expandedDeptIds.value = expandedDeptIds.value.filter((item) => departmentId(item) !== normalizedDeptId);
    return;
  }
  expandedDeptIds.value = [...expandedDeptIds.value, deptId];
}

function selectDepartment(department) {
  const selectedId = departmentId(department?.deptId);
  if (!selectedId) return;
  const sourceDepartment = findDepartment(departmentTree.value, selectedId) || department;
  selectedDepartment.value = sourceDepartment;
  if (!sourceDepartment.children?.length) return;
  if (expandedDeptIds.value.some((item) => departmentId(item) === selectedId)) return;
  expandedDeptIds.value = [...expandedDeptIds.value, sourceDepartment.deptId];
}

function getPrimaryDepartmentName(employee) {
  const departments = employee.departments || [];
  if (!departments.length) {
    return "-";
  }
  return departments.map((item) => item.name || departmentIndex.value.get(departmentId(item.deptId))?.node.name).filter(Boolean).join("；") || "-";
}

async function loadDepartmentTree() {
  loadingTree.value = true;
  loadingEnabledDepartments.value = true;
  treeError.value = "";
  try {
    let [data, enabledData] = await Promise.all([
      apiGet("/api/org/departments/tree"),
      apiGet("/api/org/enabled-departments"),
    ]);
    if (data.orgRevision != null && enabledData.orgRevision != null && String(data.orgRevision) !== String(enabledData.orgRevision)) {
      [data, enabledData] = await Promise.all([apiGet("/api/org/departments/tree"), apiGet("/api/org/enabled-departments")]);
      if (String(data.orgRevision) !== String(enabledData.orgRevision)) throw new Error("组织架构正在更新，请重新加载部门");
    }
    departmentTree.value = data.items || [];
    enabledDepartmentIds.value = new Set((enabledData.departmentIds || []).map(departmentId).filter(Boolean));
    enabledDepartmentRevision.value = departmentId(enabledData.revision);
    enabledDepartmentOrgRevision.value = departmentId(enabledData.orgRevision);
    enabledDepartmentSnapshot.value = serializeEnabledDepartmentIds(enabledDepartmentIds.value);
    enabledDepartmentsLoaded.value = true;

    const current = findDepartment(organizationDepartmentTree.value, selectedDepartment.value?.deptId || initialDirectoryQuery.get("dept"));
    const fallback = current || getDefaultDept(organizationDepartmentTree.value);
    if (departmentId(fallback?.deptId) !== departmentId(selectedDepartment.value?.deptId)) {
      skipNextDepartmentWatch = true;
      selectedDepartment.value = fallback;
    } else if (fallback) {
      selectedDepartment.value = fallback;
    }
    if (fallback && !expandedDeptIds.value.length) {
      expandedDeptIds.value = departmentIndex.value.get(departmentId(fallback.deptId))?.path.map(item => item.deptId) || [fallback.deptId];
    }
  } catch (error) {
    treeError.value = error instanceof Error ? error.message : "组织架构加载失败";
  } finally {
    loadingTree.value = false;
    loadingEnabledDepartments.value = false;
  }
}

function setShowDisabledDepartments(checked) {
  if (savingEnabledDepartments.value || loadingEnabledDepartments.value) return;
  if (checked && !editingEnabledDepartments.value) return;
  showDisabledDepartments.value = Boolean(checked);
  if (showDisabledDepartments.value) return;
  const current = findDepartment(organizationDepartmentTree.value, selectedDepartment.value?.deptId);
  if (current) {
    selectedDepartment.value = current;
    return;
  }
  selectedDepartment.value = getDefaultDept(organizationDepartmentTree.value);
}

function setDepartmentEnabled({ department, checked }) {
  const selectedId = departmentId(department?.deptId);
  if (!editingEnabledDepartments.value || !canManageEnabledDepartments.value || !selectedId || savingEnabledDepartments.value || loadingEnabledDepartments.value) return;
  selectDepartment(department);
  const next = new Set(enabledDepartmentIds.value);
  if (checked) next.add(selectedId);
  else next.delete(selectedId);
  enabledDepartmentIds.value = next;
  showDisabledDepartments.value = true;
}

function discardEnabledDepartmentChanges() {
  let savedIds = [];
  try {
    savedIds = JSON.parse(enabledDepartmentSnapshot.value || "[]");
  } catch {
    savedIds = [];
  }
  enabledDepartmentIds.value = new Set(savedIds.map(departmentId).filter(Boolean));
}

function finishEnabledDepartmentEdit() {
  editingEnabledDepartments.value = false;
  showDisabledDepartments.value = false;
  const current = findDepartment(organizationDepartmentTree.value, selectedDepartment.value?.deptId);
  selectedDepartment.value = current || getDefaultDept(organizationDepartmentTree.value);
}

function startEnabledDepartmentEdit() {
  if (!canManageEnabledDepartments.value || loadingEnabledDepartments.value || savingEnabledDepartments.value || syncingContacts.value) return;
  clearFeedback();
  editingEnabledDepartments.value = true;
  showDisabledDepartments.value = true;
}

function cancelEnabledDepartmentEdit() {
  if (savingEnabledDepartments.value) return;
  discardEnabledDepartmentChanges();
  finishEnabledDepartmentEdit();
}

async function saveEnabledDepartments() {
  if (!editingEnabledDepartments.value || !canManageEnabledDepartments.value || !enabledDepartmentsDirty.value || savingEnabledDepartments.value || syncingContacts.value) return;
  savingEnabledDepartments.value = true;
  errorMessage.value = "";
  clearFeedback();
  try {
    const data = await apiPut("/api/org/enabled-departments", {
      departmentIds: [...enabledDepartmentIds.value].sort((left, right) => left.localeCompare(right)),
      revision: enabledDepartmentRevision.value,
      orgRevision: enabledDepartmentOrgRevision.value,
    });
    enabledDepartmentIds.value = new Set((data.departmentIds || []).map(departmentId).filter(Boolean));
    enabledDepartmentRevision.value = departmentId(data.revision);
    enabledDepartmentOrgRevision.value = departmentId(data.orgRevision);
    enabledDepartmentSnapshot.value = serializeEnabledDepartmentIds(enabledDepartmentIds.value);
    showFeedback("启用部门设置已保存");
    finishEnabledDepartmentEdit();
  } catch (error) {
    if (Number(error?.status) === 409) {
      errorMessage.value = "钉钉组织或启用部门配置已更新，请重新加载后再保存。";
    } else {
      showFeedback(error instanceof Error ? error.message : "启用部门保存失败", "error");
    }
  } finally {
    savingEnabledDepartments.value = false;
  }
}

async function loadDepartmentData() {
  const requestSeq = ++departmentDataRequestSeq;
  departmentError.value = "";
  if (!selectedDepartment.value?.deptId) {
    departmentDetail.value = null; departmentEmployees.value = []; loadingDepartment.value = false;
    return;
  }
  loadingDepartment.value = true;
  departmentDetail.value = null;
  departmentEmployees.value = [];
  try {
    const deptId = selectedDepartment.value?.deptId;
    const params = { includeSubDepartments: includeSubDepartments.value ? 1 : 0, includeDepartments: 1, status: "在职", keyword: departmentKeyword.value.trim() };
    const fetchData = () => Promise.all([
      apiGet(`/api/org/departments/${deptId}`),
      apiGet(`/api/org/departments/${deptId}/employees`, params),
    ]);
    let [detailData, employeesData] = await fetchData();
    if (detailData?.orgRevision != null && employeesData.orgRevision != null && String(detailData.orgRevision) !== String(employeesData.orgRevision)) {
      [detailData, employeesData] = await fetchData();
      if (String(detailData.orgRevision) !== String(employeesData.orgRevision)) throw new Error("组织架构正在更新，请重新加载人员");
    }
    if (requestSeq === departmentDataRequestSeq && !workspaceUnmounted) {
      departmentDetail.value = detailData;
      departmentEmployees.value = employeesData.items || [];
    }
  } catch (error) {
    if (requestSeq === departmentDataRequestSeq) departmentError.value = error.message || "员工数据加载失败";
  } finally {
    if (requestSeq === departmentDataRequestSeq) loadingDepartment.value = false;
  }
}

function reloadOrganization() {
  const reload = () => { void loadDepartmentTree().then(loadDepartmentData); };
  if (confirmLeaveOrganizationSettings(reload)) reload();
}

function syncDirectoryQuery() {
  if (managementTab.value !== "department") return;
  const url = new URL(window.location.href);
  const state = { dept: selectedDepartment.value?.deptId, q: departmentKeyword.value.trim(), treeQ: treeKeyword.value.trim(), scope: "", children: includeSubDepartments.value ? "" : "0" };
  Object.entries(state).forEach(([key, value]) => { if (value !== "" && value != null) url.searchParams.set(key, value); else url.searchParams.delete(key); });
  window.history.replaceState(window.history.state, "", url);
}
function restoreDirectoryQuery() {
  if (managementTab.value !== "department") return;
  const query = new URLSearchParams(window.location.search);
  departmentKeyword.value = query.get("q") || "";
  treeKeyword.value = query.get("treeQ") || "";
  includeSubDepartments.value = query.get("children") !== "0";
  const department = findDepartment(organizationDepartmentTree.value, query.get("dept"));
  if (department) selectedDepartment.value = department;
}


async function loadEmployeeDirectory(force = false) {
  if (loadingEmployeeDirectory.value && !force) {
    return;
  }
  loadingEmployeeDirectory.value = true;
  errorMessage.value = "";
  try {
    const data = await apiGet("/api/org/employees", {
      status: "在职",
      includeDepartments: 1,
    });
    employeeDirectory.value = data.items || [];
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "员工目录加载失败";
  } finally {
    loadingEmployeeDirectory.value = false;
  }
}

async function loadInactiveData() {
  if (!canAccessInactiveEmployees.value) {
    inactiveEmployees.value = [];
    return;
  }
  loadingInactive.value = true;
  errorMessage.value = "";
  try {
    const data = await apiGet("/api/org/employees/inactive");
    inactiveEmployees.value = data.items || [];
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "离职人员加载失败";
  } finally {
    loadingInactive.value = false;
  }
}

async function loadProxyEmployees() {
  if (!canUseProxy.value) {
    proxyEmployees.value = [];
    return;
  }
  loadingProxyEmployees.value = true;
  errorMessage.value = "";
  try {
    const data = await apiGet("/api/auth/proxy/candidates", {
      keyword: proxyKeyword.value,
    });
    proxyEmployees.value = data.items || [];
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "代理员工加载失败";
  } finally {
    loadingProxyEmployees.value = false;
  }
}


function openEmployeeActionDialog(employee) {
  selectedEmployeeActionTarget.value = employee;
  employeeActionDialogOpen.value = true;
}

function closeEmployeeActionDialog() {
  if (accountStatusSavingUserId.value || proxyActionUserId.value) {
    return;
  }
  employeeActionDialogOpen.value = false;
  selectedEmployeeActionTarget.value = null;
}

async function handleEmployeeProxyAction() {
  const employee = selectedEmployeeActionTarget.value;
  if (!employee || !canUseProxy.value) {
    return;
  }
  employeeActionDialogOpen.value = false;
  selectedEmployeeActionTarget.value = null;
  await startProxy(employee);
}

function handleEmployeeAccountStatusAction() {
  const employee = selectedEmployeeActionTarget.value;
  if (!employee || !canManageEmployeeAccountStatus.value) return;
  accountTarget.value = { employee, accountStatus: employee.accountStatus === "启用" ? "禁用" : "启用" };
}
async function accountStatusSaved(result) {
  accountTarget.value = null;
  employeeActionDialogOpen.value = false;
  selectedEmployeeActionTarget.value = null;
  organizationActionDialogOpen.value = false;
  showFeedback(`已${result.accountStatus} ${result.count} 人，操作记录已保存`);
  await loadDepartmentData();
}

async function syncContacts() {
  if (!canSyncContacts.value) {
    showFeedback("只有组织架构管理员可以同步通讯录", "error");
    return;
  }
  syncingContacts.value = true;
  errorMessage.value = "";
  clearFeedback();
  try {
    let submittedFeedbackShown = false;
    const result = await runOrganizationSync({
      isCancelled: () => workspaceUnmounted,
      onProgress: (progress) => {
        syncRun.value = progress;
        if (progress?.status === "running" && !submittedFeedbackShown) {
          submittedFeedbackShown = true;
          showFeedback("同步任务已提交，正在后台读取钉钉通讯录...", "info");
        }
      },
    });
    if (!result) return;
    void refreshLastSyncTime();
    await loadDepartmentTree();
    const tasks = [loadDepartmentData()];
    if (managementTab.value === "inactive") {
      tasks.push(loadInactiveData());
    }
    await Promise.all(tasks);
    showFeedback(`同步完成：${result.departmentCount ?? 0} 个部门，${result.employeeCount ?? 0} 名员工，${result.membershipCount ?? 0} 条部门关系`);
  } catch (error) {
    showFeedback(error instanceof Error ? error.message : "同步失败", "error");
  } finally {
    syncingContacts.value = false;
    if (!workspaceUnmounted) void refreshLastSyncTime();
  }
}


function openOrganizationActionDialog() {
  if (!canOpenOrganizationActions.value) {
    showFeedback("当前账号没有组织操作权限", "error");
    return;
  }
  organizationActionDialogOpen.value = true;
  if (canSyncContacts.value) void refreshLastSyncTime();
}

function closeOrganizationActionDialog() {
  if (organizationActionRunning.value || organizationActivityOpen.value) {
    return;
  }
  organizationActionDialogOpen.value = false;
}

async function runOrganizationAction(action, skipLeaveCheck = false) {
  if (organizationActionRunning.value || accountSaving.value) return;
  if (action !== "sync") {
    if (canManageEmployeeAccountStatus.value) accountTarget.value = { accountStatus: action === "disableAll" ? "禁用" : "启用" };
    return;
  }
  if (!canSyncContacts.value) return;
  if (!skipLeaveCheck && !confirmLeaveOrganizationSettings(() => { void runOrganizationAction(action, true); })) return;
  finishEnabledDepartmentEdit();
  organizationActionRunning.value = action;
  organizationActionDialogOpen.value = false;
  try { await syncContacts(); }
  finally { organizationActionRunning.value = ""; }
}

function isDingTalkEnvironment() {
  const userAgent = navigator.userAgent || "";
  if (/dingtalk/i.test(userAgent)) {
    return true;
  }
  const loginType = String(session.value?.loginType || "").trim().toLowerCase();
  if (["workbench", "free", "silent"].includes(loginType)) {
    return true;
  }
  const platform = window.dd?.env?.platform || window.DingTalkPC?.env?.platform || "";
  return Boolean(platform && platform !== "notInDingTalk");
}

async function performLogout() {
  try {
    await logoutLoginSession();
    window.location.href = "/auth/";
  } catch (error) {
    showFeedback(error instanceof Error ? error.message : "退出失败，当前登录状态仍然保留", "error");
  }
}

function continueLogout() {
  if (!requestCompanyEntitiesLeave(() => { void performLogout(); })) return;
  void performLogout();
}

function logout() {
  if (!confirmLeaveOrganizationSettings(continueLogout)) return;
  continueLogout();
}

async function startProxy(employee) {
  const targetUserId = String(employee?.userId || "").trim();
  if (!targetUserId) {
    return;
  }
  if (targetUserId === currentSessionUserId.value) {
    showFeedback("当前已在该账号下，无需重复代理", "info");
    return;
  }
  if (targetUserId === actorSessionUserId.value) {
    showFeedback("原账号无需代理，请直接使用退出代理", "info");
    return;
  }
  selectedProxyEmployee.value = employee;
  proxyConfirmOpen.value = true;
}

function confirmProxyStart() {
  if (confirmLeaveOrganizationSettings(() => { void performProxyStart(); })) void performProxyStart();
}

async function performProxyStart() {
  const employee = selectedProxyEmployee.value;
  const targetUserId = String(employee?.userId || "").trim();
  if (!targetUserId) {
    proxyConfirmOpen.value = false;
    selectedProxyEmployee.value = null;
    return;
  }
  proxyActionUserId.value = targetUserId;
  errorMessage.value = "";
  try {
    const data = await apiPost("/api/auth/proxy/start", {
      userId: targetUserId,
    });
    const nextSession = {
      ...(session.value || {}),
      ...data,
    };
    session.value = nextSession;
    saveLoginSession(nextSession);
    navigateTo(APP_PATH);
  } catch (error) {
    showFeedback(error instanceof Error ? error.message : "代理登录失败", "error");
  } finally {
    proxyActionUserId.value = "";
    proxyConfirmOpen.value = false;
    selectedProxyEmployee.value = null;
  }
}

function closeProxyConfirm() {
  if (proxyActionUserId.value) {
    return;
  }
  proxyConfirmOpen.value = false;
  selectedProxyEmployee.value = null;
}

function getProxyButtonLabel(employee) {
  const targetUserId = String(employee?.userId || "").trim();
  if (!targetUserId) {
    return "代理";
  }
  if (proxyActionUserId.value === targetUserId) {
    return "处理中...";
  }
  if (targetUserId === currentSessionUserId.value) {
    return "当前账号";
  }
  if (targetUserId === actorSessionUserId.value) {
    return "原账号";
  }
  return "代理";
}

function isProxyButtonDisabled(employee) {
  const targetUserId = String(employee?.userId || "").trim();
  if (!targetUserId) {
    return true;
  }
  if (proxyActionUserId.value) {
    return true;
  }
  return targetUserId === currentSessionUserId.value || targetUserId === actorSessionUserId.value;
}

async function stopProxy() {
  if (!isProxying.value) {
    return;
  }
  proxyStopConfirmOpen.value = true;
}

async function confirmStopProxy() {
  proxyActionUserId.value = currentProxyUserId.value || "__stop__";
  errorMessage.value = "";
  try {
    const data = await apiPost("/api/auth/proxy/stop");
    const nextSession = {
      ...(session.value || {}),
      ...data,
    };
    session.value = nextSession;
    saveLoginSession(nextSession);
    window.location.reload();
  } catch (error) {
    showFeedback(error instanceof Error ? error.message : "退出代理失败", "error");
  } finally {
    proxyActionUserId.value = "";
    proxyStopConfirmOpen.value = false;
  }
}

function closeStopProxyConfirm() {
  if (proxyActionUserId.value) {
    return;
  }
  proxyStopConfirmOpen.value = false;
}

function confirmLeaveOrganizationSettings(continueAction) {
  const saveInProgress = managementTab.value === "department"
    ? savingEnabledDepartments.value
    : managementTab.value === "robot-messages" ? Boolean(robotMessagesPanel.value?.isSaveInProgress?.())
    : managementTab.value === "notifications" ? Boolean(notificationsPanel.value?.isSaveInProgress?.())
    : managementTab.value === "permissions" && Boolean(organizationSettingsPanel.value?.isSaveInProgress?.());
  if (saveInProgress || accountSaving.value) {
    showFeedback(ORGANIZATION_SETTINGS_SAVING_LEAVE_MESSAGE, "info");
    return false;
  }
  const hasPendingChanges = managementTab.value === "department"
    ? enabledDepartmentsDirty.value
    : managementTab.value === "robot-messages" ? Boolean(robotMessagesPanel.value?.hasPendingChanges?.())
    : managementTab.value === "notifications" ? Boolean(notificationsPanel.value?.hasPendingChanges?.())
    : managementTab.value === "permissions" && Boolean(organizationSettingsPanel.value?.hasPendingChanges?.());
  if (!hasPendingChanges) return true;
  pendingOrganizationLeaveAction = typeof continueAction === "function" ? continueAction : null;
  organizationLeaveConfirmOpen.value = true;
  return false;
}

function continueEditingOrganizationSettings() {
  pendingOrganizationLeaveAction = null;
  organizationLeaveConfirmOpen.value = false;
}

function discardOrganizationSettingsAndLeave() {
  const continueAction = pendingOrganizationLeaveAction;
  pendingOrganizationLeaveAction = null;
  organizationLeaveConfirmOpen.value = false;
  if (managementTab.value === "department") cancelEnabledDepartmentEdit();
  permissionSettingsDirty.value = false;
  robotSettingsDirty.value = false;
  if (typeof continueAction === "function") continueAction();
}

function handleOrganizationSettingsSavingChange(value) {
  const isSaving = Boolean(value);
  permissionSettingsSaving.value = isSaving;
}

function handleOrganizationSettingsDirtyChange(value) {
  permissionSettingsDirty.value = Boolean(value);
}

function redirectToLoginWithError(message) {
  clearLoginSession();
  const params = new URLSearchParams();
  if (message) {
    params.set("error", message);
  }
  window.location.href = params.toString() ? `/auth/?${params.toString()}` : "/auth/";
}

async function ensureSessionIsAllowed() {
  try {
    const validatedSession = await validateLoginSession(session.value);
    session.value = {
      ...(session.value || {}),
      ...validatedSession,
    };
    saveLoginSession(session.value);
    if ((managementTab.value === "inactive" && !canAccessInactiveEmployees.value)
      || (["permissions", "company-entities", "administrative-regions", "business-registry", "application-template"].includes(managementTab.value) && !canConfigurePermissions.value)) {
      openManagementSubPage("department");
    }
    return true;
  } catch (reason) {
    redirectToLoginWithError(reason instanceof Error ? reason.message : "登录已失效");
    return false;
  }
}

function requestCompanyEntitiesLeave(continueAction) {
  if (managementTab.value !== "company-entities") return true;
  const event = new CustomEvent(SETTINGS_COMPANY_ENTITIES_LEAVE_EVENT, {
    cancelable: true,
    detail: { continue: continueAction },
  });
  return window.dispatchEvent(event);
}

function commitManagementSubPage(tabId, { skipLeaveCheck = false } = {}) {
  const requestedTabId = tabId;
  if (tabId === "organization") {
    tabId = ["inactive", "company-entities", "administrative-regions", "business-registry", "application-template", "robot-messages", "notifications"].includes(managementTab.value) ? "department" : managementTab.value;
  }
  if (tabId === "inactive" && !canAccessInactiveEmployees.value) {
    tabId = "department";
  }
  if (tabId === "permissions" && !canConfigurePermissions.value) tabId = "department";
  if (tabId === "company-entities" && !canConfigurePermissions.value) tabId = "department";
  if (tabId === "administrative-regions" && !canConfigurePermissions.value) tabId = "department";
  if (tabId === "business-registry" && !canConfigurePermissions.value) tabId = "department";
  if (tabId === "application-template" && !canConfigurePermissions.value) tabId = "department";
  if (
    tabId !== managementTab.value
    && !skipLeaveCheck
    && !confirmLeaveOrganizationSettings(() => commitManagementSubPage(requestedTabId, { skipLeaveCheck: true }))
  ) {
    return;
  }
  if (tabId !== managementTab.value && managementTab.value === "department" && editingEnabledDepartments.value) {
    finishEnabledDepartmentEdit();
  }
  if (tabId !== managementTab.value) clearFeedback();
  const pathMap = {
    department: SETTINGS_ORGANIZATION_PATH,
    permissions: SETTINGS_ORGANIZATION_PERMISSIONS_PATH,
    inactive: SETTINGS_HANDOVER_PATH,
    "company-entities": SETTINGS_COMPANY_ENTITIES_PATH,
    "administrative-regions": SETTINGS_ADMINISTRATIVE_REGIONS_PATH,
    "business-registry": SETTINGS_BUSINESS_REGISTRY_PATH,
    "robot-messages": SETTINGS_ROBOT_MESSAGES_PATH,
    notifications: SETTINGS_NOTIFICATIONS_PATH,
    "application-template": SETTINGS_APPLICATION_TEMPLATE_PATH,
  };
  const path = pathMap[tabId] || SETTINGS_ORGANIZATION_PATH;
  if (window.location.pathname.replace(/\/+$/, "") === path) {
    managementTab.value = tabId;
    return;
  }
  managementTab.value = tabId;
  navigateTo(path, { replace: true });
}

function openManagementSubPage(tabId) {
  if (managementTab.value === "company-entities" && tabId !== "company-entities") {
    if (!requestCompanyEntitiesLeave(() => commitManagementSubPage(tabId))) return;
  }
  commitManagementSubPage(tabId);
}

function openManagementLink({ item, event }) {
  if (item.id !== "application-template") return;
  const opening = openApplicationTemplateTab(event);
  if (opening) {
    errorMessage.value = "";
    opening.catch(reason => { if (!workspaceUnmounted) showFeedback(reason.message, "error"); });
  }
}

watch(() => props.initialManagementTab, (tab) => {
  if (!["department", "permissions", "inactive", "company-entities", "administrative-regions", "business-registry", "application-template", "robot-messages", "notifications"].includes(tab)) return;
  if (managementTab.value === "department" && tab !== "department" && editingEnabledDepartments.value) {
    cancelEnabledDepartmentEdit();
  }
  managementTab.value = tab;
});

watch(
  [enabledDepartmentsDirty, permissionSettingsDirty, robotSettingsDirty],
  ([enabledDirty, permissionDirty, robotDirty]) => emit("dirty-change", enabledDirty || permissionDirty || robotDirty),
  { immediate: true },
);

watch(
  [savingEnabledDepartments, permissionSettingsSaving, accountSaving, robotSettingsSaving],
  ([enabledSaving, permissionSaving, accountBusy, robotBusy]) => emit("saving-change", enabledSaving || permissionSaving || accountBusy || robotBusy),
  { immediate: true },
);

watch(
  () => selectedDepartment.value?.deptId,
  () => {
    if (skipNextDepartmentWatch) {
      skipNextDepartmentWatch = false;
      return;
    }
    loadDepartmentData();
  },
);

watch(includeSubDepartments, () => {
  loadDepartmentData();
});

watch([departmentKeyword, treeKeyword, includeSubDepartments, () => selectedDepartment.value?.deptId], syncDirectoryQuery);

watch(departmentKeyword, () => {
  ++departmentDataRequestSeq;
  loadingDepartment.value = true;
  if (departmentKeywordTimer !== null) {
    window.clearTimeout(departmentKeywordTimer);
  }
  departmentKeywordTimer = window.setTimeout(() => {
    departmentKeywordTimer = null;
    loadDepartmentData();
  }, 300);
});

watch(managementTab, (tab) => {
  if (tab === "department") {
    syncDirectoryQuery();
    if (canSyncContacts.value) void refreshLastSyncTime();
    if (!departmentTree.value.length) {
      void loadDepartmentTree().then(loadDepartmentData);
      return;
    }
    void loadDepartmentData();
    return;
  }
  if (tab === "inactive") {
    if (!canAccessInactiveEmployees.value) {
      managementTab.value = "department";
      return;
    }
    loadInactiveData();
    return;
  }
});

onMounted(async () => {
  workspaceUnmounted = false;
  const allowed = await ensureSessionIsAllowed();
  if (!allowed) {
    return;
  }
  syncStatusTimer = window.setInterval(() => { if (managementTab.value === "department" && canSyncContacts.value && !document.hidden) void refreshLastSyncTime(); }, 15000);
  window.addEventListener("popstate", restoreDirectoryQuery);
  if (["company-entities", "administrative-regions", "business-registry", "application-template", "robot-messages", "notifications"].includes(managementTab.value)) return;
  if (canSyncContacts.value) void refreshLastSyncTime();
  await loadDepartmentTree();
  const tasks = [
    loadDepartmentData(),
  ];
  if (managementTab.value === "inactive" && canAccessInactiveEmployees.value) {
    tasks.push(loadInactiveData());
  }
  await Promise.all(tasks);
});

onBeforeUnmount(() => {
  workspaceUnmounted = true;
  ++departmentDataRequestSeq;
  window.clearInterval(syncStatusTimer);
  window.removeEventListener("popstate", restoreDirectoryQuery);
  if (departmentKeywordTimer !== null) {
    window.clearTimeout(departmentKeywordTimer);
  }
  emit("dirty-change", false);
  emit("saving-change", false);
});
</script>

<template>
  <PlatformActionToast v-bind="feedback" @close="clearFeedback" />
  <div class="auth-org-surface h-full min-h-0 overflow-hidden bg-slate-100 text-slate-900">

    <div class="settings-workspace-body flex h-full min-h-0">
      <PlatformSidebar
        fixed
        module-title="后台管理"
        :module-icon="ShieldCheck"
        :sections="managementSections"
        :active-item-id="activeSidebarItemId"
        @item-click="openManagementSubPage($event.id)"
        @link-click="openManagementLink"
      />

    <main class="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden md:pl-[216px]">
      <nav v-if="standalonePage" class="flex h-12 shrink-0 items-center border-b border-slate-200 bg-white px-3" :aria-label="`${standalonePage.label}页面`">
        <div role="tablist" :aria-label="`${standalonePage.label}页面`">
          <button
            :id="standalonePage.tabId"
            type="button"
            role="tab"
            aria-selected="true"
            :aria-controls="standalonePage.panelId"
            class="inline-flex h-8 items-center rounded-md bg-slate-900 px-3 text-sm font-medium text-white"
          >{{ standalonePage.label }}</button>
        </div>
      </nav>
      <SettingsOrganizationTabs
        v-else-if="!['robot-messages', 'notifications'].includes(managementTab)"
        department-label="部门与成员"
        :active-tab="managementTab"
        :disabled="organizationSettingsSaving"
        :show-permissions="canConfigurePermissions"
        :show-handover="canAccessInactiveEmployees"
        @select="openManagementSubPage"
      />
      <section class="flex min-h-0 flex-1 flex-col p-3 sm:p-4" :class="[contentClass, { 'notification-page-content': managementTab === 'notifications' }]">
        <div v-if="errorMessage" role="alert" class="mb-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {{ errorMessage }}
          <button v-if="managementTab === 'department' && errorMessage.includes('重新加载')" type="button" class="ml-3 font-semibold underline" @click="reloadOrganization">重新加载配置</button>
        </div>

        <div class="flex min-h-0 flex-1 flex-col gap-4">
          <section
            id="auth-dingtalk-organization-panel"
            v-show="managementTab === 'department'"
            class="flex min-h-0 min-w-0 flex-1"
            role="tabpanel"
            aria-labelledby="auth-dingtalk-organization-tab"
          >
            <SettingsOrganizationPanel
              v-if="managementTab === 'department'"
              :can-open-organization-actions="canOpenOrganizationActions"
              :organization-action-running="organizationActionRunning"
              :department-tree="organizationDepartmentTree"
              :selected-department="selectedDepartment"
              :expanded-dept-ids="expandedDeptIds"
              :selected-department-name="selectedDepartmentName"
              :department-employees="departmentEmployees"
              :selected-manager="selectedManager"
              :managers="selectedManagers"
              :department-path="selectedDepartmentPath"
              :direct-employee-count="departmentDetail?.directEmployeeCount ?? null"
              :subtree-employee-count="departmentDetail?.subtreeEmployeeCount ?? null"
              :error-message="departmentError"
              :tree-error="treeError"
              :loading-tree="loadingTree"
              :tree-keyword="treeKeyword"
              @retry="loadDepartmentData"
              @retry-tree="reloadOrganization"
              @update-tree-keyword="treeKeyword = $event"
              :include-sub-departments="includeSubDepartments"
              :department-keyword="departmentKeyword"
              :loading-department="loadingDepartment"
              :sorted-department-employees="sortedDepartmentEmployees"
              :can-operate-department-employee="canOperateDepartmentEmployee"
              :account-status-saving-user-id="accountStatusSavingUserId"
              :proxy-action-user-id="proxyActionUserId"
              :primary-department-name="getPrimaryDepartmentName"
              :show-disabled-departments="showDisabledDepartments"
              :can-manage-enabled-departments="canManageEnabledDepartments"
              :editing-enabled-departments="editingEnabledDepartments"
              :enabled-department-ids="[...enabledDepartmentIds]"
              :enabled-departments-dirty="enabledDepartmentsDirty"
              :loading-enabled-departments="loadingEnabledDepartments || syncingContacts"
              :saving-enabled-departments="savingEnabledDepartments"
              @open-organization-action="openOrganizationActionDialog"
              @select-department="selectDepartment"
              @toggle-department="toggleExpanded"
              @update-include-sub-departments="includeSubDepartments = $event"
              @update-department-keyword="departmentKeyword = $event"
              @open-employee-action="openEmployeeActionDialog"
              @update-show-disabled-departments="setShowDisabledDepartments"
              @update-department-enabled="setDepartmentEnabled"
              @start-enabled-departments-edit="startEnabledDepartmentEdit"
              @cancel-enabled-departments-edit="cancelEnabledDepartmentEdit"
              @save-enabled-departments="saveEnabledDepartments"
            />
          </section>

          <section
            id="auth-permissions-panel"
            v-show="managementTab === 'permissions'"
            class="flex min-h-0 min-w-0 flex-1"
            role="tabpanel"
            aria-labelledby="auth-permissions-tab"
          >
            <SettingsOrganizationPermissionsPanel
              v-if="managementTab === 'permissions'"
              ref="organizationSettingsPanel"
              @dirty-change="handleOrganizationSettingsDirtyChange"
              @saving-change="handleOrganizationSettingsSavingChange"
            />
          </section>

          <SettingsHandoverPanel
            id="auth-handover-panel"
            v-if="managementTab === 'inactive'"
            role="tabpanel"
            aria-labelledby="auth-handover-tab"
            :inactive-keyword="inactiveKeyword"
            :loading-inactive="loadingInactive"
            :filtered-inactive-employees="filteredInactiveEmployees"
            @update-inactive-keyword="inactiveKeyword = $event"
          />

          <SettingsCompanyEntitiesPanel
            v-if="managementTab === 'company-entities' && canConfigurePermissions"
            @dirty-change="emit('dirty-change', $event)"
            @saving-change="emit('saving-change', $event)"
          />

          <SettingsApplicationTemplateEntry
            v-if="managementTab === 'application-template' && canConfigurePermissions"
          />

          <SettingsRobotMessagesPanel
            v-if="managementTab === 'robot-messages'" ref="robotMessagesPanel"
            @dirty-change="robotSettingsDirty = Boolean($event)" @saving-change="robotSettingsSaving = Boolean($event)"
          />

          <SettingsNotificationsPanel
            v-if="managementTab === 'notifications'" ref="notificationsPanel"
            @dirty-change="emit('dirty-change', $event)" @saving-change="emit('saving-change', $event)"
          />

          <SettingsBusinessRegistryPanel
            v-if="managementTab === 'business-registry' && canConfigurePermissions"
          />

          <SettingsAdministrativeRegionsPanel
            v-if="managementTab === 'administrative-regions' && canConfigurePermissions"
          />
        </div>
      </section>
    </main>
    </div>

    <div
      v-if="organizationActionDialogOpen"
      :inert="accountTarget || organizationLeaveConfirmOpen || organizationActivityOpen ? true : undefined"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/55"
      v-backdrop-dismiss="closeOrganizationActionDialog"
    >
      <div
        ref="organizationActionPanel" tabindex="-1"
        class="flex max-h-[calc(100dvh-2rem)] w-[420px] flex-col overflow-hidden rounded-lg bg-white shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="organization-action-dialog-title"
        @click.stop
      >
        <div class="flex shrink-0 items-center justify-between border-b border-slate-200 px-5 py-4">
          <span id="organization-action-dialog-title" class="text-sm text-slate-900">操作</span>
          <button type="button" class="text-slate-400 hover:text-slate-600" aria-label="关闭操作窗口" @click="closeOrganizationActionDialog">
            <X class="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <div class="min-h-0 space-y-3 overflow-y-auto px-5 py-5">
          <SettingsOrganizationActivity
            :last-sync-label="lastSyncLabel" :sync-run="syncRun" :sync-status="syncStatus" :busy="organizationSettingsSaving || syncingContacts"
            :can-sync="canSyncContacts" :can-manage-accounts="canManageEmployeeAccountStatus"
            @sync="runOrganizationAction('sync')" @refresh="refreshLastSyncTime" @drawer-change="organizationActivityOpen = $event" />
          <button
            v-if="canManageEmployeeAccountStatus"
            class="desktop-action-option desktop-action-option-danger"
            :disabled="Boolean(organizationActionRunning)"
            @click="runOrganizationAction('disableAll')"
          >
            <div class="desktop-action-option-main">
              <div class="desktop-action-option-icon">
                <UserX class="h-4 w-4" />
              </div>
              <div class="desktop-action-option-copy">
                <span class="desktop-action-option-title">全部禁用</span>
                <span class="desktop-action-option-meta">批量禁用全部在职账号</span>
              </div>
            </div>
            <span class="desktop-action-option-state">{{ organizationActionRunning === "disableAll" ? "处理中" : "执行" }}</span>
          </button>
          <button
            v-if="canManageEmployeeAccountStatus"
            class="desktop-action-option desktop-action-option-success"
            :disabled="Boolean(organizationActionRunning)"
            @click="runOrganizationAction('enableAll')"
          >
            <div class="desktop-action-option-main">
              <div class="desktop-action-option-icon">
                <ShieldCheck class="h-4 w-4" />
              </div>
              <div class="desktop-action-option-copy">
                <span class="desktop-action-option-title">全部启用</span>
                <span class="desktop-action-option-meta">批量恢复全部在职账号</span>
              </div>
            </div>
            <span class="desktop-action-option-state">{{ organizationActionRunning === "enableAll" ? "处理中" : "执行" }}</span>
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="employeeActionDialogOpen && selectedEmployeeActionTarget"
      :inert="accountTarget ? true : undefined"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/55"
      v-backdrop-dismiss="closeEmployeeActionDialog"
    >
      <div ref="employeeActionPanel" tabindex="-1" role="dialog" aria-modal="true" aria-labelledby="employee-action-title" class="w-[420px] rounded-lg bg-white shadow-xl" @click.stop>
        <div class="border-b border-slate-200 px-5 py-4">
          <div id="employee-action-title" class="text-sm text-slate-900">员工操作</div>
          <div class="mt-1 text-xs text-slate-500">
            {{ selectedEmployeeActionTarget.name }}（{{ selectedEmployeeActionTarget.userId }}）
          </div>
        </div>
        <div class="space-y-3 px-5 py-5">
          <button
            v-if="canUseProxy"
            class="desktop-action-option desktop-action-option-sync"
            :disabled="isProxyButtonDisabled(selectedEmployeeActionTarget)"
            @click="handleEmployeeProxyAction"
          >
            <div class="desktop-action-option-main">
              <div class="desktop-action-option-icon">
                <UserRoundX class="h-4 w-4" />
              </div>
              <div class="desktop-action-option-copy">
                <span class="desktop-action-option-title">代理</span>
                <span class="desktop-action-option-meta">切换进入该员工账号</span>
              </div>
            </div>
            <span class="desktop-action-option-state">{{ getProxyButtonLabel(selectedEmployeeActionTarget) }}</span>
          </button>
          <button
            v-if="canManageEmployeeAccountStatus"
            class="desktop-action-option"
            :class="selectedEmployeeActionTarget.accountStatus === '启用' ? 'desktop-action-option-danger' : 'desktop-action-option-success'"
            :disabled="accountStatusSavingUserId === selectedEmployeeActionTarget.userId"
            @click="handleEmployeeAccountStatusAction"
          >
            <div class="desktop-action-option-main">
              <div class="desktop-action-option-icon">
                <UserX v-if="selectedEmployeeActionTarget.accountStatus === '启用'" class="h-4 w-4" />
                <ShieldCheck v-else class="h-4 w-4" />
              </div>
              <div class="desktop-action-option-copy">
                <span class="desktop-action-option-title">{{ selectedEmployeeActionTarget.accountStatus === "启用" ? "停用" : "启用" }}</span>
                <span class="desktop-action-option-meta">当前账号状态：{{ selectedEmployeeActionTarget.accountStatus }}</span>
              </div>
            </div>
            <span class="desktop-action-option-state">
              {{ accountStatusSavingUserId === selectedEmployeeActionTarget.userId ? "处理中" : "执行" }}
            </span>
          </button>
        </div>
      </div>
    </div>

    <div v-if="proxyConfirmOpen" :inert="organizationLeaveConfirmOpen ? true : undefined" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" v-backdrop-dismiss="closeProxyConfirm">
      <div class="w-[420px] rounded-lg bg-white shadow-xl" @click.stop>
        <div class="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <span class="text-sm text-slate-900">确认代理</span>
          <button class="text-slate-400 hover:text-slate-600" @click="closeProxyConfirm">
            <X class="h-4 w-4" />
          </button>
        </div>
        <div class="px-5 py-5 text-sm text-slate-700">
          确认代理登录
          <span class="font-medium text-slate-900">
            {{ selectedProxyEmployee?.displayName || selectedProxyEmployee?.name || "-" }}
          </span>
          吗？
        </div>
        <div class="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button class="rounded-lg px-4 py-1.5 text-sm text-slate-600 hover:bg-slate-100" :disabled="Boolean(proxyActionUserId)" @click="closeProxyConfirm">
            取消
          </button>
          <button class="rounded-lg bg-sky-600 px-4 py-1.5 text-sm text-white hover:bg-sky-700" :disabled="Boolean(proxyActionUserId)" @click="confirmProxyStart">
            {{ proxyActionUserId ? "处理中..." : "确认代理" }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="proxyStopConfirmOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" v-backdrop-dismiss="closeStopProxyConfirm">
      <div class="w-[420px] rounded-lg bg-white shadow-xl" @click.stop>
        <div class="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <span class="text-sm text-slate-900">退出代理</span>
          <button class="text-slate-400 hover:text-slate-600" @click="closeStopProxyConfirm">
            <X class="h-4 w-4" />
          </button>
        </div>
        <div class="px-5 py-5 text-sm text-slate-700">
          确认退出代理并返回原账号
          <span class="font-medium text-slate-900">{{ session?.actorDisplay || "-" }}</span>
          吗？
        </div>
        <div class="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button class="rounded-lg px-4 py-1.5 text-sm text-slate-600 hover:bg-slate-100" :disabled="Boolean(proxyActionUserId)" @click="closeStopProxyConfirm">
            取消
          </button>
          <button class="rounded-lg bg-amber-600 px-4 py-1.5 text-sm text-white hover:bg-amber-700" :disabled="Boolean(proxyActionUserId)" @click="confirmStopProxy">
            {{ proxyActionUserId ? "处理中..." : "确认退出" }}
          </button>
        </div>
      </div>
    </div>

    <SettingsAccountStatusDialog :target="accountTarget" @close="accountTarget = null" @saved="accountStatusSaved" @busy-change="accountSaving = $event" />
    <SettingsUnsavedChangesDialog
      :open="organizationLeaveConfirmOpen"
      @cancel="continueEditingOrganizationSettings"
      @confirm="discardOrganizationSettingsAndLeave"
    />

  </div>
</template>

<style scoped>
.settings-workspace-body {
  padding-top: var(--platform-shell-top-inset, 0px);
}

@media (min-width: 768px) {
  .notification-page-content {
    padding: 0;
  }
}

.scrollbar-hidden {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.scrollbar-hidden::-webkit-scrollbar {
  display: none;
}

:deep(.desktop-action-option) {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 1.15rem;
  padding: 0.95rem 1rem;
  text-align: left;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.98));
  box-shadow: 0 12px 28px rgba(148, 163, 184, 0.1);
  transition:
    transform 160ms ease,
    box-shadow 160ms ease,
    border-color 160ms ease,
    background-color 160ms ease;
}

:deep(.desktop-action-option:hover:not(:disabled)) {
  transform: translateY(-1px);
  box-shadow: 0 18px 34px rgba(148, 163, 184, 0.16);
}

:deep(.desktop-action-option:disabled) {
  cursor: not-allowed;
  opacity: 0.68;
  transform: none;
}

:deep(.desktop-action-option-main) {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.9rem;
}

:deep(.desktop-action-option-icon) {
  display: inline-flex;
  height: 2.4rem;
  width: 2.4rem;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 0.95rem;
}

:deep(.desktop-action-option-copy) {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
}

:deep(.desktop-action-option-title) {
  font-size: 0.95rem;
  font-weight: 600;
  color: rgb(15 23 42);
}

:deep(.desktop-action-option-meta) {
  font-size: 0.74rem;
  color: rgb(100 116 139);
}

:deep(.desktop-action-option-state) {
  flex-shrink: 0;
  border-radius: 999px;
  padding: 0.4rem 0.7rem;
  font-size: 0.74rem;
  font-weight: 600;
}

:deep(.desktop-action-option-sync) {
  border-color: rgba(186, 230, 253, 0.9);
  background: linear-gradient(180deg, rgba(240, 249, 255, 0.98), rgba(239, 246, 255, 0.94));
}

:deep(.desktop-action-option-sync .desktop-action-option-icon) {
  background: rgba(224, 242, 254, 0.96);
  color: rgb(3 105 161);
}

:deep(.desktop-action-option-sync .desktop-action-option-state) {
  background: rgba(224, 242, 254, 0.95);
  color: rgb(3 105 161);
}

:deep(.desktop-action-option-danger) {
  border-color: rgba(254, 205, 211, 0.92);
  background: linear-gradient(180deg, rgba(255, 241, 242, 0.98), rgba(255, 245, 245, 0.94));
}

:deep(.desktop-action-option-danger .desktop-action-option-icon) {
  background: rgba(255, 228, 230, 0.96);
  color: rgb(190 24 93);
}

:deep(.desktop-action-option-danger .desktop-action-option-state) {
  background: rgba(255, 228, 230, 0.95);
  color: rgb(190 24 93);
}

:deep(.desktop-action-option-success) {
  border-color: rgba(187, 247, 208, 0.92);
  background: linear-gradient(180deg, rgba(240, 253, 244, 0.98), rgba(236, 253, 245, 0.94));
}

:deep(.desktop-action-option-success .desktop-action-option-icon) {
  background: rgba(220, 252, 231, 0.96);
  color: rgb(21 128 61);
}

:deep(.desktop-action-option-success .desktop-action-option-state) {
  background: rgba(220, 252, 231, 0.95);
  color: rgb(21 128 61);
}

</style>
