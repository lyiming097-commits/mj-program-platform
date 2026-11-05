<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import CableMallWorkspace from "@/components/cable-mall/CableMallWorkspace_web.vue";
import SessionGuard from "@/components/layout/SessionGuard.vue";
import { CABLE_MALL_PATH } from "@/config";
import { getCurrentPath, ROUTE_CHANGE_EVENT } from "@/router-lite";

const routePath = ref(getCurrentPath());
const isCableMallPage = computed(() => isCableMallRoute(routePath.value));

function isCableMallRoute(path) {
  return path === CABLE_MALL_PATH || path.startsWith(`${CABLE_MALL_PATH}/`);
}

function redirectOutsideCableMall(path) {
  if (!isCableMallRoute(path)) {
    window.location.replace("/auth/");
  }
}

function updateRoutePath(event) {
  const nextPath = event?.detail?.path || getCurrentPath();
  routePath.value = nextPath;
  redirectOutsideCableMall(nextPath);
}

onMounted(() => {
  window.addEventListener(ROUTE_CHANGE_EVENT, updateRoutePath);
  window.addEventListener("popstate", updateRoutePath);
  redirectOutsideCableMall(routePath.value);
});

onBeforeUnmount(() => {
  window.removeEventListener(ROUTE_CHANGE_EVENT, updateRoutePath);
  window.removeEventListener("popstate", updateRoutePath);
});
</script>

<template>
  <div v-if="isCableMallPage" class="flex h-screen min-h-screen flex-col overflow-hidden bg-slate-100 text-slate-900">
    <SessionGuard />
    <CableMallWorkspace />
  </div>
</template>
