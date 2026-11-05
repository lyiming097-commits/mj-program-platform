<script setup>
import { ChevronRight, FileText, Plus } from "@lucide/vue";

defineProps({
  products: { type: Array, default: () => [] },
  editable: { type: Boolean, default: true },
  description: { type: String, default: "关联后，产品说明书会同步到对应现场人员的资料页。" },
});

const emit = defineEmits(["add", "open"]);

function productImage(product) {
  const id = Number(product?.productId || 0);
  return id > 0 ? `/api/after-sales/product-catalog/${id}/image?variant=thumbnail` : "";
}

function productMeta(product) {
  return [product?.brand, product?.model].filter(Boolean).join(" / ") || "暂无品牌型号";
}

function productDisplayName(product) {
  return String(product?.abbr || product?.name || "").trim() || "未命名产品";
}
</script>

<template>
  <details class="as-presales-fold as-related-products-fold">
    <summary>相关产品 <small>{{ products.length ? `${products.length} 项` : '暂未添加' }}</small></summary>
    <div class="as-related-products-panel">
      <div class="as-related-products-head">
        <div><strong>已关联产品</strong><span>{{ description }}</span></div>
        <button v-if="editable" type="button" class="as-button as-button--secondary" @click="emit('add')"><Plus />添加产品</button>
      </div>
      <div v-if="products.length" class="as-related-products-list">
        <article v-for="product in products" :key="product.productId">
          <button type="button" class="as-related-product-open" :aria-label="`查看${productDisplayName(product)}详情`" aria-haspopup="dialog" @click="emit('open', product)">
            <span class="as-related-product-image"><img v-if="productImage(product)" :src="productImage(product)" alt=""><FileText v-else aria-hidden="true" /></span>
            <span class="as-related-product-copy"><strong>{{ productDisplayName(product) }}</strong><small>{{ productMeta(product) }}</small><em>{{ product.manuals?.length ? `${product.manuals.length} 份说明书` : '暂无说明书' }}</em></span>
            <ChevronRight class="as-related-product-chevron" aria-hidden="true" />
          </button>
        </article>
      </div>
      <div v-else class="as-related-products-empty"><FileText /><span><strong>暂无相关产品</strong><small v-if="editable">点击“添加产品”从产品档案中选择。</small></span></div>
    </div>
  </details>
</template>
