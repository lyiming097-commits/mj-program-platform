<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Database, FileClock, Home, Inbox, LayoutTemplate, LoaderCircle, PanelsTopLeft, RotateCcw, Settings, ShieldAlert } from "@lucide/vue";
import { loginSessionIdentityKey, PlatformSidebar, startSessionKeepAlive } from "@platform-ui";

import { apiGet, apiPost, apiPatch, apiUpload, apiDelete } from "@/api";
import { Lightbulb } from "@lucide/vue";
import { PlatformSoftwareSuggestions, useSoftwareSuggestionsContext } from "@platform-ui";
import AdminPermissionSettings from "@/components/AdminPermissionSettings.vue";
import ApplicationDetailDrawer from "@/components/approval/ApplicationDetailDrawer.vue";
import ApplicationFormDrawer from "@/components/approval/ApplicationFormDrawer.vue";
import ApprovalSuccessToast from "@/components/approval/ApprovalSuccessToast.vue";
import ApprovalWorkspace from "@/components/approval/ApprovalWorkspace.vue";
import TemplateEditor from "@/components/approval/TemplateEditor.vue";
import UnsavedChangesDialog from "@/components/UnsavedChangesDialog.vue";
import { LOGIN_SESSION_CHANGE_EVENT, clearLoginSession, loadLoginSession, saveLoginSession, validateLoginSession } from "@/session";

const APP_PATH = "/approval-center/";
const SETTINGS_PERMISSION_PATH = `${APP_PATH}settings/permissions/`;
const TEMPLATE_MANAGEMENT_PATH = `${APP_PATH}templates/`;
const HISTORY_INDEX_KEY = "__approvalCenterHistoryIndex";
const session = ref(loadLoginSession());
const route = ref(resolveRoute());
const loading = ref(true);
const errorMessage = ref("");
const actionError = ref("");
const mobileMenuOpen = ref(false);
const editorDirty = ref(false);
const formDirty = ref(false);
const permissionDirty = ref(false);
const suggestionsRef = ref(null);
const suggestionsDirty = ref(false);
const suggestionsBusy = ref(false);
useSoftwareSuggestionsContext("approval-center", path => requestProtectedAction(() => {
  navigateInternal(path, { bypassGuard: true });
  nextTick(() => suggestionsRef.value?.navigate(path));
}));
const permissionRefreshConfirmOpen = ref(false);
const discardConfirmOpen = ref(false);
const discardConfirmMessage = ref("当前页面的修改尚未保存，离开后本次修改不会保留。");
const refreshKey = ref(0);
const activeDraft = ref(null);
const successNotice = ref(null);
let successNoticeId = 0;

let currentIdentityKey = loginSessionIdentityKey(session.value);
let stopSessionKeepAlive = null;
let disposed = false;
let pendingDiscardAction = null;
let currentUrl = `${window.location.pathname}${window.location.search}`;
let historyRestoreTargetIndex = null;
let queuedHistoryDelta = null;
let currentHistoryIndex = historyStateIndex();

if (currentHistoryIndex === null) {
  currentHistoryIndex = 0;
  window.history.replaceState({
    ...normalizedHistoryState(window.history.state),
    [HISTORY_INDEX_KEY]: currentHistoryIndex,
  }, "");
}

const canManageApp = computed(() => Boolean(session.value?.canManageApp));
const managedCategoryIds = computed(() => {
  const source = session.value?.managedCategoryIds
    ?? session.value?.managed_category_ids
    ?? session.value?.managedCategories
    ?? [];
  return Array.isArray(source)
    ? source.map((value) => String(value?.id ?? value).trim()).filter(Boolean)
    : [];
});
const canManageTemplates = computed(() => Boolean(
  session.value?.canManageTemplates
  || canManageApp.value
  || managedCategoryIds.value.length > 0,
));
const hasPendingChanges = computed(() => editorDirty.value || formDirty.value || permissionDirty.value || suggestionsDirty.value);
const isEditor = computed(() => route.value.name === "template-editor");
const isSettingsPage = computed(() => route.value.name === "settings");
const isTemplateManagement = computed(() => route.value.name === "template-management");
const isOverlayRoute = computed(() => ["application-detail", "application-form"].includes(route.value.name));
const workspaceRoute = computed(() => isOverlayRoute.value ? route.value.background : route.value);
const sidebarItems = computed(() => [
  { id: "home", label: "审批首页", path: APP_PATH, icon: Home },
  { id: "approvals", label: "审批中心", path: `${APP_PATH}approvals/`, icon: Inbox },
  { id: "drafts", label: "草稿箱", path: `${APP_PATH}drafts/`, icon: FileClock },
  ...(canManageApp.value ? [{ id: "data", label: "数据中心", path: `${APP_PATH}data/`, icon: Database }] : []),
  ...(canManageTemplates.value ? [{ id: "templates", label: "表单管理", path: TEMPLATE_MANAGEMENT_PATH, icon: LayoutTemplate }] : []),
  ...(canManageApp.value ? [{ id: "settings", label: "设置", path: SETTINGS_PERMISSION_PATH, icon: Settings }] : []),
  { id: "suggestions", label: "本软件优化建议", path: `${APP_PATH}suggestions/`, icon: Lightbulb },
]);
const activeSidebarItemId = computed(() => {
  if (route.value.name === "suggestions") return "suggestions";
  if (isEditor.value || isTemplateManagement.value || workspaceRoute.value?.name === "template-management") return "templates";
  if (isSettingsPage.value || workspaceRoute.value?.name === "settings") return "settings";
  return workspaceRoute.value?.page || "home";
});

function parseQuery(search = window.location.search) {
  return Object.fromEntries(new URLSearchParams(search).entries());
}
function normalizedPath(pathname = window.location.pathname) {
  return String(pathname || "/").replace(/\/+$/, "") || "/";
}
function normalizedHistoryState(state) {
  return state && typeof state === "object" ? state : {};
}
function historyStateIndex(state = window.history.state) {
  const value = Number(normalizedHistoryState(state)[HISTORY_INDEX_KEY]);
  return Number.isInteger(value) ? value : null;
}
function replaceAppHistory(path) {
  window.history.replaceState({
    ...normalizedHistoryState(window.history.state),
    [HISTORY_INDEX_KEY]: currentHistoryIndex,
  }, "", path);
}
function pushAppHistory(path) {
  currentHistoryIndex += 1;
  window.history.pushState({ [HISTORY_INDEX_KEY]: currentHistoryIndex }, "", path);
}
function safeReturnRoute(query) {
  const candidate = String(query.return || "");
  if (!candidate.startsWith(APP_PATH) || candidate.includes("\n") || candidate.includes("\r")) return null;
  try {
    const target = new URL(candidate, window.location.origin);
    const resolved = resolveRoute(target.pathname, target.search, { allowOverlay: false });
    return ["workspace", "settings", "template-management"].includes(resolved.name) ? resolved : null;
  } catch {
    return null;
  }
}
function resolveRoute(pathname = window.location.pathname, search = window.location.search, options = {}) {
  if (String(pathname).replace(/\/+$/, "") === "/approval-center/suggestions") return { name: "suggestions", page: "suggestions", query: parseQuery(search) };
  const path = normalizedPath(pathname);
  const query = parseQuery(search);
  const pages = {
    "/approval-center": "home",
    "/approval-center/approvals": "approvals",
    "/approval-center/drafts": "drafts",
    "/approval-center/data": "data",
  };
  if (pages[path]) return { name: "workspace", page: pages[path], query };
  if (["/approval-center/settings", "/approval-center/settings/permissions"].includes(path)) {
    return {
      name: "settings",
      page: "permissions",
      query,
      ...(path === "/approval-center/settings" ? { canonicalPath: SETTINGS_PERMISSION_PATH } : {}),
    };
  }
  if (path === "/approval-center/settings/templates") {
    return { name: "template-management", page: "templates", query, canonicalPath: TEMPLATE_MANAGEMENT_PATH };
  }
  if (path === "/approval-center/templates") {
    return { name: "template-management", page: "templates", query };
  }
  if (path === "/approval-center/templates/new") return { name: "template-editor", page: "templates", templateId: "", step: query.step || "basic", starterKey: query.starter || "", query };
  const editor = path.match(/^\/approval-center\/templates\/([^/]+)\/edit$/);
  if (editor) return { name: "template-editor", page: "templates", templateId: decodeURIComponent(editor[1]), step: query.step || "basic", starterKey: "", query };
  if (options.allowOverlay !== false) {
    const detail = path.match(/^\/approval-center\/applications\/([^/]+)$/);
    if (detail) return { name: "application-detail", page: "approvals", applicationId: decodeURIComponent(detail[1]), query, background: safeReturnRoute(query) || { name: "workspace", page: "approvals", query: { tab: "pending" } } };
    const form = path.match(/^\/approval-center\/apply\/([^/]+)$/);
    if (form) return { name: "application-form", page: "home", templateId: decodeURIComponent(form[1]), draftId: query.draftId || "", query, background: safeReturnRoute(query) || { name: "workspace", page: query.draftId ? "drafts" : "home", query: {} } };
  }
  return { name: "workspace", page: "home", query: {}, unknown: true };
}
function currentLocation() {
  return `${window.location.pathname}${window.location.search}`;
}
function requestProtectedAction(action, message = "") {
  if (suggestionsBusy.value) { actionError.value = "正在保存，请完成后再离开。"; return false; }
  if (discardConfirmOpen.value || permissionRefreshConfirmOpen.value) return false;
  if (!hasPendingChanges.value) {
    action();
    return true;
  }
  pendingDiscardAction = action;
  discardConfirmMessage.value = message || "当前页面的修改尚未保存，离开后本次修改不会保留。";
  discardConfirmOpen.value = true;
  return true;
}
function navigateInternal(path, { replace = false, bypassGuard = false } = {}) {
  const perform = () => {
    const target = new URL(path, window.location.origin);
    const resolved = resolveRoute(target.pathname, target.search);
    const pathname = resolved.canonicalPath || target.pathname;
    const nextUrl = `${pathname}${target.search}`;
    if (replace || nextUrl === currentLocation()) replaceAppHistory(nextUrl);
    else pushAppHistory(nextUrl);
    currentUrl = nextUrl;
    route.value = resolved.canonicalPath
      ? resolveRoute(pathname, target.search)
      : resolved;
    mobileMenuOpen.value = false;
    actionError.value = "";
    window.scrollTo({ top: 0, behavior: "auto" });
  };
  if (bypassGuard) perform();
  else requestProtectedAction(perform);
}
function navigate(itemOrPath, options = {}) {
  const path = typeof itemOrPath === "string" ? itemOrPath : itemOrPath?.path;
  if (!path) return;
  mobileMenuOpen.value = false;
  if (path.startsWith(APP_PATH)) navigateInternal(path, options);
  else requestProtectedAction(() => window.location.assign(path));
}
function continueEditing() {
  pendingDiscardAction = null;
  discardConfirmOpen.value = false;
}
function discardAndContinue() {
  const action = pendingDiscardAction;
  pendingDiscardAction = null;
  discardConfirmOpen.value = false;
  editorDirty.value = false;
  formDirty.value = false;
  permissionDirty.value = false;
  suggestionsRef.value?.discard();
  suggestionsDirty.value = false;
  if (typeof action === "function") action();
}
function backgroundReturnPath() {
  const value = String(route.value.query?.return || "");
  if (value.startsWith(APP_PATH)) return value;
  if (route.value.name === "application-form" && route.value.draftId) return `${APP_PATH}drafts/`;
  if (route.value.name === "application-detail") return `${APP_PATH}approvals/`;
  return APP_PATH;
}
function returnFromOverlay() {
  navigateInternal(backgroundReturnPath(), { replace: true, bypassGuard: true });
  activeDraft.value = null;
  formDirty.value = false;
}
function openApplication(id) {
  const params = new URLSearchParams({ return: isOverlayRoute.value ? backgroundReturnPath() : currentLocation() });
  navigateInternal(`${APP_PATH}applications/${encodeURIComponent(id)}/?${params.toString()}`);
}
function startApplication(templateId, draftId = "", draft = null) {
  activeDraft.value = draft;
  const params = new URLSearchParams({ return: isOverlayRoute.value ? backgroundReturnPath() : currentLocation() });
  if (draftId) params.set("draftId", String(draftId));
  navigateInternal(`${APP_PATH}apply/${encodeURIComponent(templateId)}/?${params.toString()}`);
}
function templateEditorPath(id = "", starter = "", context = {}) {
  const params = new URLSearchParams({ step: "basic" });
  if (starter) params.set("starter", starter);
  const categoryId = context && typeof context === "object"
    ? String(context.categoryId ?? context.category_id ?? "").trim()
    : "";
  if (categoryId) params.set("categoryId", categoryId);
  return id ? `${APP_PATH}templates/${encodeURIComponent(id)}/edit/?${params}` : `${APP_PATH}templates/new/?${params}`;
}
function templateEditorUrl(id = "", starter = "", context = {}) {
  const target = new URL(templateEditorPath(id, starter, context), window.location.origin);
  if (route.value.name === "template-management") {
    target.searchParams.set("return", currentLocation());
  }
  return target;
}
function isDesktopDingTalk() {
  if (/android|iphone|ipad|ipod|mobile/i.test(navigator.userAgent || "")) return false;
  const platform = String(window.dd?.env?.platform || window.DingTalkPC?.env?.platform || "").toLowerCase();
  return platform ? platform === "pc" : /dingtalk/i.test(navigator.userAgent || "");
}
function editorWorkbenchLink(id, context = {}) {
  if (!id || !isDesktopDingTalk()) return "";
  // AppLink routes directly to the PC workbench; openLink defaults to the system browser.
  const link = new URL("https://applink.dingtalk.com/page/link");
  link.searchParams.set("url", templateEditorUrl(id, "", context).href);
  link.searchParams.set("targetDesktop", "workbench");
  return link.href;
}
function openTemplateEditor(id = "", starter = "", context = {}) {
  const target = templateEditorUrl(id, starter, context);
  navigateInternal(`${target.pathname}${target.search}`);
}

function handleNewTemplate(starter = "", context = {}) {
  openTemplateEditor("", starter, context);
}

function handleEditTemplate(id = "", context = {}) {
  if (id) openTemplateEditor(id, "", context);
}

function handleTemplateSaved(payload) {
  editorDirty.value = false;
  if (route.value.templateId || !payload?.id) return;
  const params = new URLSearchParams({ step: route.value.step || "basic" });
  const categoryId = String(
    payload?.template?.categoryId
    ?? payload?.template?.category_id
    ?? route.value.query?.categoryId
    ?? "",
  ).trim();
  if (categoryId) params.set("categoryId", categoryId);
  if (route.value.query?.return) params.set("return", route.value.query.return);
  navigateInternal(`${APP_PATH}templates/${encodeURIComponent(payload.id)}/edit/?${params}`, { replace: true, bypassGuard: true });
}
function closeTemplateEditor(context = {}) {
  const returnPath = String(route.value.query?.return || "");
  const returnRoute = safeReturnRoute(route.value.query || {});
  if (returnRoute?.name === "template-management") {
    navigate(returnPath, { replace: true });
    return;
  }
  const categoryId = String(
    context?.categoryId
    ?? context?.category_id
    ?? route.value.query?.categoryId
    ?? "",
  ).trim();
  const params = new URLSearchParams();
  if (categoryId) params.set("categoryId", categoryId);
  navigate(`${TEMPLATE_MANAGEMENT_PATH}${params.size ? `?${params}` : ""}`, { replace: true });
}
function handleApplicationSubmitted(application) {
  formDirty.value = false;
  refreshKey.value += 1;
  showSuccessNotice("审批已提交");
  if (application?.id) {
    const params = new URLSearchParams({ return: `${APP_PATH}approvals/?tab=initiated` });
    navigateInternal(`${APP_PATH}applications/${encodeURIComponent(application.id)}/?${params}`, { replace: true, bypassGuard: true });
  } else navigateInternal(`${APP_PATH}approvals/?tab=initiated`, { replace: true, bypassGuard: true });
}
function showSuccessNotice(message) {
  successNotice.value = { id: ++successNoticeId, message };
}
function dismissSuccessNotice(id) {
  if (successNotice.value?.id === id) successNotice.value = null;
}
function handleApplicationChanged(payload = {}) {
  refreshKey.value += 1;
  const messages = { approve: "审批已同意", reject: "审批已拒绝", return: "申请已退回", withdraw: "申请已撤回" };
  if (messages[payload.action]) showSuccessNotice(messages[payload.action]);
}
function closeForm(payload = {}) {
  if (payload.dirty || formDirty.value) requestProtectedAction(returnFromOverlay, "当前申请尚未提交或保存为草稿，离开后本次修改不会保留。");
  else returnFromOverlay();
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
  return [401, 403].includes(status) || message.includes("Missing auth token") || message.includes("登录已失效");
}
async function refreshSession() {
  loading.value = true;
  errorMessage.value = "";
  try {
    const cached = loadLoginSession();
    const [validated, appSession] = await Promise.all([validateLoginSession(cached), apiGet("/api/approval-center/session/")]);
    const next = { ...(cached || {}), ...validated, ...appSession };
    currentIdentityKey = loginSessionIdentityKey(next);
    session.value = next;
    saveLoginSession(next);
    if (
      route.value.name === "settings"
      && !Boolean(next.canManageApp)
      && Boolean(next.canManageTemplates || next.managedCategoryIds?.length)
    ) {
      navigateInternal(`${TEMPLATE_MANAGEMENT_PATH}${window.location.search}`, { replace: true, bypassGuard: true });
    }
  } catch (reason) {
    if (isAuthenticationError(reason)) return redirectToLogin(reason instanceof Error ? reason.message : "登录已失效");
    errorMessage.value = reason instanceof Error ? reason.message : "页面加载失败";
  } finally {
    loading.value = false;
  }
}
function toggleMobileMenu() {
  mobileMenuOpen.value = !mobileMenuOpen.value;
}
function traverseHistoryAfterRestore(delta) {
  if (!delta) return;
  if (historyRestoreTargetIndex !== null) {
    queuedHistoryDelta = delta;
    return;
  }
  window.history.go(delta);
}
function restoreCurrentHistoryEntry(nextIndex) {
  const delta = nextIndex - currentHistoryIndex;
  if (!delta) return 0;
  historyRestoreTargetIndex = currentHistoryIndex;
  window.history.go(-delta);
  return delta;
}
function syncRouteFromLocation() {
  const resolved = resolveRoute();
  if (resolved.canonicalPath) {
    const nextUrl = `${resolved.canonicalPath}${window.location.search}`;
    replaceAppHistory(nextUrl);
    currentUrl = nextUrl;
    route.value = resolveRoute(resolved.canonicalPath, window.location.search);
  } else if (resolved.unknown) {
    replaceAppHistory(APP_PATH);
    currentUrl = APP_PATH;
    route.value = resolveRoute(APP_PATH, "");
  } else {
    currentUrl = currentLocation();
    route.value = resolved;
  }
  activeDraft.value = null;
  mobileMenuOpen.value = false;
}
function handlePopState(event) {
  const nextIndex = historyStateIndex(event.state);
  if (historyRestoreTargetIndex !== null) {
    if (nextIndex === historyRestoreTargetIndex) {
      currentHistoryIndex = nextIndex;
      historyRestoreTargetIndex = null;
      const delta = queuedHistoryDelta;
      queuedHistoryDelta = null;
      if (delta) window.history.go(delta);
    } else if (nextIndex !== null) {
      window.history.go(historyRestoreTargetIndex - nextIndex);
    }
    return;
  }

  if (hasPendingChanges.value || suggestionsBusy.value) {
    if (nextIndex !== null) {
      const delta = restoreCurrentHistoryEntry(nextIndex);
      if (delta) requestProtectedAction(() => traverseHistoryAfterRestore(delta));
      return;
    }

    pushAppHistory(currentUrl);
    requestProtectedAction(() => window.history.back());
    return;
  }
  if (nextIndex !== null) currentHistoryIndex = nextIndex;
  syncRouteFromLocation();
  if (route.value.name === "suggestions") { const path = currentLocation(); nextTick(() => suggestionsRef.value?.navigate(path)); }
}
function handleBeforeUnload(event) {
  if (!hasPendingChanges.value && !suggestionsBusy.value) return;
  event.preventDefault();
  event.returnValue = "";
}
function handleSessionChange(event) {
  const next = event?.detail?.session ?? loadLoginSession();
  const identity = loginSessionIdentityKey(next);
  if (event?.detail?.remote && currentIdentityKey && identity !== currentIdentityKey) return window.location.reload();
  currentIdentityKey = identity;
  session.value = next ? { ...(session.value || {}), ...next } : null;
}

watch(mobileMenuOpen, (open) => document.body.classList.toggle("app-mobile-menu-open", open));
watch(route, (current) => {
  document.title = current.name === "template-editor"
    ? `${current.templateId ? "编辑表单" : "新建表单"} - 审批中心`
    : current.name === "template-management" ? "表单管理 - 审批中心"
    : current.name === "settings" ? "设置 - 审批中心"
    : "审批中心";
}, { immediate: true });
onMounted(async () => {
  syncRouteFromLocation();
  window.addEventListener("popstate", handlePopState);
  window.addEventListener("beforeunload", handleBeforeUnload);
  window.addEventListener(LOGIN_SESSION_CHANGE_EVENT, handleSessionChange);
  await refreshSession();
  if (disposed) return;
  stopSessionKeepAlive = startSessionKeepAlive({
    shouldRun: () => Boolean(loadLoginSession()),
    validate: () => validateLoginSession(loadLoginSession()),
    onValidated: (validated) => {
      const next = { ...(loadLoginSession() || {}), ...validated };
      if (currentIdentityKey && loginSessionIdentityKey(next) !== currentIdentityKey) return window.location.reload();
      session.value = { ...(session.value || {}), ...next };
      saveLoginSession(session.value, { broadcast: false });
    },
    onError: (reason) => isAuthenticationError(reason) && redirectToLogin("登录已失效"),
  });
});
onBeforeUnmount(() => {
  disposed = true;
  document.body.classList.remove("app-mobile-menu-open");
  window.removeEventListener("popstate", handlePopState);
  window.removeEventListener("beforeunload", handleBeforeUnload);
  window.removeEventListener(LOGIN_SESSION_CHANGE_EVENT, handleSessionChange);
  stopSessionKeepAlive?.();
});
</script>

<template>
  <div class="min-h-screen bg-[#eef3f9] text-slate-950">
    <PlatformSidebar v-if="!loading && !errorMessage" fixed module-title="审批中心" module-subtitle="流程审批" :module-icon="PanelsTopLeft" :items="sidebarItems" :active-item-id="activeSidebarItemId" @item-click="navigate" />
    <div v-if="mobileMenuOpen" class="app-mobile-sidebar-mask" aria-hidden="true" v-backdrop-dismiss="() => { mobileMenuOpen = false }" />
    <div v-if="mobileMenuOpen" class="app-mobile-sidebar-panel" role="dialog" aria-modal="true" aria-label="审批中心导航"><PlatformSidebar class="app-mobile-sidebar" module-title="审批中心" module-subtitle="流程审批" :module-icon="PanelsTopLeft" :items="sidebarItems.filter(item => item.id !== 'suggestions')" :active-item-id="activeSidebarItemId" @item-click="navigate" /></div>

    <main class="app-main approval-app-main" :class="{ 'is-full-width': loading || errorMessage }">
      <div v-if="actionError" class="approval-alert is-error approval-shell-alert" role="alert">{{ actionError }}</div>
      <div v-if="loading" class="approval-status-panel approval-shell-status" role="status"><LoaderCircle class="animate-spin text-blue-600" aria-hidden="true" />正在加载审批中心...</div>
      <div v-else-if="errorMessage" class="approval-alert is-error approval-shell-status" role="alert"><span class="flex-1">{{ errorMessage }}</span><button type="button" class="approval-link-button" @click="refreshSession"><RotateCcw aria-hidden="true" />重试</button></div>

      <PlatformSoftwareSuggestions v-else-if="route.name === 'suggestions'" ref="suggestionsRef" class="platform-suggestions-page"
        app-id="approval-center" :api-get="apiGet" :api-post="apiPost" :api-patch="apiPatch" :api-upload="apiUpload" :api-delete="apiDelete"
        :suspended="discardConfirmOpen" @dirty-change="suggestionsDirty=$event" @busy-change="suggestionsBusy=$event" @request-leave="requestProtectedAction($event)" />
      <section v-else-if="isSettingsPage && !canManageApp" class="approval-permission-empty"><ShieldAlert aria-hidden="true" /><h1>暂无权限设置权限</h1><p>只有审批应用管理员可以配置应用权限。</p><button type="button" class="approval-button approval-button-secondary" @click="navigate(APP_PATH)">返回审批首页</button></section>
      <section v-else-if="isSettingsPage" class="approval-settings-page">
        <div class="approval-settings-workspace">
          <AdminPermissionSettings
            class="min-h-0 flex-1"
            @dirty-change="permissionDirty = $event"
            @confirm-open-change="permissionRefreshConfirmOpen = $event"
            @saved="permissionDirty = false"
          />
        </div>
      </section>
      <section v-else-if="isTemplateManagement && !canManageTemplates" class="approval-permission-empty"><ShieldAlert aria-hidden="true" /><h1>暂无表单管理权限</h1><p>只有拥有分类管理权限的成员可以维护表单和流程。</p><button type="button" class="approval-button approval-button-secondary" @click="navigate(APP_PATH)">返回审批首页</button></section>
      <section v-else-if="isTemplateManagement" class="approval-settings-page">
        <div class="approval-settings-workspace is-template-management">
          <ApprovalWorkspace
            :key="`templates:${refreshKey}`"
            page="templates"
            :query="route.query"
            :can-manage="canManageTemplates"
            :can-manage-app="canManageApp"
            :managed-category-ids="managedCategoryIds"
            :editor-link-for-template="editorWorkbenchLink"
            @navigate="navigate"
            @edit-template="handleEditTemplate"
            @new-template="handleNewTemplate"
            @dirty-change="permissionDirty = $event"
            @confirm-open-change="permissionRefreshConfirmOpen = $event"
            @success-notice="showSuccessNotice"
          />
        </div>
      </section>
      <TemplateEditor v-else-if="isEditor && canManageTemplates" :key="`editor:${route.templateId || route.starterKey}:${route.query?.categoryId || ''}`" :template-id="route.templateId" :starter-key="route.starterKey" :step="route.step" :category-id="route.query?.categoryId || ''" :can-manage-app="canManageApp" :managed-category-ids="managedCategoryIds" @navigate="navigate" @dirty-change="editorDirty = $event" @saved="handleTemplateSaved" @published="refreshKey += 1" @success-notice="showSuccessNotice" @close="closeTemplateEditor" />
      <section v-else-if="isEditor" class="approval-permission-empty"><ShieldAlert aria-hidden="true" /><h1>暂无表单管理权限</h1><p>只有拥有分类管理权限的成员可以维护表单和流程。</p><button type="button" class="approval-button approval-button-secondary" @click="navigate(APP_PATH)">返回审批首页</button></section>
      <ApprovalWorkspace v-else :key="`${workspaceRoute.page}:${refreshKey}`" :page="workspaceRoute.page" :query="workspaceRoute.query" :can-manage="canManageTemplates" :can-manage-app="canManageApp" :managed-category-ids="managedCategoryIds" :editor-link-for-template="editorWorkbenchLink" @navigate="navigate" @open-application="openApplication" @apply="startApplication" @edit-template="handleEditTemplate" @new-template="handleNewTemplate" @success-notice="showSuccessNotice" />
    </main>

    <ApplicationDetailDrawer :open="route.name === 'application-detail'" :application-id="route.applicationId" @close="returnFromOverlay" @changed="handleApplicationChanged" />
    <ApplicationFormDrawer :open="route.name === 'application-form'" :template-id="route.templateId" :draft-id="route.draftId" :initial-draft="activeDraft" @dirty-change="formDirty = $event" @close="closeForm" @submitted="handleApplicationSubmitted" @success-notice="showSuccessNotice" />
    <ApprovalSuccessToast :notice="successNotice" @dismiss="dismissSuccessNotice" />
    <UnsavedChangesDialog :open="discardConfirmOpen" :message="discardConfirmMessage" fallback-focus-selector=".platform-sidebar-item.active" @cancel="continueEditing" @confirm="discardAndContinue" />
  </div>
</template>
