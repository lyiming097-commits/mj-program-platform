import { readonly, shallowRef } from "vue";
import {
  ApiError,
  del,
  onStoredSessionCleared,
  post,
  readStoredSession,
  renewStoredSession,
  requestWeChatLogin,
  writeStoredSession,
} from "@/api/client";
import type {
  MiniSession,
  WeChatLoginResult,
  WeChatRegistrationChallenge,
} from "@/api/types";
import { resetMobileTasks } from "@/composables/useMobileTasks";

type SessionState =
  | { status: "anonymous"; session: null }
  | { status: "restoring"; session: MiniSession | null }
  | { status: "registration"; session: null; challenge: WeChatRegistrationChallenge }
  | { status: "authenticated"; session: MiniSession };

const MANUAL_LOGOUT_STORAGE_KEY = "mj.afterSales.mini.manualLogout";

const state = shallowRef<SessionState>(
  readStoredSession()
    ? { status: "authenticated", session: readStoredSession() as MiniSession }
    : { status: "anonymous", session: null },
);
let restorePromise: Promise<boolean> | null = null;
let restoreEpoch = -1;
let sessionEpoch = 0;

onStoredSessionCleared(() => {
  sessionEpoch += 1;
  resetMobileTasks();
  state.value = { status: "anonymous", session: null };
});

function saveSession(session: MiniSession): void {
  sessionEpoch += 1;
  const previousUserId = state.value.session?.user.userId || readStoredSession()?.user.userId || "";
  if (!previousUserId || previousUserId !== session.user.userId) resetMobileTasks();
  uni.removeStorageSync(MANUAL_LOGOUT_STORAGE_KEY);
  writeStoredSession(session);
  state.value = { status: "authenticated", session };
}

function isRegistrationChallenge(value: WeChatLoginResult): value is WeChatRegistrationChallenge {
  return "registrationRequired" in value && value.registrationRequired === true;
}

export async function loginWithWeChat(): Promise<WeChatLoginResult> {
  const loginEpoch = sessionEpoch;
  const result = await requestWeChatLogin();
  if (loginEpoch !== sessionEpoch) throw new ApiError("登录状态已变更，请重新登录", 401, "AUTH_SESSION_CHANGED");
  uni.removeStorageSync(MANUAL_LOGOUT_STORAGE_KEY);
  if (isRegistrationChallenge(result)) {
    writeStoredSession(null);
    state.value = { status: "registration", session: null, challenge: result };
    return result;
  }
  saveSession(result);
  return result;
}

export async function registerWithWeChat(
  registrationToken: string,
  name: string,
  privacyVersion: string,
): Promise<MiniSession> {
  const registrationEpoch = sessionEpoch;
  const session = await post<MiniSession>(
    "/api/auth/wechat-mini/register",
    { registrationToken, name, privacyAccepted: true, privacyVersion },
    false,
  );
  if (registrationEpoch !== sessionEpoch) throw new ApiError("登录状态已变更，请重新登录", 401, "AUTH_SESSION_CHANGED");
  saveSession(session);
  return session;
}

export function deleteWeChatAccount(): Promise<{ ok: true; message: string }> {
  return del("/api/auth/wechat-mini/account");
}

export async function logoutWithWeChat(): Promise<void> {
  const logoutEpoch = sessionEpoch;
  try {
    await post("/api/auth/logout");
  } catch {
    // Local credentials must still be removed when the network is unavailable.
  } finally {
    if (logoutEpoch === sessionEpoch || !readStoredSession()) {
      clearSession();
      uni.setStorageSync(MANUAL_LOGOUT_STORAGE_KEY, true);
    }
  }
}

export function isManuallyLoggedOut(): boolean {
  return uni.getStorageSync(MANUAL_LOGOUT_STORAGE_KEY) === true;
}

export function restoreSession(): Promise<boolean> {
  if (restorePromise && restoreEpoch === sessionEpoch) return restorePromise;
  const existing = readStoredSession();
  if (!existing) {
    clearSession();
    return Promise.resolve(false);
  }
  state.value = { status: "restoring", session: existing };
  const requestEpoch = sessionEpoch;
  const restoring = renewStoredSession()
    .then((session) => {
      if (requestEpoch !== sessionEpoch || readStoredSession()?.token !== session.token) return false;
      saveSession(session);
      return true;
    })
    .catch(() => {
      if (requestEpoch === sessionEpoch) clearSession();
      return false;
    })
    .finally(() => { if (restorePromise === restoring) restorePromise = null; });
  restorePromise = restoring;
  restoreEpoch = requestEpoch;
  return restoring;
}

export function clearSession(): void {
  writeStoredSession(null);
}

export function useSession() {
  return {
    state: readonly(state),
    loginWithWeChat,
    registerWithWeChat,
    restoreSession,
    clearSession,
  };
}
