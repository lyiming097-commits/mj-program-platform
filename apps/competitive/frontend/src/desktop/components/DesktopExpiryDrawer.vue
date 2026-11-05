<script setup>
import { AlertTriangle, CalendarClock, CalendarDays } from "lucide-vue-next";

import AppModal from "@/shared/AppModal.vue";

defineProps({ open: Boolean, summary: { type: Object, default: null } });
defineEmits(["close"]);

function timingLabel(daysRemaining) {
  if (daysRemaining < 0) return `已逾期 ${Math.abs(daysRemaining)} 天`;
  if (daysRemaining === 0) return "今日到期";
  return `${daysRemaining} 天后到期`;
}
</script>

<template>
  <AppModal
    :open="open"
    title="到期任务"
    subtitle="未来 30 天及已过期的竞品采集资料"
    width="672px"
    @close="$emit('close')"
  >
    <div class="expiry-summary">
      <article class="upcoming"><span><CalendarDays :size="16" /></span><div><small>未来 30 天到期</small><strong>{{ summary?.upcomingCount ?? '-' }}<em>条</em></strong></div></article>
      <article class="expired"><span><AlertTriangle :size="16" /></span><div><small>已过期</small><strong>{{ summary?.expiredCount ?? '-' }}<em>条</em></strong></div></article>
    </div>
    <div v-if="!summary" class="empty-state compact">正在读取到期任务...</div>
    <div v-else-if="!summary.tasks.length" class="empty-state compact">未来 30 天没有到期任务</div>
    <div v-else class="task-list">
      <article v-for="task in summary.tasks" :key="task.id" class="task-row">
        <span class="task-icon" :class="{ expired: task.daysRemaining < 0 }"><CalendarClock :size="17" /></span>
        <div><div class="task-title"><strong>{{ task.title }}</strong><em :class="{ expired: task.daysRemaining < 0 }">{{ timingLabel(task.daysRemaining) }}</em></div><p>关联产品：{{ task.productName }} · 责任人：{{ task.owner }}</p><small>有效期至 {{ task.expires }}</small></div>
      </article>
    </div>
  </AppModal>
</template>

<style scoped>
.expiry-summary { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: -20px -20px 16px; border-bottom: 1px solid #edf1f6; background: #fbfcfe; padding: 12px 20px; }
.expiry-summary article { display: flex; min-width: 0; align-items: center; gap: 10px; border: 1px solid #e5ebf3; border-radius: 8px; padding: 10px 12px; }.expiry-summary article.upcoming { background: #f1f6ff; }.expiry-summary article.expired { background: #fff4f5; }
.expiry-summary article > span { display: grid; width: 32px; height: 32px; flex: 0 0 auto; place-items: center; border-radius: 7px; background: #fff; color: #155eef; box-shadow: 0 1px 2px rgba(21,94,239,.1); }.expiry-summary article.expired > span { color: #e11d48; }
.expiry-summary small, .expiry-summary strong { display: block; }.expiry-summary small { color: #6680a3; font-size: 10px; }.expiry-summary strong { margin-top: 2px; color: #155eef; font-size: 19px; line-height: 21px; }.expiry-summary article.expired strong { color: #e11d48; }.expiry-summary em { margin-left: 4px; font-size: 10px; font-style: normal; font-weight: 500; }
.task-list { display: grid; gap: 9px; }.task-row { display: flex; align-items: flex-start; gap: 12px; border: 1px solid #dfe7f1; border-radius: 8px; background: #fff; padding: 13px; }.task-icon { display: grid; width: 36px; height: 36px; flex: 0 0 auto; place-items: center; border-radius: 7px; background: #fffbeb; color: #d97706; }.task-icon.expired { background: #fff1f2; color: #e11d48; }.task-row > div { min-width: 0; flex: 1; }.task-title { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }.task-title strong { color: #17345e; font-size: 12px; }.task-title em { border-radius: 10px; background: #fffbeb; padding: 2px 7px; color: #b45309; font-size: 9px; font-style: normal; font-weight: 700; }.task-title em.expired { background: #fff1f2; color: #e11d48; }.task-row p { margin: 5px 0 0; color: #71839d; font-size: 10px; }.task-row small { display: block; margin-top: 4px; color: #94a3b8; font-size: 9px; }.compact { min-height: 180px; }
</style>
