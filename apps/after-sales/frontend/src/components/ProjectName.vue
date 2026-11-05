<script setup>
import { computed } from "vue";

const props = defineProps({
  name: { type: String, required: true },
  createdAt: { type: String, default: "" },
  now: { type: Number, required: true },
});
const calendar = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
});
const isNew = computed(() => {
  const created = Date.parse(props.createdAt);
  return Number.isFinite(created) && calendar.format(created) === calendar.format(props.now);
});
</script>

<template>
  <strong class="as-project-name">
    <span class="as-project-name__text" :title="name">{{ name }}</span>
    <span v-if="isNew" class="as-project-name__new" title="今日在 CRM 新建的项目（北京时间）">新</span>
  </strong>
</template>

<style scoped>
.as-project-name__new { display: none; }
@media (min-width: 841px) {
  .as-project-name {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: center;
    gap: 6px;
  }
  .as-project-name__text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .as-project-name__new {
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    border-radius: 4px;
    padding: 1px 5px;
    background: #fef3c7;
    color: #b45309;
    font-size: 11px;
    font-weight: 600;
    line-height: 18px;
  }
}
</style>
