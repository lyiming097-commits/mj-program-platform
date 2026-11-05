<script setup>
import { computed, ref, shallowRef, watch } from "vue";
import { BookOpen, Database, ExternalLink, FileText, Image, ListTree, LoaderCircle, RotateCcw } from "@lucide/vue";
import ProjectDetailDrawer from "@/components/ProjectDetailDrawer.vue";
import ProductImageGallery from "@/components/ProductImageGallery.vue";
import { manualNavigation } from "@/components/manualNavigation.js";

const props = defineProps({
  open: { type: Boolean, default: false },
  product: { type: Object, default: null },
  level: { type: Number, default: 3 },
  loading: { type: Boolean, default: false },
  error: { type: String, default: "" },
});

const emit = defineEmits(["close", "retry"]);

const categoryPath = computed(() => [
  props.product?.categoryA,
  props.product?.categoryB,
  props.product?.categoryC,
].filter(Boolean).join(" · ") || "未分类");

const basics = computed(() => [
  { label: "产品名称", value: props.product?.name },
  { label: "产品简称", value: props.product?.abbr },
  { label: "规格型号", value: props.product?.model },
  { label: "品牌", value: props.product?.brand },
  { label: "金蝶代码", value: props.product?.kingdeeCode },
  { label: "计量单位", value: props.product?.unit },
]);

const parameterRows = computed(() => (
  Array.isArray(props.product?.parameterRows) ? props.product.parameterRows : []
));

const manuals = computed(() => (
  (Array.isArray(props.product?.manuals) ? props.product.manuals : []).map((manual) => ({
    ...manual,
    navigation: manualNavigation(manual?.url, {
      origin: window.location.origin,
      userAgent: navigator.userAgent,
      platform: window.dd?.env?.platform || window.DingTalkPC?.env?.platform,
      portalEmbedded: window.frameElement?.dataset.portalEmbed === "true",
      portalDingTalk: window.frameElement?.dataset.portalDingtalk === "true",
    }),
  }))
));

const detailPageRef = ref(null);
const basicsSection = ref(null);
const parametersSection = ref(null);
const documentsSection = ref(null);
const instructionsSection = ref(null);
const quickNavTarget = shallowRef(null);
const activeSection = shallowRef("basics");
const quickNavItems = [
  { key: "basics", label: "基础资料", icon: Database },
  { key: "parameters", label: "产品参数", icon: ListTree },
  { key: "documents", label: "产品资料", icon: FileText },
  { key: "instructions", label: "说明书", icon: BookOpen },
];

function scrollToSection(key) {
  const targets = {
    basics: basicsSection.value,
    parameters: parametersSection.value,
    documents: documentsSection.value,
    instructions: instructionsSection.value,
  };
  activeSection.value = key;
  targets[key]?.scrollIntoView({ behavior: "smooth", block: "start" });
}

watch(
  [() => props.open, detailPageRef],
  ([open, element]) => {
    if (!open || !element) {
      quickNavTarget.value = null;
      return;
    }
    activeSection.value = "basics";
    quickNavTarget.value = element.closest(".el-drawer") || element;
  },
  { immediate: true, flush: "post" },
);
</script>

<template>
  <ProjectDetailDrawer
    :open="open"
    :title="product?.name || '产品详情'"
    eyebrow="产品档案"
    size="72%"
    :level="level"
    @close="emit('close')"
  >
    <div v-if="loading" class="product-detail-status" role="status"><LoaderCircle class="as-spin" />正在读取产品档案...</div>
    <div v-else-if="error" class="product-detail-status product-detail-status--error" role="alert"><span>{{ error }}</span><button type="button" class="as-button as-button--secondary" @click="emit('retry')"><RotateCcw />重试</button></div>
    <article v-else-if="product" ref="detailPageRef" class="product-detail">
      <Teleport v-if="quickNavTarget" :to="quickNavTarget">
        <nav class="product-quick-nav" aria-label="产品详情快捷入口">
          <button v-for="item in quickNavItems" :key="item.key" type="button" :title="item.label" :class="{ active: activeSection === item.key }" @click="scrollToSection(item.key)"><component :is="item.icon" /><span>{{ item.label }}</span></button>
        </nav>
      </Teleport>

      <div class="product-archive-content">
        <ProductImageGallery class="product-gallery-desktop" :images="product.productImages" :fallback-url="product.productPreview" :name="product.name" />
        <div class="product-gallery-main product-gallery-mobile">
          <img v-if="product.productPreview" :src="product.productPreview" :alt="product.name">
          <div v-else class="product-gallery-empty"><Image aria-hidden="true" /><span>暂无产品图片</span></div>
        </div>

        <section ref="basicsSection" class="product-archive-section">
          <header class="product-archive-section-head"><span></span><Database /><h3>基础资料</h3><em>{{ product.lifecycle || '在用产品' }}</em></header>
          <p class="product-category-path">{{ categoryPath }}</p>
          <dl class="product-basics-grid">
            <div v-for="item in basics" :key="item.label"><dt>{{ item.label }}</dt><dd :title="item.value || '-'">{{ item.value || '-' }}</dd></div>
          </dl>
        </section>

        <section ref="parametersSection" class="product-archive-section">
          <header class="product-archive-section-head"><span></span><ListTree /><h3>产品参数</h3><em>{{ parameterRows.length }} 项</em></header>
          <div v-if="parameterRows.length" class="product-parameter-table">
            <div class="product-parameter-head"><strong>方案参数</strong><strong>招标参数</strong><strong>投标参数</strong></div>
            <div v-for="row in parameterRows" :key="row.id" class="product-parameter-row"><p>{{ row.scheme || '-' }}</p><p>{{ row.tender || '-' }}</p><p>{{ row.bid || '-' }}</p></div>
          </div>
          <p v-else class="product-archive-empty">{{ product.parameterText || '暂无产品参数' }}</p>
        </section>

        <section ref="documentsSection" class="product-archive-section">
          <header class="product-archive-section-head"><span></span><FileText /><h3>产品资料</h3></header>
          <dl class="product-document-list"><div><dt>产品说明</dt><dd>{{ product.configInfo || '-' }}</dd></div><div><dt>包装信息</dt><dd>{{ product.packageInfo || '-' }}</dd></div></dl>
        </section>

        <section ref="instructionsSection" class="product-archive-section">
          <header class="product-archive-section-head"><span></span><BookOpen /><h3>说明书</h3><em>{{ manuals.length }} 份</em></header>
          <div v-if="manuals.length" class="product-manual-list">
            <template v-for="manual in manuals" :key="manual.key">
              <a v-if="manual.navigation" :href="manual.navigation.href" :target="manual.navigation.target" :rel="manual.navigation.rel" :aria-label="`打开${manual.label}`"><BookOpen /><strong>{{ manual.label }}</strong><span>打开说明书</span><ExternalLink /></a>
              <span v-else class="product-manual-unavailable"><BookOpen /><strong>{{ manual.label }}</strong><span>链接不可用</span></span>
            </template>
          </div>
          <p v-else class="product-archive-empty">暂无说明书</p>
        </section>
      </div>
    </article>
  </ProjectDetailDrawer>
</template>

<style scoped>
.product-detail-status { display: flex; min-height: 120px; align-items: center; justify-content: center; gap: 10px; color: #526174; font-size: 12px; }
.product-detail-status svg { width: 17px; height: 17px; }
.product-detail-status--error { flex-wrap: wrap; color: #b4232f; }
.product-detail { position: relative; box-sizing: border-box; width: 100%; max-width: 1392px; min-height: 100%; margin: 0 auto; color: #111827; }
.product-quick-nav { position: absolute; left: -88px; top: 96px; z-index: 1; display: flex; width: 112px; flex-direction: column; gap: 8px; }
.product-quick-nav button { display: flex; width: 100%; min-height: 36px; align-items: center; gap: 7px; border: 1px solid #bfdbfe; border-right: 0; border-radius: 8px 0 0 8px; background: rgba(255, 255, 255, 0.97); padding: 0 12px; color: #1d4ed8; cursor: pointer; font-size: 11px; font-weight: 800; box-shadow: 0 8px 18px rgba(15, 23, 42, 0.12); transition: transform 160ms ease, background 160ms ease, border-color 160ms ease, color 160ms ease, box-shadow 160ms ease; }
.product-quick-nav button:hover, .product-quick-nav button.active { border-color: #2563eb; background: #2563eb; color: #fff; box-shadow: 0 12px 24px rgba(37, 99, 235, 0.22); transform: translateX(-2px); }
.product-quick-nav button:focus-visible { outline: 2px solid #93c5fd; outline-offset: 2px; }
.product-quick-nav svg { width: 15px; height: 15px; flex: 0 0 auto; }
.product-quick-nav span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.product-archive-content { position: relative; z-index: 2; display: grid; gap: 12px; border: 1px solid #dbe4f0; border-radius: 8px; background: #fff; padding: 20px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05); }
.product-gallery-main { display: grid; width: 100%; min-height: 420px; height: min(60vh, 620px); place-items: center; overflow: hidden; border: 1px solid #e2e8f0; border-radius: 8px; background: #fbfcfe; }
.product-gallery-mobile { display: none; }
.product-gallery-main > img { width: 100%; height: 100%; object-fit: contain; padding: 24px; }
.product-gallery-empty { display: grid; place-items: center; gap: 8px; color: #94a3b8; font-size: 11px; }
.product-gallery-empty svg { width: 48px; height: 48px; }
.product-archive-section { scroll-margin-top: 18px; overflow: hidden; border-top: 1px solid #e2e8f0; padding-top: 8px; }
.product-archive-section-head { display: flex; min-height: 42px; align-items: center; gap: 8px; padding: 8px 4px; }
.product-archive-section-head > span { width: 3px; height: 18px; border-radius: 2px; background: #2563eb; }
.product-archive-section-head svg { width: 16px; height: 16px; color: #2563eb; }
.product-archive-section-head h3 { margin: 0; color: #172033; font-size: 13px; letter-spacing: 0; }
.product-archive-section-head em { margin-left: auto; border-radius: 4px; background: #f1f5f9; padding: 3px 7px; color: #64748b; font-size: 9px; font-style: normal; font-weight: 700; }
.product-category-path { margin: 0; background: #f8fafc; padding: 10px 12px; color: #64748b; font-size: 10px; }
.product-basics-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid #edf2f7; border-left: 1px solid #edf2f7; margin: 0; }
.product-basics-grid > div { min-width: 0; border-right: 1px solid #edf2f7; border-bottom: 1px solid #edf2f7; padding: 10px 12px; }
.product-basics-grid dt { color: #8491a3; font-size: 9px; }
.product-basics-grid dd { overflow: hidden; margin: 4px 0 0; color: #344054; font-size: 11px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.product-parameter-table { overflow-x: auto; border: 1px solid #e2e8f0; }
.product-parameter-head, .product-parameter-row { display: grid; min-width: 720px; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.product-parameter-head { border-bottom: 1px solid #dbe4f0; background: #f7faff; }
.product-parameter-head strong { border-right: 1px solid #e2e8f0; padding: 9px 11px; color: #475569; font-size: 10px; }
.product-parameter-row { border-bottom: 1px solid #edf2f7; }
.product-parameter-row:last-child { border-bottom: 0; }
.product-parameter-row p { margin: 0; border-right: 1px solid #edf2f7; padding: 10px 11px; color: #536277; font-size: 10px; line-height: 17px; white-space: pre-wrap; }
.product-parameter-head strong:last-child, .product-parameter-row p:last-child { border-right: 0; }
.product-document-list { display: grid; gap: 0; border: 1px solid #e2e8f0; margin: 0; }
.product-document-list > div { display: grid; grid-template-columns: 130px minmax(0, 1fr); border-bottom: 1px solid #edf2f7; }
.product-document-list > div:last-child { border-bottom: 0; }
.product-document-list dt { background: #f8fafc; padding: 11px 12px; color: #64748b; font-size: 10px; font-weight: 700; }
.product-document-list dd { margin: 0; padding: 11px 12px; color: #344054; font-size: 10px; line-height: 18px; white-space: pre-wrap; }
.product-manual-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.product-manual-list > a, .product-manual-unavailable { display: grid; min-width: 0; min-height: 40px; grid-template-columns: 28px minmax(0, 1fr) auto 16px; align-items: center; gap: 8px; border: 1px solid #dfe7f1; border-radius: 7px; background: #fbfdff; padding: 10px; color: inherit; text-decoration: none; transition: border-color 160ms ease, background 160ms ease, box-shadow 160ms ease; }
.product-manual-list > a:hover { border-color: #93c5fd; background: #f4f8ff; box-shadow: 0 6px 16px rgba(37, 99, 235, 0.08); }
.product-manual-list > a:focus-visible { outline: 2px solid #93c5fd; outline-offset: 2px; }
.product-manual-unavailable { opacity: 0.8; }
.product-manual-list svg { width: 16px; height: 16px; color: #2563eb; }
.product-manual-list strong { overflow: hidden; color: #344054; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.product-manual-list span { color: var(--as-positive-text, #15803d); font-size: 9px; }
.product-manual-unavailable > span { color: #64748b; }
.product-archive-empty { min-height: 54px; margin: 0; border: 1px solid #e2e8f0; padding: 14px; color: #8491a3; font-size: 10px; line-height: 18px; white-space: pre-wrap; }
@media (max-width: 980px) { .product-detail { padding-top: 54px; } .product-quick-nav { left: 10px; right: 10px; top: 62px; width: auto; flex-direction: row; gap: 6px; border-bottom: 1px solid #dbe4f0; background: rgba(241, 245, 249, 0.97); padding: 6px; } .product-quick-nav button { min-width: 0; flex: 1; justify-content: center; border-right: 1px solid #bfdbfe; border-radius: 6px; padding: 0 8px; box-shadow: none; } .product-quick-nav button:hover, .product-quick-nav button.active { transform: none; } }
@media (max-width: 640px) { .product-archive-content { padding: 12px; } .product-gallery-desktop { display: none; } .product-gallery-mobile { display: grid; } .product-gallery-main { min-height: 260px; height: 42vh; } .product-basics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .product-quick-nav span { display: none; } .product-manual-list { grid-template-columns: 1fr; } }
</style>
