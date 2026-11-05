<script setup>
import { computed, nextTick, ref } from "vue";
import { PlatformImagePreviewDialog, sanitizeRichHtml } from "@platform-ui";
import { messageHtml, plainToHtml } from "./robotMessageContent";
defineOptions({ inheritAttrs: false });
const props = defineProps({
  html: { type: String, default: "" },
  text: { type: String, default: "" },
  inlineImages: { type: Boolean, default: false },
});
const emit = defineEmits(["preview-change"]);
const rendered = computed(() =>
  props.html ? (props.inlineImages ? inlineHtml(props.html) : messageHtml(props.html)) : plainToHtml(props.text),
);
function inlineHtml(value) {
  const template = document.createElement("template");
  template.innerHTML = sanitizeRichHtml(value);
  template.content.querySelectorAll("img").forEach(image => {
    image.setAttribute("role", "button");
    image.setAttribute("tabindex", "0");
    image.setAttribute("aria-label", "查看图片原图");
  });
  return template.innerHTML;
}
const preview = ref("");
let trigger;
function openImage(event) {
  const image = event.target.closest("img");
  if (!image || !event.currentTarget.contains(image)) return;
  if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  trigger = image;
  preview.value = image.getAttribute("src");
  emit("preview-change", true);
}
async function closeImage() {
  preview.value = "";
  emit("preview-change", false);
  await nextTick();
  trigger?.focus();
}
</script>
<template>
  <div
    v-bind="$attrs"
    class="robot-rich-message"
    @click="openImage"
    @keydown="openImage"
    v-html="rendered"
  />
  <PlatformImagePreviewDialog
    :open="Boolean(preview)"
    :source="preview"
    @close="closeImage"
  />
</template>
<style scoped>
.robot-rich-message {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.8;
}
.robot-rich-message :deep(img) {
  display: block;
  max-width: 100%;
  max-height: 360px;
  object-fit: contain;
  margin: 10px 0;
  cursor: zoom-in;
  border-radius: 6px;
}
.robot-rich-message :deep(a) {
  color: #2563eb;
  text-decoration: underline;
}
.robot-rich-message :deep(ul) {
  list-style: disc;
  padding-left: 24px;
}
.robot-rich-message :deep(ol) {
  list-style: decimal;
  padding-left: 24px;
}
.robot-rich-message :deep(blockquote) {
  border-left: 3px solid #cbd5e1;
  padding-left: 12px;
}
</style>
