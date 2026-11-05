<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { ArrowLeft, LoaderCircle } from "@lucide/vue";
import AutoGlow from "@/components/shared/AutoGlow.vue";
import GeoTriangles from "@/components/shared/GeoTriangles.vue";
import Particles from "@/components/shared/Particles.vue";
import { API_BASE_URL, APP_PATH } from "@/config";
import { consumeOAuthState } from "@/oauth-state";
import { saveLoginSession } from "@/session";

const loading = ref(true);
const error = ref("");
const payload = ref(null);
const loginType = ref("scan");
let controller = null;

const pageTitle = computed(() => (loginType.value === "workbench" ? "免登完成" : "登录完成"));
const loadingText = computed(() =>
  payload.value
    ? "登录成功，正在进入管理后台..."
    : loginType.value === "workbench"
      ? "正在完成工作台免登..."
      : "请求后端接口中...",
);
const lines = computed(() => [
  { label: "loginType", value: payload.value?.loginType ?? loginType.value ?? "-" },
  { label: "reason", value: payload.value?.reason ?? "-" },
  { label: "userId", value: payload.value?.userId ?? "-" },
  { label: "nick", value: payload.value?.nick ?? "-" },
  { label: "avatarUrl", value: payload.value?.avatarUrl ?? "-" },
  { label: "phone", value: payload.value?.phone ?? "-" },
  { label: "unionId", value: payload.value?.unionId ?? "-" },
  { label: "stateCode", value: payload.value?.stateCode ?? "-" },
]);

function goHome() {
  window.location.href = "/auth/";
}

function goToScanFallback(message) {
  const params = new URLSearchParams({ skipWorkbench: "1" });
  if (message) {
    params.set("error", message);
  }
  window.location.href = `/auth/?${params.toString()}`;
}

function isDingTalkContainer() {
  const userAgent = navigator.userAgent || "";
  if (/dingtalk/i.test(userAgent)) {
    return true;
  }
  const platform = window.dd?.env?.platform || window.DingTalkPC?.env?.platform || "";
  return Boolean(platform && platform !== "notInDingTalk");
}

function clearAuthCallbackFromUrl() {
  const nextUrl = new URL(window.location.href);
  ["authCode", "auth_code", "code", "state"].forEach((key) => nextUrl.searchParams.delete(key));
  window.history.replaceState({}, "", `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`);
}

onMounted(() => {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code") || url.searchParams.get("authCode") || url.searchParams.get("auth_code");
  const state = url.searchParams.get("state") || "";
  loginType.value = (url.searchParams.get("loginType") || "scan").trim().toLowerCase();
  clearAuthCallbackFromUrl();

  if (!code) {
    if (loginType.value === "workbench") {
      if (isDingTalkContainer()) {
        error.value = "工作台免登未返回授权码，请返回后重新免登。";
        loading.value = false;
      } else {
        goToScanFallback("工作台免登未返回授权码，已切换到扫码登录。");
      }
      return;
    }
    error.value = "登录回调缺少授权码，无法完成登录。";
    loading.value = false;
    return;
  }

  if (loginType.value === "scan" && !consumeOAuthState(state)) {
    error.value = "登录状态校验失败，请重新扫码登录。";
    loading.value = false;
    return;
  }

  controller = new AbortController();
  const load = async () => {
    try {
      const resp = await fetch(`${API_BASE_URL}/api/auth/code`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          authCode: code,
          loginType: loginType.value,
        }),
        signal: controller.signal,
      });
      const data = await resp.json();
      if (!resp.ok) {
        const message = typeof data?.error === "string" ? data.error : "Request failed";
        throw new Error(message);
      }
      payload.value = data;
      saveLoginSession(data);
      window.setTimeout(() => {
        window.location.href = APP_PATH;
      }, 500);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }

      const message = err instanceof Error ? err.message : "Failed to fetch user info";
      if (loginType.value === "workbench") {
        if (isDingTalkContainer()) {
          error.value = message;
        } else {
          goToScanFallback(`${message}，已切换到扫码登录。`);
        }
        return;
      }
      error.value = message;
    } finally {
      loading.value = false;
    }
  };

  load();
});

onBeforeUnmount(() => {
  controller?.abort();
});
</script>

<template>
  <div
    class="size-full min-h-screen flex items-center justify-center relative overflow-hidden px-4"
    style="background: linear-gradient(135deg, #0d1f3c 0%, #162a4a 30%, #1a2744 50%, #1e2156 80%, #0d1f3c 100%)"
  >
    <GeoTriangles />
    <AutoGlow />
    <Particles />

    <div class="relative z-10 w-full max-w-xl rounded-2xl bg-white shadow-xl shadow-black/15 p-6">
      <div class="flex items-center justify-between gap-3 border-b border-gray-100 pb-4">
        <div>
          <h2 class="text-gray-800 text-xl font-semibold">{{ pageTitle }}</h2>
          <p class="text-gray-500 text-sm">正在进入系统</p>
        </div>
        <button
          class="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
          @click="goHome"
        >
          <ArrowLeft class="w-4 h-4" />
          返回
        </button>
      </div>

      <div v-if="loading" class="mt-6 rounded-xl border border-gray-200 bg-gray-50 p-4 text-gray-600 flex items-center gap-2">
        <LoaderCircle class="w-4 h-4 animate-spin" />
        {{ loadingText }}
      </div>

      <div v-if="!loading && error" class="mt-6 rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-700 text-sm">
        {{ error }}
      </div>

      <template v-if="!loading && !error && payload">
        <div
          v-if="payload.detailWarning"
          class="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-800 text-sm"
        >
          {{ payload.detailWarning }}。已使用免登返回的基础身份信息完成登录。
        </div>

        <div class="mt-6 grid gap-3">
          <div
            v-for="line in lines"
            :key="line.label"
            class="rounded-xl border border-gray-200 bg-white p-3 flex items-center justify-between gap-4"
          >
            <span class="text-gray-500 text-sm">{{ line.label }}</span>
            <span class="text-gray-800 text-sm break-all text-right">{{ String(line.value) }}</span>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
