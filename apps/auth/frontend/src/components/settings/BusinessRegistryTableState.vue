<script setup>
import { LoaderCircle, RotateCcw } from "@lucide/vue";

defineProps({ colspan: { type: Number, required: true }, loading: Boolean, error: { type: String, default: "" }, empty: Boolean, message: { type: String, default: "暂无记录。" } });
defineEmits(["retry"]);
</script>

<template>
  <tr v-if="loading || error || empty" class="registry-state-row">
    <td :colspan="colspan">
      <div v-if="loading" role="status" class="registry-list-state"><LoaderCircle class="h-5 w-5 animate-spin text-blue-600" aria-hidden="true" />正在加载记录…</div>
      <div v-else-if="error" role="alert" class="registry-list-state">{{ error }}<button type="button" class="org-button" @click="$emit('retry')"><RotateCcw class="h-4 w-4" aria-hidden="true" />重新加载</button></div>
      <div v-else class="registry-list-state">{{ message }}</div>
    </td>
  </tr>
</template>
