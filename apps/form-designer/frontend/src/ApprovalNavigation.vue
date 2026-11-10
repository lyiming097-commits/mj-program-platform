<script setup lang="ts">
import { Clock3, PanelsTopLeft, Send, Settings, UserRoundCheck, UserRoundPlus } from '@lucide/vue'
import type { ApprovalRecordScope, ApprovalSection } from './types'

defineProps<{ active: ApprovalSection; counts: Record<ApprovalRecordScope, number> }>()
const emit = defineEmits<{ select: [item: ApprovalSection] }>()
const records = [
  { id: 'pending', label: '待我处理', icon: Clock3 },
  { id: 'mine', label: '我创建的', icon: UserRoundPlus },
  { id: 'processed', label: '我已处理', icon: UserRoundCheck },
  { id: 'copied', label: '抄送我的', icon: Send },
] as const
</script>

<template>
  <nav class="approval-navigation" aria-label="审批导航">
    <ul class="approval-navigation-list">
      <li v-for="item in records" :key="item.id">
        <button type="button" :aria-current="active === item.id ? 'page' : undefined" @click="emit('select', item.id)">
          <component :is="item.icon" :size="17" />
          {{ item.label }}（{{ counts[item.id] }}）
        </button>
      </li>
      <li>
        <button type="button" :aria-current="active === 'workspace' ? 'page' : undefined" @click="emit('select', 'workspace')">
          <PanelsTopLeft :size="17" />审批中心
        </button>
      </li>
      <li>
        <button type="button" :aria-current="active === 'settings' ? 'page' : undefined" @click="emit('select', 'settings')">
          <Settings :size="17" />设置
        </button>
      </li>
    </ul>
  </nav>
</template>
