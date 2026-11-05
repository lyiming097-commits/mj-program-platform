<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import { BookOpen, Check, ChevronLeft, ChevronRight, Image, LoaderCircle, PackageOpen, Search } from "@lucide/vue";
import { ElOption, ElSelect } from "element-plus/es/components/select/index.mjs";
import "element-plus/es/components/select/style/css";
import ProjectDetailDrawer from "@/components/ProjectDetailDrawer.vue";
import RelatedProductDetailDrawer from "@/components/RelatedProductDetailDrawer.vue";
import { collectionRows, serviceApi } from "@/serviceApi";

const props = defineProps({
  open: { type: Boolean, default: false },
  projectName: { type: String, default: "" },
  selectedProducts: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
});

const emit = defineEmits(["close", "confirm"]);

const DEFAULT_CATEGORY_A = "自制设备";
const loading = shallowRef(false);
const keyword = shallowRef("");
const categoryA = shallowRef("");
const categoryB = shallowRef("");
const categoryC = shallowRef("");
const page = shallowRef(1);
const pageSize = 24;
const total = shallowRef(0);
const rows = ref([]);
const categoriesA = ref([]);
const categoriesB = ref([]);
const categoriesC = ref([]);
const selectedIds = ref([]);
const detailProduct = ref(null);
const loadError = shallowRef("");
let searchTimer = 0;
let requestSequence = 0;

const selectedCount = computed(() => selectedIds.value.length);
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));

function productId(product) {
  return Number(product?.productId || 0);
}

function isSelected(product) {
  return selectedIds.value.includes(productId(product));
}

function toggleProduct(product) {
  const id = productId(product);
  if (!id) return;
  selectedIds.value = isSelected(product)
    ? selectedIds.value.filter((value) => value !== id)
    : [...selectedIds.value, id];
}

function openProductDetail(product) {
  detailProduct.value = product;
}

function closeProductDetail() {
  detailProduct.value = null;
}

function productMeta(product) {
  return [product.brand, product.model].filter(Boolean).join(" / ") || "暂无品牌型号";
}

function productDisplayName(product) {
  return String(product?.abbr || product?.name || "").trim() || "未命名产品";
}

function productCategory(product) {
  return [product.categoryA, product.categoryB, product.categoryC].filter(Boolean).join(" · ") || "未分类";
}

async function loadProducts() {
  if (!props.open) return;
  const sequence = ++requestSequence;
  loading.value = true;
  loadError.value = "";
  try {
    const response = await serviceApi.listProductCatalog({
      q: keyword.value.trim(),
      categoryA: categoryA.value,
      categoryB: categoryB.value,
      categoryC: categoryC.value,
      page: page.value,
      pageSize,
    });
    if (sequence !== requestSequence) return;
    rows.value = collectionRows(response);
    total.value = Number(response?.total || 0);
    categoriesA.value = Array.isArray(response?.categoriesA) ? response.categoriesA : [];
    categoriesB.value = Array.isArray(response?.categoriesB) ? response.categoriesB : [];
    categoriesC.value = Array.isArray(response?.categoriesC) ? response.categoriesC : [];
  } catch (reason) {
    if (sequence !== requestSequence) return;
    rows.value = [];
    total.value = 0;
    loadError.value = reason instanceof Error ? reason.message : "产品档案读取失败";
  } finally {
    if (sequence === requestSequence) loading.value = false;
  }
}

function search() {
  window.clearTimeout(searchTimer);
  page.value = 1;
  void loadProducts();
}

function scheduleSearch() {
  window.clearTimeout(searchTimer);
  requestSequence += 1;
  searchTimer = window.setTimeout(search, 220);
}

function selectCategoryA(value) {
  categoryA.value = value || "";
  categoryB.value = "";
  categoryC.value = "";
  search();
}

function selectCategoryB(value) {
  categoryB.value = value || "";
  categoryC.value = "";
  search();
}

function selectCategoryC(value) {
  categoryC.value = value || "";
  search();
}

function changePage(nextPage) {
  if (nextPage < 1 || nextPage > totalPages.value || nextPage === page.value) return;
  page.value = nextPage;
  void loadProducts();
}

watch(
  () => props.open,
  (open) => {
    if (!open) {
      window.clearTimeout(searchTimer);
      requestSequence += 1;
      loading.value = false;
      detailProduct.value = null;
      return;
    }
    selectedIds.value = props.selectedProducts.map(productId).filter(Boolean);
    keyword.value = "";
    categoryA.value = DEFAULT_CATEGORY_A;
    categoryB.value = "";
    categoryC.value = "";
    page.value = 1;
    void loadProducts();
  },
  { immediate: true },
);

onBeforeUnmount(() => window.clearTimeout(searchTimer));
</script>

<template>
  <ProjectDetailDrawer
    :open="open"
    :title="`添加产品${projectName ? ` · ${projectName}` : ''}`"
    size="78%"
    :level="2"
    @close="emit('close')"
  >
    <div class="related-product-picker">
      <div class="related-product-toolbar">
        <label class="related-product-search">
          <span>搜索产品</span>
          <span class="related-product-control"><Search /><input v-model="keyword" type="search" placeholder="输入产品简称、名称、品牌、型号或金蝶代码" @input="scheduleSearch" @keyup.enter="search"></span>
        </label>
        <label class="related-product-filter">
          <span>产品分类</span>
          <span class="related-product-selects">
            <ElSelect :model-value="categoryA" clearable filterable placeholder="一级分类" popper-class="related-product-select-popper" @change="selectCategoryA">
              <ElOption v-for="item in categoriesA" :key="item" :label="item" :value="item" />
            </ElSelect>
            <ElSelect :model-value="categoryB" clearable filterable placeholder="二级分类" popper-class="related-product-select-popper" :disabled="!categoryA" @change="selectCategoryB">
              <ElOption v-for="item in categoriesB" :key="item" :label="item" :value="item" />
            </ElSelect>
            <ElSelect :model-value="categoryC" clearable filterable placeholder="三级分类" popper-class="related-product-select-popper" :disabled="!categoryB" @change="selectCategoryC">
              <ElOption v-for="item in categoriesC" :key="item" :label="item" :value="item" />
            </ElSelect>
          </span>
        </label>
      </div>

      <div v-if="loadError" class="related-product-error" role="alert">{{ loadError }}</div>
      <div class="related-product-grid" :aria-busy="loading">
        <article
          v-for="product in rows"
          :key="product.productId"
          class="related-product-card"
          :class="{ selected: isSelected(product) }"
        >
          <button type="button" class="related-product-open" :aria-label="`查看${productDisplayName(product)}详情`" title="查看产品详情" @click="openProductDetail(product)">
            <div class="related-product-image">
              <img v-if="product.productThumb" :src="product.productThumb" :alt="productDisplayName(product)">
              <Image v-else aria-hidden="true" />
            </div>
            <div class="related-product-copy">
              <div class="related-product-context"><span>{{ productCategory(product) }}</span><em>{{ product.lifecycle || '在用产品' }}</em></div>
              <h3>{{ productDisplayName(product) }}</h3>
              <p>{{ productMeta(product) }}</p>
              <div class="related-product-card-footer"><span><BookOpen />{{ product.manuals?.length ? `${product.manuals.length} 份说明书` : '暂无说明书' }}</span></div>
            </div>
          </button>
          <button type="button" class="related-product-select" :class="{ selected: isSelected(product) }" :aria-pressed="isSelected(product)" @click="toggleProduct(product)"><Check v-if="isSelected(product)" /><PackageOpen v-else />{{ isSelected(product) ? '已选择' : '选择' }}</button>
        </article>
        <div v-if="loading" class="related-product-state"><LoaderCircle class="as-spin" />正在读取产品档案...</div>
        <div v-else-if="!rows.length && !loadError" class="related-product-state"><PackageOpen />没有找到符合条件的产品</div>
      </div>

      <div class="related-product-pagination">
        <button type="button" aria-label="上一页" :disabled="page <= 1 || loading" @click="changePage(page - 1)"><ChevronLeft /></button>
        <span>第 {{ page }} / {{ totalPages }} 页，共 {{ total }} 项</span>
        <button type="button" aria-label="下一页" :disabled="page >= totalPages || loading" @click="changePage(page + 1)"><ChevronRight /></button>
      </div>
    </div>
    <template #footer>
      <div class="related-product-confirm-bar">
        <span>已选择 <strong>{{ selectedCount }}</strong> 项产品</span>
        <button type="button" class="related-product-confirm" :disabled="saving" @click="emit('confirm', selectedIds)"><LoaderCircle v-if="saving" class="as-spin" /><Check v-else />确认关联</button>
      </div>
    </template>
  </ProjectDetailDrawer>

  <RelatedProductDetailDrawer
    :open="Boolean(detailProduct)"
    :product="detailProduct"
    @close="closeProductDetail"
  />
</template>

<style scoped>
.related-product-picker { display: flex; min-height: 100%; flex-direction: column; }
.related-product-toolbar { position: sticky; top: 0; z-index: 3; display: grid; grid-template-columns: minmax(260px, 1fr) minmax(340px, 1fr); align-items: end; gap: 12px; margin-bottom: 14px; border: 1px solid #dbe4f0; border-radius: 8px; background: rgba(255, 255, 255, 0.96); padding: 12px; box-shadow: 0 4px 14px rgba(15, 23, 42, 0.05); backdrop-filter: blur(8px); }
.related-product-search, .related-product-filter { display: grid; min-width: 0; gap: 6px; color: #475569; font-size: 11px; font-weight: 650; }
.related-product-control { display: flex; height: 34px; align-items: center; gap: 8px; border: 1px solid #d8e1ec; border-radius: 7px; background: #fff; padding: 0 10px; color: #7b8da3; }
.related-product-control:focus-within { border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1); }
.related-product-control svg { width: 15px; height: 15px; flex: 0 0 auto; }
.related-product-control input { min-width: 0; flex: 1; border: 0; outline: 0; background: transparent; color: #172033; font: inherit; font-size: 12px; letter-spacing: 0; }
.related-product-selects { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.related-product-selects :deep(.el-select__wrapper) { min-height: 34px; border-radius: 7px; box-shadow: 0 0 0 1px #d8e1ec inset; }
.related-product-selects :deep(.el-select__wrapper.is-focused) { box-shadow: 0 0 0 1px #2563eb inset, 0 0 0 2px rgba(37, 99, 235, 0.1); }
:global(.related-product-select-popper.el-popper) { z-index: 2600 !important; }
.related-product-error { margin-bottom: 12px; border: 1px solid #fecaca; border-radius: 7px; background: #fff7f7; padding: 10px 12px; color: #b42318; font-size: 12px; }
.related-product-grid { position: relative; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; min-height: 300px; }
.related-product-card { position: relative; min-height: 158px; overflow: hidden; border: 1px solid #dce5ef; border-radius: 8px; background: #fff; transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease; }
.related-product-card:hover { border-color: #bfdbfe; box-shadow: 0 10px 24px rgba(37, 99, 235, 0.09); transform: translateY(-2px); }
.related-product-card.selected { border-color: #2563eb; background: #f8fbff; box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1); }
.related-product-open { display: grid; width: 100%; min-height: 158px; grid-template-columns: 124px minmax(0, 1fr); border: 0; background: transparent; padding: 0; color: inherit; cursor: pointer; text-align: left; }
.related-product-open:focus-visible { outline: 2px solid #60a5fa; outline-offset: -2px; }
.related-product-image { display: grid; min-width: 0; place-items: center; overflow: hidden; border-right: 1px solid #edf2f7; background: #f8fafc; color: #94a3b8; }
.related-product-image img { width: 100%; height: 100%; object-fit: contain; padding: 8px; }
.related-product-image svg { width: 30px; height: 30px; }
.related-product-copy { display: flex; min-width: 0; flex-direction: column; padding: 13px 14px 50px; }
.related-product-context { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 8px; color: #64748b; font-size: 10px; }
.related-product-context span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.related-product-context em { flex: 0 0 auto; border-radius: 4px; background: #ecfdf5; padding: 2px 6px; color: #0f766e; font-style: normal; }
.related-product-copy h3 { display: -webkit-box; min-height: 40px; margin: 7px 0 3px; overflow: hidden; color: #172033; font-size: 14px; font-weight: 700; line-height: 1.45; letter-spacing: 0; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.related-product-copy > p { margin: 0 0 10px; overflow: hidden; color: #64748b; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.related-product-card-footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; }
.related-product-card-footer > span { display: inline-flex; min-width: 0; align-items: center; gap: 5px; color: #64748b; font-size: 11px; }
.related-product-card-footer > span svg { width: 14px; height: 14px; }
.related-product-select { position: absolute; right: 14px; bottom: 13px; display: inline-flex; min-width: 78px; height: 30px; align-items: center; justify-content: center; gap: 5px; border: 1px solid #bfdbfe; border-radius: 6px; background: #eff6ff; color: #1d4ed8; cursor: pointer; font-size: 11px; font-weight: 700; }
.related-product-select.selected { border-color: #86efac; background: #f0fdf4; color: #15803d; }
.related-product-select:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; }
.related-product-select svg { width: 14px; height: 14px; }
.related-product-state { grid-column: 1 / -1; display: flex; min-height: 300px; align-items: center; justify-content: center; gap: 8px; color: #7b8da3; font-size: 13px; }
.related-product-state svg { width: 22px; height: 22px; }
.related-product-pagination { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 18px 0 12px; color: #64748b; font-size: 11px; }
.related-product-pagination button { display: grid; width: 30px; height: 30px; place-items: center; border: 1px solid #dbe4f0; border-radius: 6px; background: #fff; color: #475569; cursor: pointer; }
.related-product-pagination button:disabled { cursor: not-allowed; opacity: 0.45; }
.related-product-pagination svg { width: 15px; height: 15px; }
.related-product-confirm-bar { display: flex; min-height: 58px; align-items: center; justify-content: space-between; gap: 16px; background: #fff; padding: 12px 18px; }
.related-product-confirm-bar > span { color: #475569; font-size: 12px; }
.related-product-confirm-bar strong { color: #1d4ed8; font-size: 18px; }
.related-product-confirm { display: inline-flex; min-width: 112px; height: 34px; align-items: center; justify-content: center; gap: 6px; border: 1px solid #1d4ed8; border-radius: 7px; background: #2563eb; color: #fff; cursor: pointer; font-size: 12px; font-weight: 750; }
.related-product-confirm:disabled { cursor: not-allowed; opacity: 0.55; }
.related-product-confirm svg { width: 15px; height: 15px; }
@media (max-width: 980px) { .related-product-toolbar { grid-template-columns: 1fr; } .related-product-grid { grid-template-columns: 1fr; } }
@media (max-width: 767px) { .related-product-open { grid-template-columns: 104px minmax(0, 1fr); } }
</style>
