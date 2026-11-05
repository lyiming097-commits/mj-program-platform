<script setup>
import { computed } from "vue";
import { ChevronLeft, ChevronRight } from "lucide-vue-next";

const props = defineProps({
  page: { type: Number, required: true },
  pageSize: { type: Number, default: 20 },
  pages: { type: Number, default: 1 },
  total: { type: Number, default: 0 },
  compact: { type: Boolean, default: false },
});

const emit = defineEmits(["change"]);
const current = computed(() => Math.min(Math.max(1, props.page), Math.max(1, props.pages)));
const items = computed(() => {
  const total = Math.max(1, props.pages);
  if (props.compact) {
    if (total <= 6) return Array.from({ length: total }, (_, index) => index + 1);
    if (current.value <= 4) return [1, 2, 3, 4, 5, "right", total];
    if (current.value >= total - 3) return [1, "left", total - 4, total - 3, total - 2, total - 1, total];
    return [1, "left", current.value - 1, current.value, current.value + 1, "right", total];
  }
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
  if (current.value <= 4) return [1, 2, 3, 4, 5, "right", total];
  if (current.value >= total - 3) return [1, "left", total - 4, total - 3, total - 2, total - 1, total];
  return [1, "left", current.value - 1, current.value, current.value + 1, "right", total];
});
</script>

<template>
  <footer class="desktop-pagination" :class="{ compact }">
    <span>共 {{ total }} 条 · 每页 {{ pageSize }} 条</span>
    <nav aria-label="分页">
      <button type="button" :disabled="current <= 1" :aria-label="compact ? '上一页' : undefined" :title="compact ? '上一页' : undefined" @click="emit('change', current - 1)"><ChevronLeft v-if="compact" :size="15" aria-hidden="true" /><template v-else>上一页</template></button>
      <template v-for="item in items" :key="item">
        <button
          v-if="typeof item === 'number'"
          type="button"
          :class="{ active: item === current }"
          :aria-current="item === current ? 'page' : undefined"
          @click="emit('change', item)"
        >{{ item }}</button>
        <span v-else class="ellipsis" aria-hidden="true">...</span>
      </template>
      <button type="button" :disabled="current >= Math.max(1, pages)" :aria-label="compact ? '下一页' : undefined" :title="compact ? '下一页' : undefined" @click="emit('change', current + 1)"><ChevronRight v-if="compact" :size="15" aria-hidden="true" /><template v-else>下一页</template></button>
    </nav>
  </footer>
</template>

<style scoped>
.desktop-pagination { position: relative; display: flex; min-height: 54px; flex: 0 0 auto; align-items: center; border-top: 1px solid #d9e4f0; background: #fff; padding: 0 16px; color: #64748b; font-size: 11px; }
.desktop-pagination nav { position: absolute; left: 50%; display: flex; align-items: center; transform: translateX(-50%); }
.desktop-pagination button { min-width: 36px; height: 32px; border: 0; background: transparent; padding: 0 8px; color: #334b70; font-size: 12px; }
.desktop-pagination button:first-child, .desktop-pagination button:last-child { min-width: 64px; color: #7f8fa7; }
.desktop-pagination button:hover:not(:disabled) { background: #f8fafc; }
.desktop-pagination button.active { background: #fff; color: #175cff; font-weight: 700; box-shadow: 0 2px 8px rgba(32, 61, 103, .12); }
.desktop-pagination button:disabled { opacity: .45; }
.ellipsis { display: grid; width: 28px; height: 32px; place-items: center; color: #7f8fa7; }
.desktop-pagination.compact { justify-content: space-between; gap: 8px; padding: 0 12px; }
.desktop-pagination.compact > span { white-space: nowrap; font-variant-numeric: tabular-nums; }
.desktop-pagination.compact nav { position: static; flex: 0 0 auto; transform: none; }
.desktop-pagination.compact button { display: grid; min-width: 28px; width: 28px; height: 32px; place-items: center; padding: 0; }
.desktop-pagination.compact button:first-child, .desktop-pagination.compact button:last-child { min-width: 30px; width: 30px; }
.desktop-pagination.compact .ellipsis { width: 12px; }
</style>
