<script setup>
import { computed, ref, toRefs } from "vue";

import { useAmapPreview } from "@/composables/useAmapPreview";

const props = defineProps({ latitude: Number, longitude: Number });
const { latitude, longitude } = toRefs(props);
const mapElement = ref(null);
const { loading, error } = useAmapPreview(mapElement, latitude, longitude);
const status = computed(() => error.value || (loading.value ? "地图加载中..." : ""));
</script>

<template>
  <div class="location-preview">
    <div ref="mapElement" class="location-preview-map" />
    <div v-if="status" class="location-preview-status" :class="{ error: error }">{{ status }}</div>
  </div>
</template>

<style scoped>
.location-preview{position:relative;width:100%;height:170px;overflow:hidden;border-bottom:1px solid #dfe6ee;background:#eef3f8}
.location-preview-map{width:100%;height:100%}
.location-preview-status{position:absolute;inset:0;display:grid;place-items:center;background:#f8fafccc;color:#64748b;font-size:10px}
.location-preview-status.error{color:#be123c}
</style>
