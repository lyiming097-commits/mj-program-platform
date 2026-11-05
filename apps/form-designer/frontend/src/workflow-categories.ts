import type { WorkflowSchema } from './types'

export const DEFAULT_WORKFLOW_CATEGORIES = [
  '销售流程', '商务流程', '售前流程', '采购流程',
  '行政流程', '人事流程', '财务流程', '产品流程',
] as const

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
  ])]
}
