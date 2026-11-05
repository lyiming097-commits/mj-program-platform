import { createPlatformSessionStore } from "@platform-ui";
import { API_BASE_URL } from "@/config";

const sessionStore = createPlatformSessionStore({
  apiBaseUrl: API_BASE_URL,
});
export const {
  LOGIN_SESSION_KEY,
  LOGIN_SESSION_CHANGE_EVENT,
  loadLoginSession,
  saveLoginSession,
  clearLoginSession,
  validateLoginSession,
  logoutLoginSession,
  applyAuthTokenRefreshFromResponse,
} = sessionStore;
