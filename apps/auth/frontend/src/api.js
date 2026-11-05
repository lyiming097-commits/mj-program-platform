import { API_BASE_URL } from "@/config";
import { DING_CORP_ID } from "@/config";
import { loginSessionIdentityKey } from "@platform-ui";
import {
  applyAuthTokenRefreshFromResponse,
  clearLoginSession,
  loadLoginSession,
  saveLoginSession,
  validateLoginSession,
} from "@/session";
import { ensureDingTalkRuntimeSdk } from "@/dingtalk-sdk";

const DEFAULT_REQUEST_TIMEOUT_MS = 15000;
const DING_REAUTH_TIMEOUT_MS = 10000;
const WORKBENCH_LOGIN_TYPE = "workbench";
let dingTalkReloginPromise = null;
let authRevalidationPromise = null;

function buildUrl(path, params = null) {
  const url = new URL(path, API_BASE_URL);
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") {
        return;
      }
      url.searchParams.set(key, String(value));
    });
  }
  return url.toString();
}

function redirectToLogin(message) {
  clearLoginSession();
  const params = new URLSearchParams();
  if (message) {
    params.set("error", message);
  }
  window.location.href = params.toString() ? `/auth/?${params.toString()}` : "/auth/";
}

const AUTH_FAILURE_CODES = new Set([
  "INVALID_AUTH_TOKEN",
  "MISSING_AUTH_TOKEN",
  "AUTH_SESSION_REVOKED",
  "AUTH_SESSION_NOT_FOUND",
  "AUTH_SESSION_MISMATCH",
  "AUTH_SESSION_CHANGED",
  "AUTH_VERSION_MISMATCH",
  "EMPLOYEE_INACTIVE",
  "ACCOUNT_DISABLED",
  "EMPLOYEE_NOT_ALLOWED",
  "PROXY_ACTOR_NOT_FOUND",
  "PROXY_ACTOR_INACTIVE",
  "PROXY_ACTOR_ACCOUNT_DISABLED",
  "PROXY_AUTH_VERSION_MISMATCH",
  "PROXY_ACTOR_NOT_SYSTEM_ADMIN",
]);

function shouldRedirectForbidden(error) {
  return AUTH_FAILURE_CODES.has(error?.code) || String(error?.message || "").includes("登录已失效");
}

function responseError(response, data, fallbackMessage) {
  const error = new Error(data?.error || data?.message || fallbackMessage);
  error.status = response.status;
  error.code = data?.code || "";
  error.requestId = data?.requestId || response.headers.get("X-Request-Id") || "";
  return error;
}

function formatDingTalkError(value) {
  if (!value) return "Unknown DingTalk error";
  if (typeof value === "string") return value;
  if (typeof value?.errorMessage === "string" && value.errorMessage.trim()) return value.errorMessage;
  if (typeof value?.message === "string" && value.message.trim()) return value.message;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function isDesktopDingTalk() {
  const userAgent = navigator.userAgent || "";
  return /dingtalk/i.test(userAgent)
    && !/(android|iphone|ipad|ipod|mobile|harmonyos)/i.test(userAgent)
    && /(windows|macintosh|mac os x)/i.test(userAgent);
}

function getDingTalkRuntime() {
  if (isDesktopDingTalk() && window.DingTalkPC?.runtime?.permission?.requestAuthCode) {
    return { sdk: window.DingTalkPC, platform: "pc" };
  }
  if (window.dd?.runtime?.permission?.requestAuthCode || window.dd?.getAuthCode) {
    return { sdk: window.dd, platform: "h5" };
  }
  if (window.DingTalkPC?.runtime?.permission?.requestAuthCode) {
    return { sdk: window.DingTalkPC, platform: "pc" };
  }
  return null;
}

function isDingTalkContainer() {
  const userAgent = navigator.userAgent || "";
  if (/dingtalk/i.test(userAgent)) return true;
  const runtime = getDingTalkRuntime();
  return Boolean(runtime?.sdk?.env?.platform && runtime.sdk.env.platform !== "notInDingTalk");
}

function waitForDingTalkRuntime(timeoutMs = DING_REAUTH_TIMEOUT_MS) {
  const startedAt = Date.now();
  return new Promise((resolve) => {
    const poll = () => {
      const runtime = getDingTalkRuntime();
      if (runtime) {
        resolve(runtime);
        return;
      }
      if (Date.now() - startedAt >= timeoutMs) {
        resolve(null);
        return;
      }
      window.setTimeout(poll, 80);
    };
    poll();
  });
}

function requestDingTalkAuthCode(runtime) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutId);
      const code = result?.code || result?.authCode || result?.auth_code || "";
      if (!code) {
        reject(new Error(`钉钉免登未返回 code：${formatDingTalkError(result)}`));
        return;
      }
      resolve(code);
    };
    const fail = (reason) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutId);
      reject(new Error(formatDingTalkError(reason)));
    };
    const timeoutId = window.setTimeout(() => fail("钉钉免登授权超时"), DING_REAUTH_TIMEOUT_MS);
    const sdk = runtime?.sdk;
    const requestAuthCode = sdk?.runtime?.permission?.requestAuthCode;
    try {
      if (typeof requestAuthCode === "function") {
        const result = requestAuthCode({
          corpId: DING_CORP_ID,
          onSuccess: finish,
          success: finish,
          onFail: fail,
          fail,
        });
        if (result && typeof result.then === "function") {
          result.then(finish).catch(fail);
        }
        window.setTimeout(() => {
          if (!settled && typeof sdk?.getAuthCode === "function") {
            const fallbackResult = sdk.getAuthCode({
              corpId: DING_CORP_ID,
              onSuccess: finish,
              success: finish,
              onFail: fail,
              fail,
            });
            if (fallbackResult && typeof fallbackResult.then === "function") {
              fallbackResult.then(finish).catch(fail);
            }
          }
        }, 2500);
        return;
      }
      if (typeof sdk?.getAuthCode === "function") {
        const result = sdk.getAuthCode({
          corpId: DING_CORP_ID,
          onSuccess: finish,
          success: finish,
          onFail: fail,
          fail,
        });
        if (result && typeof result.then === "function") {
          result.then(finish).catch(fail);
        }
        return;
      }
      fail("当前钉钉容器不支持免登授权接口");
    } catch (error) {
      fail(error);
    }
  });
}

async function completeDingTalkRelogin() {
  if (!isDingTalkContainer()) {
    throw new Error("非钉钉环境");
  }
  if (!DING_CORP_ID) {
    throw new Error("缺少钉钉 corpId 配置");
  }
  await ensureDingTalkRuntimeSdk();
  const runtime = await waitForDingTalkRuntime();
  if (!runtime) {
    throw new Error("钉钉 JS-SDK 未加载完成");
  }
  const authCode = await requestDingTalkAuthCode(runtime);
  const response = await fetch(`${API_BASE_URL}/api/auth/code`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      authCode,
      loginType: WORKBENCH_LOGIN_TYPE,
    }),
  });
  const data = await parseJsonResponse(response);
  if (!response.ok) {
    throw new Error(data?.error || "钉钉免登失败");
  }
  saveLoginSession(data);
  return data;
}

async function ensureDingTalkRelogin() {
  if (!dingTalkReloginPromise) {
    dingTalkReloginPromise = completeDingTalkRelogin().finally(() => {
      dingTalkReloginPromise = null;
    });
  }
  return dingTalkReloginPromise;
}

async function parseJsonResponse(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function currentSessionIdentityKey() {
  const session = loadLoginSession();
  if (!session?.sessionId && !session?.userId && !session?.actorUserId) return "";
  return loginSessionIdentityKey(session);
}

function currentPrincipalIdentityKey() {
  const session = loadLoginSession();
  if (!session?.userId && !session?.actorUserId) return "";
  return [
    String(session.userId || ""),
    String(session.actorUserId || ""),
    session.isProxying ? "proxy" : "direct",
  ].join(":");
}

function sessionChangedError() {
  const error = new Error("登录身份已切换，请刷新页面后继续操作");
  error.code = "AUTH_SESSION_CHANGED";
  return error;
}

async function revalidateCurrentSession() {
  if (!authRevalidationPromise) {
    authRevalidationPromise = (async () => {
      const current = loadLoginSession() || {};
      const validated = await validateLoginSession(current);
      const next = { ...current, ...validated };
      saveLoginSession(next, { broadcast: false });
      return next;
    })().finally(() => {
      authRevalidationPromise = null;
    });
  }
  return authRevalidationPromise;
}

async function recoverCurrentCookieSession(path, requestOptions, startedIdentityKey) {
  if (requestOptions.__retriedAfterSessionRecovery || path === "/api/auth/session/validate") {
    return false;
  }
  const current = await revalidateCurrentSession();
  const nextIdentityKey = loginSessionIdentityKey(current);
  if (startedIdentityKey && nextIdentityKey && startedIdentityKey !== nextIdentityKey) {
    throw sessionChangedError();
  }
  return true;
}

async function request(path, options = {}, params = null, requestOptions = {}) {
  const startedIdentityKey = currentSessionIdentityKey();
  const startedPrincipalIdentityKey = currentPrincipalIdentityKey();
  const timeoutMs = Number(requestOptions.timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS);
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  let response;
  try {
    response = await fetch(buildUrl(path, params), {
      ...options,
      credentials: "include",
      headers: options.headers || {},
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }

  let data = await parseJsonResponse(response);

  if (response.status === 401) {
    const apiError = responseError(response, data, "登录已失效");
    const message = apiError.message;
    try {
      if (await recoverCurrentCookieSession(path, requestOptions, startedIdentityKey)) {
        return request(path, options, params, { ...requestOptions, __retriedAfterSessionRecovery: true });
      }
    } catch (validationError) {
      if (validationError?.code === "AUTH_SESSION_CHANGED") throw validationError;
      if (![401, 403].includes(Number(validationError?.status || 0))) throw validationError;
    }
    if (!requestOptions.__retriedAfterRelogin && isDingTalkContainer()) {
      try {
        await ensureDingTalkRelogin();
        const nextPrincipalIdentityKey = currentPrincipalIdentityKey();
        if (
          startedPrincipalIdentityKey
          && nextPrincipalIdentityKey
          && startedPrincipalIdentityKey !== nextPrincipalIdentityKey
        ) {
          throw sessionChangedError();
        }
        return request(path, options, params, { ...requestOptions, __retriedAfterRelogin: true });
      } catch (error) {
        if (error?.code === "AUTH_SESSION_CHANGED") throw error;
        redirectToLogin(error instanceof Error ? error.message : message);
        throw error;
      }
    }
    redirectToLogin(message);
    throw apiError;
  }

  if (response.status === 403) {
    const apiError = responseError(response, data, "当前账号没有操作权限");
    if (shouldRedirectForbidden(apiError)) {
      if (requestOptions.__retriedAfterSessionRecovery) throw apiError;
      try {
        if (await recoverCurrentCookieSession(path, requestOptions, startedIdentityKey)) {
          return request(path, options, params, { ...requestOptions, __retriedAfterSessionRecovery: true });
        }
      } catch (validationError) {
        if (validationError?.code === "AUTH_SESSION_CHANGED") throw validationError;
        if ([401, 403].includes(Number(validationError?.status || 0))) {
          redirectToLogin(apiError.message);
        }
        throw validationError;
      }
      redirectToLogin(apiError.message);
    }
    throw apiError;
  }

  if (!response.ok) {
    throw responseError(response, data, "请求失败");
  }
  applyAuthTokenRefreshFromResponse(response);
  return data;
}

export async function apiGet(path, params = null, requestOptions = {}) {
  return request(
    path,
    {},
    params,
    requestOptions,
  );
}

export async function apiPost(path, body = null, requestOptions = {}) {
  return request(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : null,
  }, null, requestOptions);
}

export async function apiUpload(path, formData, requestOptions = {}) {
  if (!(formData instanceof FormData)) {
    throw new TypeError("上传内容必须是 FormData");
  }
  return request(path, {
    method: "POST",
    // Let fetch add the multipart boundary. Setting Content-Type here breaks uploads.
    body: formData,
  }, null, requestOptions);
}

export async function apiPatch(path, body = null, requestOptions = {}) {
  return request(path, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : null,
  }, null, requestOptions);
}

export async function apiPut(path, body = null, requestOptions = {}) {
  return request(path, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : null,
  }, null, requestOptions);
}

export async function apiDelete(path, requestOptions = {}) {
  return request(path, {
    method: "DELETE",
  }, null, requestOptions);
}
