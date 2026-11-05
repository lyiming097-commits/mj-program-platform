<script setup>
import { onBeforeUnmount, onMounted } from "vue";
import { loginSessionIdentityKey, startSessionKeepAlive } from "@platform-ui";
import {
  LOGIN_SESSION_CHANGE_EVENT,
  clearLoginSession,
  loadLoginSession,
  saveLoginSession,
  validateLoginSession,
} from "@/session";

let currentIdentityKey = loginSessionIdentityKey(loadLoginSession());
let stopSessionKeepAlive = null;

function redirectToLogin(error) {
  clearLoginSession();
  const params = new URLSearchParams();
  const message = error instanceof Error ? error.message : "登录已失效";
  if (message) params.set("error", message);
  window.location.href = params.toString() ? `/auth/?${params.toString()}` : "/auth/";
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

onMounted(async () => {
  window.addEventListener(LOGIN_SESSION_CHANGE_EVENT, handleSessionChange);
  try {
    const session = { ...(loadLoginSession() || {}), ...await validateLoginSession(loadLoginSession()) };
    currentIdentityKey = loginSessionIdentityKey(session);
    saveLoginSession(session);
    stopSessionKeepAlive = startSessionKeepAlive({
      shouldRun: () => Boolean(loadLoginSession()),
      validate: () => validateLoginSession(loadLoginSession()),
      onValidated: (validatedSession) => {
        const nextSession = { ...(loadLoginSession() || {}), ...validatedSession };
        currentIdentityKey = loginSessionIdentityKey(nextSession);
        saveLoginSession(nextSession, { broadcast: false });
      },
      onError: (error) => {
        if ([401, 403].includes(Number(error?.status || 0))) redirectToLogin(error);
      },
    });
  } catch (error) {
    redirectToLogin(error);
  }
});

onBeforeUnmount(() => {
  window.removeEventListener(LOGIN_SESSION_CHANGE_EVENT, handleSessionChange);
  stopSessionKeepAlive?.();
});
</script>
