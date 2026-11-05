<script setup>
import { computed, shallowRef, toRef, watch } from "vue";
import { FileText } from "lucide-vue-next";

const props = defineProps({
  file: { type: Object, default: null },
  src: { type: String, default: "" },
  name: { type: String, default: "附件" },
  type: { type: String, default: "" },
});
const file = toRef(props, "file");
const localUrl = shallowRef("");
const failed = shallowRef(false);
const mediaType = computed(() => props.file?.type || props.type || "");
const imageSource = computed(() => props.src || localUrl.value);
const canShowImage = computed(() => mediaType.value.startsWith("image/") && imageSource.value && !failed.value);

watch(file, (nextFile, _previousFile, onCleanup) => {
  failed.value = false;
  localUrl.value = "";
  if (!nextFile?.type?.startsWith("image/")) return;
  const url = URL.createObjectURL(nextFile);
  localUrl.value = url;
  onCleanup(() => URL.revokeObjectURL(url));
}, { immediate: true });
watch(() => props.src, () => { failed.value = false; });
</script>

<template>
  <img v-if="canShowImage" class="attachment-thumbnail image" :src="imageSource" :alt="name" @error="failed = true" />
  <span v-else class="attachment-thumbnail fallback"><FileText :size="17" /></span>
</template>

<style scoped>
.attachment-thumbnail{display:grid;flex:0 0 auto;place-items:center;overflow:hidden;border:1px solid #dce6f1;border-radius:6px;background:#fff;color:#155eef}
.attachment-thumbnail.image{object-fit:cover}
.attachment-thumbnail.fallback{background:#eff6ff}
</style>
