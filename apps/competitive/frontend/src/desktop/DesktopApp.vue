<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, shallowRef } from "vue";
import { Lightbulb } from "@lucide/vue";
import { PlatformSoftwareSuggestions, PlatformUnsavedChangesDialog, isSoftwareSuggestionsPath, useSoftwareSuggestionsContext, useSoftwareSuggestionsGuard } from "@platform-ui";
import { apiGet, apiPost, apiPatch, apiUpload, apiDelete } from "@/api";
import {
  ClipboardCheck,
  FileStack,
  LayoutDashboard,
  Settings,
} from "lucide-vue-next";

import { useAppContext } from "@/composables/useAppContext";
import AppToast from "@/shared/AppToast.vue";
import AppConfirmDialog from "@/shared/AppConfirmDialog.vue";
import DesktopAuditPage from "@/desktop/pages/DesktopAuditPage.vue";
import DesktopBoardPage from "@/desktop/pages/DesktopBoardPage.vue";
import DesktopCollectionPage from "@/desktop/pages/DesktopCollectionPage.vue";
import DesktopExpiryDrawer from "@/desktop/components/DesktopExpiryDrawer.vue";
import DesktopSettingsPage from "@/desktop/pages/DesktopSettingsPage.vue";
import CompetitiveSidebar from "@/desktop/components/CompetitiveSidebar.vue";

const page = shallowRef(isSoftwareSuggestionsPath("competitive") ? "suggestions" : "board");
const { suggestionsRef, suggestionsDirty, suggestionsBusy, suggestionsConfirmOpen, requestSuggestionsAction, interceptSuggestionsAction, cancelSuggestionsLeave, confirmSuggestionsLeave } = useSoftwareSuggestionsGuard();
useSoftwareSuggestionsContext("competitive", path => requestSuggestionsAction(() => {
  pendingSuggestionPath = path;
  requestPage("suggestions");
  if (page.value === "suggestions") applyPendingSuggestionPath();
}));
const toast = shallowRef("");
const expiryOpen = shallowRef(false);
const auditEditing = shallowRef(false);
const settingsDirty = shallowRef(false);
const pendingPage = shallowRef("");
let toastTimer;
let pendingSuggestionPath = "";
function applyPendingSuggestionPath() {
  const path = pendingSuggestionPath;
  pendingSuggestionPath = "";
  if (path) nextTick(() => suggestionsRef.value?.navigate(path));
}

const {
  access,
  accessReady,
  metrics,
  expiry,
  loading,
  error,
  refreshContext,
  refreshMetrics,
  refreshExpiry,
} = useAppContext();

const navItems = computed(() => [
  { id: "board", label: "竞品看板", icon: LayoutDashboard, visible: true },
  { id: "collection", label: "采集列表", icon: FileStack, visible: access.value.canCollect },
  { id: "audit", label: "资料审核", icon: ClipboardCheck, visible: access.value.canReview },
  { id: "settings", label: "系统设置", icon: Settings, visible: access.value.canManage },
  { id: "suggestions", label: "本软件优化建议", icon: Lightbulb, visible: true },
].filter((item) => item.visible));

function notify(message) {
  toast.value = message;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { toast.value = ""; }, 2400);
}

function selectPage(item) {
  if (item.id.startsWith("metric-")) return;
  requestPage(item.id);
}

function requestPage(nextPage) {
  if (interceptSuggestionsAction(() => requestPage(nextPage))) return;
  if (nextPage === page.value) return;
  if ((page.value === "audit" && auditEditing.value)
    || (page.value === "settings" && settingsDirty.value)) {
    pendingPage.value = nextPage;
    return;
  }
  auditEditing.value = false;
  settingsDirty.value = false;
  commitPage(nextPage);
}

function commitPage(nextPage) {
  const path = nextPage === "suggestions" ? "/competitive/suggestions/" : "/competitive/";
  window.history.replaceState({ ...window.history.state, __competitivePage: page.value }, "");
  if (window.location.pathname !== path) window.history.pushState({ __competitivePage: nextPage }, "", path);
  page.value = nextPage;
  if (nextPage === "suggestions") applyPendingSuggestionPath();
}
function handlePopState(event) {
  const path = window.location.pathname + window.location.search;
  const nextPage = isSoftwareSuggestionsPath("competitive") ? "suggestions" : event.state?.__competitivePage || "board";
  if (suggestionsDirty.value || suggestionsBusy.value) {
    window.history.pushState({ __competitivePage: page.value }, "", suggestionsRef.value?.getLocation() || "/competitive/suggestions/");
    requestSuggestionsAction(() => window.history.back());
    return;
  }
  if ((page.value === "audit" && auditEditing.value) || (page.value === "settings" && settingsDirty.value)) {
    window.history.pushState({ __competitivePage: page.value }, "", "/competitive/");
    if (nextPage === "suggestions") pendingSuggestionPath = path;
    requestPage(nextPage);
    return;
  }
  page.value = nextPage;
  if (nextPage === "suggestions") nextTick(() => suggestionsRef.value?.navigate(path));
}

function discardAndNavigate() {
  const nextPage = pendingPage.value;
  pendingPage.value = "";
  auditEditing.value = false;
  settingsDirty.value = false;
  commitPage(nextPage);
}


async function openExpiry() {
  expiryOpen.value = true;
  try { await refreshExpiry(); } catch (reason) { notify(reason.message || "到期任务加载失败"); }
}

async function handleChanged(message) {
  await refreshMetrics();
  notify(message);
}

async function loadContext() {
  if (loading.value) return;
  try { await refreshContext(); } catch { notify(error.value || "系统数据加载失败"); }
}

onMounted(loadContext);
onMounted(() => window.addEventListener("popstate", handlePopState));
onBeforeUnmount(() => window.removeEventListener("popstate", handlePopState));

</script>

<template>
  <div class="desktop-shell">
    <div class="desktop-body">
      <CompetitiveSidebar
        :access="access"
        :active-item-id="page"
        :items="navItems"
        :metrics="metrics"
        :ready="accessReady"
        :loading="loading"
        :error="error"
        @item-click="selectPage"
        @retry="loadContext"
      />
      <main class="desktop-content" :class="{ 'audit-workspace': accessReady && ['audit','suggestions'].includes(page) }">
        <div v-if="!accessReady" class="context-feedback" :role="error ? 'alert' : 'status'">
          <p>{{ error ? `权限加载失败：${error}` : '正在校验访问权限...' }}</p>
          <button v-if="error" type="button" class="btn" :disabled="loading" @click="loadContext">重试</button>
        </div>
        <PlatformSoftwareSuggestions v-else-if="page === 'suggestions'" ref="suggestionsRef"
          app-id="competitive" :api-get="apiGet" :api-post="apiPost" :api-patch="apiPatch" :api-upload="apiUpload" :api-delete="apiDelete"
          :suspended="suggestionsConfirmOpen" @dirty-change="suggestionsDirty=$event" @busy-change="suggestionsBusy=$event" @request-leave="requestSuggestionsAction($event)" />
        <DesktopBoardPage v-else-if="page === 'board'" :access="access" :expiry="expiry" @notify="notify" @open-expiry="openExpiry" />
        <DesktopCollectionPage v-else-if="page === 'collection'" @changed="handleChanged" @notify="notify" />
        <DesktopAuditPage v-else-if="page === 'audit'" @changed="handleChanged" @notify="notify" @editing-change="auditEditing = $event" />
        <DesktopSettingsPage v-else-if="page === 'settings'" @notify="notify" @dirty-change="settingsDirty = $event" />
      </main>
    </div>
    <DesktopExpiryDrawer :open="expiryOpen" :summary="expiry" @close="expiryOpen = false" />
    <AppConfirmDialog
      :open="Boolean(pendingPage)"
      title="放弃未保存的修改？"
      :description="page === 'settings' ? '系统设置尚未保存，离开后本次修改将不会保留。' : '当前审核内容尚未保存，离开后本次修改将不会保留。'"
      confirm-label="放弃修改"
      cancel-label="继续编辑"
      danger
      @cancel="pendingPage = ''; pendingSuggestionPath = ''"
      @confirm="discardAndNavigate"
    />
    <AppToast :message="toast" />
    <PlatformUnsavedChangesDialog :open="suggestionsConfirmOpen" @cancel="cancelSuggestionsLeave" @confirm="confirmSuggestionsLeave" />
  </div>
</template>

<style scoped>
.desktop-shell { display: flex; width: 100vw; height: 100vh; flex-direction: column; overflow: hidden; background: #f3f6fa; }
.desktop-body { display: flex; min-height: 0; flex: 1; }
.desktop-content { min-width: 0; min-height: 0; flex: 1; overflow: auto; padding: 16px; }
.desktop-content.audit-workspace { display: flex; flex-direction: column; overflow: hidden; }
.context-feedback { display: flex; min-height: 160px; align-items: center; justify-content: center; flex-direction: column; gap: 12px; color: #64748b; font-size: 13px; }
.context-feedback p { margin: 0; }
</style>
