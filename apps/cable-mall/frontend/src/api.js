import { createPlatformApiClient } from "@platform-ui";

import { API_BASE_URL } from "@/config";
import * as sessionStore from "@/session";

export const {
  apiFetchRaw,
  apiGet,
  apiPost,
  apiPatch,
  apiPut,
  apiUpload,
  apiDelete,
} = createPlatformApiClient({
  apiBaseUrl: API_BASE_URL,
  sessionStore,
});
