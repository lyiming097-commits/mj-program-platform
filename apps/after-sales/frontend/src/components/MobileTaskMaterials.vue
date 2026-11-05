<script setup>
import { ChevronRight, FileLock2 } from "@lucide/vue";

defineProps({
  materials: { type: Array, default: () => [] },
});

const emit = defineEmits(["open"]);

function display(item, ...keys) {
  for (const key of keys) {
    const value = item?.[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return "-";
}
</script>

<template>
  <details class="as-field-section as-mobile-detail-fold as-mobile-task-material-section">
    <summary class="as-field-section__head"><div><h2>产品说明书</h2></div><span class="as-status">{{ materials.length }} 份</span></summary>
    <div class="as-mobile-material-list as-mobile-task-materials">
      <button v-for="material in materials" :key="material.id" type="button" @click="emit('open', material)">
        <span><FileLock2 /></span>
        <div>
          <strong>{{ display(material, 'title', 'name', 'file_name', 'fileName') }}</strong>
          <small>{{ display(material, 'resourceTypeLabel', 'category_name', 'categoryName', 'category') }}</small>
          <p>{{ display(material, 'audienceLabel', 'authorization_display', 'authorizationDisplay', 'projectName', 'project_name') }}</p>
        </div>
        <ChevronRight />
      </button>
      <div v-if="!materials.length" class="as-empty as-empty--compact"><FileLock2 /> 当前任务暂无关联产品说明书</div>
    </div>
  </details>
</template>
