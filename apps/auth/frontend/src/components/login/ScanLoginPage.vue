<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { LoaderCircle, QrCode, RefreshCw, ShieldCheck, Smartphone } from "@lucide/vue";
import logoImage from "@/assets/logo.png";
import AutoGlow from "@/components/shared/AutoGlow.vue";
import GeoTriangles from "@/components/shared/GeoTriangles.vue";
import Particles from "@/components/shared/Particles.vue";
import QrCodeSVG from "@/components/shared/QrCodeSVG.vue";
import {
  AUTH_DEV_LOGIN_ENABLED,
  APP_PATH,
  API_BASE_URL,
  DING_CLIENT_ID,
  DING_CORP_ID,
  DING_SCOPE,
  DING_VIEW_SIZE,
  DING_WIDGET_SIZE,
  REDIRECT_URI,
} from "@/config";
import { clearLoginSession, loadLoginSession, saveLoginSession, validateLoginSession } from "@/session";
import { consumeOAuthState, createOAuthState } from "@/oauth-state";
import { ensureDingTalkLoginSdk } from "@/dingtalk-sdk";

const WORKBENCH_LOGIN_TYPE = "workbench";
const SCAN_LOGIN_TYPE = "scan";
const WORKBENCH_AUTH_JS_API = "runtime.permission.requestAuthCode";
const JSAPI_CONFIG_TIMEOUT_MS = 8000;
const DING_AUTH_TIMEOUT_MS = 10000;

const scanned = ref(false);
const widgetReady = ref(false);
const error = ref("");
const autoLoginPending = ref(false);
const autoLoginHint = ref("");
const widgetNonce = ref(0);
const dingTalkMode = ref(false);
const devLoginMode = ref(false);

const pageUrl = new URL(window.location.href);
const skipWorkbenchLogin = pageUrl.searchParams.get("skipWorkbench") === "1";
const fallbackError = pageUrl.searchParams.get("error")?.trim() || "";
const authCodeInUrl = pageUrl.searchParams.get("authCode") || pageUrl.searchParams.get("code") || pageUrl.searchParams.get("auth_code") || "";
const loginTypeInUrl = (pageUrl.searchParams.get("loginType") || SCAN_LOGIN_TYPE).trim().toLowerCase();
const oauthStateInUrl = pageUrl.searchParams.get("state") || "";
const containerId = computed(() => `ding-login-container-${widgetNonce.value}`);
const loginPanelTitle = computed(() => {
  if (devLoginMode.value) {
    return "本地测试登录";
  }
  return dingTalkMode.value ? "钉钉免登" : "扫码登录";
});
const autoLoginTitle = computed(() => (
  devLoginMode.value ? "正在使用白名单账号登录" : "正在尝试工作台免登"
));

let cancelled = false;
let timer = null;
let loginCodeInFlight = "";
let scanLoginState = "";

function clearAuthCodeFromUrl() {
  const nextUrl = new URL(window.location.href);
  ["authCode", "auth_code", "code", "state"].forEach((key) => nextUrl.searchParams.delete(key));
  window.history.replaceState({}, "", `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`);
}

function formatDingTalkError(value) {
  if (!value) {
    return "Unknown DingTalk error";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value?.errorMessage === "string" && value.errorMessage.trim()) {
    return value.errorMessage;
  }
  if (typeof value?.message === "string" && value.message.trim()) {
    return value.message;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

async function completeLogin(code, loginType) {
  const normalizedCode = String(code || "").trim();
  if (!normalizedCode || loginCodeInFlight === normalizedCode) {
    return;
  }
  loginCodeInFlight = normalizedCode;

  const resp = await fetch(`${API_BASE_URL}/api/auth/code`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      authCode: normalizedCode,
      loginType,
    }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    loginCodeInFlight = "";
    const message = typeof data?.error === "string" ? data.error : "登录失败";
    throw new Error(message);
  }
  saveLoginSession(data);
  window.location.href = APP_PATH;
}

async function completeDevLogin() {
  const resp = await fetch(`${API_BASE_URL}/api/auth/dev/login`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ loginType: "dev" }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    const message = typeof data?.error === "string" ? data.error : "本地测试登录失败";
    throw new Error(message);
  }
  saveLoginSession(data);
  window.location.href = APP_PATH;
}

function goToScanFallback(message) {
  const params = new URLSearchParams({ skipWorkbench: "1" });
  if (message) {
    params.set("error", message);
  }
  window.location.href = `/auth/?${params.toString()}`;
}

async function resumeSavedSession(savedSession, showExpiredMessage = false) {
  try {
    const validatedSession = await validateLoginSession(savedSession);
    saveLoginSession({ ...(savedSession || {}), ...validatedSession });
    window.location.href = APP_PATH;
    return true;
  } catch (reason) {
    clearLoginSession();
    if (showExpiredMessage) {
      error.value = reason instanceof Error ? reason.message : "登录已失效";
    }
    return false;
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
  if (/dingtalk/i.test(userAgent)) {
    return true;
  }
  const runtime = getDingTalkRuntime();
  return Boolean(runtime?.sdk?.env?.platform && runtime.sdk.env.platform !== "notInDingTalk");
}

function waitForDingTalkRuntime(timeoutMs = 10000) {
  const startedAt = Date.now();
  return new Promise((resolve) => {
    const poll = () => {
      if (cancelled) {
        resolve(null);
        return;
      }

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

async function fetchDingTalkJsApiConfig(jsApiList) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), JSAPI_CONFIG_TIMEOUT_MS);
  const params = new URLSearchParams({
    url: window.location.href.split("#")[0],
    jsApiList: jsApiList.join(","),
  });

  try {
    const resp = await fetch(`${API_BASE_URL}/api/dingtalk/jsapi_config?${params.toString()}`, {
      signal: controller.signal,
    });
    let data = {};
    try {
      data = await resp.json();
    } catch {
      data = {};
    }
    if (!resp.ok) {
      const detail = data?.detail ? `：${formatDingTalkError(data.detail)}` : "";
      throw new Error(`${data?.error || "钉钉 JSAPI 签名获取失败"}${detail}`);
    }
    return data;
  } catch (reason) {
    if (reason instanceof DOMException && reason.name === "AbortError") {
      throw new Error("钉钉 JSAPI 签名获取超时");
    }
    throw reason;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function waitForDingTalkReady(sdk, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let timeoutId = null;

    const finish = () => {
      if (settled) {
        return;
      }
      settled = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
      resolve();
    };

    const fail = (reason) => {
      if (settled) {
        return;
      }
      settled = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
      reject(new Error(formatDingTalkError(reason)));
    };

    if (typeof sdk.error === "function") {
      sdk.error((reason) => {
        fail(reason);
      });
    }

    if (typeof sdk.ready === "function") {
      sdk.ready(finish);
      timeoutId = window.setTimeout(() => {
        fail("钉钉 JSAPI ready 超时");
      }, timeoutMs);
      return;
    }

    finish();
  });
}

async function configureDingTalkForWorkbench(runtime) {
  const sdk = runtime?.sdk;
  if (!sdk || runtime?.platform === "pc" || typeof sdk.config !== "function") {
    return runtime;
  }

  autoLoginHint.value = "正在初始化钉钉移动端免登环境...";
  const config = await fetchDingTalkJsApiConfig([WORKBENCH_AUTH_JS_API]);
  sdk.config({
    agentId: config.agentId || undefined,
    corpId: config.corpId || DING_CORP_ID || undefined,
    timeStamp: config.timeStamp,
    nonceStr: config.nonceStr,
    signature: config.signature,
    jsApiList: config.jsApiList?.length ? config.jsApiList : [WORKBENCH_AUTH_JS_API],
  });
  await waitForDingTalkReady(sdk);
  runtime.jsapiConfigured = true;
  return runtime;
}

function cleanupTimer() {
  if (timer !== null) {
    window.clearInterval(timer);
    timer = null;
  }
}

function initScanLogin() {
  if (cancelled || !window.DTFrameLogin || autoLoginPending.value) {
    return false;
  }

  const container = document.getElementById(containerId.value);
  if (!container) {
    return false;
  }

  container.innerHTML = "";
  widgetReady.value = true;

  window.DTFrameLogin(
    {
      id: containerId.value,
      width: DING_WIDGET_SIZE,
      height: DING_WIDGET_SIZE,
    },
    {
      redirect_uri: encodeURIComponent(REDIRECT_URI),
      client_id: DING_CLIENT_ID,
      scope: DING_SCOPE,
      response_type: "code",
      state: scanLoginState || createOAuthState(),
      prompt: "consent",
      corpId: DING_CORP_ID,
    },
    (loginResult) => {
      if (cancelled) {
        return;
      }
      if (loginResult.redirectUrl) {
        window.location.href = loginResult.redirectUrl;
        return;
      }
      if (loginResult.authCode) {
        scanned.value = true;
        window.setTimeout(() => {
          completeLogin(loginResult.authCode, SCAN_LOGIN_TYPE).catch((reason) => {
            error.value = reason instanceof Error ? reason.message : "登录失败";
            scanned.value = false;
          });
        }, 250);
        return;
      }
      error.value = "扫码成功，但未返回授权码。";
    },
    (errorMsg) => {
      if (!cancelled) {
        error.value = `扫码登录失败：${errorMsg}`;
      }
    },
  );

  return true;
}

function startScanLogin() {
  devLoginMode.value = false;
  dingTalkMode.value = false;
  autoLoginPending.value = false;
  autoLoginHint.value = "";
  widgetReady.value = false;
  widgetNonce.value += 1;
  scanLoginState = createOAuthState();

  if (!DING_CLIENT_ID) {
    if (!error.value) {
      error.value = "缺少扫码登录配置：请设置 VITE_DING_CLIENT_ID。";
    }
    return;
  }

  cleanupTimer();
  if (initScanLogin()) {
    return;
  }

  timer = window.setInterval(() => {
    if (initScanLogin()) {
      cleanupTimer();
    }
  }, 120);
}

async function tryWorkbenchLogin() {
  devLoginMode.value = false;
  dingTalkMode.value = true;
  if (!DING_CORP_ID) {
    return {
      ok: false,
      message: "检测到钉钉工作台环境，但缺少 corpId 配置",
    };
  }

  autoLoginPending.value = true;
  autoLoginHint.value = "检测到钉钉工作台环境，正在请求免登授权...";

  const runtime = await waitForDingTalkRuntime();
  if (!runtime) {
    autoLoginPending.value = false;
    autoLoginHint.value = "";
    return {
      ok: false,
      message: "钉钉 JS-SDK 未加载完成",
    };
  }

  let jsapiConfigError = "";
  try {
    await configureDingTalkForWorkbench(runtime);
  } catch (reason) {
    // requestAuthCode is documented as not requiring dd.config, so config failure
    // should not block login. Keep the detail for the final error if auth still fails.
    jsapiConfigError = formatDingTalkError(reason);
  }

  return new Promise((resolve) => {
    let settled = false;
    let failTimer = null;
    let lastAttemptAt = 0;
    let lastSdkError = "";
    const sdk = runtime.sdk;
    const platform = runtime.platform;

    const finish = (payload) => {
      if (settled || cancelled) {
        return;
      }
      settled = true;
      if (failTimer !== null) {
        window.clearTimeout(failTimer);
      }
      if (!payload.ok) {
        autoLoginPending.value = false;
        autoLoginHint.value = "";
      }
      resolve(payload);
    };

    const finishWithAuthCode = (result) => {
      const authCode = result?.code || result?.authCode || result?.auth_code || "";
      if (!authCode) {
        finish({ ok: false, message: `工作台免登成功，但未返回 code：${formatDingTalkError(result)}` });
        return;
      }
      autoLoginHint.value = "免登授权成功，正在进入工作台...";
      completeLogin(authCode, WORKBENCH_LOGIN_TYPE)
        .then(() => {
          finish({ ok: true });
        })
        .catch((reason) => {
          finish({
            ok: false,
            message: reason instanceof Error ? reason.message : "工作台免登失败",
          });
        });
    };

    const finishWithAuthFail = (reason) => {
      lastSdkError = formatDingTalkError(reason);
      finish({
        ok: false,
        message: `工作台免登失败：${lastSdkError}`,
      });
    };

    const callRuntimeRequestAuthCode = () => {
      const requestAuthCodeFn = sdk?.runtime?.permission?.requestAuthCode;
      if (typeof requestAuthCodeFn !== "function") {
        return false;
      }
      const result = requestAuthCodeFn({
        corpId: DING_CORP_ID,
        onSuccess: finishWithAuthCode,
        success: finishWithAuthCode,
        onFail: finishWithAuthFail,
        fail: finishWithAuthFail,
      });
      if (result && typeof result.then === "function") {
        result.then(finishWithAuthCode).catch(finishWithAuthFail);
      }
      return true;
    };

    const callGetAuthCodeFallback = () => {
      const getAuthCodeFn = sdk?.getAuthCode;
      if (typeof getAuthCodeFn !== "function") {
        return false;
      }
      const result = getAuthCodeFn({
        corpId: DING_CORP_ID,
        onSuccess: finishWithAuthCode,
        success: finishWithAuthCode,
        onFail: finishWithAuthFail,
        fail: finishWithAuthFail,
      });
      if (result && typeof result.then === "function") {
        result.then(finishWithAuthCode).catch(finishWithAuthFail);
      }
      return true;
    };

    const requestAuthCode = (source) => {
      const now = Date.now();
      if (settled || now - lastAttemptAt < 1000) {
        return;
      }
      lastAttemptAt = now;
      autoLoginHint.value =
        source === "ready"
          ? `钉钉${platform === "pc" ? "桌面端" : "移动端"}容器已就绪，正在请求免登授权...`
          : `正在通过钉钉${platform === "pc" ? "桌面端" : "移动端"}容器请求免登授权...`;

      try {
        const calledRuntime = callRuntimeRequestAuthCode();
        if (!calledRuntime) {
          const calledFallback = callGetAuthCodeFallback();
          if (!calledFallback) {
            finish({ ok: false, message: "当前钉钉容器不支持免登授权接口" });
          }
          return;
        }
        window.setTimeout(() => {
          if (!settled) {
            callGetAuthCodeFallback();
          }
        }, 2500);
      } catch (reason) {
        lastSdkError = formatDingTalkError(reason);
        if (!callGetAuthCodeFallback()) {
          finishWithAuthFail(reason);
        }
      }
    };

    failTimer = window.setTimeout(() => {
      finish({
        ok: false,
        message: [
          lastSdkError ? `工作台免登失败：${lastSdkError}` : "工作台免登授权超时",
          jsapiConfigError ? `JSAPI 初始化提示：${jsapiConfigError}` : "",
        ].filter(Boolean).join("；"),
      });
    }, DING_AUTH_TIMEOUT_MS);

    if (typeof sdk.error === "function") {
      sdk.error((reason) => {
        lastSdkError = formatDingTalkError(reason);
      });
    }

    if (platform !== "pc" && typeof sdk.ready === "function" && !runtime.jsapiConfigured) {
      let readyCalled = false;
      sdk.ready(() => {
        readyCalled = true;
        requestAuthCode("ready");
      });
      window.setTimeout(() => {
        if (!readyCalled) {
          requestAuthCode("retry");
        }
      }, 3000);
    } else {
      requestAuthCode("direct");
      window.setTimeout(() => {
        requestAuthCode("retry");
      }, 1500);
    }
  });
}

async function startWorkbenchOnlyLogin() {
  dingTalkMode.value = true;
  scanned.value = false;
  widgetReady.value = false;
  error.value = "";
  cleanupTimer();

  let result;
  try {
    result = await tryWorkbenchLogin();
  } catch (reason) {
    autoLoginPending.value = false;
    autoLoginHint.value = "";
    error.value = reason instanceof Error ? reason.message : "钉钉免登失败，请重试。";
    return false;
  }
  if (cancelled || result.ok) {
    return true;
  }
  error.value = result.message || "钉钉免登失败，请重试。";
  return false;
}

function retryWorkbenchLogin() {
  if (autoLoginPending.value) {
    return;
  }
  error.value = "";
  startWorkbenchOnlyLogin();
}

async function startDevLogin() {
  devLoginMode.value = true;
  dingTalkMode.value = false;
  scanned.value = false;
  widgetReady.value = false;
  error.value = "";
  cleanupTimer();
  autoLoginPending.value = true;
  autoLoginHint.value = "正在读取 FULL_ACCESS_USER_IDS 的第一个账号并签发登录会话...";
  try {
    await completeDevLogin();
    return true;
  } catch (reason) {
    autoLoginPending.value = false;
    autoLoginHint.value = "";
    error.value = reason instanceof Error ? reason.message : "本地测试登录失败";
    return false;
  }
}

onMounted(async () => {
  cancelled = false;
  try {
    await ensureDingTalkLoginSdk();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "钉钉安全组件加载失败";
  }
  const runningInDingTalk = isDingTalkContainer();
  dingTalkMode.value = runningInDingTalk;

  if (authCodeInUrl) {
    if (loginTypeInUrl === SCAN_LOGIN_TYPE && !consumeOAuthState(oauthStateInUrl)) {
      clearAuthCodeFromUrl();
      error.value = "登录状态校验失败，请重新扫码登录。";
      startScanLogin();
      return;
    }
    clearAuthCodeFromUrl();
    autoLoginPending.value = true;
    autoLoginHint.value = "登录成功，正在进入管理后台...";
    try {
      await completeLogin(authCodeInUrl, loginTypeInUrl);
      return;
    } catch (reason) {
      autoLoginPending.value = false;
      autoLoginHint.value = "";
      const message = reason instanceof Error ? reason.message : "登录失败";
      if (loginTypeInUrl === WORKBENCH_LOGIN_TYPE) {
        if (runningInDingTalk) {
          dingTalkMode.value = true;
          error.value = message;
        } else {
          goToScanFallback(`${message}，已切换到扫码登录。`);
        }
        return;
      }
      goToScanFallback(`${message}，请重新扫码登录。`);
      return;
    }
  }

  const savedSession = loadLoginSession();
  const resumed = await resumeSavedSession(savedSession, Boolean(savedSession));
  if (resumed) {
    return;
  }

  if (AUTH_DEV_LOGIN_ENABLED) {
    await startDevLogin();
    return;
  }

  if (!error.value) {
    error.value = fallbackError;
  }

  if (scanned.value) {
    return;
  }

  if (skipWorkbenchLogin && !runningInDingTalk) {
    startScanLogin();
    return;
  }

  if (runningInDingTalk) {
    await startWorkbenchOnlyLogin();
    return;
  }

  startScanLogin();
});

onBeforeUnmount(() => {
  cancelled = true;
  cleanupTimer();
});
</script>

<template>
  <div
    class="size-full min-h-screen flex items-center justify-center relative overflow-hidden"
    style="background: linear-gradient(135deg, #0d1f3c 0%, #162a4a 30%, #1a2744 50%, #1e2156 80%, #0d1f3c 100%)"
  >
    <GeoTriangles />

    <div
      class="absolute inset-0 opacity-[0.07]"
      style="background-image: radial-gradient(circle, #94a3b8 1px, transparent 1px); background-size: 28px 28px"
    />

    <div class="absolute -top-32 -right-32 w-[500px] h-[500px] rounded-full bg-blue-500/10 blur-[120px]" />
    <div class="absolute -bottom-40 -left-40 w-[600px] h-[600px] rounded-full bg-indigo-500/8 blur-[140px]" />
    <AutoGlow />
    <Particles />

    <svg class="absolute top-8 left-8 w-20 h-20 text-cyan-500/15" viewBox="0 0 80 80">
      <path d="M0 20 L0 0 L20 0" fill="none" stroke="currentColor" stroke-width="1" />
    </svg>
    <svg class="absolute bottom-8 right-8 w-20 h-20 text-cyan-500/15" viewBox="0 0 80 80">
      <path d="M80 60 L80 80 L60 80" fill="none" stroke="currentColor" stroke-width="1" />
    </svg>

    <div class="relative z-10 flex flex-col items-center w-full max-w-sm px-4">
      <div
        class="w-16 h-16 rounded-2xl bg-gradient-to-br from-cyan-400/28 to-blue-500/24 backdrop-blur-md flex items-center justify-center mb-5 border border-cyan-300/35 shadow-none"
      >
        <img :src="logoImage" alt="迈杰教育科技" class="w-12 h-12 object-contain" />
      </div>

      <h1 class="text-white/90 tracking-widest mb-1">迈 杰 教 育 科 技</h1>
      <p class="text-cyan-300/60 text-xs tracking-wider mb-8">MAIJIE EducationTech</p>

      <div class="w-full rounded-2xl bg-white shadow-none overflow-hidden" style="background-color: #ffffff">
        <div class="flex items-center gap-2 px-6 py-4 border-b border-gray-100 bg-white">
          <QrCode class="w-4 h-4 text-blue-500" />
          <span class="text-gray-600 text-sm">{{ loginPanelTitle }}</span>
        </div>

        <div class="flex flex-col items-center px-6 py-8 bg-white">
          <div
            class="rounded-xl flex items-center justify-center relative bg-white overflow-hidden shadow-none"
            :style="{ width: `${DING_VIEW_SIZE}px`, height: `${DING_VIEW_SIZE}px`, backgroundColor: '#ffffff' }"
          >
            <div v-if="autoLoginPending" class="flex flex-col items-center gap-3 text-center px-6">
              <LoaderCircle class="w-10 h-10 text-blue-500 animate-spin" />
              <p class="text-slate-700 text-sm">{{ autoLoginTitle }}</p>
              <p class="text-gray-400 text-xs leading-5">{{ autoLoginHint }}</p>
            </div>
            <div v-else-if="scanned" class="flex flex-col items-center gap-2">
              <ShieldCheck class="w-12 h-12 text-emerald-500" />
              <p class="text-emerald-600 text-sm">扫码成功</p>
              <p class="text-gray-400 text-xs">请在手机上确认登录</p>
            </div>
            <div v-else-if="dingTalkMode" class="flex flex-col items-center gap-3 text-center px-6">
              <ShieldCheck class="w-12 h-12 text-blue-500" />
              <p class="text-slate-700 text-sm">钉钉免登未完成</p>
              <p class="text-gray-400 text-xs leading-5">已识别为钉钉环境。免登失败通常是服务器连接钉钉接口异常或授权码已失效，请重新免登。</p>
              <button
                type="button"
                class="mt-1 inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition hover:bg-blue-700"
                @click="retryWorkbenchLogin"
              >
                <RefreshCw class="w-4 h-4" />
                重新免登
              </button>
            </div>
            <div v-else-if="devLoginMode" class="flex flex-col items-center gap-3 text-center px-6">
              <ShieldCheck class="w-12 h-12 text-blue-500" />
              <p class="text-slate-700 text-sm">本地测试登录未完成</p>
              <p class="text-gray-400 text-xs leading-5">请确认 auth-backend 已开启本地测试登录，并且 FULL_ACCESS_USER_IDS 至少配置了一个账号。</p>
              <button
                type="button"
                class="mt-1 inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition hover:bg-blue-700"
                @click="startDevLogin"
              >
                <RefreshCw class="w-4 h-4" />
                重新登录
              </button>
            </div>
            <template v-else>
              <div
                :id="containerId"
                class="bg-white"
                :style="{ width: `${DING_WIDGET_SIZE}px`, height: `${DING_WIDGET_SIZE}px` }"
              />
              <div v-if="!widgetReady" class="absolute inset-0 p-2.5 bg-white rounded-xl">
                <QrCodeSVG />
              </div>
            </template>
          </div>

          <div v-if="!autoLoginPending && !dingTalkMode && !devLoginMode" class="mt-6 flex items-center gap-2 text-gray-500 text-sm">
            <Smartphone class="w-4 h-4 text-blue-400" />
            <span>使用 手机钉钉 扫描二维码</span>
          </div>

          <div v-if="!widgetReady && !scanned && !autoLoginPending && !dingTalkMode && !devLoginMode" class="mt-3 flex items-center gap-2 text-xs text-blue-400">
            <LoaderCircle class="w-3.5 h-3.5 animate-spin" />
            加载扫码组件中...
          </div>

          <div v-if="error" class="mt-3 text-xs text-rose-500 text-center break-all leading-5">
            {{ error }}
          </div>
        </div>
      </div>

      <p class="text-white/30 text-xs mt-10 tracking-wide">© 2026 杭州迈杰教育科技有限公司 · 版权所有</p>
    </div>
  </div>
</template>
