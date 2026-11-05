import { computed, readonly, shallowRef } from "vue";

import { loginSessionIdentityKey, startSessionKeepAlive } from "@platform-ui";

import {
  fetchExpirySummary,
  fetchPermissions,
  fetchSidebarMetrics,
} from "@/features/competitiveApi";
import {
  loginSessionPrincipalKey,
  validateOrRecoverLoginSession,
} from "@/features/dingTalkSessionRecovery";
import {
  loadLoginSession,
  saveLoginSession,
  clearLoginSession,
  hasLoginSessionIdentity,
} from "@/session";

const session = shallowRef(loadLoginSession());
const access = shallowRef({
  permissions: [],
  canAccess: false,
  canCollect: false,
  canReview: false,
  canManage: false,
});
const accessReady = shallowRef(false);
const metrics = shallowRef(null);
const expiry = shallowRef(null);
const loading = shallowRef(false);
const error = shallowRef("");
let currentIdentityKey = loginSessionIdentityKey(session.value);
let currentPrincipalKey = loginSessionPrincipalKey(session.value);
let currentIdentityEstablished = hasLoginSessionIdentity(session.value);
let stopSessionKeepAlive = null;

function redirectToLoginWithError(reason) {
  clearLoginSession();
  const message = reason instanceof Error ? reason.message : "登录已失效";
  const params = new URLSearchParams();
  if (message) params.set("error", message);
  window.location.assign(params.toString() ? `/auth/?${params.toString()}` : "/auth/");
}

function startKeepAlive() {
  if (stopSessionKeepAlive) return;
  stopSessionKeepAlive = startSessionKeepAlive({
    shouldRun: () => Boolean(loadLoginSession()),
    validate: () => validateOrRecoverLoginSession(loadLoginSession()),
    onValidated: ({ session: nextSession, recovered }) => {
      const nextIdentityKey = loginSessionIdentityKey(nextSession);
      const nextPrincipalKey = loginSessionPrincipalKey(nextSession);
      const sameRecoveredPrincipal = recovered
        && currentPrincipalKey
        && nextPrincipalKey === currentPrincipalKey;
      if (currentIdentityEstablished && nextIdentityKey !== currentIdentityKey && !sameRecoveredPrincipal) {
        window.location.reload();
        return;
      }
      currentIdentityKey = nextIdentityKey;
      currentPrincipalKey = nextPrincipalKey;
      currentIdentityEstablished = hasLoginSessionIdentity(nextSession);
      session.value = nextSession;
      saveLoginSession(nextSession, { broadcast: false });
    },
    onError: (reason) => {
      if ([401, 403].includes(Number(reason?.status || 0))) {
        redirectToLoginWithError(reason);
      }
    },
  });
}

async function refreshContext() {
  loading.value = true;
  error.value = "";
  try {
    const { session: nextSession } = await validateOrRecoverLoginSession(session.value);
    session.value = nextSession;
    currentIdentityKey = loginSessionIdentityKey(nextSession);
    currentPrincipalKey = loginSessionPrincipalKey(nextSession);
    currentIdentityEstablished = hasLoginSessionIdentity(nextSession);
    saveLoginSession(nextSession, { broadcast: false });
    startKeepAlive();
    const nextAccess = await fetchPermissions();
    session.value = { ...nextSession, ...nextAccess };
    access.value = nextAccess;
    accessReady.value = true;
    const [metricsResult, expiryResult] = await Promise.allSettled([
      nextAccess.canAccess ? fetchSidebarMetrics() : null,
      nextAccess.canReview ? fetchExpirySummary() : null,
    ]);
    metrics.value = metricsResult.status === "fulfilled" ? metricsResult.value : null;
    expiry.value = expiryResult.status === "fulfilled" ? expiryResult.value : null;
    if (metricsResult.status === "rejected") throw metricsResult.reason;
    if (expiryResult.status === "rejected") throw expiryResult.reason;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "系统数据加载失败";
    if ([401, 403].includes(Number(reason?.status || 0))) {
      redirectToLoginWithError(reason);
    }
    throw reason;
  } finally {
    loading.value = false;
  }
}

async function refreshMetrics() {
  metrics.value = access.value.canAccess ? await fetchSidebarMetrics() : null;
}

async function refreshExpiry() {
  expiry.value = access.value.canReview ? await fetchExpirySummary() : null;
}

export function useAppContext() {
  return {
    session: readonly(session),
    access: readonly(access),
    accessReady: readonly(accessReady),
    metrics: readonly(metrics),
    expiry: readonly(expiry),
    loading: readonly(loading),
    error: readonly(error),
    expiryCount: computed(
      () => (expiry.value?.upcomingCount || 0) + (expiry.value?.expiredCount || 0),
    ),
    refreshContext,
    refreshMetrics,
    refreshExpiry,
  };
}
