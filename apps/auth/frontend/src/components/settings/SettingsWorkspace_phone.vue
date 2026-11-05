<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  Building2,
  RefreshCw,
  ShieldCheck,
  UserRoundX,
  UserX,
  X,
} from "@lucide/vue";
import {
  APP_PATH,
  SETTINGS_HANDOVER_PATH,
  SETTINGS_ORGANIZATION_PATH,
  SETTINGS_ORGANIZATION_PERMISSIONS_PATH,
} from "@/config";
import { apiGet, apiPost } from "@/api";
import { runOrganizationSync } from "@/organization-sync";
import { useOrganizationSyncTime } from "@/use-organization-sync-time";
import { employeeMatchesDirectoryKeyword } from "@/directory-search";
import { markMobileBackHandled, MOBILE_BACK_REQUEST_EVENT, MOBILE_CLOSE_PAGE_PICKERS_EVENT, MOBILE_MENU_EVENT, navigateTo } from "@/router-lite";
import SettingsHandoverPanel from "@/components/settings/SettingsHandoverPanel_phone.vue";
import SettingsOrganizationPanel from "@/components/settings/SettingsOrganizationPanel_phone.vue";
import SettingsOrganizationTabs from "@/components/settings/SettingsOrganizationTabs.vue";
import SettingsOrganizationPermissionsPanel from "@/components/settings/SettingsOrganizationPermissionsPanel.vue";
import { clearLoginSession, loadLoginSession, logoutLoginSession, saveLoginSession, validateLoginSession } from "@/session";


const props = defineProps({
  initialManagementTab: {
    type: String,
    default: "department",
  },
});
const emit = defineEmits(["dirty-change", "saving-change"]);

const managementTab = ref(
  ["department", "permissions", "inactive"].includes(props.initialManagementTab)
    ? props.initialManagementTab
    : "department",
);
const session = ref(loadLoginSession());
const organizationSettingsPanel = ref(null);
const organizationSettingsSaving = ref(false);
const mobilePagePickerOpen = ref(false);

const loadingTree = ref(false);
const loadingDepartment = ref(false);
const loadingEmployeeDirectory = ref(false);
const loadingInactive = ref(false);
const syncingContacts = ref(false);
const { lastSyncLabel, refreshLastSyncTime } = useOrganizationSyncTime();
const organizationActionDialogOpen = ref(false);
const organizationActionRunning = ref("");
const accountStatusSavingUserId = ref("");
const errorMessage = ref("");
const statusMessage = ref("");

const departmentTree = ref([]);
const selectedDepartmentId = ref("");
const departmentPickerParentId = ref(null);
const departmentDetail = ref(null);
const departmentEmployees = ref([]);
const includeSubDepartments = ref(true);
const departmentKeyword = ref("");

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
const ORGANIZATION_SETTINGS_SAVING_LEAVE_MESSAGE = "组织配置正在保存，请等待保存完成后再离开";

const isProxying = computed(() => Boolean(session.value?.isProxying));
const canConfigurePermissions = computed(() => Boolean(session.value?.isFullAccessUser) && !isProxying.value);
const canSyncContacts = computed(() => Boolean(session.value?.canSyncContacts) && !isProxying.value);
const canManageEmployeeAccountStatus = computed(() => Boolean(session.value?.canManageEmployeeAccountStatus) && !isProxying.value);
const canAccessInactiveEmployees = computed(() => Boolean(session.value?.canAccessInactiveEmployees) && !isProxying.value);
const canUseProxy = computed(() => Boolean(session.value?.canStartProxy || session.value?.canSwitchProxy));
const canOpenOrganizationActions = computed(() => canSyncContacts.value || canManageEmployeeAccountStatus.value);
const canOperateDepartmentEmployee = computed(() => canManageEmployeeAccountStatus.value || canUseProxy.value);
const canShowLogout = computed(() => !isDingTalkEnvironment());

function flattenDepartmentTree(nodes, depth = 0, items = []) {
  nodes.forEach((node) => {
    items.push({
      deptId: node.deptId,
      name: node.name,
      pinyinInitials: node.pinyinInitials || "",
      depth,
    });
    flattenDepartmentTree(node.children || [], depth + 1, items);
  });
  return items;
}

function buildDepartmentMaps(nodes, parentId = null, maps = { nodesById: new Map(), parentById: new Map() }) {
  nodes.forEach((node) => {
    const nodeId = String(node.deptId);
    maps.nodesById.set(nodeId, node);
    maps.parentById.set(nodeId, parentId === null ? null : String(parentId));
    buildDepartmentMaps(node.children || [], node.deptId, maps);
  });
  return maps;
}

function getDepartmentPathNodes(nodeId, maps) {
  const path = [];
  let currentId = nodeId;
  while (currentId) {
    const node = maps.nodesById.get(currentId);
    if (!node) {
      break;
    }
    path.unshift(node);
    currentId = maps.parentById.get(currentId);
  }
  return path;
}

const flatDepartments = computed(() => flattenDepartmentTree(departmentTree.value));
const departmentMaps = computed(() => buildDepartmentMaps(departmentTree.value));
const selectedDepartment = computed(() => departmentMaps.value.nodesById.get(String(selectedDepartmentId.value)) || null);
const selectedDepartmentPath = computed(() => getDepartmentPathNodes(String(selectedDepartmentId.value || ""), departmentMaps.value));
const selectedDepartmentHasChildren = computed(() => Boolean(selectedDepartment.value?.children?.length));
const departmentPickerOptions = computed(() => {
  if (departmentPickerParentId.value === "__root__") {
    return departmentTree.value;
  }
  if (departmentPickerParentId.value === null) {
    return [];
  }
  const parentNode = departmentMaps.value.nodesById.get(String(departmentPickerParentId.value));
  return parentNode?.children || [];
});
const selectedManager = computed(() => departmentDetail.value?.manager || null);
const sortedDepartmentEmployees = computed(() => {
  const managerUserId = String(selectedManager.value?.userId || "").trim();
  const items = [...departmentEmployees.value];
  if (!managerUserId) {
    return items;
  }
  return items.sort((left, right) => {
    const leftIsManager = left.userId === managerUserId ? 0 : 1;
    const rightIsManager = right.userId === managerUserId ? 0 : 1;
    if (leftIsManager !== rightIsManager) {
      return leftIsManager - rightIsManager;
    }
    return String(left.userId || "").localeCompare(String(right.userId || ""));
  });
});
const managementTabs = computed(() => {
  return [
    { id: "organization", label: "组织架构", path: SETTINGS_ORGANIZATION_PATH, icon: Building2 },
  ];
});

const activeSidebarItemId = "organization";
const filteredInactiveEmployees = computed(() => {
  return inactiveEmployees.value.filter((employee) => employeeMatchesDirectoryKeyword(employee, inactiveKeyword.value));
});

const currentProxyUserId = computed(() => (isProxying.value ? session.value?.userId || "" : ""));
const currentSessionUserId = computed(() => session.value?.userId || "");
const actorSessionUserId = computed(() => session.value?.actorUserId || session.value?.userId || "");
const currentProxyDisplay = computed(() => session.value?.nick || session.value?.name || session.value?.userId || "-");
const actorDisplay = computed(() => session.value?.actorDisplay || session.value?.actorName || session.value?.actorUserId || "-");

let skipNextDepartmentWatch = false;
let departmentKeywordTimer = null;
let departmentDataRequestSeq = 0;
let workspaceUnmounted = false;

function getPrimaryDepartmentName(employee) {
  const departments = employee.departments || [];
  if (!departments.length) {
    return "-";
  }
  return departments.map((item) => item.name).join(" / ");
}

function openDepartmentLevelPicker(parentId) {
  departmentPickerParentId.value = parentId;
}

function openDepartmentSiblingPicker(deptId) {
  const parentId = departmentMaps.value.parentById.get(String(deptId));
  departmentPickerParentId.value = parentId === null ? "__root__" : parentId;
}

function selectDepartmentFromPicker(deptId) {
  selectedDepartmentId.value = String(deptId);
  departmentPickerParentId.value = null;
}

async function loadDepartmentTree() {
  loadingTree.value = true;
  try {
    const data = await apiGet("/api/org/departments/tree");
    departmentTree.value = data.items || [];
    if (!selectedDepartmentId.value && flatDepartments.value.length) {
      skipNextDepartmentWatch = true;
      selectedDepartmentId.value = String(flatDepartments.value[0].deptId);
    }
  } finally {
    loadingTree.value = false;
  }
}

async function loadDepartmentData() {
  const departmentId = String(selectedDepartment.value?.deptId || selectedDepartmentId.value || "");
  if (!departmentId) {
    departmentDetail.value = null;
    departmentEmployees.value = [];
    return;
  }

  const requestSeq = departmentDataRequestSeq + 1;
  departmentDataRequestSeq = requestSeq;
  loadingDepartment.value = true;
  errorMessage.value = "";
  try {
    const [detailData, employeesData] = await Promise.all([
      apiGet(`/api/org/departments/${departmentId}`),
      apiGet(`/api/org/departments/${departmentId}/employees`, {
        includeSubDepartments: includeSubDepartments.value ? 1 : 0,
        includeDepartments: 1,
        status: "在职",
        keyword: departmentKeyword.value,
      }),
    ]);
    if (requestSeq === departmentDataRequestSeq) {
      departmentDetail.value = detailData;
      departmentEmployees.value = employeesData.items || [];
    }
  } catch (error) {
    if (requestSeq === departmentDataRequestSeq) {
      errorMessage.value = error instanceof Error ? error.message : "员工数据加载失败";
    }
  } finally {
    if (requestSeq === departmentDataRequestSeq) {
      loadingDepartment.value = false;
    }
  }
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

async function toggleEmployeeAccountStatus(employee) {
  if (!canManageEmployeeAccountStatus.value) {
    errorMessage.value = "只有组织架构管理员可以启用或禁用账号";
    return;
  }
  accountStatusSavingUserId.value = employee.userId;
  errorMessage.value = "";
  try {
    await apiPost(`/api/org/employees/${encodeURIComponent(employee.userId)}/account-status`, {
      accountStatus: employee.accountStatus === "启用" ? "禁用" : "启用",
    });
    await Promise.all([loadDepartmentData(), loadEmployeeDirectory(true)]);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "账号状态更新失败";
  } finally {
    accountStatusSavingUserId.value = "";
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

async function handleEmployeeAccountStatusAction() {
  const employee = selectedEmployeeActionTarget.value;
  if (!employee || !canManageEmployeeAccountStatus.value) {
    return;
  }
  try {
    await toggleEmployeeAccountStatus(employee);
    employeeActionDialogOpen.value = false;
    selectedEmployeeActionTarget.value = null;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "账号状态更新失败";
  }
}

async function syncContacts() {
  if (!canSyncContacts.value) {
    errorMessage.value = "只有组织架构管理员可以同步通讯录";
    return;
  }
  syncingContacts.value = true;
  errorMessage.value = "";
  statusMessage.value = "";
  try {
    const result = await runOrganizationSync({
      isCancelled: () => workspaceUnmounted,
      onProgress: (syncRun) => {
        if (syncRun?.status === "running") {
          statusMessage.value = "同步任务已提交，正在后台读取钉钉通讯录...";
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
    statusMessage.value = `同步完成：${result.departmentCount ?? 0} 个部门，${result.employeeCount ?? 0} 名员工，${result.membershipCount ?? 0} 条部门关系`;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "同步失败";
    statusMessage.value = "";
  } finally {
    syncingContacts.value = false;
  }
}

async function updateAllEmployeeAccountStatus(accountStatus) {
  if (!canManageEmployeeAccountStatus.value) {
    errorMessage.value = "只有组织架构管理员可以批量启用或禁用账号";
    return;
  }
  errorMessage.value = "";
  await apiPost("/api/org/employees/account-status/bulk", {
    accountStatus,
  });
  await Promise.all([
    loadDepartmentData(),
    loadEmployeeDirectory(true),
    loadInactiveData(),
  ]);
}

function openOrganizationActionDialog() {
  if (!canOpenOrganizationActions.value) {
    errorMessage.value = "当前账号没有组织操作权限";
    return;
  }
  organizationActionDialogOpen.value = true;
  if (canSyncContacts.value) void refreshLastSyncTime();
}

function closeOrganizationActionDialog() {
  if (organizationActionRunning.value) {
    return;
  }
  organizationActionDialogOpen.value = false;
}

async function runOrganizationAction(action) {
  if (organizationActionRunning.value) {
    return;
  }
  if (action === "sync" && !canSyncContacts.value) {
    errorMessage.value = "只有组织架构管理员可以同步通讯录";
    return;
  }
  if ((action === "disableAll" || action === "enableAll") && !canManageEmployeeAccountStatus.value) {
    errorMessage.value = "只有组织架构管理员可以批量启用或禁用账号";
    return;
  }
  organizationActionRunning.value = action;
  errorMessage.value = "";
  try {
    if (action === "sync") {
      await syncContacts();
    } else if (action === "disableAll") {
      await updateAllEmployeeAccountStatus("禁用");
    } else if (action === "enableAll") {
      await updateAllEmployeeAccountStatus("启用");
    }
    organizationActionDialogOpen.value = false;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "操作失败";
  } finally {
    organizationActionRunning.value = "";
  }
}

function isDingTalkEnvironment() {
  const userAgent = navigator.userAgent || "";
  if (/dingtalk/i.test(userAgent)) return true;
  const loginType = String(session.value?.loginType || "").trim().toLowerCase();
  if (["workbench", "free", "silent"].includes(loginType)) return true;
  const platform = window.dd?.env?.platform || window.DingTalkPC?.env?.platform || "";
  return Boolean(platform && platform !== "notInDingTalk");
}

async function logout() {
  if (!confirmLeaveOrganizationSettings()) return;
  try {
    await logoutLoginSession();
    window.location.href = "/auth/";
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "退出失败，当前登录状态仍然保留";
  }
}

async function startProxy(employee) {
  const targetUserId = String(employee?.userId || "").trim();
  if (!targetUserId) {
    return;
  }
  if (targetUserId === currentSessionUserId.value) {
    errorMessage.value = "当前已在该账号下，无需重复代理";
    return;
  }
  if (targetUserId === actorSessionUserId.value) {
    errorMessage.value = "原账号无需代理，请直接使用退出代理";
    return;
  }
  selectedProxyEmployee.value = employee;
  proxyConfirmOpen.value = true;
}

async function confirmProxyStart() {
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
    errorMessage.value = error instanceof Error ? error.message : "代理登录失败";
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
    errorMessage.value = error instanceof Error ? error.message : "退出代理失败";
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

function returnPrevious() {
  mobilePagePickerOpen.value = false;
  if (!confirmLeaveOrganizationSettings()) return;
  navigateTo(APP_PATH, { replace: true });
}

function confirmLeaveOrganizationSettings() {
  const saveInProgress = managementTab.value === "permissions"
    && Boolean(organizationSettingsPanel.value?.isSaveInProgress?.());
  if (saveInProgress) {
    errorMessage.value = ORGANIZATION_SETTINGS_SAVING_LEAVE_MESSAGE;
    return false;
  }
  const hasPendingChanges = managementTab.value === "permissions"
    && Boolean(organizationSettingsPanel.value?.hasPendingChanges?.());
  if (!hasPendingChanges) return true;
  return window.confirm("组织配置有未保存的修改，确认放弃并离开？");
}

function handleOrganizationSettingsSavingChange(value) {
  const isSaving = Boolean(value);
  organizationSettingsSaving.value = isSaving;
  emit("saving-change", isSaving);
  if (!isSaving && errorMessage.value === ORGANIZATION_SETTINGS_SAVING_LEAVE_MESSAGE) {
    errorMessage.value = "";
  }
}

function handleMobileBackRequest(event) {
  if (proxyStopConfirmOpen.value) {
    closeStopProxyConfirm();
    markMobileBackHandled(event);
    return;
  }
  if (proxyConfirmOpen.value) {
    closeProxyConfirm();
    markMobileBackHandled(event);
    return;
  }
  if (employeeActionDialogOpen.value) {
    closeEmployeeActionDialog();
    markMobileBackHandled(event);
    return;
  }
  if (organizationActionDialogOpen.value) {
    closeOrganizationActionDialog();
    markMobileBackHandled(event);
    return;
  }
  if (departmentPickerParentId.value !== null) {
    departmentPickerParentId.value = null;
    markMobileBackHandled(event);
    return;
  }
  if (mobilePagePickerOpen.value) {
    mobilePagePickerOpen.value = false;
    markMobileBackHandled(event);
    return;
  }
  if (
    managementTab.value === "permissions"
    && (
      organizationSettingsPanel.value?.isSaveInProgress?.()
      || organizationSettingsPanel.value?.hasPendingChanges?.()
    )
  ) {
    returnPrevious();
    markMobileBackHandled(event);
  }
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
      || (managementTab.value === "permissions" && !canConfigurePermissions.value)) {
      openManagementSubPage("department");
    }
    return true;
  } catch (reason) {
    redirectToLoginWithError(reason instanceof Error ? reason.message : "登录已失效");
    return false;
  }
}

function openManagementSubPage(tabId) {
  if (tabId === "organization") {
    tabId = managementTab.value === "inactive" ? "department" : managementTab.value;
  }
  if (tabId === "inactive" && !canAccessInactiveEmployees.value) {
    tabId = "department";
  }
  if (tabId === "permissions" && !canConfigurePermissions.value) tabId = "department";
  const changingPanel = tabId !== "permissions";
  if (tabId !== managementTab.value && (changingPanel || organizationSettingsSaving.value) && !confirmLeaveOrganizationSettings()) {
    mobilePagePickerOpen.value = false;
    return;
  }
  const pathMap = {
    department: SETTINGS_ORGANIZATION_PATH,
    permissions: SETTINGS_ORGANIZATION_PERMISSIONS_PATH,
    inactive: SETTINGS_HANDOVER_PATH,
  };
  const path = pathMap[tabId] || SETTINGS_ORGANIZATION_PATH;
  if (window.location.pathname.replace(/\/+$/, "") === path) {
    managementTab.value = tabId;
    mobilePagePickerOpen.value = false;
    return;
  }
  managementTab.value = tabId;
  mobilePagePickerOpen.value = false;
  navigateTo(path, { replace: true });
}

watch(() => props.initialManagementTab, (tab) => {
  if (["department", "permissions", "inactive"].includes(tab)) managementTab.value = tab;
});

function openMobileMenu() {
  mobilePagePickerOpen.value = !mobilePagePickerOpen.value;
}

function closeMobilePagePicker() {
  mobilePagePickerOpen.value = false;
}

watch(
  selectedDepartmentId,
  () => {
    departmentPickerParentId.value = null;
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

watch(departmentKeyword, () => {
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
    loadDepartmentData();
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
  window.addEventListener(MOBILE_MENU_EVENT, openMobileMenu);
  window.addEventListener(MOBILE_CLOSE_PAGE_PICKERS_EVENT, closeMobilePagePicker);
  window.addEventListener(MOBILE_BACK_REQUEST_EVENT, handleMobileBackRequest);
  const allowed = await ensureSessionIsAllowed();
  if (!allowed) {
    return;
  }
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
  window.removeEventListener(MOBILE_MENU_EVENT, openMobileMenu);
  window.removeEventListener(MOBILE_CLOSE_PAGE_PICKERS_EVENT, closeMobilePagePicker);
  window.removeEventListener(MOBILE_BACK_REQUEST_EVENT, handleMobileBackRequest);
  if (departmentKeywordTimer !== null) {
    window.clearTimeout(departmentKeywordTimer);
  }
});
</script>

<template>
  <div class="settings-mobile-shell mobile-shell min-h-screen overflow-y-auto pt-14 text-slate-900">
    <div
      v-if="mobilePagePickerOpen"
      class="mobile-page-mask"
      v-backdrop-dismiss="($event) => { mobilePagePickerOpen = false }"
    />
    <div
      v-if="mobilePagePickerOpen"
      class="mobile-menu-panel mobile-page-picker fixed inset-x-0 z-[60] max-h-[50vh] px-2.5 py-2"
    >
      <div class="mobile-picker-list">
        <button
          v-for="item in managementTabs"
          :key="item.id"
          type="button"
          class="mobile-picker-option"
          :class="activeSidebarItemId === item.id ? 'mobile-picker-option-active' : ''"
          @click="openManagementSubPage(item.id)"
        >
          <span class="mobile-picker-icon">
            <component :is="item.icon" class="h-4 w-4" />
          </span>
          <span class="mobile-picker-label">{{ item.label }}</span>
          <span v-if="activeSidebarItemId === item.id" class="mobile-picker-state">当前</span>
        </button>
      </div>
    </div>

    <SettingsOrganizationTabs
      :active-tab="managementTab"
      :disabled="organizationSettingsSaving"
      :show-permissions="canConfigurePermissions"
      :show-handover="canAccessInactiveEmployees"
      @select="openManagementSubPage"
    />
    <main class="settings-mobile-content pb-6" :class="managementTab === 'permissions' ? '' : 'space-y-3 px-3 py-3'">
      <div v-if="errorMessage" class="mobile-panel border border-rose-100 bg-rose-50/90 px-4 py-3 text-sm text-rose-700">
        {{ errorMessage }}
      </div>
      <div v-if="statusMessage" class="mobile-panel border border-emerald-100 bg-emerald-50/90 px-4 py-3 text-sm text-emerald-700">
        {{ statusMessage }}
      </div>

      <section
        id="auth-dingtalk-organization-panel"
        v-show="managementTab === 'department'"
        role="tabpanel"
        aria-labelledby="auth-dingtalk-organization-tab"
      >
        <SettingsOrganizationPanel
          v-if="managementTab === 'department'"
          :can-manage-employee-account-status="canOpenOrganizationActions"
          :organization-action-running="organizationActionRunning"
          :selected-department="selectedDepartment"
          :selected-department-path="selectedDepartmentPath"
          :selected-department-has-children="selectedDepartmentHasChildren"
          :department-picker-options="departmentPickerOptions"
          :all-departments="flatDepartments"
          :department-employees="departmentEmployees"
          :selected-manager="selectedManager"
          :include-sub-departments="includeSubDepartments"
          :department-keyword="departmentKeyword"
          :loading-department="loadingDepartment"
          :sorted-department-employees="sortedDepartmentEmployees"
          :can-operate-department-employee="canOperateDepartmentEmployee"
          :account-status-saving-user-id="accountStatusSavingUserId"
          :proxy-action-user-id="proxyActionUserId"
          :primary-department-name="getPrimaryDepartmentName"
          @open-organization-action="openOrganizationActionDialog"
          @open-department-sibling-picker="openDepartmentSiblingPicker"
          @open-department-level-picker="openDepartmentLevelPicker"
          @select-department-from-picker="selectDepartmentFromPicker"
          @update-include-sub-departments="includeSubDepartments = $event"
          @update-department-keyword="departmentKeyword = $event"
          @open-employee-action="openEmployeeActionDialog"
        />
      </section>

      <section
        id="auth-permissions-panel"
        v-show="managementTab === 'permissions'"
        role="tabpanel"
        aria-labelledby="auth-permissions-tab"
      >
        <SettingsOrganizationPermissionsPanel
          v-if="managementTab === 'permissions'"
          ref="organizationSettingsPanel"
          @dirty-change="emit('dirty-change', $event)"
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
    </main>

    <div
      v-if="organizationActionDialogOpen"
      class="mobile-dialog-overlay px-4"
      v-backdrop-dismiss="closeOrganizationActionDialog"
    >
      <div class="mobile-dialog w-full max-w-sm" @click.stop>
        <div class="border-b border-slate-200 px-5 py-4">
          <div class="text-base font-semibold text-slate-900">操作</div>
        </div>
        <div class="space-y-3 px-5 py-5">
          <button
            v-if="canSyncContacts"
            class="mobile-action-option mobile-action-option-sync"
            :disabled="Boolean(organizationActionRunning)"
            @click="runOrganizationAction('sync')"
          >
            <div class="mobile-action-option-main">
              <div class="mobile-action-option-icon">
                <RefreshCw class="h-4 w-4" :class="organizationActionRunning === 'sync' ? 'animate-spin' : ''" />
              </div>
              <div class="mobile-action-option-copy">
                <span class="mobile-action-option-title">同步</span>
                <span class="mobile-action-option-meta">拉取最新组织通讯录</span>
                <span class="mobile-action-option-meta" aria-live="polite">{{ lastSyncLabel }}</span>
              </div>
            </div>
            <span class="mobile-action-option-state">{{ organizationActionRunning === "sync" ? "处理中" : "执行" }}</span>
          </button>
          <button
            v-if="canManageEmployeeAccountStatus"
            class="mobile-action-option mobile-action-option-danger"
            :disabled="Boolean(organizationActionRunning)"
            @click="runOrganizationAction('disableAll')"
          >
            <div class="mobile-action-option-main">
              <div class="mobile-action-option-icon">
                <UserX class="h-4 w-4" />
              </div>
              <div class="mobile-action-option-copy">
                <span class="mobile-action-option-title">全部禁用</span>
                <span class="mobile-action-option-meta">批量禁用全部在职账号</span>
              </div>
            </div>
            <span class="mobile-action-option-state">{{ organizationActionRunning === "disableAll" ? "处理中" : "执行" }}</span>
          </button>
          <button
            v-if="canManageEmployeeAccountStatus"
            class="mobile-action-option mobile-action-option-success"
            :disabled="Boolean(organizationActionRunning)"
            @click="runOrganizationAction('enableAll')"
          >
            <div class="mobile-action-option-main">
              <div class="mobile-action-option-icon">
                <ShieldCheck class="h-4 w-4" />
              </div>
              <div class="mobile-action-option-copy">
                <span class="mobile-action-option-title">全部启用</span>
                <span class="mobile-action-option-meta">批量恢复全部在职账号</span>
              </div>
            </div>
            <span class="mobile-action-option-state">{{ organizationActionRunning === "enableAll" ? "处理中" : "执行" }}</span>
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="employeeActionDialogOpen && selectedEmployeeActionTarget"
      class="mobile-dialog-overlay mobile-proxy-dialog-overlay px-4"
      v-backdrop-dismiss="closeEmployeeActionDialog"
    >
      <div class="mobile-dialog mobile-proxy-sheet w-full max-w-sm" @click.stop>
        <div class="mobile-proxy-sheet-head">
          <div class="mobile-proxy-employee-avatar">
            <img
              v-if="selectedEmployeeActionTarget.avatarUrl"
              :src="selectedEmployeeActionTarget.avatarUrl"
              :alt="selectedEmployeeActionTarget.name"
              class="h-full w-full object-cover"
              referrerpolicy="no-referrer"
            />
            <span v-else>{{ selectedEmployeeActionTarget.name?.slice(0, 1) || "?" }}</span>
          </div>
          <div class="min-w-0 flex-1">
            <div class="mobile-proxy-sheet-title">{{ selectedEmployeeActionTarget.name }}</div>
            <div class="mobile-proxy-sheet-subtitle">{{ selectedEmployeeActionTarget.userId }}</div>
            <div class="mobile-proxy-sheet-meta">
              <span>{{ getPrimaryDepartmentName(selectedEmployeeActionTarget) }}</span>
              <span>{{ selectedEmployeeActionTarget.accountStatus || "未知状态" }}</span>
            </div>
          </div>
          <button class="mobile-proxy-sheet-close" @click="closeEmployeeActionDialog">
            <X class="h-4 w-4" />
          </button>
        </div>
        <div class="mobile-proxy-sheet-actions">
          <button
            v-if="canUseProxy"
            class="mobile-action-option mobile-action-option-proxy"
            :disabled="isProxyButtonDisabled(selectedEmployeeActionTarget)"
            @click="handleEmployeeProxyAction"
          >
            <div class="mobile-action-option-main">
              <div class="mobile-action-option-icon">
                <UserRoundX class="h-4 w-4" />
              </div>
              <div class="mobile-action-option-copy">
                <span class="mobile-action-option-title">代理</span>
                <span class="mobile-action-option-meta">切换进入该员工账号</span>
              </div>
            </div>
            <span class="mobile-action-option-state">{{ getProxyButtonLabel(selectedEmployeeActionTarget) }}</span>
          </button>
          <button
            v-if="canManageEmployeeAccountStatus"
            class="mobile-action-option"
            :class="selectedEmployeeActionTarget.accountStatus === '启用' ? 'mobile-action-option-danger' : 'mobile-action-option-success'"
            :disabled="accountStatusSavingUserId === selectedEmployeeActionTarget.userId"
            @click="handleEmployeeAccountStatusAction"
          >
            <div class="mobile-action-option-main">
              <div class="mobile-action-option-icon">
                <UserX v-if="selectedEmployeeActionTarget.accountStatus === '启用'" class="h-4 w-4" />
                <ShieldCheck v-else class="h-4 w-4" />
              </div>
              <div class="mobile-action-option-copy">
                <span class="mobile-action-option-title">{{ selectedEmployeeActionTarget.accountStatus === "启用" ? "停用" : "启用" }}</span>
                <span class="mobile-action-option-meta">当前账号状态：{{ selectedEmployeeActionTarget.accountStatus }}</span>
              </div>
            </div>
            <span class="mobile-action-option-state">
              {{ accountStatusSavingUserId === selectedEmployeeActionTarget.userId ? "处理中" : "执行" }}
            </span>
          </button>
        </div>
      </div>
    </div>

    <div v-if="proxyConfirmOpen" class="mobile-dialog-overlay mobile-proxy-dialog-overlay px-4" v-backdrop-dismiss="closeProxyConfirm">
      <div class="mobile-dialog mobile-proxy-confirm-card w-full max-w-sm" @click.stop>
        <div class="mobile-proxy-confirm-head">
          <div class="mobile-proxy-confirm-icon is-primary">
            <UserRoundX class="h-5 w-5" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="mobile-proxy-confirm-title">确认代理</div>
            <div class="mobile-proxy-confirm-subtitle">将临时切换到目标员工账号</div>
          </div>
          <button class="mobile-proxy-confirm-close" @click="closeProxyConfirm">
            <X class="h-4 w-4" />
          </button>
        </div>
        <div class="mobile-proxy-confirm-body">
          <div class="mobile-proxy-target-card">
            <div class="mobile-proxy-employee-avatar">
              <img
                v-if="selectedProxyEmployee?.avatarUrl"
                :src="selectedProxyEmployee.avatarUrl"
                :alt="selectedProxyEmployee?.name"
                class="h-full w-full object-cover"
                referrerpolicy="no-referrer"
              />
              <span v-else>{{ selectedProxyEmployee?.name?.slice(0, 1) || "?" }}</span>
            </div>
            <div class="min-w-0 flex-1">
              <div class="mobile-proxy-target-name">{{ selectedProxyEmployee?.displayName || selectedProxyEmployee?.name || "-" }}</div>
              <div class="mobile-proxy-target-meta">{{ selectedProxyEmployee?.userId || "-" }}</div>
              <div class="mobile-proxy-target-meta">{{ getPrimaryDepartmentName(selectedProxyEmployee || {}) }}</div>
            </div>
          </div>
          <div class="mobile-proxy-confirm-note">
            代理后页面权限、头像、账号信息都会按目标账号展示。
          </div>
        </div>
        <div class="mobile-proxy-confirm-actions">
          <button class="mobile-proxy-confirm-button is-secondary" :disabled="Boolean(proxyActionUserId)" @click="closeProxyConfirm">
            取消
          </button>
          <button class="mobile-proxy-confirm-button is-primary" :disabled="Boolean(proxyActionUserId)" @click="confirmProxyStart">
            {{ proxyActionUserId ? "处理中..." : "确认代理" }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="proxyStopConfirmOpen" class="mobile-dialog-overlay mobile-proxy-dialog-overlay px-4" v-backdrop-dismiss="closeStopProxyConfirm">
      <div class="mobile-dialog mobile-proxy-confirm-card w-full max-w-sm" @click.stop>
        <div class="mobile-proxy-confirm-head">
          <div class="mobile-proxy-confirm-icon is-warning">
            <UserRoundX class="h-5 w-5" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="mobile-proxy-confirm-title">退出代理</div>
            <div class="mobile-proxy-confirm-subtitle">退出后将返回原账号</div>
          </div>
          <button class="mobile-proxy-confirm-close" @click="closeStopProxyConfirm">
            <X class="h-4 w-4" />
          </button>
        </div>
        <div class="mobile-proxy-confirm-body">
          <div class="mobile-proxy-account-row">
            <span>当前代理</span>
            <b>{{ currentProxyDisplay }}</b>
          </div>
          <div class="mobile-proxy-account-row">
            <span>返回账号</span>
            <b>{{ actorDisplay }}</b>
          </div>
        </div>
        <div class="mobile-proxy-confirm-actions">
          <button class="mobile-proxy-confirm-button is-secondary" :disabled="Boolean(proxyActionUserId)" @click="closeStopProxyConfirm">
            取消
          </button>
          <button class="mobile-proxy-confirm-button is-warning" :disabled="Boolean(proxyActionUserId)" @click="confirmStopProxy">
            {{ proxyActionUserId ? "处理中..." : "确认退出" }}
          </button>
        </div>
      </div>
    </div>

  </div>
</template>

<style>
.scrollbar-hidden {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.scrollbar-hidden::-webkit-scrollbar {
  display: none;
}

.mobile-action-option {
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

.mobile-action-option:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 18px 34px rgba(148, 163, 184, 0.16);
}

.mobile-action-option:disabled {
  cursor: not-allowed;
  opacity: 0.68;
  transform: none;
}

.mobile-action-option-main {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.9rem;
}

.mobile-action-option-icon {
  display: inline-flex;
  height: 2.4rem;
  width: 2.4rem;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 0.95rem;
}

.mobile-action-option-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
}

.mobile-action-option-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: rgb(15 23 42);
}

.mobile-action-option-meta {
  font-size: 0.74rem;
  color: rgb(100 116 139);
}

.mobile-action-option-state {
  flex-shrink: 0;
  border-radius: 999px;
  padding: 0.4rem 0.7rem;
  font-size: 0.74rem;
  font-weight: 600;
}

.mobile-action-option-sync {
  border-color: rgba(186, 230, 253, 0.9);
  background: linear-gradient(180deg, rgba(240, 249, 255, 0.98), rgba(239, 246, 255, 0.94));
}

.mobile-action-option-sync .mobile-action-option-icon {
  background: rgba(224, 242, 254, 0.96);
  color: rgb(3 105 161);
}

.mobile-action-option-sync .mobile-action-option-state {
  background: rgba(224, 242, 254, 0.95);
  color: rgb(3 105 161);
}

.mobile-action-option-danger {
  border-color: rgba(254, 205, 211, 0.92);
  background: linear-gradient(180deg, rgba(255, 241, 242, 0.98), rgba(255, 245, 245, 0.94));
}

.mobile-action-option-danger .mobile-action-option-icon {
  background: rgba(255, 228, 230, 0.96);
  color: rgb(190 24 93);
}

.mobile-action-option-danger .mobile-action-option-state {
  background: rgba(255, 228, 230, 0.95);
  color: rgb(190 24 93);
}

.mobile-action-option-success {
  border-color: rgba(187, 247, 208, 0.92);
  background: linear-gradient(180deg, rgba(240, 253, 244, 0.98), rgba(236, 253, 245, 0.94));
}

.mobile-action-option-success .mobile-action-option-icon {
  background: rgba(220, 252, 231, 0.96);
  color: rgb(21 128 61);
}

.mobile-action-option-success .mobile-action-option-state {
  background: rgba(220, 252, 231, 0.95);
  color: rgb(21 128 61);
}

.mobile-shell {
  position: relative;
  background:
    radial-gradient(circle at top left, rgba(14, 165, 233, 0.16), transparent 34%),
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.14), transparent 28%),
    linear-gradient(180deg, #f7fbff 0%, #eff5fb 46%, #f8fafc 100%);
}

.mobile-shell::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 10% 8%, rgba(255, 255, 255, 0.84), transparent 24%),
    radial-gradient(circle at 92% 16%, rgba(191, 219, 254, 0.45), transparent 22%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.12), transparent 22%);
  opacity: 0.95;
}

.mobile-nav-trigger {
  position: relative;
  z-index: 1;
  border: 0;
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
}

.mobile-menu-panel {
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  box-shadow: 0 18px 38px rgba(15, 23, 42, 0.16);
  backdrop-filter: none;
}

.mobile-page-picker {
  display: flex;
  flex-direction: column;
  top: env(safe-area-inset-top);
  border-left: 0;
  border-right: 0;
  border-top: 1px solid rgba(226, 232, 240, 0.95);
  border-bottom: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 0;
  box-shadow: 0 18px 36px rgba(15, 23, 42, 0.16);
}

.mobile-page-mask {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  top: env(safe-area-inset-top);
  z-index: 50;
  background: rgba(2, 6, 23, 0.7);
}

.mobile-picker-list {
  display: grid;
  min-height: 0;
  overflow-y: auto;
  gap: 0.16rem;
  padding-bottom: 0.32rem;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
}

.mobile-picker-list::-webkit-scrollbar {
  display: none;
}

.mobile-picker-option {
  display: grid;
  min-height: 2.72rem;
  width: 100%;
  grid-template-columns: 1.82rem minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.56rem;
  border-radius: 8px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  background: rgba(255, 255, 255, 0.96);
  padding: 0.42rem 0.6rem;
  text-align: left;
  box-shadow: 0 5px 12px rgba(148, 163, 184, 0.08);
  transition:
    border-color 160ms ease,
    background 160ms ease,
    box-shadow 160ms ease;
}

.mobile-picker-option-active {
  border-color: rgba(37, 99, 235, 0.28);
  background: linear-gradient(180deg, #eff6ff 0%, #ffffff 100%);
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.1);
}

.mobile-picker-icon {
  display: inline-flex;
  height: 1.82rem;
  width: 1.82rem;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  background: #f1f5f9;
  color: #475569;
}

.mobile-picker-option-active .mobile-picker-icon {
  background: #dbeafe;
  color: #1d4ed8;
}

.mobile-picker-label {
  min-width: 0;
  overflow: hidden;
  color: #0f172a;
  font-size: 0.84rem;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-picker-state {
  border-radius: 999px;
  background: #2563eb;
  padding: 0.14rem 0.48rem;
  color: #ffffff;
  font-size: 0.66rem;
  line-height: 1rem;
  font-weight: 700;
}

.mobile-dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(2, 6, 23, 0.7);
}

.mobile-dialog {
  border-radius: 1.75rem;
  background: #ffffff;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.2);
}

.mobile-proxy-dialog-overlay {
  background: rgba(2, 6, 23, 0.66);
}

.mobile-proxy-sheet,
.mobile-proxy-confirm-card {
  overflow: hidden;
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.96);
  box-shadow: 0 22px 52px rgba(15, 23, 42, 0.24);
}

.mobile-proxy-sheet-head,
.mobile-proxy-confirm-head {
  display: flex;
  align-items: center;
  gap: 0.72rem;
  border-bottom: 1px solid rgba(226, 232, 240, 0.86);
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  padding: 0.78rem 0.82rem;
}

.mobile-proxy-employee-avatar {
  display: flex;
  height: 2.55rem;
  width: 2.55rem;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 9px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 0.92rem;
  font-weight: 850;
}

.mobile-proxy-sheet-title,
.mobile-proxy-target-name,
.mobile-proxy-confirm-title {
  min-width: 0;
  overflow: hidden;
  color: #0f172a;
  font-size: 0.94rem;
  font-weight: 850;
  line-height: 1.25rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-proxy-sheet-subtitle,
.mobile-proxy-target-meta,
.mobile-proxy-confirm-subtitle {
  min-width: 0;
  overflow: hidden;
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-proxy-sheet-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.28rem;
  margin-top: 0.28rem;
}

.mobile-proxy-sheet-meta span {
  max-width: 100%;
  overflow: hidden;
  border-radius: 6px;
  background: #f1f5f9;
  padding: 0.12rem 0.36rem;
  color: #475569;
  font-size: 0.66rem;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-proxy-sheet-close,
.mobile-proxy-confirm-close {
  display: inline-flex;
  height: 2rem;
  width: 2rem;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #f1f5f9;
  color: #64748b;
}

.mobile-proxy-sheet-actions {
  display: grid;
  gap: 0.5rem;
  background: #ffffff;
  padding: 0.72rem;
}

.mobile-action-option-proxy {
  border-color: rgba(125, 211, 252, 0.65);
  background: linear-gradient(180deg, #f0f9ff 0%, #ffffff 100%);
}

.mobile-proxy-confirm-icon {
  display: flex;
  height: 2.35rem;
  width: 2.35rem;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
}

.mobile-proxy-confirm-icon.is-primary {
  background: #eff6ff;
  color: #2563eb;
}

.mobile-proxy-confirm-icon.is-warning {
  background: #fff7ed;
  color: #d97706;
}

.mobile-proxy-confirm-body {
  display: grid;
  gap: 0.5rem;
  background: #ffffff;
  padding: 0.8rem;
}

.mobile-proxy-target-card {
  display: flex;
  align-items: center;
  gap: 0.68rem;
  border-radius: 9px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: #f8fafc;
  padding: 0.62rem;
}

.mobile-proxy-confirm-note {
  border-radius: 8px;
  background: #eff6ff;
  padding: 0.5rem 0.6rem;
  color: #1d4ed8;
  font-size: 0.72rem;
  font-weight: 700;
  line-height: 1.15rem;
}

.mobile-proxy-account-row {
  display: flex;
  min-height: 2.35rem;
  align-items: center;
  justify-content: space-between;
  gap: 0.7rem;
  border-radius: 8px;
  background: #f8fafc;
  padding: 0.48rem 0.6rem;
}

.mobile-proxy-account-row span {
  flex-shrink: 0;
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 700;
}

.mobile-proxy-account-row b {
  min-width: 0;
  overflow: hidden;
  color: #0f172a;
  font-size: 0.82rem;
  font-weight: 850;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-proxy-confirm-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem;
  border-top: 1px solid rgba(226, 232, 240, 0.86);
  background: #f8fafc;
  padding: 0.72rem 0.8rem;
}

.mobile-proxy-confirm-button {
  min-height: 2.45rem;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 850;
}

.mobile-proxy-confirm-button.is-secondary {
  border: 1px solid rgba(226, 232, 240, 0.96);
  background: #ffffff;
  color: #475569;
}

.mobile-proxy-confirm-button.is-primary {
  background: #2563eb;
  color: #ffffff;
  box-shadow: 0 10px 22px rgba(37, 99, 235, 0.22);
}

.mobile-proxy-confirm-button.is-warning {
  background: #d97706;
  color: #ffffff;
  box-shadow: 0 10px 22px rgba(217, 119, 6, 0.22);
}

.mobile-proxy-confirm-button:disabled {
  opacity: 0.68;
  box-shadow: none;
}

.mobile-panel {
  position: relative;
  border-radius: 22px;
  border: 1px solid rgba(255, 255, 255, 0.88);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 18px 44px rgba(148, 163, 184, 0.15);
  backdrop-filter: blur(14px);
}

.mobile-field-card {
  border-radius: 1.15rem;
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.96));
  box-shadow: 0 12px 24px rgba(148, 163, 184, 0.1);
}

.mobile-toolbar-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: rgba(248, 250, 252, 0.96);
  padding: 0.38rem 0.75rem;
  font-size: 0.75rem;
  line-height: 1rem;
  color: rgb(71 85 105);
}

.mobile-toolbar-chip-active {
  border-color: rgba(56, 189, 248, 0.45);
  background: rgba(240, 249, 255, 0.98);
  color: rgb(3 105 161);
}

.mobile-toolbar-chip-inactive {
  background: rgba(241, 245, 249, 0.96);
  color: rgb(100 116 139);
}

.mobile-primary-button {
  border-radius: 0.9rem;
  background: linear-gradient(135deg, #0284c7 0%, #2563eb 100%);
  color: #ffffff;
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.18);
}

.mobile-primary-button:disabled {
  opacity: 0.72;
  box-shadow: none;
}

.mobile-secondary-button {
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: #ffffff;
  color: rgb(71 85 105);
}

.mobile-warning-button {
  border-radius: 999px;
  background: rgb(255 247 237);
  color: rgb(194 65 12);
}

.mobile-dept-chip {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: 0.35rem;
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: #ffffff;
  padding: 0.38rem 0.75rem;
  font-size: 0.82rem;
  line-height: 1rem;
  color: rgb(15 23 42);
}

.mobile-dept-chip-placeholder {
  color: rgb(100 116 139);
  border-style: dashed;
}

.mobile-dept-option {
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: rgba(248, 250, 252, 0.96);
  padding: 0.45rem 0.8rem;
  font-size: 0.8rem;
  line-height: 1rem;
  color: rgb(51 65 85);
}

.mobile-dept-option-active {
  border-color: rgba(56, 189, 248, 0.45);
  background: rgba(240, 249, 255, 0.98);
  color: rgb(3 105 161);
}

.mobile-list-card {
  position: relative;
  overflow: hidden;
  border-radius: 22px;
  border: 1px solid rgba(226, 232, 240, 0.86);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.96));
  box-shadow: 0 18px 42px rgba(148, 163, 184, 0.12);
}

.mobile-list-card::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  width: 4px;
  background: linear-gradient(180deg, rgba(14, 165, 233, 0.9), rgba(59, 130, 246, 0.36));
}

.mobile-list-card-disabled::before {
  background: linear-gradient(180deg, rgba(239, 68, 68, 0.9), rgba(244, 63, 94, 0.38));
}

.mobile-manager-avatar {
  box-shadow:
    0 0 0 2px rgb(251 191 36),
    0 0 0 5px rgba(255, 251, 235, 0.96);
}

.mobile-manager-badge {
  position: absolute;
  left: -0.3rem;
  top: -0.35rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 1.15rem;
  width: 1.15rem;
  border-radius: 0.35rem;
  background: linear-gradient(135deg, #f59e0b 0%, #ea580c 100%);
  color: #ffffff;
  transform: rotate(-22deg);
  box-shadow: 0 8px 16px rgba(245, 158, 11, 0.28);
}

.mobile-shell input,
.mobile-shell select,
.mobile-shell button {
  -webkit-tap-highlight-color: transparent;
}

.mobile-shell,
.mobile-shell * {
  scrollbar-width: none;
}

.mobile-shell::-webkit-scrollbar,
.mobile-shell *::-webkit-scrollbar {
  width: 0;
  height: 0;
}

.settings-mobile-shell.mobile-shell {
  background: #f1f5f9;
}

.settings-mobile-shell.mobile-shell::before {
  display: none;
}

.settings-mobile-shell .settings-mobile-content {
  -webkit-overflow-scrolling: touch;
}

.settings-mobile-shell .mobile-panel {
  overflow: hidden;
  border-radius: 9px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: #ffffff;
  box-shadow: 0 6px 16px rgba(148, 163, 184, 0.12);
  backdrop-filter: none;
}

.settings-mobile-shell .mobile-panel.p-4 {
  padding: 0.72rem !important;
}

.settings-mobile-shell .mobile-field-card {
  border-radius: 8px;
  border-color: rgba(226, 232, 240, 0.95);
  background: #f8fafc;
  box-shadow: none;
}

.settings-mobile-shell .mobile-list-card {
  overflow: hidden;
  border-radius: 9px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: #ffffff;
  box-shadow: 0 6px 14px rgba(148, 163, 184, 0.12);
}

.settings-mobile-shell .mobile-list-card.p-4 {
  padding: 0.72rem !important;
}

.settings-mobile-shell .mobile-list-card::before {
  width: 3px;
  background: #2563eb;
}

.settings-mobile-shell .mobile-list-card-active::before {
  background: #2563eb;
}

.settings-mobile-shell .mobile-list-card-disabled::before {
  background: #f97316;
}

.settings-mobile-shell .mobile-toolbar-chip {
  min-height: 1.72rem;
  border-radius: 6px;
  padding: 0.32rem 0.58rem;
  background: #f8fafc;
  font-size: 0.72rem;
  font-weight: 700;
}

.settings-mobile-shell .mobile-toolbar-chip-active {
  border-color: rgba(37, 99, 235, 0.3);
  background: #eff6ff;
  color: #1d4ed8;
}

.settings-mobile-shell .mobile-toolbar-chip-inactive {
  background: #f8fafc;
  color: #64748b;
}

.settings-mobile-shell .mobile-primary-button,
.settings-mobile-shell .mobile-secondary-button,
.settings-mobile-shell .mobile-warning-button {
  min-height: 2rem;
  border-radius: 7px !important;
  font-weight: 750;
}

.settings-mobile-shell .mobile-primary-button {
  background: #2563eb;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
}

.settings-mobile-shell .mobile-secondary-button {
  border-color: rgba(203, 213, 225, 0.95);
  background: #ffffff;
  color: #475569;
}

.settings-mobile-shell .mobile-warning-button {
  background: #fff7ed;
  color: #c2410c;
}

.settings-mobile-shell .mobile-dept-chip,
.settings-mobile-shell .mobile-dept-option {
  border-radius: 7px;
  border-color: rgba(226, 232, 240, 0.95);
  background: #ffffff;
  box-shadow: none;
}

.settings-mobile-shell .mobile-dept-chip {
  padding: 0.34rem 0.58rem;
  font-size: 0.78rem;
  font-weight: 700;
}

.settings-mobile-shell .mobile-dept-option {
  padding: 0.38rem 0.62rem;
  font-size: 0.76rem;
  font-weight: 700;
}

.settings-mobile-shell .mobile-dept-option-active {
  border-color: rgba(37, 99, 235, 0.3);
  background: #eff6ff;
  color: #1d4ed8;
}

.settings-mobile-shell input,
.settings-mobile-shell textarea,
.settings-mobile-shell select {
  border-radius: 8px !important;
  font-size: 0.85rem;
}

.settings-mobile-shell .mobile-action-option {
  border-radius: 8px;
  padding: 0.66rem 0.7rem;
  background: #ffffff;
  box-shadow: 0 6px 14px rgba(148, 163, 184, 0.12);
}

.settings-mobile-shell .mobile-action-option-icon {
  height: 2.1rem;
  width: 2.1rem;
  border-radius: 8px;
}

.settings-mobile-shell .mobile-action-option-title {
  font-size: 0.86rem;
}

.settings-mobile-shell .mobile-action-option-meta {
  font-size: 0.7rem;
}

.settings-mobile-shell .mobile-action-option-state {
  border-radius: 7px;
  padding: 0.34rem 0.56rem;
}

.settings-mobile-shell .mobile-dialog-overlay {
  background: rgba(15, 23, 42, 0.38);
}

.settings-mobile-shell .mobile-dialog {
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  box-shadow: 0 20px 44px rgba(15, 23, 42, 0.2);
}

.settings-mobile-shell .mobile-manager-avatar {
  box-shadow:
    0 0 0 2px #f59e0b,
    0 0 0 4px rgba(255, 247, 237, 0.96);
}

.settings-mobile-shell .mobile-proxy-sheet,
.settings-mobile-shell .mobile-proxy-confirm-card {
  border-radius: 10px;
}

.settings-mobile-shell .mobile-proxy-sheet-head,
.settings-mobile-shell .mobile-proxy-confirm-head {
  padding: 0.7rem;
}

.settings-mobile-shell .mobile-proxy-confirm-actions {
  padding: 0.64rem 0.7rem;
}

.settings-mobile-shell .mobile-proxy-confirm-button {
  min-height: 2.34rem;
  border-radius: 7px;
}

</style>
