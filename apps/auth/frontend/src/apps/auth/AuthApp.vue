<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { loginSessionIdentityKey, startSessionKeepAlive } from "@platform-ui";
import LoginResultPage from "@/components/login/LoginResultPage.vue";
import ScanLoginPage from "@/components/login/ScanLoginPage.vue";
import SettingsOrganizationPage from "@/components/settings/SettingsOrganizationPage.vue";
import SettingsUnsavedChangesDialog from "@/components/settings/SettingsUnsavedChangesDialog.vue";
import {
  AUTH_LOGIN_PATH,
  SETTINGS_APPLICATION_TEMPLATE_PATH,
  RESULT_PATH,
  SETTINGS_ADMINISTRATIVE_REGIONS_PATH,
  SETTINGS_BUSINESS_REGISTRY_PATH,
  SETTINGS_ROBOT_MESSAGES_PATH,
  SETTINGS_NOTIFICATIONS_PATH,
  SETTINGS_COMPANY_ENTITIES_LEAVE_EVENT,
  SETTINGS_COMPANY_ENTITIES_PATH,
  SETTINGS_HANDOVER_PATH,
  SETTINGS_ORGANIZATION_PERMISSIONS_PATH,
  SETTINGS_ORGANIZATION_PATH,
  SETTINGS_ENABLED_DEPARTMENTS_PATH,
} from "@/config";
import { getCurrentPath, ROUTE_CHANGE_EVENT } from "@/router-lite";
import {
  LOGIN_SESSION_CHANGE_EVENT,
  clearLoginSession,
  loadLoginSession,
  saveLoginSession,
  validateLoginSession,
} from "@/session";

const routePath = ref(getCurrentPath());
const isLoginResultPage = computed(() => routePath.value === RESULT_PATH);
const isOrganizationPage = computed(() => routePath.value === SETTINGS_ORGANIZATION_PATH);
const isEnabledDepartmentsPage = computed(() => routePath.value === SETTINGS_ENABLED_DEPARTMENTS_PATH);
const isHandoverPage = computed(() => routePath.value === SETTINGS_HANDOVER_PATH);
const isPermissionsPage = computed(() => routePath.value === SETTINGS_ORGANIZATION_PERMISSIONS_PATH);
const isCompanyEntitiesPage = computed(() => routePath.value === SETTINGS_COMPANY_ENTITIES_PATH);
const isAdministrativeRegionsPage = computed(() => routePath.value === SETTINGS_ADMINISTRATIVE_REGIONS_PATH);
const isApplicationTemplatePage = computed(() => routePath.value === SETTINGS_APPLICATION_TEMPLATE_PATH);
const isBusinessRegistryPage = computed(() => routePath.value === SETTINGS_BUSINESS_REGISTRY_PATH);
const isRobotMessagesPage = computed(() => routePath.value === SETTINGS_ROBOT_MESSAGES_PATH);
const isNotificationsPage = computed(() => routePath.value === SETTINGS_NOTIFICATIONS_PATH);
const isSettingsPage = computed(() => (
  isOrganizationPage.value
  || isRobotMessagesPage.value
  || isNotificationsPage.value
  || isEnabledDepartmentsPage.value
  || isHandoverPage.value
  || isPermissionsPage.value
  || isCompanyEntitiesPage.value
  || isAdministrativeRegionsPage.value
  || isBusinessRegistryPage.value
  || isApplicationTemplatePage.value
));
const isLoginPage = computed(() => routePath.value === AUTH_LOGIN_PATH || routePath.value === `${AUTH_LOGIN_PATH}/`);
const organizationSettingsDirty = ref(false);
const organizationSettingsSaving = ref(false);
const routeLeaveConfirmOpen = ref(false);
let currentIdentityKey = loginSessionIdentityKey(loadLoginSession());
let stopSessionKeepAlive = null;
let pendingRoutePath = "";

function cancelRouteLeave() {
  pendingRoutePath = "";
  routeLeaveConfirmOpen.value = false;
}

function discardAndContinueRouteLeave() {
  const nextPath = pendingRoutePath;
  pendingRoutePath = "";
  routeLeaveConfirmOpen.value = false;
  if (!nextPath) return;
  organizationSettingsDirty.value = false;
  window.history.replaceState({}, "", nextPath);
  routePath.value = nextPath;
}

function updateRoutePath(event) {
  const nextPath = event?.detail?.path || getCurrentPath();
  if (
    event?.type === "popstate"
    && routePath.value === SETTINGS_COMPANY_ENTITIES_PATH
    && nextPath !== routePath.value
    && (organizationSettingsSaving.value || organizationSettingsDirty.value)
  ) {
    window.history.pushState({}, "", routePath.value);
    window.dispatchEvent(new CustomEvent(SETTINGS_COMPANY_ENTITIES_LEAVE_EVENT, {
      cancelable: true,
      detail: {
        continue: () => {
          organizationSettingsDirty.value = false;
          organizationSettingsSaving.value = false;
          window.history.replaceState({}, "", nextPath);
          routePath.value = nextPath;
        },
      },
    }));
    return;
  }
  if (
    event?.type === "popstate"
    && [SETTINGS_ORGANIZATION_PATH, SETTINGS_ORGANIZATION_PERMISSIONS_PATH, SETTINGS_ROBOT_MESSAGES_PATH, SETTINGS_NOTIFICATIONS_PATH].includes(routePath.value)
    && nextPath !== routePath.value
  ) {
    if (organizationSettingsSaving.value) {
      window.history.pushState({}, "", routePath.value);
      return;
    }
    if (!organizationSettingsDirty.value) {
      routePath.value = nextPath;
      return;
    }
    if (window.matchMedia("(max-width: 767px)").matches) {
      if (!window.confirm("组织配置有未保存的修改，确认放弃并离开？")) {
        window.history.pushState({}, "", routePath.value);
        return;
      }
      organizationSettingsDirty.value = false;
      routePath.value = nextPath;
      return;
    }
    window.history.pushState({}, "", routePath.value);
    if (routeLeaveConfirmOpen.value) {
      return;
    }
    pendingRoutePath = nextPath;
    routeLeaveConfirmOpen.value = true;
    return;
  }
  routePath.value = nextPath;
}

function handleSessionChange(event) {
  const nextSession = event?.detail?.session ?? loadLoginSession();
  const nextIdentityKey = loginSessionIdentityKey(nextSession);
  if (event?.detail?.remote && nextIdentityKey !== currentIdentityKey) {
    window.location.reload();
    return;
  }
  currentIdentityKey = nextIdentityKey;
}

function handleKeepAliveError(reason) {
  if (![401, 403].includes(Number(reason?.status || 0))) {
    return;
  }
  clearLoginSession();
  window.location.assign(AUTH_LOGIN_PATH);
}

function handleBeforeUnload(event) {
  if (!organizationSettingsDirty.value && !organizationSettingsSaving.value) return;
  event.preventDefault();
  event.returnValue = "";
}

onMounted(() => {
  if (routePath.value === SETTINGS_ENABLED_DEPARTMENTS_PATH) {
    window.history.replaceState({}, "", SETTINGS_ORGANIZATION_PATH);
    routePath.value = SETTINGS_ORGANIZATION_PATH;
  }
  window.addEventListener(ROUTE_CHANGE_EVENT, updateRoutePath);
  window.addEventListener("popstate", updateRoutePath);
  window.addEventListener(LOGIN_SESSION_CHANGE_EVENT, handleSessionChange);
  window.addEventListener("beforeunload", handleBeforeUnload);
  stopSessionKeepAlive = startSessionKeepAlive({
    shouldRun: () => isSettingsPage.value && Boolean(loadLoginSession()),
    validate: () => validateLoginSession(loadLoginSession()),
    onValidated: (validatedSession) => {
      const nextSession = { ...(loadLoginSession() || {}), ...validatedSession };
      currentIdentityKey = loginSessionIdentityKey(nextSession);
      saveLoginSession(nextSession, { broadcast: false });
    },
    onError: handleKeepAliveError,
  });
});

onBeforeUnmount(() => {
  window.removeEventListener(ROUTE_CHANGE_EVENT, updateRoutePath);
  window.removeEventListener("popstate", updateRoutePath);
  window.removeEventListener(LOGIN_SESSION_CHANGE_EVENT, handleSessionChange);
  window.removeEventListener("beforeunload", handleBeforeUnload);
  stopSessionKeepAlive?.();
});
</script>

<template>
  <LoginResultPage v-if="isLoginResultPage" />

  <div v-else-if="isSettingsPage" class="flex h-screen min-h-screen flex-col overflow-hidden bg-slate-100 text-slate-900">
    <SettingsOrganizationPage
      :initial-management-tab="isNotificationsPage ? 'notifications' : isRobotMessagesPage ? 'robot-messages' : isApplicationTemplatePage ? 'application-template' : isBusinessRegistryPage ? 'business-registry' : isAdministrativeRegionsPage ? 'administrative-regions' : isCompanyEntitiesPage ? 'company-entities' : isPermissionsPage ? 'permissions' : isHandoverPage ? 'inactive' : 'department'"
      @dirty-change="organizationSettingsDirty = Boolean($event)"
      @saving-change="organizationSettingsSaving = Boolean($event)"
    />
  </div>

  <ScanLoginPage v-else-if="isLoginPage" />
  <ScanLoginPage v-else />

  <SettingsUnsavedChangesDialog
    :open="routeLeaveConfirmOpen"
    @cancel="cancelRouteLeave"
    @confirm="discardAndContinueRouteLeave"
  />
</template>
