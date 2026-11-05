<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  CircleDollarSign,
  ClipboardList,
  Gift,
  Handshake,
  LayoutDashboard,
  LoaderCircle,
  MessageSquareText,
  Monitor,
  PanelsTopLeft,
  RotateCcw,
  Settings,
  ShieldAlert,
  Users,
  Wrench,
  Lightbulb,
} from "@lucide/vue";
import {
  loginSessionIdentityKey,
  PlatformSidebar,
  PlatformSoftwareSuggestions,
  useSoftwareSuggestionsContext,
  startSessionKeepAlive,
} from "@platform-ui";
import { apiGet, apiPost, apiPatch, apiUpload, apiDelete } from "@/api";
import { managementCapabilities, managementPageAllowed } from "@/managementAccess";
import {
  loginSessionPrincipalKey,
  validateOrRecoverLoginSession,
} from "@/features/dingTalkSessionRecovery";
import DashboardView from "@/components/DashboardView.vue";
import PublicDemo from "@/components/PublicDemo.vue";
import PresalesWorkspace from "@/components/PresalesWorkspace.vue";
import ProjectCollaborationPanel from "@/components/ProjectCollaborationPanel.vue";
import ProjectWorkspace from "@/components/ProjectWorkspace.vue";
import ResourceWorkspace from "@/components/ResourceWorkspace.vue";
import SettlementWorkspace from "@/components/SettlementWorkspace.vue";
import RewardWorkspace from "@/components/RewardWorkspace.vue";
import TeamWorkspace from "@/components/TeamWorkspace.vue";
import SettingsWorkspace from "@/components/SettingsWorkspace.vue";
import UnsavedChangesDialog from "@/components/UnsavedChangesDialog.vue";
import {
  LOGIN_SESSION_CHANGE_EVENT,
  clearLoginSession,
  loadLoginSession,
  saveLoginSession,
} from "@/session";

const APP_PATH = "/after-sales/";
const PUBLIC_DEMO_PATH = "/after-sales/demo/";
const PERMISSION_SETTINGS_PATH = "/after-sales/settings/permissions/";
const SETTINGS_ORGANIZATION_PATH = "/auth/settings/organization";

const PAGE_PATHS = {
  dashboard: APP_PATH,
  presales: "/after-sales/presales/",
  midsales: "/after-sales/midsales/",
  aftersales: "/after-sales/aftersales/",
  collaboration: "/after-sales/collaboration/",
  settlements: "/after-sales/settlements/",
  team: "/after-sales/team/",
  rewards: "/after-sales/rewards/",
  permissions: PERMISSION_SETTINGS_PATH,
  suggestions: "/after-sales/suggestions/",
};
const SETTINGS_TAB_IDS = new Set(["tags", "prizes", "admin"]);

function readSettlementFocus(search = "") {
  const params = new URLSearchParams(search);
  return {
    projectId: params.get("projectId") || "",
    sourceNodeId: params.get("sourceNodeId") || "",
  };
}

function readProjectFocus(search = "") {
  const params = new URLSearchParams(search);
  return {
    projectId: params.get("projectId") || "",
    nodeKey: params.get("nodeKey") || "",
    roundId: params.get("roundId") || "",
  };
}

function readCollaborationFocus(search = "") {
  const params = new URLSearchParams(search);
  return { ticketId: params.get("ticketId") || "" };
}

const session = ref(loadLoginSession());
// Platform broadcasts carry identity, never this application's permissions.
const applicationAccess = ref(null);
const permissionError = ref("");
const permissionValidating = ref(false);
const workspaceSession = computed(() => session.value ? { ...session.value, ...applicationAccess.value } : null);
const isPublicDemo = window.location.pathname.replace(/\/+$/, "") === PUBLIC_DEMO_PATH.replace(/\/+$/, "");
const currentPage = ref(resolvePage(window.location.pathname));
const settingsTab = ref(resolveSettingsTab(window.location.search));
const settlementFocus = ref(readSettlementFocus(window.location.search));
const projectFocus = ref(readProjectFocus(window.location.search));
const collaborationFocus = ref(readCollaborationFocus(window.location.search));
const loading = ref(true);
const error = ref("");
const actionError = ref("");
const mobileMenuOpen = ref(false);
const permissionDirty = ref(false);
const suggestionsRef = ref(null);
const suggestionsDirty = ref(false);
const suggestionsBusy = ref(false);
const settlementDirty = ref(false);
const settlementBusy = ref(false);
const projectDirty = ref(false);
const projectBusy = ref(false);
const projectWorkspaceRef = ref(null);
const pageBusy = computed(() => suggestionsBusy.value || settlementBusy.value || projectBusy.value);
const pageDirty = computed(() => permissionDirty.value || suggestionsDirty.value || settlementDirty.value || projectDirty.value);
useSoftwareSuggestionsContext("after-sales", path => requestPermissionAction(() => {
  navigate({ path: new URL(path, window.location.origin).pathname });
  nextTick(() => suggestionsRef.value?.navigate(path));
}));
const permissionRefreshConfirmOpen = ref(false);
const discardConfirmOpen = ref(false);
const discardConfirmMessage = ref("当前页面的修改尚未保存，离开后本次修改不会保留。");

let currentIdentityKey = loginSessionIdentityKey(session.value);
let currentPrincipalKey = loginSessionPrincipalKey(session.value);
let stopSessionKeepAlive = null;
let disposed = false;
let pendingDiscardAction = null;
let permissionRequestEpoch = 0;

const capabilities = computed(() => managementCapabilities(session.value ? applicationAccess.value : null));
const canManageApp = computed(() => capabilities.value.admitted);
const canManageService = computed(() => capabilities.value.service);
const canManageSettlements = canManageApp;
const pageAllowed = (page) => Boolean(session.value) && managementPageAllowed(applicationAccess.value, page);


const adminSidebarItems = [
  { id: "dashboard", label: "总览", path: PAGE_PATHS.dashboard, icon: LayoutDashboard },
  { id: "presales", label: "售前服务", path: PAGE_PATHS.presales, icon: ClipboardList },
  { id: "midsales", label: "售中服务", path: PAGE_PATHS.midsales, icon: Handshake },
  { id: "aftersales", label: "售后服务", path: PAGE_PATHS.aftersales, icon: Wrench },
  { id: "collaboration", label: "工单与反馈", path: PAGE_PATHS.collaboration, icon: MessageSquareText },
  { id: "settlements", label: "结算中心", path: PAGE_PATHS.settlements, icon: CircleDollarSign },
  { id: "team", label: "服务团队", path: PAGE_PATHS.team, icon: Users },
  { id: "rewards", label: "服务奖励", path: PAGE_PATHS.rewards, icon: Gift },
  { id: "permissions", label: "设置 / 权限", path: PAGE_PATHS.permissions, icon: Settings },
  { id: "suggestions", label: "本软件优化建议", path: PAGE_PATHS.suggestions, icon: Lightbulb },
];
const sidebarItems = computed(() => {
  if (canManageApp.value) {
    return adminSidebarItems.filter((item) => pageAllowed(item.id));
  }
  return [];
});

const projectType = computed(() => ({ presales: "presales", midsales: "midsales", aftersales: "aftersales" }[currentPage.value] || ""));
const resourceType = computed(() => (["team", "rewards", "settlements", "collaboration"].includes(currentPage.value) ? currentPage.value : ""));

function resolvePage(pathname) {
  const normalized = String(pathname || "").replace(/\/+$/, "") || "/";
  const match = Object.entries(PAGE_PATHS).find(([, path]) => path.replace(/\/+$/, "") === normalized);
  return match?.[0] || "dashboard";
}

function isKnownPagePath(pathname) {
  const normalized = String(pathname || "").replace(/\/+$/, "") || "/";
  return Object.values(PAGE_PATHS).some((path) => path.replace(/\/+$/, "") === normalized);
}

function resolveSettingsTab(search = "") {
  const tab = new URLSearchParams(search).get("tab") || "tags";
  return SETTINGS_TAB_IDS.has(tab) ? tab : "tags";
}

function applyWorkspaceForSession() {
  if (!isKnownPagePath(window.location.pathname)) {
    currentPage.value = "dashboard";
    window.history.replaceState({}, "", APP_PATH);
  }
  if (canManageApp.value) {
    if (!pageAllowed(currentPage.value)) {
      currentPage.value = "dashboard";
      window.history.replaceState({}, "", APP_PATH);
    }
    return;
  }
  currentPage.value = "dashboard";
  if (window.location.pathname !== APP_PATH) {
    window.history.replaceState({}, "", APP_PATH);
  }
}

function redirectToLogin(message = "") {
  clearLoginSession();
  const params = new URLSearchParams();
  if (message) params.set("error", message);
  window.location.assign(params.toString() ? `/auth/?${params}` : "/auth/");
}

function isAuthenticationError(reason) {
  const status = Number(reason?.status || 0);
  const message = reason instanceof Error ? reason.message : "";
  return status === 401 || status === 403 || message.includes("Missing auth token") || message.includes("登录已失效");
}

async function refreshApplicationAccess(loginSession = session.value) {
  const principalKey = loginSessionPrincipalKey(loginSession);
  if (!principalKey) return;
  const requestEpoch = ++permissionRequestEpoch;
  permissionValidating.value = true;
  try {
    const access = await apiGet("/api/after-sales/session/");
    if (disposed || requestEpoch !== permissionRequestEpoch
      || principalKey !== loginSessionPrincipalKey(session.value)
      || principalKey !== loginSessionPrincipalKey(loadLoginSession())) return;
    if (typeof access?.canManageApp !== "boolean") throw new Error("应用权限返回不完整，请重试");
    applicationAccess.value = access;
    permissionError.value = "";
    applyWorkspaceForSession();
  } finally {
    if (requestEpoch === permissionRequestEpoch) permissionValidating.value = false;
  }
}

async function revalidateApplicationAccess(loginSession = session.value) {
  const principalKey = loginSessionPrincipalKey(loginSession);
  const requestEpoch = permissionRequestEpoch + 1;
  try {
    await refreshApplicationAccess(loginSession);
  } catch (reason) {
    if (disposed || requestEpoch !== permissionRequestEpoch || principalKey !== loginSessionPrincipalKey(loadLoginSession())) return;
    if (isAuthenticationError(reason)) {
      redirectToLogin(reason instanceof Error ? reason.message : "登录已失效");
      return;
    }
    permissionError.value = reason instanceof Error ? reason.message : "应用权限暂时无法核验";
  }
}

async function refreshSession() {
  loading.value = true;
  error.value = "";
  actionError.value = "";
  const cachedSession = loadLoginSession();
  try {
    const { session: validatedSession } = await validateOrRecoverLoginSession(cachedSession);
    currentIdentityKey = loginSessionIdentityKey(validatedSession);
    currentPrincipalKey = loginSessionPrincipalKey(validatedSession);
    session.value = validatedSession;
    saveLoginSession(validatedSession);
    await refreshApplicationAccess(validatedSession);
  } catch (reason) {
    if (isAuthenticationError(reason)) {
      redirectToLogin(reason instanceof Error ? reason.message : "登录已失效");
      return;
    }
    error.value = reason instanceof Error ? reason.message : "页面加载失败";
  } finally { loading.value = false; }
}

function requestPermissionAction(action, message = "") {
  if (pageBusy.value) { actionError.value = "正在保存，请完成后再离开。"; return false; }
  if (discardConfirmOpen.value || permissionRefreshConfirmOpen.value) return false;
  if (!pageDirty.value) {
    action();
    return true;
  }
  pendingDiscardAction = action;
  discardConfirmMessage.value = message || "当前页面的修改尚未保存，离开后本次修改不会保留。";
  discardConfirmOpen.value = true;
  return true;
}

function navigate(item) {
  if (!item?.path) return;
  closeMobileMenu();
  if (!item.path.startsWith(APP_PATH)) {
    requestPermissionAction(() => window.location.assign(item.path));
    return;
  }
  const nextPage = resolvePage(item.path);
  if (!pageAllowed(nextPage)) return;
  requestPermissionAction(() => {
    if (`${window.location.pathname}${window.location.search}` !== item.path) window.history.pushState({}, "", item.path);
    currentPage.value = nextPage;
    settlementFocus.value = nextPage === "settlements" ? readSettlementFocus(new URL(item.path, window.location.origin).search) : { projectId: "", sourceNodeId: "" };
    projectFocus.value = { projectId: "", nodeKey: "" };
    collaborationFocus.value = { ticketId: "" };
    if (nextPage === "permissions") settingsTab.value = "tags";
    window.scrollTo({ top: 0, behavior: "auto" });
  });
}

function handleDashboardNavigate(target = {}) {
  const nextPage = String(target.page || "dashboard");
  if (!pageAllowed(nextPage)) return;
  const basePath = PAGE_PATHS[nextPage] || PAGE_PATHS.dashboard;
  const params = new URLSearchParams();
  if (["presales", "midsales", "aftersales"].includes(nextPage)) {
    if (target.projectId) params.set("projectId", String(target.projectId));
    if (target.nodeKey) params.set("nodeKey", String(target.nodeKey));
  } else if (nextPage === "collaboration" && target.ticketId) {
    params.set("ticketId", String(target.ticketId));
  }
  const nextPath = `${basePath}${params.toString() ? `?${params.toString()}` : ""}`;
  requestPermissionAction(() => {
    if (`${window.location.pathname}${window.location.search}` !== nextPath) {
      window.history.pushState({}, "", nextPath);
    }
    currentPage.value = nextPage;
    projectFocus.value = readProjectFocus(new URL(nextPath, window.location.origin).search);
    collaborationFocus.value = readCollaborationFocus(new URL(nextPath, window.location.origin).search);
    settlementFocus.value = { projectId: "", sourceNodeId: "" };
    window.scrollTo({ top: 0, behavior: "auto" });
  });
}

function handleSettlementOpen(payload = {}) {
  if (!canManageSettlements.value) return;
  const projectId = String(payload.projectId || "").trim();
  const sourceNodeId = String(payload.sourceNodeId || "").trim();
  const params = new URLSearchParams();
  if (projectId) params.set("projectId", projectId);
  if (sourceNodeId) params.set("sourceNodeId", sourceNodeId);
  const nextPath = `${PAGE_PATHS.settlements}${params.toString() ? `?${params.toString()}` : ""}`;
  requestPermissionAction(() => {
    settlementFocus.value = { projectId, sourceNodeId };
    if (`${window.location.pathname}${window.location.search}` !== nextPath) window.history.pushState({}, "", nextPath);
    currentPage.value = "settlements";
    window.scrollTo({ top: 0, behavior: "auto" });
  });
}

function handleSettingsTabChange(tab) {
  const nextTab = SETTINGS_TAB_IDS.has(tab) ? tab : "tags";
  settingsTab.value = nextTab;
  if (currentPage.value !== "permissions") return;
  const nextPath = nextTab === "tags" ? PAGE_PATHS.permissions : `${PAGE_PATHS.permissions}?tab=${encodeURIComponent(nextTab)}`;
  if (`${window.location.pathname}${window.location.search}` !== nextPath) {
    window.history.replaceState({}, "", nextPath);
  }
}

function requestSettingsTabChange(tab) {
  if (settingsTab.value === tab) return;
  requestPermissionAction(() => handleSettingsTabChange(tab));
}

function continueEditing() {
  pendingDiscardAction = null;
  discardConfirmOpen.value = false;
}

function discardAndContinue() {
  const action = pendingDiscardAction;
  pendingDiscardAction = null;
  discardConfirmOpen.value = false;
  permissionDirty.value = false;
  suggestionsRef.value?.discard();
  suggestionsDirty.value = false;
  settlementDirty.value = false;
  projectWorkspaceRef.value?.discard();
  projectDirty.value = false;
  if (typeof action === "function") action();
}

async function handlePermissionsSaved() {
  permissionDirty.value = false;
  await revalidateApplicationAccess();
}

function toggleMobileMenu() { mobileMenuOpen.value = !mobileMenuOpen.value; }
function closeMobileMenu() { mobileMenuOpen.value = false; }

function handleSessionChange(event) {
  const nextSession = event?.detail?.session ?? loadLoginSession();
  const nextIdentityKey = loginSessionIdentityKey(nextSession);
  const nextPrincipalKey = loginSessionPrincipalKey(nextSession);
  const principalChanged = currentPrincipalKey && nextPrincipalKey !== currentPrincipalKey;
  if ((event?.detail?.remote && currentPrincipalKey && nextIdentityKey !== currentIdentityKey)
    || (nextSession && principalChanged && !loading.value)) {
    applicationAccess.value = null;
    permissionRequestEpoch += 1;
    window.location.reload();
    return;
  }
  currentIdentityKey = nextIdentityKey;
  currentPrincipalKey = nextPrincipalKey;
  session.value = nextSession ? { ...(session.value || {}), ...nextSession } : null;
  if (!nextSession || principalChanged) {
    applicationAccess.value = null;
    permissionRequestEpoch += 1;
  }
}

function handlePopState() {
  let nextPage = resolvePage(window.location.pathname);
  if (!isKnownPagePath(window.location.pathname)) {
    nextPage = "dashboard";
    window.history.replaceState({}, "", APP_PATH);
  }
  if ((pageDirty.value || pageBusy.value) && (nextPage !== currentPage.value || currentPage.value === "suggestions")) {
    window.history.pushState({}, "", currentPage.value === "suggestions" ? suggestionsRef.value?.getLocation() || PAGE_PATHS.suggestions : PAGE_PATHS[currentPage.value] || APP_PATH);
    requestPermissionAction(() => window.history.back());
    return;
  }
  currentPage.value = nextPage;
  if (nextPage === "suggestions") { const path = window.location.pathname + window.location.search; nextTick(() => suggestionsRef.value?.navigate(path)); }
  if (!pageAllowed(nextPage)) {
    currentPage.value = "dashboard";
    window.history.replaceState({}, "", APP_PATH);
  }
  settlementFocus.value = nextPage === "settlements" ? readSettlementFocus(window.location.search) : { projectId: "", sourceNodeId: "" };
  projectFocus.value = ["presales", "midsales", "aftersales"].includes(nextPage) ? readProjectFocus(window.location.search) : { projectId: "", nodeKey: "" };
  collaborationFocus.value = nextPage === "collaboration" ? readCollaborationFocus(window.location.search) : { ticketId: "" };
  if (nextPage === "permissions") settingsTab.value = resolveSettingsTab(window.location.search);
  closeMobileMenu();
}

function handleBeforeUnload(event) {
  if (!pageDirty.value && !pageBusy.value) return;
  event.preventDefault();
  event.returnValue = "";
}

watch(mobileMenuOpen, (open) => document.body.classList.toggle("app-mobile-menu-open", open));

onMounted(async () => {
  if (isPublicDemo) return;
  document.body.classList.add("as-admin-theme");
  window.addEventListener("popstate", handlePopState);
  window.addEventListener("beforeunload", handleBeforeUnload);
  window.addEventListener(LOGIN_SESSION_CHANGE_EVENT, handleSessionChange);
  await refreshSession();
  if (disposed) return;
  stopSessionKeepAlive = startSessionKeepAlive({
    shouldRun: () => Boolean(loadLoginSession()),
    validate: () => validateOrRecoverLoginSession(loadLoginSession()),
    onValidated: async ({ session: nextSession, recovered }) => {
      const nextIdentityKey = loginSessionIdentityKey(nextSession);
      const nextPrincipalKey = loginSessionPrincipalKey(nextSession);
      const sameRecoveredPrincipal = recovered
        && currentPrincipalKey
        && nextPrincipalKey === currentPrincipalKey;
      if (currentIdentityKey && nextIdentityKey !== currentIdentityKey && !sameRecoveredPrincipal) { window.location.reload(); return; }
      currentIdentityKey = nextIdentityKey;
      currentPrincipalKey = nextPrincipalKey;
      session.value = nextSession;
      saveLoginSession(nextSession, { broadcast: false });
      await revalidateApplicationAccess(nextSession);
    },
    onError: (reason) => { if (isAuthenticationError(reason)) redirectToLogin(reason instanceof Error ? reason.message : "登录已失效"); },
  });
});

onBeforeUnmount(() => {
  disposed = true;
  document.body.classList.remove("as-admin-theme");
  document.body.classList.remove("app-mobile-menu-open");
  window.removeEventListener("popstate", handlePopState);
  window.removeEventListener("beforeunload", handleBeforeUnload);
  window.removeEventListener(LOGIN_SESSION_CHANGE_EVENT, handleSessionChange);
  stopSessionKeepAlive?.();
});
</script>

<template>
  <PublicDemo v-if="isPublicDemo" />
  <div v-else class="as-app" :class="{ 'is-provider-only': !canManageApp }">
    <PlatformSidebar fixed module-title="迈杰服务" module-subtitle="服务业务工作台" :module-icon="PanelsTopLeft" :items="sidebarItems" :active-item-id="currentPage" @item-click="navigate" />

    <div v-if="mobileMenuOpen" class="app-mobile-sidebar-mask" aria-hidden="true" v-backdrop-dismiss="closeMobileMenu" />
    <div v-if="mobileMenuOpen" class="app-mobile-sidebar-panel" role="dialog" aria-modal="true" aria-label="迈杰服务导航">
      <PlatformSidebar class="app-mobile-sidebar" module-title="迈杰服务" module-subtitle="服务业务工作台" :module-icon="PanelsTopLeft" :items="sidebarItems.filter(item => item.id !== 'suggestions')" :active-item-id="currentPage" @item-click="navigate" />
    </div>

    <main class="as-main">
      <div v-if="actionError" class="as-alert as-alert--error as-shell-alert">{{ actionError }}</div>
      <div v-if="permissionError" class="as-alert as-alert--error as-shell-alert" role="alert">
        <span>{{ permissionError }}，应用权限尚未重新确认，请重试。</span>
        <button type="button" class="as-button as-button--secondary" :disabled="permissionValidating" @click="revalidateApplicationAccess()"><RotateCcw />重新验证权限</button>
      </div>
      <div v-if="loading" class="as-session-loading"><LoaderCircle class="as-spin" />正在验证登录与应用权限...</div>
      <div v-else-if="error" class="as-session-error"><ShieldAlert /><div><strong>应用加载失败</strong><span>{{ error }}</span></div><button type="button" class="as-button as-button--secondary" @click="refreshSession"><RotateCcw />重试</button></div>

      <div v-else-if="!canManageApp" class="as-admin-workspace"><section class="as-no-access" role="alert"><ShieldAlert /><h1>无权使用迈杰服务</h1><p>请联系系统管理员分配业务员、服务管理员或系统管理员权限。</p></section></div>

      <div v-else class="as-admin-workspace">
        <PlatformSoftwareSuggestions v-if="currentPage === 'suggestions'" ref="suggestionsRef" class="platform-suggestions-page"
          app-id="after-sales" :api-get="apiGet" :api-post="apiPost" :api-patch="apiPatch" :api-upload="apiUpload" :api-delete="apiDelete"
          :suspended="discardConfirmOpen" @dirty-change="suggestionsDirty=$event" @busy-change="suggestionsBusy=$event" @request-leave="requestPermissionAction($event)" />
        <section v-else-if="!pageAllowed(currentPage)" class="as-no-access"><ShieldAlert /><h1>暂无此项权限</h1><p>请联系系统管理员核对业务分工和权限。</p></section>
        <SettingsWorkspace v-else-if="currentPage === 'permissions'" :initial-tab="settingsTab" @tab-request="requestSettingsTabChange" @dirty-change="permissionDirty = Boolean($event)" @confirm-open-change="permissionRefreshConfirmOpen = Boolean($event)" @saved="handlePermissionsSaved" />
        <DashboardView v-else-if="currentPage === 'dashboard'" @navigate="handleDashboardNavigate" />
        <PresalesWorkspace v-else-if="currentPage === 'presales'" ref="projectWorkspaceRef" :session="workspaceSession" :focus-project-id="projectFocus.projectId" :focus-node-key="projectFocus.nodeKey" :focus-round-id="projectFocus.roundId || ''" @open-settlement="handleSettlementOpen" @dirty-change="projectDirty = $event" @busy-change="projectBusy = $event" />
        <ProjectWorkspace v-else-if="projectType" ref="projectWorkspaceRef" :key="projectType" :service-type="projectType" :session="workspaceSession" :focus-project-id="projectFocus.projectId" :focus-node-key="projectFocus.nodeKey" @open-settlement="handleSettlementOpen" @dirty-change="projectDirty = $event" @busy-change="projectBusy = $event" />
        <ProjectCollaborationPanel v-else-if="resourceType === 'collaboration'" :session="workspaceSession" :focus-ticket-id="collaborationFocus.ticketId" />
        <SettlementWorkspace v-else-if="resourceType === 'settlements'" :focus-project-id="settlementFocus.projectId" :focus-source-node-id="settlementFocus.sourceNodeId" @dirty-change="settlementDirty = $event" @busy-change="settlementBusy = $event" />
        <TeamWorkspace v-else-if="resourceType === 'team'" :can-manage="canManageService" />
        <RewardWorkspace v-else-if="resourceType === 'rewards'" />
        <ResourceWorkspace v-else-if="resourceType" :resource="resourceType" />
      </div>
    </main>

    <UnsavedChangesDialog :open="discardConfirmOpen" :message="discardConfirmMessage" :layer="settlementDirty || projectDirty ? 3300 : 220" fallback-focus-selector=".platform-sidebar-item.active" @cancel="continueEditing" @confirm="discardAndContinue" />
  </div>
</template>
