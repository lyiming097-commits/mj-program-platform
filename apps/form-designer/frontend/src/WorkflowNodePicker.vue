<script setup lang="ts">
import { BadgeCheck, GitFork, Mail, UserRound } from '@lucide/vue'
import { onMounted, ref } from 'vue'
import type { AddableWorkflowNodeType } from './types'

const emit = defineEmits<{
  add: [type: AddableWorkflowNodeType]
  dragStart: [event: DragEvent, type: AddableWorkflowNodeType]
  dragEnd: []
}>()
const picker = ref<HTMLElement | null>(null)

onMounted(() => {
  const element = picker.value
  const viewport = element?.closest('.workflow-viewport')
  if (!element || !viewport) return
  const bounds = viewport.getBoundingClientRect()
  element.style.width = `${Math.min(312, bounds.width - 24)}px`
  const rect = element.getBoundingClientRect()
  const horizontalShift = Math.max(bounds.left + 12 - rect.left, Math.min(0, bounds.right - 12 - rect.right))
  const verticalShift = Math.max(bounds.top + 12 - rect.top, Math.min(0, bounds.bottom - 12 - rect.bottom))
  element.style.marginLeft = `${horizontalShift}px`
  element.style.marginTop = `${verticalShift}px`
})
</script>

<template>
  <div ref="picker" class="workflow-picker" aria-label="添加流程节点" @click.stop>
    <strong>人工节点</strong>
    <div class="workflow-picker-options">
      <button type="button" draggable="true" @dragstart.stop="emit('dragStart', $event, 'approval')" @dragend="emit('dragEnd')" @click="emit('add', 'approval')">
        <span class="workflow-picker-icon"><UserRound :size="16" /></span>审批人
      </button>
      <button type="button" draggable="true" @dragstart.stop="emit('dragStart', $event, 'executor')" @dragend="emit('dragEnd')" @click="emit('add', 'executor')">
        <span class="workflow-picker-icon"><BadgeCheck :size="16" /></span>执行人
      </button>
      <button type="button" draggable="true" @dragstart.stop="emit('dragStart', $event, 'cc')" @dragend="emit('dragEnd')" @click="emit('add', 'cc')">
        <span class="workflow-picker-icon"><Mail :size="16" /></span>抄送人
      </button>
    </div>
      <strong class="workflow-picker-divider">分支节点</strong>
      <div class="workflow-picker-options">
        <button type="button" draggable="true" @dragstart.stop="emit('dragStart', $event, 'condition')" @dragend="emit('dragEnd')" @click="emit('add', 'condition')">
          <span class="workflow-picker-icon condition"><GitFork :size="16" /></span>条件分支
        </button>
      </div>
  </div>
</template>
