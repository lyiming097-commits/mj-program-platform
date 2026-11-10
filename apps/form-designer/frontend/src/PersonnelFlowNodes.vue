<script setup lang="ts">
import { BadgeCheck, Check, GitFork, Mail, UserRound } from '@lucide/vue'
import type { AssigneeMode, WorkflowNode } from './types'

defineProps<{
  nodes: WorkflowNode[]
  searchedId?: string
  replaced?: ReadonlyMap<string, ReadonlySet<string>>
  selected?: { node: WorkflowNode; source: string } | null
  disabled: boolean
  personName: (id: string) => string
}>()
const emit = defineEmits<{ select: [node: WorkflowNode, source: string] }>()

const icons = { approval: UserRound, executor: BadgeCheck, cc: Mail }
const ruleLabels: Partial<Record<AssigneeMode, string>> = {
  initiator: '由发起人处理',
  direct_manager: '按直属主管规则分配',
  department_manager: '按部门主管规则分配',
  form_field: '按表单成员字段分配',
}
</script>

<template>
  <div class="personnel-sequence">
    <template v-for="(node, index) in nodes" :key="node.id">
      <span v-if="index" class="personnel-wire arrow" aria-hidden="true"></span>
      <div v-if="node.type === 'condition'" class="personnel-condition">
        <span class="personnel-condition-title"><GitFork :size="14" aria-hidden="true" />{{ node.name }}</span>
        <template v-if="node.branches?.length">
          <span class="personnel-wire short" aria-hidden="true"></span>
          <div class="personnel-branches" :style="{ '--personnel-branch-count': node.branches.length }">
            <div v-for="branch in node.branches" :key="branch.id" class="personnel-branch">
              <span class="personnel-rail split" aria-hidden="true"></span>
              <span class="personnel-wire short" aria-hidden="true"></span>
              <div class="personnel-branch-title">
                <strong>{{ branch.name }}</strong><small v-if="branch.isDefault">默认</small>
              </div>
              <span :class="['personnel-wire', { arrow: branch.nodes?.length }]" aria-hidden="true"></span>
              <PersonnelFlowNodes
                v-if="branch.nodes?.length" :nodes="branch.nodes" :searched-id="searchedId"
                :replaced="replaced" :selected="selected" :disabled="disabled" :person-name="personName"
                @select="(child, id) => emit('select', child, id)"
              />
              <span class="personnel-wire tail" aria-hidden="true"></span>
              <span class="personnel-rail merge" aria-hidden="true"></span>
            </div>
          </div>
        </template>
      </div>
      <span v-else-if="node.type === 'start' || node.type === 'end'" :class="['personnel-terminal', node.type]">
        <component :is="node.type === 'start' ? UserRound : Check" :size="14" aria-hidden="true" />{{ node.name }}
      </span>
      <article v-else class="personnel-node-card" :class="{
        'search-hit': searchedId && node.assignees?.includes(searchedId),
        selected: selected?.node.id === node.id,
      }">
        <strong><component :is="icons[node.type]" :size="16" aria-hidden="true" />{{ node.name }}</strong>
        <div v-if="node.assignees?.length" class="personnel-names">
          <button
            v-for="id in node.assignees" :key="id" type="button" class="personnel-name"
            :class="{
              'search-hit': id === searchedId,
              'personnel-marked': id === searchedId || replaced?.get(node.id)?.has(id),
            }"
            :aria-pressed="selected?.node.id === node.id && selected.source === id"
            :aria-label="'修改 ' + node.name + ' 的 ' + personName(id)"
            :disabled="disabled" @click="emit('select', node, id)"
          >{{ personName(id) }}</button>
        </div>
        <small v-else>{{ ruleLabels[node.assigneeMode ?? 'specified'] || '尚未指定人员' }}</small>
      </article>
    </template>
  </div>
</template>

<style scoped>
.personnel-sequence, .personnel-condition, .personnel-branch {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.personnel-terminal, .personnel-condition-title {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 13px;
  border-radius: 18px;
  font-size: 12px;
}
.personnel-terminal { background: #283647; color: #fff; }
.personnel-terminal.end { background: #64748b; }
.personnel-condition-title { border: 1px solid #dce5f0; background: #fff; color: #26394f; }
.personnel-condition-title svg, .personnel-branch-title strong { color: #a4471a; }
.personnel-wire {
  position: relative;
  width: 0;
  height: 24px;
  flex: none;
  border-inline-start: 1px solid var(--personnel-wire);
}
.personnel-wire.short { height: 14px; }
.personnel-wire.tail { min-height: 15px; flex: 1; }
.personnel-wire.arrow::after {
  content: "";
  position: absolute;
  left: -3.5px;
  bottom: 2px;
  width: 6px;
  height: 6px;
  border-right: 1px solid var(--personnel-wire);
  border-bottom: 1px solid var(--personnel-wire);
  transform: rotate(45deg);
}
.personnel-branches {
  display: grid;
  width: max-content;
  grid-template-columns: repeat(var(--personnel-branch-count), minmax(196px, 1fr));
}
.personnel-branch { position: relative; padding: 0 10px; }
.personnel-rail { position: absolute; inset-inline: 0; height: 1px; background: var(--personnel-wire); }
.personnel-rail.split { top: 0; }
.personnel-rail.merge { bottom: 0; }
.personnel-branch:first-child > .personnel-rail { left: 50%; }
.personnel-branch:last-child > .personnel-rail { right: 50%; }
.personnel-node-card, .personnel-branch-title {
  width: 176px;
  padding: 8px 9px;
  border: 1px solid #dce5f0;
  border-radius: 7px;
  background: #fff;
  box-shadow: 0 1px 4px #102d4d08;
  overflow-wrap: anywhere;
}
.personnel-branch-title { display: flex; justify-content: space-between; align-items: center; gap: 5px; font-size: 12px; }
.personnel-branch-title small { color: #5f728b; white-space: nowrap; }
.personnel-node-card.selected { border-color: #1677ff; box-shadow: 0 0 0 1px #1677ff; }
.personnel-node-card.search-hit {
  border-color: #1d4ed8;
  background: #eff6ff;
  box-shadow: 0 0 0 2px #1d4ed8;
}
.personnel-node-card > strong { display: flex; align-items: center; gap: 6px; color: #20354d; font-size: 13px; }
.personnel-node-card svg { flex: none; color: #1668cf; }
.personnel-names { display: grid; gap: 4px; margin-top: 5px; }
.personnel-name {
  min-height: 28px;
  padding: 4px 6px;
  border: 0;
  border-radius: 4px;
  background: #f2f5f9;
  color: #304b66;
  text-align: left;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.personnel-name:hover:not(.search-hit):not(:disabled) { box-shadow: inset 0 0 0 1px #9cc5fd; }
.personnel-name.personnel-marked { background: #fff0f1; color: #b4232e; }
.personnel-name.search-hit {
  background: #ffe4e6;
  color: #9f1239;
  font-weight: 650;
  box-shadow: inset 0 0 0 2px #be123c;
}
.personnel-node-card > small { display: block; margin-top: 4px; color: #5f728b; }
@media (pointer: coarse) { .personnel-name { min-height: 44px; } }
</style>
