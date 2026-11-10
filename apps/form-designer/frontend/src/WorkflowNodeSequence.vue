<script lang="ts">
import type { Component } from 'vue'
import type { AddableWorkflowNodeType, WorkflowBranch, WorkflowNode, WorkflowNodeType } from './types'

type Scope = 'root' | 'branch'
type DropHandler = (event: DragEvent, scope: Scope, index: number, branchId?: string) => void
type NodeDropHandler = (event: DragEvent, node: WorkflowNode, scope: Scope, index: number, branchId?: string) => void

export interface WorkflowCanvasEditor {
  icons: Record<WorkflowNodeType, Component>
  names: Record<WorkflowNodeType, string>
  selectedNodeId: string | null
  selectedBranchId: string | null
  draggedNodeId?: string
  dropTarget: string
  dropKey: (scope: Scope, index: number, branchId?: string) => string
  togglePicker: (index: number, branchId?: string) => void
  pickerOpen: (index: number, branchId?: string) => boolean
  addNode: (type: AddableWorkflowNodeType) => void
  selectNode: (node: WorkflowNode) => void
  removeNode: (id: string) => void
  selectBranch: (node: WorkflowNode, branch: WorkflowBranch) => void
  addBranch: (node: WorkflowNode) => void
  branchSummary: (branch: WorkflowBranch) => string
  assigneeSummary: (node: WorkflowNode) => string
  changed: () => void
  startDrag: (event: DragEvent, node: WorkflowNode, scope: Scope, branchId?: string) => void
  startNewDrag: (event: DragEvent, type: AddableWorkflowNodeType) => void
  finishDrag: () => void
  hover: DropHandler
  drop: DropHandler
  hoverNode: NodeDropHandler
  dropNode: NodeDropHandler
}
</script>

<script setup lang="ts">
import { computed } from 'vue'
import { ChevronRight, Plus, Settings2, Trash2 } from '@lucide/vue'
import WorkflowNodePicker from './WorkflowNodePicker.vue'

const props = defineProps<{ nodes: WorkflowNode[]; editor: WorkflowCanvasEditor; branchId?: string }>()
const scope = computed(() => props.branchId ? 'branch' : 'root')
const indexOffset = computed(() => props.branchId ? 0 : 1)
function addLabel(index: number) {
  if (index) return `在${props.nodes[index - 1].name}后添加节点`
  return props.branchId ? '在分支开始处添加节点' : '在发起后添加节点'
}
</script>

<template>
  <div :class="['workflow-node-sequence', { 'branch-node-list': branchId }]">
    <template v-for="(node, index) in [...nodes, null]" :key="node?.id ?? 'last-connector'">
      <div
        :class="['workflow-connector', { 'workflow-drop-active': editor.dropTarget === editor.dropKey(scope, index + indexOffset, branchId) }]"
        @dragover="editor.hover($event, scope, index + indexOffset, branchId)"
        @drop="editor.drop($event, scope, index + indexOffset, branchId)"
      >
        <span class="flow-line"></span>
        <button type="button" class="flow-add-button" :aria-label="addLabel(index)" :aria-expanded="editor.pickerOpen(index + indexOffset, branchId)" @click.stop="editor.togglePicker(index + indexOffset, branchId)"><Plus :size="15" /></button>
        <span class="workflow-drop-placeholder">放置到此处</span>
        <WorkflowNodePicker v-if="editor.pickerOpen(index + indexOffset, branchId)" @add="editor.addNode" @drag-start="editor.startNewDrag" @drag-end="editor.finishDrag" />
      </div>
      <section v-if="node?.type === 'condition'" :class="['condition-stage', { selected: editor.selectedNodeId === node.id, 'drag-source': editor.draggedNodeId === node.id }]" draggable="true"
        @dragstart.stop="editor.startDrag($event, node, scope, branchId)" @dragend.stop="editor.finishDrag"
        @dragover="editor.hoverNode($event, node, scope, index + indexOffset, branchId)" @drop="editor.dropNode($event, node, scope, index + indexOffset, branchId)">
        <div class="condition-stage-heading">
          <button type="button" class="condition-stage-label" @click.stop="editor.addBranch(node)">添加条件</button>
          <button type="button" class="icon-button small-icon" aria-label="配置条件分支" @click.stop="editor.selectNode(node)"><Settings2 :size="13" /></button>
          <button type="button" class="icon-button small-icon" aria-label="删除分支节点" @click.stop="editor.removeNode(node.id)"><Trash2 :size="13" /></button>
        </div>
        <div class="branch-columns" :style="{ '--branch-count': node.branches?.length || 1 }">
          <div v-for="(branch, branchIndex) in node.branches" :key="branch.id" :class="['workflow-branch', { active: editor.selectedBranchId === branch.id }]">
            <span class="branch-rail split" aria-hidden="true"></span>
            <button type="button" class="branch-rule" @click.stop="editor.selectBranch(node, branch)">
              <span class="branch-heading"><strong>{{ branch.name }}</strong><span class="branch-order">{{ branch.isDefault ? '默认出口' : `优先级${branchIndex + 1}` }}</span><Settings2 :size="13" /></span>
              <span class="branch-rule-summary">{{ editor.branchSummary(branch) }}</span>
            </button>
            <WorkflowNodeSequence :nodes="branch.nodes" :editor="editor" :branch-id="branch.id" />
            <span class="branch-rail merge" aria-hidden="true"></span>
          </div>
        </div>
        <div class="branch-merge-connector" aria-hidden="true"></div>
      </section>
      <article v-else-if="node" :data-workflow-node-id="node.id" :class="['workflow-node-card', { selected: editor.selectedNodeId === node.id, 'drag-source': editor.draggedNodeId === node.id }]" draggable="true"
        @dragstart.stop="editor.startDrag($event, node, scope, branchId)" @dragend.stop="editor.finishDrag"
        @dragover="editor.hoverNode($event, node, scope, index + indexOffset, branchId)" @drop="editor.dropNode($event, node, scope, index + indexOffset, branchId)" @click.stop="editor.selectNode(node)">
        <div class="workflow-node-head">
          <div :class="['workflow-node-icon', node.type]"><component :is="editor.icons[node.type]" :size="16" /></div>
          <div><input v-model="node.name" class="workflow-node-title-input" :aria-label="`${editor.names[node.type]}节点名称`" draggable="false" @click.stop="editor.selectNode(node)" @input="editor.changed" /></div>
          <button type="button" class="icon-button small-icon" aria-label="删除节点" @click.stop="editor.removeNode(node.id)"><Trash2 :size="14" /></button>
        </div>
        <button type="button" class="workflow-assignee-summary" @click.stop="editor.selectNode(node)"><span>{{ editor.assigneeSummary(node) }}</span><ChevronRight :size="14" /></button>
      </article>
    </template>
  </div>
</template>
