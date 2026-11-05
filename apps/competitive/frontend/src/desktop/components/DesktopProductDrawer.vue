<script setup>
import { computed, shallowRef, watch } from "vue";
import { PackageSearch } from "lucide-vue-next";

import { fetchCompetitors, fetchProductDetail, productImageUrl } from "@/features/competitiveApi";
import { productArchiveFields } from "@/features/productArchiveFields";
import AppDrawer from "@/shared/AppDrawer.vue";
import ProductParameterTabs from "@/shared/ProductParameterTabs.vue";
import DesktopCompetitorDrawer from "./DesktopCompetitorDrawer.vue";

const props = defineProps({ product: { type: Object, default: null }, access: { type: Object, required: true } });
const emit = defineEmits(["close", "notify", "deleted", "updated"]);
const competitors = shallowRef([]);
const selectedId = shallowRef("");
const loading = shallowRef(false);
const productDetail = shallowRef(null);
const archiveFields = computed(() => productArchiveFields(productDetail.value || props.product));

async function load() {
  if (!props.product) { competitors.value = []; return; }
  loading.value = true;
  try {
    const [competitorResult, detailResult] = await Promise.all([
      fetchCompetitors({ page: 1, pageSize: 100, productId: props.product.id }),
      fetchProductDetail(props.product.id),
    ]);
    competitors.value = competitorResult.items;
    productDetail.value = detailResult;
  }
  catch (reason) { emit("notify", reason.message || "竞品列表加载失败"); }
  finally { loading.value = false; }
}

function handleDeleted(id) {
  competitors.value = competitors.value.filter((item) => item.id !== id);
  emit("deleted", id);
}

function handleUpdated(value) {
  competitors.value = competitors.value.map((item) => item.id === value.id ? value : item);
  emit("updated", value);
}

watch(() => props.product?.id, load, { immediate: true });
</script>

<template>
  <AppDrawer
    :open="Boolean(product)"
    :title="product?.name || '产品详情'"
    :subtitle="product ? `${product.model || product.shortName || '-'} · 产品竞品详情` : ''"
    width="1120px"
    workspace
    @close="emit('close')"
  >
    <div v-if="product" class="product-detail">
      <section class="archive-panel">
        <header><h3>我司产品资料</h3><span>产品档案</span></header>
        <div class="archive-body">
          <div class="product-image"><PackageSearch :size="24" /><img v-if="product.hasImage" :src="productImageUrl(product.id)" :alt="product.name" /></div>
          <span class="category-badge">{{ [product.productDomain, product.levelTwo, product.category].filter(Boolean).join(' / ') || '-' }}</span>
          <h4>{{ product.name }}</h4><p>{{ product.fullName || product.model || '-' }}</p>
          <dl><template v-for="field in archiveFields" :key="field[0]"><div v-if="field[2] !== 'parameter'"><dt>{{ field[0] }}</dt><dd>{{ field[1] || '-' }}</dd></div><div v-else-if="field[0] === '投标参数'" class="parameter-tabs-field"><dt class="visually-hidden">产品参数</dt><dd><ProductParameterTabs :product="productDetail || product" /></dd></div></template><div><dt>地区覆盖</dt><dd>{{ product.coverage || '-' }}</dd></div><div><dt>关联竞品</dt><dd>{{ competitors.length }} 条竞品资料</dd></div></dl>
        </div>
      </section>
      <section class="competitor-panel">
        <header><h3>关联竞品</h3><span>{{ competitors.length }} 条</span></header>
        <div class="competitor-table">
          <div class="table-head"><span>竞品资料</span><span>地区覆盖</span><span>来源</span><span>更新时间</span><span>有效期</span></div>
          <button v-for="item in competitors" :key="item.id" type="button" class="competitor-row" @click="selectedId = item.id">
            <span class="competitor-copy"><strong>{{ item.brand }} · {{ item.model || '型号待补充' }}</strong><small>{{ item.name || '-' }}</small></span>
            <span>{{ item.regions?.join('、') || '-' }}</span><span>{{ item.sources || 0 }} 条</span><time>{{ item.updated || '-' }}</time><time :class="{ expired: item.status === '已过期' }">{{ item.expires || '-' }}</time>
          </button>
          <div v-if="loading" class="empty-state">正在加载...</div><div v-else-if="!competitors.length" class="empty-state">该产品下暂无竞品</div>
        </div>
      </section>
    </div>
  </AppDrawer>
  <DesktopCompetitorDrawer :id="selectedId" :access="access" @close="selectedId = ''" @notify="emit('notify', $event)" @deleted="handleDeleted" @updated="handleUpdated" />
</template>

<style scoped>
.product-detail { display: grid; height: 100%; min-height: 0; grid-template-columns: 300px minmax(0, 1fr); gap: 16px; }
.archive-panel, .competitor-panel { display: flex; min-height: 0; flex-direction: column; overflow: hidden; border: 1px solid #dfe6ee; border-radius: 8px; background: #fff; }
.archive-panel > header, .competitor-panel > header { display: flex; min-height: 48px; flex: 0 0 auto; align-items: center; justify-content: space-between; border-bottom: 1px solid #dfe6ee; padding: 0 14px; }
.archive-panel h3, .competitor-panel h3 { margin: 0; color: #132b50; font-size: 13px; }.archive-panel header span, .competitor-panel header span { color: #64748b; font-size: 10px; }
.archive-body { min-height: 0; flex: 1; overflow-y: auto; padding: 14px; scrollbar-color: #b8c4d1 transparent; scrollbar-width: thin; }
.archive-body::-webkit-scrollbar { width: 5px; }
.archive-body::-webkit-scrollbar-track { background: transparent; }
.archive-body::-webkit-scrollbar-thumb { border-radius: 5px; background: #b8c4d1; }
.product-image { position: relative; display: grid; width: 100%; height: 176px; place-items: center; overflow: hidden; border: 1px solid #dfe6ee; border-radius: 7px; background: #f8fafc; color: #b6c2d2; }.product-image img { position: absolute; inset: 0; width: 100%; height: 100%; background: #fff; object-fit: contain; }
.category-badge { display: inline-flex; margin-top: 12px; border: 1px solid #bfdbfe; border-radius: 4px; background: #eff6ff; padding: 3px 7px; color: #1d4ed8; font-size: 9px; }.archive-body h4 { margin: 10px 0 0; color: #132b50; font-size: 14px; }.archive-body > p { margin: 4px 0 0; color: #64748b; font-size: 10px; }
.archive-body dl { margin: 14px 0 0; }.archive-body dl > div { display: grid; grid-template-columns: 82px minmax(0, 1fr); gap: 8px; border-top: 1px solid #edf1f5; padding: 8px 0; }.archive-body dt { color: #94a3b8; font-size: 9px; }.archive-body dd { overflow-wrap: anywhere; margin: 0; color: #334155; font-size: 10px; line-height: 1.45; white-space: pre-wrap; }
.archive-body dl > div.parameter-tabs-field { grid-template-columns: minmax(0, 1fr); padding: 11px 0; }
.parameter-tabs-field dd { min-width: 0; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%); white-space: nowrap; }
.competitor-table { min-height: 0; flex: 1; overflow: auto; }.table-head, .competitor-row { display: grid; min-width: 760px; grid-template-columns: minmax(220px, 1fr) minmax(110px, .8fr) 76px 110px 110px; align-items: center; gap: 10px; }.table-head { position: sticky; z-index: 2; top: 0; min-height: 38px; border-bottom: 1px solid #d4e1ee; background: #f1f6fb; padding: 0 12px; color: #203858; font-size: 10px; font-weight: 700; }
.competitor-row { width: 100%; min-height: 68px; border: 0; border-bottom: 1px solid #e2e8f0; background: #fff; padding: 9px 12px; color: #64748b; font-size: 10px; text-align: left; }.competitor-row:nth-of-type(odd) { background: #fbfdff; }.competitor-row:hover { background: #f4f8fd; }
.competitor-copy { min-width: 0; }.competitor-copy strong, .competitor-copy small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.competitor-copy strong { color: #132b50; font-size: 12px; }.competitor-copy small { margin-top: 5px; color: #64748b; font-size: 9px; }.competitor-row time { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }.competitor-row time.expired { color: #dc2626; font-weight: 700; }
</style>
