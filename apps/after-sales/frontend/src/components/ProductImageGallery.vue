<script setup>
import { computed, ref, watch } from "vue";
import { ChevronLeft, ChevronRight, Image } from "@lucide/vue";
import ImagePreviewDialog from "@/components/ImagePreviewDialog.vue";

const props = defineProps({
  images: { type: Array, default: () => [] },
  fallbackUrl: { type: String, default: "" },
  name: { type: String, default: "产品" },
});

const galleryImages = computed(() => {
  const rows = Array.isArray(props.images) ? props.images : [];
  const images = rows.map((image, index) => ({
    key: image?.slot || String(index),
    preview: String(image?.preview || image?.thumbnail || ""),
    thumbnail: String(image?.thumbnail || image?.preview || ""),
  })).filter((image) => image.preview);
  return images.length ? images : (props.fallbackUrl ? [{ key: "cover", preview: props.fallbackUrl, thumbnail: props.fallbackUrl }] : []);
});

const selectedIndex = ref(0);
const fullImageOpen = ref(false);
const failedUrls = ref([]);
const selectedImage = computed(() => galleryImages.value[selectedIndex.value] || galleryImages.value[0]);
const moreCount = computed(() => Math.max(0, galleryImages.value.length - 4));

function sourceFor(image) {
  if (!image) return "";
  if (image.preview && !failedUrls.value.includes(image.preview)) return image.preview;
  return !failedUrls.value.includes(image.thumbnail) ? image.thumbnail : "";
}

function thumbnailFor(image) {
  if (!image) return "";
  if (image.thumbnail && !failedUrls.value.includes(image.thumbnail)) return image.thumbnail;
  return sourceFor(image);
}

const selectedSource = computed(() => sourceFor(selectedImage.value));

function markFailed(url) {
  if (url && !failedUrls.value.includes(url)) failedUrls.value = [...failedUrls.value, url];
}

function selectImage(index) {
  if (!galleryImages.value.length) return;
  selectedIndex.value = (index + galleryImages.value.length) % galleryImages.value.length;
}

watch([() => props.images, () => props.fallbackUrl, () => props.name], () => {
  selectedIndex.value = 0;
  fullImageOpen.value = false;
  failedUrls.value = [];
});
</script>

<template>
  <section class="as-product-gallery" :aria-label="`${name}产品图片`">
    <div class="as-product-gallery-main">
      <button v-if="selectedSource" type="button" class="as-product-gallery-view" :aria-label="`查看${name}第${selectedIndex + 1}张大图`" @click="fullImageOpen = true">
        <img :src="selectedSource" :alt="`${name}第${selectedIndex + 1}张图片`" @error="markFailed($event.target.getAttribute('src'))">
      </button>
      <div v-else class="as-product-gallery-empty" role="status"><Image aria-hidden="true" /><span>{{ galleryImages.length ? '产品图片暂时无法加载' : '暂无产品图片' }}</span></div>
      <template v-if="galleryImages.length > 1">
        <button type="button" class="as-product-gallery-arrow as-product-gallery-arrow--left" aria-label="上一张图片" title="上一张图片" @click="selectImage(selectedIndex - 1)"><ChevronLeft aria-hidden="true" /></button>
        <button type="button" class="as-product-gallery-arrow as-product-gallery-arrow--right" aria-label="下一张图片" title="下一张图片" @click="selectImage(selectedIndex + 1)"><ChevronRight aria-hidden="true" /></button>
        <span class="as-product-gallery-count" aria-live="polite">{{ selectedIndex + 1 }} / {{ galleryImages.length }}</span>
      </template>
    </div>
    <div v-if="galleryImages.length > 1" class="as-product-gallery-thumbs" role="group" aria-label="选择产品图片">
      <button v-for="(image, index) in galleryImages.slice(0, 4)" :key="image.key" type="button" class="as-product-gallery-thumb" :class="{ 'is-selected': selectedIndex === index }" :aria-label="`显示第${index + 1}张图片`" :aria-pressed="selectedIndex === index" @click="selectImage(index)">
        <img v-if="thumbnailFor(image)" :src="thumbnailFor(image)" :alt="`${name}缩略图${index + 1}`" loading="lazy" @error="markFailed($event.target.getAttribute('src'))">
        <Image v-else aria-hidden="true" />
      </button>
      <button v-if="moreCount" type="button" class="as-product-gallery-thumb as-product-gallery-more" :class="{ 'is-selected': selectedIndex >= 4 }" :aria-label="`显示第5张图片，其余${moreCount}张可通过左右箭头浏览`" :aria-pressed="selectedIndex >= 4" @click="selectImage(4)">
        <img v-if="thumbnailFor(galleryImages[4])" :src="thumbnailFor(galleryImages[4])" :alt="`${name}更多缩略图`" loading="lazy" @error="markFailed($event.target.getAttribute('src'))">
        <span>+{{ moreCount }}</span>
      </button>
    </div>
    <ImagePreviewDialog :open="fullImageOpen && Boolean(selectedSource)" :src="selectedSource" :images="galleryImages" :initial-index="selectedIndex" :title="name" @close="fullImageOpen = false" />
  </section>
</template>

<style scoped>
.as-product-gallery { min-width: 0; }
.as-product-gallery-main { position: relative; display: grid; width: 100%; min-height: 340px; height: min(58vh, 590px); place-items: center; overflow: hidden; border: 1px solid #e2e8f0; border-radius: 8px; background: #f6f8fc; }
.as-product-gallery-view { display: block; width: 100%; height: 100%; min-width: 0; min-height: 0; border: 0; background: transparent; padding: 0; cursor: zoom-in; }
.as-product-gallery-view img { display: block; width: 100%; height: 100%; box-sizing: border-box; object-fit: contain; padding: 18px; }
.as-product-gallery-empty { display: grid; place-items: center; gap: 8px; color: #64748b; font-size: 13px; }
.as-product-gallery-empty svg { width: 42px; height: 42px; color: #94a3b8; }
.as-product-gallery-arrow { position: absolute; top: 50%; display: grid; width: 42px; height: 56px; place-items: center; transform: translateY(-50%); border: 1px solid #dbe4f0; border-radius: 8px; background: rgb(255 255 255 / 96%); color: #1e3a5f; box-shadow: 0 4px 14px rgb(15 23 42 / 14%); cursor: pointer; }
.as-product-gallery-arrow:hover { border-color: #93c5fd; color: #1d4ed8; }
.as-product-gallery-arrow--left { left: 10px; }
.as-product-gallery-arrow--right { right: 10px; }
.as-product-gallery-arrow svg { width: 22px; height: 22px; }
.as-product-gallery-count { position: absolute; right: 12px; bottom: 10px; border-radius: 4px; background: rgb(15 23 42 / 68%); padding: 4px 7px; color: #fff; font-size: 12px; font-variant-numeric: tabular-nums; pointer-events: none; }
.as-product-gallery-thumbs { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 9px; margin-top: 10px; }
.as-product-gallery-thumb { position: relative; display: grid; min-width: 0; aspect-ratio: 4 / 3; place-items: center; overflow: hidden; border: 2px solid transparent; border-radius: 8px; background: #f8fafc; padding: 0; color: #94a3b8; cursor: pointer; }
.as-product-gallery-thumb:hover { border-color: #bfdbfe; }
.as-product-gallery-thumb.is-selected { border-color: #2563eb; }
.as-product-gallery-thumb img { display: block; width: 100%; height: 100%; object-fit: contain; }
.as-product-gallery-thumb > svg { width: 25px; height: 25px; }
.as-product-gallery-more::after { position: absolute; inset: 0; background: rgb(15 23 42 / 56%); content: ""; }
.as-product-gallery-more span { position: absolute; z-index: 1; color: #fff; font-size: 20px; font-weight: 800; }
.as-product-gallery button:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
</style>
