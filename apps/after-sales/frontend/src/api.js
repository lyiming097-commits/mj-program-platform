import { createPlatformApiClient } from "@platform-ui";
import { API_BASE_URL } from "@/config";
import * as sessionStore from "@/session";
import {
  loginSessionPrincipalKey,
  validateOrRecoverLoginSession,
} from "@/features/dingTalkSessionRecovery";

const recoveringSessionStore = {
  ...sessionStore,
  validateLoginSession: async (session) => (
    await validateOrRecoverLoginSession(session)
  ).session,
};

export const { apiFetchRaw, apiGet, apiPost, apiPatch, apiPut, apiUpload, apiDelete } =
  createPlatformApiClient({
    apiBaseUrl: API_BASE_URL,
    sessionStore: recoveringSessionStore,
    identityKey: loginSessionPrincipalKey,
  });
