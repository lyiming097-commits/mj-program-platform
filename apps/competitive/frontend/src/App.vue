<script setup>
import { computed, onBeforeUnmount, onMounted, shallowRef } from "vue";

import DesktopApp from "@/desktop/DesktopApp.vue";
import { startBundleFreshnessCheck } from "@/features/bundleFreshness";
import MobileApp from "@/mobile/MobileApp.vue";

const MOBILE_QUERY = "(max-width: 767px)";
const isMobile = shallowRef(false);
let mediaQuery;
let stopBundleFreshnessCheck;

const currentApp = computed(() => (isMobile.value ? MobileApp : DesktopApp));

function updateViewport(event) {
  isMobile.value = event.matches;
}

onMounted(() => {
  stopBundleFreshnessCheck = startBundleFreshnessCheck();
  mediaQuery = window.matchMedia(MOBILE_QUERY);
  isMobile.value = mediaQuery.matches;
  mediaQuery.addEventListener("change", updateViewport);
});

onBeforeUnmount(() => {
  stopBundleFreshnessCheck?.();
  mediaQuery?.removeEventListener("change", updateViewport);
});
</script>

<template>
  <component :is="currentApp" />
</template>
