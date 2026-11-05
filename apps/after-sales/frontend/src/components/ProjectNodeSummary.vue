<script setup>
defineProps({
  items: { type: Array, default: () => [] },
});
</script>

<template>
  <dl class="node-summary-grid">
    <div v-for="item in items" :key="item.label" class="node-summary-item" :class="{ 'is-wide': item.wide }">
      <dt>
        <span>{{ item.label }}</span>
        <em v-if="item.source" :class="`is-${item.tone || 'neutral'}`">{{ item.source }}</em>
      </dt>
      <dd :class="{ 'is-empty': !item.value || item.value === '-' }">{{ item.value || "-" }}</dd>
    </div>
  </dl>
</template>

<style scoped>
.node-summary-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 1px; overflow: hidden; border: 1px solid #dce5ef; border-radius: 6px; margin: 0; background: #e6edf4; padding: 1px; }
.node-summary-item { min-width: 0; min-height: 62px; background: #fff; padding: 9px 11px; }
.node-summary-item.is-wide { grid-column: span 2; }
.node-summary-item dt { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 8px; }
.node-summary-item dt > span { overflow: hidden; color: #748196; font-size: 10px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.node-summary-item em { flex: 0 0 auto; border-radius: 4px; background: #f1f5f9; padding: 1px 5px; color: #64748b; font-size: 8px; font-style: normal; font-weight: 750; }
.node-summary-item em.is-admin { background: #edf4ff; color: #315f9f; }
.node-summary-item em.is-mobile { background: #eaf8f2; color: #087550; }
.node-summary-item em.is-pending { background: #fff6df; color: #8a5d00; }
.node-summary-item dd { overflow: hidden; margin: 5px 0 0; color: #1f2a3a; font-size: 12px; font-weight: 750; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.node-summary-item dd.is-empty { color: #98a2b3; font-weight: 600; }
@media (max-width: 900px) { .node-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 620px) { .node-summary-grid { grid-template-columns: minmax(0, 1fr); } .node-summary-item.is-wide { grid-column: auto; } }
</style>
