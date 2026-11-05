<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, watch } from "vue";
import { LoaderCircle, RotateCcw } from "@lucide/vue";
import { fetchPresalesEstimatedFee, fetchPresalesMallFees } from "@/serviceApi";
import { loadPresalesFeeCache, readPresalesFeeCache } from "@/presalesFeeCache";

const props = defineProps({
  sourceCrmId: { type: [String, Number], default: "" },
  identityKey: { type: String, default: "" },
  embedded: Boolean,
});
const crm = reactive({ loading: false, loaded: false, error: "", amount: null });
const mall = reactive({ loading: false, loaded: false, error: "", quote: null, actual: null });
const linked = computed(() => Boolean(String(props.sourceCrmId ?? "").trim()));
let requestSequence = 0;
let refreshTimer;

function sourceError(error, source) {
  if (error?.status === 401) return "登录状态已失效，请重新登录后查看费用";
  if (error?.status === 403) return "当前账号无权读取此 CRM 项目的费用";
  if (error?.status === 404) return "对应 CRM 项目不存在或当前账号无权访问";
  return `${source}费用读取失败，请重试`;
}

function applyAmount(source, result) {
  if (source === "crm") crm.amount = result;
  else {
    mall.quote = result.externalQuote;
    mall.actual = result.actualFee;
  }
  Object.assign(source === "crm" ? crm : mall, { loaded: true, error: "" });
}

async function load(source, { force = false } = {}) {
  if (!linked.value) return;
  const sequence = requestSequence;
  const state = source === "crm" ? crm : mall;
  if (state.loading) return;
  const cached = readPresalesFeeCache(props.identityKey, props.sourceCrmId, source);
  if (cached) applyAmount(source, cached.value);
  else {
    state.loaded = false;
    if (source === "crm") crm.amount = null;
    else { mall.quote = null; mall.actual = null; }
  }
  if (!force && cached?.fresh) return;
  state.loading = true;
  state.error = "";
  const projectId = props.sourceCrmId;
  try {
    const result = await loadPresalesFeeCache(props.identityKey, projectId, source,
      () => source === "crm" ? fetchPresalesEstimatedFee(projectId) : fetchPresalesMallFees(projectId), { force });
    if (sequence === requestSequence) applyAmount(source, result);
  } catch (error) {
    if (sequence === requestSequence) {
      state.error = sourceError(error, source === "crm" ? "CRM" : "商城");
      state.loaded = false;
      if (source === "crm") crm.amount = null;
      else { mall.quote = null; mall.actual = null; }
    }
  } finally {
    if (sequence === requestSequence) state.loading = false;
  }
}

function amountLabel(value, source) {
  if (!linked.value) return "未关联";
  if (source.loading && !source.loaded) return "读取中…";
  if (source.error) return "读取失败";
  if (value === null) return "暂无金额";
  return `${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} 元`;
}

watch(() => [props.sourceCrmId, props.identityKey], () => {
  requestSequence += 1;
  Object.assign(crm, { loading: false, loaded: false, error: "", amount: null });
  Object.assign(mall, { loading: false, loaded: false, error: "", quote: null, actual: null });
  void load("crm");
  void load("mall");
}, { immediate: true });
function refreshVisibleFees() {
  if (document.visibilityState === "hidden") return;
  void load("crm");
  void load("mall");
}
onMounted(() => {
  refreshTimer = window.setInterval(refreshVisibleFees, 30_000);
  window.addEventListener("focus", refreshVisibleFees);
  document.addEventListener("visibilitychange", refreshVisibleFees);
});
onBeforeUnmount(() => {
  requestSequence += 1;
  window.clearInterval(refreshTimer);
  window.removeEventListener("focus", refreshVisibleFees);
  document.removeEventListener("visibilitychange", refreshVisibleFees);
});
</script>

<template>
  <section class="as-presales-project-fees as-panel" :role="embedded ? 'region' : 'tabpanel'" :aria-label="embedded ? '费用信息' : '项目费用信息'">
    <header class="as-panel-head"><div><h3>{{ embedded ? '费用信息' : '项目费用信息' }}</h3><p v-if="!embedded">整个售前项目共用一组费用，由 CRM 和商城提供。</p></div></header>
    <p v-if="!linked" class="as-empty as-empty--compact" role="status">本项目由迈杰服务独立维护，未关联 CRM，暂无来源费用。</p>
    <template v-for="[key, source] in [['crm', crm], ['mall', mall]]" :key="key">
      <div v-if="source.error" class="as-alert as-alert--error" role="alert"><span>{{ source.error }}</span><button type="button" class="as-button as-button--secondary" @click="load(key, { force: true })"><RotateCcw />重试{{ key === 'crm' ? ' CRM' : '商城' }}</button></div>
    </template>
    <table aria-label="售前项目费用" :aria-busy="crm.loading || mall.loading">
      <thead><tr><th scope="col">费用类型</th><th scope="col">金额</th><th scope="col">来源</th></tr></thead>
      <tbody>
        <tr><th scope="row">预计费用</th><td :class="{ 'is-muted': crm.amount === null }"><LoaderCircle v-if="crm.loading" class="as-spin" />{{ amountLabel(crm.amount, crm) }}</td><td>CRM · 预计金额</td></tr>
        <tr><th scope="row">对外报价</th><td :class="{ 'is-muted': mall.quote === null }"><LoaderCircle v-if="mall.loading" class="as-spin" />{{ amountLabel(mall.quote, mall) }}</td><td>商城 · 业务员报价总价</td></tr>
        <tr><th scope="row">实际费用</th><td :class="{ 'is-muted': mall.actual === null }"><LoaderCircle v-if="mall.loading" class="as-spin" />{{ amountLabel(mall.actual, mall) }}</td><td>商城 · A1 总价</td></tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.as-presales-project-fees { min-width: 0; }
.as-panel-head p { overflow-wrap: anywhere; }
.as-alert { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--as-group-gap, 12px); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid var(--as-border); padding: var(--as-section-gap, 16px); text-align: center; overflow-wrap: anywhere; }
thead th { background: var(--as-soft); color: var(--as-muted); font-weight: 600; }
tbody th { color: var(--as-text); font-weight: 600; }
td { color: var(--as-text); font-variant-numeric: tabular-nums; }
td:last-child, .is-muted { color: var(--as-muted); }
td svg { display: inline-block; width: 14px; height: 14px; margin-right: 6px; vertical-align: middle; }
</style>
