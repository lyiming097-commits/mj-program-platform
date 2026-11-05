const DING_REAUTH_TIMEOUT_MS = 10000;
const AUTH_REQUEST_TIMEOUT_MS = 15000;

export function loginSessionPrincipalKey(session) {
  if (!session?.userId && !session?.actorUserId) return "";
  return [
    String(session.userId || ""),
    String(session.actorUserId || ""),
    session.isProxying ? "proxy" : "direct",
  ].join(":");
}

function hasSessionIdentity(session) {
  return Boolean(session?.sessionId || session?.userId || session?.actorUserId);
}

function errorMessage(value) {
  if (!value) return "未知钉钉错误";
  if (typeof value === "string") return value;
  if (typeof value?.errorMessage === "string" && value.errorMessage.trim()) return value.errorMessage;
  if (typeof value?.message === "string" && value.message.trim()) return value.message;
  try { return JSON.stringify(value); } catch { return String(value); }
}

async function parseJson(response) {
  try { return await response.json(); } catch { return {}; }
}

export function createDingTalkSessionRecovery({
  apiBaseUrl,
  corpId,
  sessionStore,
  windowObject = window,
  navigatorObject = navigator,
  fetchImpl = (...args) => windowObject.fetch(...args),
  allowInitialLogin = () => false,
} = {}) {
  let recoveryPromise = null;

  function isDesktopDingTalk() {
    const userAgent = navigatorObject?.userAgent || "";
    return /dingtalk/i.test(userAgent)
      && !/(android|iphone|ipad|ipod|mobile|harmonyos)/i.test(userAgent)
      && /(windows|macintosh|mac os x)/i.test(userAgent);
  }

  function runtime() {
    if (isDesktopDingTalk() && windowObject.DingTalkPC?.runtime?.permission?.requestAuthCode) return windowObject.DingTalkPC;
    if (windowObject.dd?.runtime?.permission?.requestAuthCode || windowObject.dd?.getAuthCode) return windowObject.dd;
    if (windowObject.DingTalkPC?.runtime?.permission?.requestAuthCode) return windowObject.DingTalkPC;
    return null;
  }

  function isDingTalkContainer() {
    if (/dingtalk/i.test(navigatorObject?.userAgent || "")) return true;
    const sdk = runtime();
    return Boolean(sdk?.env?.platform && sdk.env.platform !== "notInDingTalk");
  }

  function waitForRuntime() {
    const startedAt = Date.now();
    return new Promise((resolve) => {
      const poll = () => {
        const sdk = runtime();
        if (sdk || Date.now() - startedAt >= DING_REAUTH_TIMEOUT_MS) {
          resolve(sdk);
          return;
        }
        windowObject.setTimeout(poll, 80);
      };
      poll();
    });
  }

  function requestAuthCode(sdk) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (result) => {
        if (settled) return;
        settled = true;
        windowObject.clearTimeout(timeoutId);
        const code = result?.code || result?.authCode || result?.auth_code || "";
        if (code) resolve(code);
        else reject(new Error(`钉钉免登未返回 code：${errorMessage(result)}`));
      };
      const fail = (reason) => {
        if (settled) return;
        settled = true;
        windowObject.clearTimeout(timeoutId);
        reject(new Error(errorMessage(reason)));
      };
      const timeoutId = windowObject.setTimeout(() => fail("钉钉免登授权超时"), DING_REAUTH_TIMEOUT_MS);
      const request = sdk?.runtime?.permission?.requestAuthCode;
      try {
        if (typeof request === "function") {
          const result = request({ corpId, onSuccess: finish, success: finish, onFail: fail, fail });
          if (result && typeof result.then === "function") result.then(finish).catch(fail);
          windowObject.setTimeout(() => {
            if (!settled && typeof sdk?.getAuthCode === "function") {
              const fallback = sdk.getAuthCode({ corpId, onSuccess: finish, success: finish, onFail: fail, fail });
              if (fallback && typeof fallback.then === "function") fallback.then(finish).catch(fail);
            }
          }, 2500);
          return;
        }
        if (typeof sdk?.getAuthCode === "function") {
          const result = sdk.getAuthCode({ corpId, onSuccess: finish, success: finish, onFail: fail, fail });
          if (result && typeof result.then === "function") result.then(finish).catch(fail);
          return;
        }
        fail("当前钉钉容器不支持免登授权接口");
      } catch (reason) { fail(reason); }
    });
  }

  function canRecover(reason, previousSession) {
    if (!isDingTalkContainer()) return false;
    if (!hasSessionIdentity(previousSession) && !allowInitialLogin()) return false;
    if (Number(reason?.status || 0) !== 401) return false;
    const code = String(reason?.code || "").trim();
    return code === "MISSING_AUTH_TOKEN"
      || (!code && /missing auth token/i.test(String(reason?.message || "")));
  }

  async function loginSilently(previousSession) {
    if (!String(corpId || "").trim()) throw new Error("缺少钉钉 corpId 配置");
    const sdk = await waitForRuntime();
    if (!sdk) throw new Error("钉钉 JS-SDK 未加载完成");
    const authCode = await requestAuthCode(sdk);
    const controller = new AbortController();
    const timeoutId = windowObject.setTimeout(() => controller.abort(), AUTH_REQUEST_TIMEOUT_MS);
    let response;
    try {
      response = await fetchImpl(new URL("/api/auth/code", apiBaseUrl).toString(), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ authCode, loginType: "workbench" }),
        signal: controller.signal,
      });
    } catch (reason) {
      if (reason?.name === "AbortError") throw new Error("钉钉免登请求超时");
      throw reason;
    } finally { windowObject.clearTimeout(timeoutId); }

    const data = await parseJson(response);
    if (!response.ok) {
      const reason = new Error(data?.error || data?.message || "钉钉免登失败");
      reason.status = response.status;
      reason.code = data?.code || "";
      throw reason;
    }
    const nextSession = { ...(previousSession || {}), ...data };
    sessionStore.saveLoginSession(nextSession);
    const previousPrincipal = loginSessionPrincipalKey(previousSession);
    const nextPrincipal = loginSessionPrincipalKey(nextSession);
    if (previousPrincipal && nextPrincipal && previousPrincipal !== nextPrincipal) {
      const reason = new Error("登录身份已切换，正在重新加载页面");
      reason.code = "AUTH_SESSION_CHANGED";
      windowObject.location.reload();
      throw reason;
    }
    return nextSession;
  }

  function validateOrRecoverLoginSession(savedSession = sessionStore.loadLoginSession()) {
    if (!recoveryPromise) {
      recoveryPromise = (async () => {
        const previousSession = savedSession || sessionStore.loadLoginSession();
        try {
          const validated = await sessionStore.validateLoginSession(previousSession);
          const nextSession = { ...(previousSession || {}), ...validated };
          sessionStore.saveLoginSession(nextSession, { broadcast: false });
          return { session: nextSession, recovered: false };
        } catch (reason) {
          if (!canRecover(reason, previousSession)) throw reason;
          try {
            return { session: await loginSilently(previousSession), recovered: true };
          } catch (recoveryError) {
            if (recoveryError?.code === "AUTH_SESSION_CHANGED") throw recoveryError;
            recoveryError.status = Number(recoveryError?.status || 0) || 401;
            recoveryError.code = recoveryError?.code || "DINGTALK_SESSION_RECOVERY_FAILED";
            throw recoveryError;
          }
        }
      })().finally(() => { recoveryPromise = null; });
    }
    return recoveryPromise;
  }

  return { isDingTalkContainer, validateOrRecoverLoginSession };
}
