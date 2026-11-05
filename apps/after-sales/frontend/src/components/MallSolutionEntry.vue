<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ExternalLink, LoaderCircle } from "@lucide/vue";
import { fetchMallProjectSolutionUrl } from "@/serviceApi";
import { manualNavigation } from "@/components/manualNavigation.js";

const props = defineProps({ sourceCrmId: { type: [String, Number], default: "" } });
const url = ref("");
const loading = ref(false);
const error = ref("");
let requestSequence = 0;
const hasCrmProject = computed(() => Boolean(String(props.sourceCrmId ?? "").trim()));
const navigation = computed(() => manualNavigation(url.value, {
  origin: window.location.origin, userAgent: navigator.userAgent,
  platform: window.dd?.env?.platform || window.DingTalkPC?.env?.platform,
  portalEmbedded: window.frameElement?.dataset.portalEmbed === "true",
  portalDingTalk: window.frameElement?.dataset.portalDingtalk === "true",
}));
async function load() {
  if (!hasCrmProject.value || loading.value) return;
  const sequence = ++requestSequence;
  loading.value = true;
  error.value = "";
  try {
    const result = await fetchMallProjectSolutionUrl(props.sourceCrmId);
    if (sequence === requestSequence) url.value = result;
  } catch (reason) {
    if (sequence !== requestSequence) return;
    error.value = reason?.code === "MALL_PROJECT_NOT_LINKED" ? reason.message
      : reason?.status === 404 ? "对应 CRM 项目不存在或当前账号无权访问"
        : reason?.status === 403 ? "当前账号没有对应 CRM 项目的访问权限"
          : "商城方案暂时无法读取，请重试";
  } finally { if (sequence === requestSequence) loading.value = false; }
}
watch(() => props.sourceCrmId, () => {
  requestSequence += 1;
  url.value = "";
  error.value = "";
  loading.value = false;
  void load();
}, { immediate: true });
onBeforeUnmount(() => { requestSequence += 1; });
</script>

<template>
  <section class="as-round-mall-solution" aria-label="商城方案">
    <div>
      <strong>商城方案</strong>
      <span role="status" aria-live="polite" :class="{ 'is-error': error }">{{ !hasCrmProject ? '本项目由迈杰服务独立维护，未关联商城项目' : error || (loading ? '正在关联当前项目的商城方案…' : '查看当前项目在商城中的方案') }}</span>
    </div>
    <a v-if="navigation" v-bind="navigation" class="as-button as-file-picker__button"><ExternalLink />打开商城方案</a>
    <button v-else-if="hasCrmProject" type="button" class="as-button as-file-picker__button" :disabled="loading" @click="load"><LoaderCircle v-if="loading" class="as-spin" />{{ loading ? '正在关联…' : '重试' }}</button>
  </section>
</template>

<style scoped>
.as-round-mall-solution { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; border: 1px solid var(--as-border); border-radius: 7px; background: var(--as-soft); padding: 12px; }
.as-round-mall-solution > div { flex: 1 1 240px; min-width: 0; }
.as-round-mall-solution strong, .as-round-mall-solution span { display: block; font-size: 12px; line-height: 18px; }
.as-round-mall-solution span { margin-top: 3px; color: var(--as-muted); overflow-wrap: anywhere; }
.as-round-mall-solution span.is-error { color: var(--as-danger); }
.as-round-mall-solution .as-button { flex: 0 0 auto; text-decoration: none; }
</style>
