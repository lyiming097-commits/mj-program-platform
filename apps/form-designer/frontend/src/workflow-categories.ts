import { computed, ref } from 'vue'
import { listWorkflowCategories } from './api'
import type { WorkflowCategoryDefinition, WorkflowSchema } from './types'

export const DEFAULT_WORKFLOW_CATEGORIES = [
  '销售流程', '商务流程', '售前流程', '采购流程',
  '行政流程', '人事流程', '财务流程', '产品流程',
] as const

export const workflowCategoryDefinitions = ref<WorkflowCategoryDefinition[]>([])
export const recycledCategories = computed(() => new Map(workflowCategoryDefinitions.value.flatMap(item =>
  item.deletedAt ? [[item.key, item.deletedAt] as const] : [],
)))
export function updateWorkflowCategory(item: WorkflowCategoryDefinition) {
  const index = workflowCategoryDefinitions.value.findIndex(category => category.key === item.key)
  if (index === -1) workflowCategoryDefinitions.value.push(item)
  else workflowCategoryDefinitions.value[index] = item
}
export function categoryLabel(key: string): string {
  return workflowCategoryDefinitions.value.find(item => item.key === key)?.name ?? key
}
export async function refreshWorkflowCategories() {
  workflowCategoryDefinitions.value = await listWorkflowCategories()
}

export function workflowCategory(workflow: WorkflowSchema): string {
  const category = workflow.publishedSnapshot
    ? workflow.publishedSnapshot.category
    : workflow.category
  return category?.trim() || '常用流程'
}

// Match the launch catalog: presets plus categories from active published snapshots.
export function publishedWorkflowCategories(workflows: WorkflowSchema[]): string[] {
  return [...new Set<string>([
    ...DEFAULT_WORKFLOW_CATEGORIES,
    ...workflows.filter(workflow => workflow.publishedSnapshot && !workflow.disabledAt && !workflow.deletedAt)
      .map(workflowCategory),
  ])].filter(category => !recycledCategories.value.has(category))
}
