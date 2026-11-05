<script setup lang="ts">
import { shallowRef, watch } from "vue";
import { downloadAuthenticatedFile } from "@/api/client";
import type { JsonRecord, ProductManual } from "@/api/types";
import TaskDetailManuals from "@/components/TaskDetailManuals.vue";

const props = defineProps<{
  products: readonly JsonRecord[];
  manuals: readonly ProductManual[];
  openingManual: string;
  projectId: number;
  nodeKey: string;
}>();

const emit = defineEmits<{ open: [manual: ProductManual] }>();
const expandedProductIds = shallowRef<readonly string[]>([]);
const productImageSources = shallowRef<Readonly<Record<string, string>>>({});
const productPreviewSources = shallowRef<Readonly<Record<string, string>>>({});
const productImageStates = shallowRef<Readonly<Record<string, "loading" | "failed">>>({});
const productImageLoads = new Map<string, Promise<string>>();

function valueText(value: unknown): string {
  return String(value ?? "").trim();
}

function productDisplayName(product: JsonRecord): string {
  return valueText(product.abbr) || valueText(product.name) || "未命名产品";
}

function productFullName(product: JsonRecord): string {
  const name = valueText(product.name);
  return name && name !== productDisplayName(product) ? name : "";
}

function productMeta(product: JsonRecord): string {
  return [product.brand, product.model].map(valueText).filter(Boolean).join(" / ") || "暂无品牌型号";
}

function productId(product: JsonRecord): string {
  return valueText(product.productId);
}

function productImageSource(product: JsonRecord): string {
  return productImageSources.value[productId(product)] || "";
}

function productImageState(product: JsonRecord): "loading" | "failed" | "" {
  return productImageStates.value[productId(product)] || "";
}

function setProductImageState(productIdValue: string, state: "loading" | "failed" | ""): void {
  const nextStates = { ...productImageStates.value };
  if (state) nextStates[productIdValue] = state;
  else delete nextStates[productIdValue];
  productImageStates.value = nextStates;
}

function productImagePath(product: JsonRecord, variant: "thumbnail" | "preview" = "thumbnail"): string {
  const currentProductId = productId(product);
  if (!currentProductId) return "";
  const configuredPath = variant === "preview" ? valueText(product.productPreview) : valueText(product.productThumb);
  const basePath = (configuredPath
    || valueText(product.productThumb)
    || `/api/after-sales/product-catalog/${encodeURIComponent(currentProductId)}/image?variant=${variant}`)
    .replace(/([?&])variant=(?:thumbnail|preview)(?=&|$)/, `$1variant=${variant}`);
  const separator = basePath.includes("?") ? "&" : "?";
  const nodeQuery = props.nodeKey ? `&nodeKey=${encodeURIComponent(props.nodeKey)}` : "";
  return `${basePath}${separator}projectId=${encodeURIComponent(String(props.projectId))}${nodeQuery}`;
}

async function loadProductImage(product: JsonRecord, notifyOnFailure = false): Promise<string> {
  const currentProductId = productId(product);
  const path = productImagePath(product);
  if (!currentProductId || !path) return "";
  if (productImageSources.value[currentProductId]) return productImageSources.value[currentProductId] || "";
  const activeLoad = productImageLoads.get(currentProductId);
  if (activeLoad) return activeLoad;

  setProductImageState(currentProductId, "loading");
  const loadPromise = downloadAuthenticatedFile(path)
    .then((source) => {
      productImageSources.value = { ...productImageSources.value, [currentProductId]: source };
      setProductImageState(currentProductId, "");
      return source;
    })
    .catch((reason: unknown) => {
      setProductImageState(currentProductId, "failed");
      if (notifyOnFailure) {
        console.error("产品图片加载失败", reason);
        uni.showToast({ title: "产品图片加载失败，请重试", icon: "none" });
      }
      return "";
    })
    .finally(() => { productImageLoads.delete(currentProductId); });
  productImageLoads.set(currentProductId, loadPromise);
  return loadPromise;
}

async function preloadProductImage(product: JsonRecord): Promise<void> {
  if (await loadProductImage(product)) return;
  await new Promise<void>((resolve) => { setTimeout(resolve, 800); });
  await loadProductImage(product);
}

function handleProductImageError(product: JsonRecord): void {
  const currentProductId = productId(product);
  if (!currentProductId) return;
  const nextSources = { ...productImageSources.value };
  delete nextSources[currentProductId];
  productImageSources.value = nextSources;
  setProductImageState(currentProductId, "failed");
}

async function previewProductImage(product: JsonRecord): Promise<void> {
  const currentProductId = productId(product);
  let thumbnail = productImageSource(product);
  if (!currentProductId) return;
  if (!thumbnail) thumbnail = await loadProductImage(product, true);
  if (!thumbnail) return;
  let current = productPreviewSources.value[currentProductId] || "";
  if (!current) {
    uni.showLoading({ title: "正在加载大图" });
    try {
      current = await downloadAuthenticatedFile(productImagePath(product, "preview"));
      productPreviewSources.value = { ...productPreviewSources.value, [currentProductId]: current };
    } catch {
      current = thumbnail;
      uni.showToast({ title: "大图加载失败，已显示缩略图", icon: "none" });
    } finally {
      uni.hideLoading();
    }
  }
  uni.previewImage({ current, urls: [current] });
}

watch(
  () => [props.projectId, props.nodeKey, ...props.products.map((product) => productId(product))].join("|"),
  () => { props.products.forEach((product) => { void preloadProductImage(product); }); },
  { immediate: true },
);

function manualsForProduct(product: JsonRecord): readonly ProductManual[] {
  const currentProductId = productId(product);
  if (!currentProductId) return [];
  return props.manuals.filter((manual) => (
    valueText(manual.productId) === currentProductId
    || valueText(manual.id).includes(`-${currentProductId}-`)
  ));
}

function productExpanded(product: JsonRecord): boolean {
  return expandedProductIds.value.includes(productId(product));
}

function toggleProduct(product: JsonRecord): void {
  const currentProductId = productId(product);
  if (!currentProductId) return;
  expandedProductIds.value = productExpanded(product)
    ? expandedProductIds.value.filter((id) => id !== currentProductId)
    : [...expandedProductIds.value, currentProductId];
}
</script>

<template>
  <view class="product-materials">
    <view v-if="props.products.length" class="product-list" role="list">
      <view
        v-for="(product, index) in props.products"
        :key="String(product.productId || index)"
        class="product-card"
        :class="{ 'is-expanded': productExpanded(product) }"
        role="listitem"
      >
        <view
          class="product-summary"
          role="button"
          :aria-label="`${productExpanded(product) ? '收起' : '展开'}${productDisplayName(product)}的说明书`"
          :aria-expanded="productExpanded(product)"
          hover-class="product-summary--pressed"
          @tap.stop="toggleProduct(product)"
        >
          <view class="product-image-frame" role="button" :aria-label="productImageSource(product) ? `查看${productDisplayName(product)}产品大图` : `重新加载${productDisplayName(product)}产品图片`" hover-class="product-image-frame--pressed" @tap.stop="previewProductImage(product)">
            <image
              v-if="productImageSource(product)"
              class="product-image"
              :src="productImageSource(product)"
              mode="aspectFit"
              :aria-label="`${productDisplayName(product)}产品图片`"
              @error="handleProductImageError(product)"
            />
            <text v-if="productImageSource(product)" class="product-image-hint">查看大图</text>
            <text v-else class="product-image-placeholder">{{ productImageState(product) === "loading" ? "加载中" : productImageState(product) === "failed" ? "点击重试" : "暂无图片" }}</text>
          </view>
          <view class="product-content">
            <view class="product-heading">
              <view class="product-title">
                <text class="product-name">{{ productDisplayName(product) }}</text>
                <text v-if="productFullName(product)" class="product-full-name">{{ productFullName(product) }}</text>
              </view>
              <view class="product-heading-actions">
                <text class="product-material-count">{{ manualsForProduct(product).length }} 份资料</text>
                <view class="product-chevron" :class="{ expanded: productExpanded(product) }" />
              </view>
            </view>
            <text class="product-meta">{{ productMeta(product) }}</text>
          </view>
        </view>
        <view v-if="productExpanded(product)" class="product-manuals">
          <TaskDetailManuals
            v-if="manualsForProduct(product).length"
            :manuals="manualsForProduct(product)"
            :opening-manual="props.openingManual"
            @open="emit('open', $event)"
          />
          <view v-else class="manual-empty">当前产品暂无可查看的说明书</view>
        </view>
      </view>
    </view>
    <view v-else class="product-empty">当前任务暂无相关产品</view>
  </view>
</template>

<style scoped>
.product-materials { display: grid; }
.product-list { display: grid; gap: 16rpx; }
.product-card { overflow: hidden; border: 1rpx solid #dce4ed; border-radius: 12rpx; background: #fff; }
.product-card.is-expanded { border-color: #b9cce7; }
.product-summary { display: flex; min-height: 128rpx; align-items: center; gap: 20rpx; padding: 22rpx; }
.product-summary--pressed { background: #f8fbff; }
.product-image-frame { position: relative; display: flex; width: 128rpx; height: 128rpx; flex: 0 0 128rpx; align-items: center; justify-content: center; overflow: hidden; border: 1rpx solid #e4e7ec; border-radius: 8rpx; background: #f7f9fc; }
.product-image-frame--pressed { opacity: .78; }
.product-image { width: 116rpx; height: 116rpx; }
.product-image-hint { position: absolute; right: 0; bottom: 0; left: 0; background: rgba(15, 23, 42, .68); padding: 5rpx 4rpx; color: #fff; font-size: 17rpx; font-weight: 700; line-height: 24rpx; text-align: center; }
.product-image-placeholder { color: #98a2b3; font-size: 19rpx; line-height: 28rpx; }
.product-content { min-width: 0; flex: 1; }
.product-heading { display: flex; min-width: 0; align-items: flex-start; justify-content: space-between; gap: 18rpx; }
.product-title { min-width: 0; }
.product-name, .product-full-name, .product-meta { display: block; }
.product-name { overflow-wrap: anywhere; color: #1d2939; font-size: 27rpx; font-weight: 800; line-height: 38rpx; }
.product-full-name { overflow-wrap: anywhere; margin-top: 4rpx; color: #667085; font-size: 21rpx; line-height: 32rpx; }
.product-heading-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 16rpx; }
.product-material-count { min-width: 88rpx; flex: 0 0 auto; border-radius: 8rpx; background: #eef4ff; padding: 7rpx 10rpx; color: #315f9f; font-size: 19rpx; font-weight: 700; line-height: 26rpx; text-align: center; }
.product-chevron { width: 15rpx; height: 15rpx; flex: 0 0 auto; border-right: 3rpx solid #7b8798; border-bottom: 3rpx solid #7b8798; margin: 0 5rpx 6rpx 0; transform: rotate(45deg); transition: transform .18s ease; }
.product-chevron.expanded { margin-top: 8rpx; margin-bottom: 0; transform: rotate(225deg); }
.product-meta { overflow-wrap: anywhere; margin-top: 12rpx; color: #344054; font-size: 23rpx; font-weight: 700; line-height: 34rpx; }
.product-manuals { border-top: 1rpx solid #e4e7ec; padding: 0 22rpx; }
.product-empty, .manual-empty { display: flex; min-height: 96rpx; align-items: center; justify-content: center; color: #7b8798; font-size: 22rpx; line-height: 34rpx; text-align: center; }
@media (max-width: 360px) {
  .product-summary { gap: 16rpx; padding: 18rpx; }
  .product-image-frame { width: 112rpx; height: 112rpx; flex-basis: 112rpx; }
  .product-image { width: 102rpx; height: 102rpx; }
  .product-heading { gap: 10rpx; }
  .product-heading-actions { gap: 10rpx; }
  .product-material-count { min-width: 78rpx; padding-right: 7rpx; padding-left: 7rpx; }
}
</style>
