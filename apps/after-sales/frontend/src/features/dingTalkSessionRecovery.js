import { API_BASE_URL, DING_CORP_ID } from "@/config";
import * as sessionStore from "@/session";
import { createDingTalkSessionRecovery } from "./dingTalkSessionRecoveryCore";

const recovery = createDingTalkSessionRecovery({
  apiBaseUrl: API_BASE_URL,
  corpId: DING_CORP_ID,
  sessionStore,
  allowInitialLogin: () => {
    const url = new URL(window.location.href);
    return url.pathname.replace(/\/+$/, "") === "/after-sales/presales"
      && Boolean(url.searchParams.get("projectId") && url.searchParams.get("nodeKey") && url.searchParams.get("roundId"));
  },
});

export const { isDingTalkContainer, validateOrRecoverLoginSession } = recovery;
export { loginSessionPrincipalKey } from "./dingTalkSessionRecoveryCore";
