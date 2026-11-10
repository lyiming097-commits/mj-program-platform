import type { ApprovalCreated, ApprovalRecord, AuthUser, CategorySupervisorConfig, FormRecord, FormSchema, FormValues, SupervisorDirectory, WorkflowRunResult, WorkflowPreview, WorkflowSchema, WorkflowTaskInboxItem } from './types'
import type { PersonnelFlow, PersonnelImpact, WorkflowCategoryDefinition, WorkflowCategorySettings } from './types'

import { apiFetchRaw, logoutLoginSession } from './session'
import type { UploadedFileInfo } from './types'
function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  return apiFetchRaw(input.replace(/^\/api\//, '/api/form-designer/'), { ...init, credentials: 'same-origin' })
}

export async function uploadFieldFile(file: File, workflowId: string, fieldId: string, runId?: string, taskId?: string): Promise<UploadedFileInfo> {
  const body = new FormData()
  body.append('file', file)
  body.append('workflowId', workflowId)
  body.append('fieldId', fieldId)
  if (runId) body.append('runId', runId)
  if (taskId) body.append('taskId', taskId)
  const response = await apiFetch('/api/uploads', { method: 'POST', body })
  if (!response.ok) throw await apiError(response, '上传失败，请重试')
  return response.json() as Promise<UploadedFileInfo>
}

function fileQuery(runId?: string, recordId?: string, inline = false) {
  const query = new URLSearchParams()
  if (runId) query.set('runId', runId)
  if (recordId) query.set('recordId', recordId)
  if (inline) query.set('inline', 'true')
  return query.size ? '?' + query.toString() : ''
}
export async function readUploadedFile(id: string, runId?: string, recordId?: string): Promise<UploadedFileInfo> {
  const response = await apiFetch(`/api/uploads/${encodeURIComponent(id)}${fileQuery(runId, recordId)}`)
  if (!response.ok) throw await apiError(response, '文件信息读取失败')
  return response.json() as Promise<UploadedFileInfo>
}
export async function readUploadedBlob(id: string, runId?: string, recordId?: string, inline = false): Promise<Blob> {
  const response = await apiFetch(`/api/uploads/${encodeURIComponent(id)}/content${fileQuery(runId, recordId, inline)}`)
  if (!response.ok) throw await apiError(response, '文件读取失败')
  return response.blob()
}

async function apiError(response: Response, fallback: string): Promise<Error> {
  try {
    const body = await response.json() as { detail?: string | string[] }
    if (Array.isArray(body.detail)) return new Error(body.detail.join('；'))
    if (body.detail) return new Error(body.detail)
  } catch {
    // Keep a useful message when the server does not return JSON.
  }
  return new Error(fallback)
}

export async function loadForm(id: string): Promise<FormSchema> {
  const response = await apiFetch(`/api/forms/${id}`)
  if (!response.ok) throw new Error('无法读取表单配置')
  return response.json() as Promise<FormSchema>
}

export async function listForms(): Promise<FormSchema[]> {
  const response = await apiFetch('/api/forms')
  if (!response.ok) throw new Error('无法读取表单列表')
  return response.json() as Promise<FormSchema[]>
}

export async function saveForm(form: FormSchema): Promise<FormSchema> {
  const response = await apiFetch(`/api/forms/${form.id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...(form.updatedAt ? { 'X-Form-Updated-At': form.updatedAt } : {}) },
    body: JSON.stringify(form),
  })
  if (!response.ok) throw await apiError(response, '表单保存失败，请重试')
  return response.json() as Promise<FormSchema>
}

export async function listFormRecords(formId: string, recycle = false): Promise<FormRecord[]> {
  const response = await apiFetch(`/api/forms/${formId}/records${recycle ? '?recycle=true' : ''}`)
  if (!response.ok) throw new Error('无法读取数据记录')
  return response.json() as Promise<FormRecord[]>
}

export async function createFormRecord(formId: string, record: Pick<FormRecord, 'title' | 'applicant' | 'values'>): Promise<FormRecord> {
  const response = await apiFetch(`/api/forms/${formId}/records`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(record),
  })
  if (!response.ok) throw new Error('新增记录失败')
  return response.json() as Promise<FormRecord>
}

export async function updateFormRecord(formId: string, record: FormRecord): Promise<FormRecord> {
  const response = await apiFetch(`/api/forms/${formId}/records/${record.id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: record.title, applicant: record.applicant, values: record.values }),
  })
  if (!response.ok) throw new Error('更新记录失败')
  return response.json() as Promise<FormRecord>
}

export async function deleteFormRecord(formId: string, recordId: string): Promise<void> {
  const response = await apiFetch(`/api/forms/${formId}/records/${recordId}`, { method: 'DELETE' })
  if (!response.ok) throw new Error('删除记录失败')
}

export async function restoreFormRecord(formId: string, recordId: string): Promise<FormRecord> {
  const response = await apiFetch(`/api/forms/${formId}/records/${recordId}/restore`, { method: 'POST' })
  if (!response.ok) throw new Error('恢复记录失败')
  return response.json() as Promise<FormRecord>
}

export async function loadWorkflow(id: string): Promise<WorkflowSchema> {
  const response = await apiFetch(`/api/workflows/${id}`)
  if (!response.ok) throw new Error('无法读取工作流配置')
  return response.json() as Promise<WorkflowSchema>
}

export async function listWorkflows(recycle = false): Promise<WorkflowSchema[]> {
  const response = await apiFetch('/api/workflows' + (recycle ? '?recycle=true' : ''))
  if (!response.ok) throw new Error('无法读取工作流列表')
  return response.json() as Promise<WorkflowSchema[]>
}

export async function listWorkflowAudit(): Promise<Array<{ id: number; action: string; actorId: string; effectiveUserId: string; createdAt: string }>> {
  const response = await apiFetch('/api/workflow-audit')
  if (!response.ok) throw await apiError(response, '无法读取流程操作记录')
  return response.json()
}

export async function saveWorkflow(workflow: WorkflowSchema): Promise<WorkflowSchema> {
  const response = await apiFetch(`/api/workflows/${workflow.id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...(workflow.updatedAt ? { 'X-Workflow-Updated-At': workflow.updatedAt } : {}) },
    body: JSON.stringify(workflow),
  })
  if (!response.ok) throw await apiError(response, '工作流保存失败')
  return response.json() as Promise<WorkflowSchema>
}

export async function createWorkflow(workflow: WorkflowSchema): Promise<WorkflowSchema> {
  const response = await apiFetch('/api/workflows', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(workflow),
  })
  if (!response.ok) throw new Error('创建工作流失败')
  return response.json() as Promise<WorkflowSchema>
}

export async function publishWorkflow(id: string): Promise<WorkflowSchema> {
  const response = await apiFetch(`/api/workflows/${id}/publish`, { method: 'POST' })
  if (!response.ok) throw await apiError(response, '工作流发布失败')
  return response.json() as Promise<WorkflowSchema>
}

export async function changeWorkflowStatus(id: string, action: 'disable' | 'enable' | 'delete' | 'restore'): Promise<WorkflowSchema> {
  const response = await apiFetch(`/api/workflows/${encodeURIComponent(id)}${action === 'delete' ? '' : '/' + action}`, { method: action === 'delete' ? 'DELETE' : 'POST' })
  if (!response.ok) throw await apiError(response, '流程状态修改失败，请重试')
  return response.json() as Promise<WorkflowSchema>
}

export async function previewWorkflowRun(id: string, payload: { values: FormValues }): Promise<WorkflowPreview> {
  const response = await apiFetch(`/api/workflows/${id}/preview`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  if (!response.ok) throw await apiError(response, '预计审批流程加载失败')
  return response.json() as Promise<WorkflowPreview>
}

export async function renameWorkflow(id: string, name: string, updatedAt: string): Promise<{ workflow: WorkflowSchema; forms: FormSchema[] }> {
  const response = await apiFetch(`/api/workflows/${encodeURIComponent(id)}/name`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, updatedAt }),
  })
  if (!response.ok) throw await apiError(response, '流程名称保存失败')
  return response.json()
}

export async function startWorkflowRun(id: string, payload: { values: FormValues; expectedVersion?: number }): Promise<WorkflowRunResult> {
  const response = await apiFetch(`/api/workflows/${id}/runs`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  if (!response.ok) throw await apiError(response, '流程发起失败')
  return response.json() as Promise<WorkflowRunResult>
}

export async function listMyWorkflowRuns(): Promise<WorkflowRunResult[]> {
  const response = await apiFetch('/api/workflow-runs/mine')
  if (!response.ok) throw await apiError(response, '无法读取我的申请记录')
  return response.json() as Promise<WorkflowRunResult[]>
}

export async function listAllWorkflowRuns(): Promise<WorkflowRunResult[]> {
  const response = await apiFetch('/api/workflow-runs')
  if (!response.ok) throw await apiError(response, '无法读取全部申请记录')
  return response.json() as Promise<WorkflowRunResult[]>
}

export async function currentUser(): Promise<AuthUser> {
  const response = await apiFetch('/api/auth/me')
  if (!response.ok) throw await apiError(response, '登录已失效')
  return response.json() as Promise<AuthUser>
}

export async function logout(): Promise<void> { await logoutLoginSession() }

export async function listUserDirectory(): Promise<AuthUser[]> {
  const response = await apiFetch('/api/users/directory')
  if (!response.ok) throw await apiError(response, '无法读取员工目录')
  return response.json() as Promise<AuthUser[]>
}

export async function listTaskInbox(): Promise<WorkflowTaskInboxItem[]> {
  const response = await apiFetch('/api/tasks/inbox')
  if (!response.ok) throw await apiError(response, '无法读取待办任务')
  return response.json() as Promise<WorkflowTaskInboxItem[]>
}

export async function listTaskHistory(): Promise<Array<{ runId: string; workflowName: string; title: string; applicant: string; runStatus: string; nodeName: string; action: string; comment: string; createdAt: string }>> {
  const response = await apiFetch('/api/tasks/history')
  if (!response.ok) throw await apiError(response, '无法读取已处理记录')
  return response.json()
}

export async function actOnTask(runId: string, taskId: string, payload: {
  action: string
  comment?: string
  values?: FormValues
  targetUsername?: string
  rejectBehavior?: 'return' | 'end'
}): Promise<{ ok: boolean; runStatus: string; taskStatus: string }> {
  const response = await apiFetch(`/api/tasks/${runId}/${taskId}/action`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  if (!response.ok) throw await apiError(response, '处理任务失败')
  return response.json() as Promise<{ ok: boolean; runStatus: string; taskStatus: string }>
}


export async function recallWorkflowRun(id: string, comment: string): Promise<{ ok: boolean; runStatus: 'recalled'; recall: NonNullable<WorkflowRunResult['recall']> }> {
  const response = await apiFetch(`/api/workflow-runs/${encodeURIComponent(id)}/recall`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment }),
  })
  if (!response.ok) throw await apiError(response, '撤回申请失败')
  return response.json()
}

export async function listApprovalRecords(scope: 'applications' | 'personal' = 'applications'): Promise<ApprovalRecord[]> {
  const response = await apiFetch('/api/approval-records' + (scope === 'personal' ? '?scope=personal' : ''))
  if (!response.ok) throw await apiError(response, '无法读取流程状态')
  return response.json()
}
export async function loadApprovalRecord(id: string): Promise<WorkflowRunResult> {
  const response = await apiFetch(`/api/approval-records/${encodeURIComponent(id)}`)
  if (!response.ok) throw await apiError(response, '无法读取审批详情')
  return response.json()
}
export async function saveNewApprovalDraft(workflow: WorkflowSchema, form: FormSchema): Promise<ApprovalCreated> {
  const response = await apiFetch(`/api/approval-drafts/${encodeURIComponent(workflow.id)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workflow, form }),
  })
  if (!response.ok) throw await apiError(response, '保存审批草稿失败')
  return response.json()
}

export async function getCategorySupervisors(): Promise<CategorySupervisorConfig> {
  const response = await apiFetch('/api/category-supervisors')
  if (!response.ok) throw await apiError(response, '无法读取分类主管')
  return response.json()
}

export async function getSupervisorDirectory(): Promise<SupervisorDirectory> {
  const response = await apiFetch('/api/permissions/directory')
  if (!response.ok) throw await apiError(response, '无法读取主管人员目录')
  return response.json()
}

export async function saveCategorySupervisors(payload: { category: string; supervisorUserIds: string[]; revision: string; orgRevision: string }): Promise<CategorySupervisorConfig> {
  const response = await apiFetch('/api/category-supervisors', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  if (!response.ok) throw Object.assign(await apiError(response, '保存分类主管失败'), { status: response.status })
  return response.json()
}

export async function listWorkflowCategories(): Promise<WorkflowCategoryDefinition[]> {
  const response = await apiFetch('/api/workflow-categories')
  if (!response.ok) throw await apiError(response, '无法读取流程分类')
  return response.json()
}

export async function getWorkflowCategorySettings(): Promise<WorkflowCategorySettings> {
  const response = await apiFetch('/api/workflow-category-settings')
  if (!response.ok) throw await apiError(response, '无法读取流程设置')
  return response.json()
}

export async function saveWorkflowCategory(payload: { key?: string; name: string; supervisorUserIds: string[]; administratorUserIds: string[]; revision: string; orgRevision: string }): Promise<WorkflowCategoryDefinition> {
  const response = await apiFetch('/api/workflow-category-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  if (!response.ok) throw Object.assign(await apiError(response, '保存流程失败'), { status: response.status })
  return response.json()
}

export async function getPersonnelImpact(userId = ''): Promise<PersonnelImpact> {
  const response = await apiFetch('/api/workflow-personnel' + (userId ? '?userId=' + encodeURIComponent(userId) : ''))
  if (!response.ok) throw await apiError(response, '人员排查失败')
  return response.json()
}

export async function changeWorkflowCategoryStatus(key: string, action: 'delete' | 'restore', revision?: string): Promise<WorkflowCategoryDefinition> {
  const response = await apiFetch('/api/workflow-category-settings/lifecycle', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key, action, revision }),
  })
  if (!response.ok) throw await apiError(response, '分组状态修改失败')
  return response.json() as Promise<WorkflowCategoryDefinition>
}

export async function savePersonnelAssignment(change: {
  workflowId: string; nodeId: string; updatedAt: string; source: string; target: string; assignees: string[]
}): Promise<{ workflow: WorkflowSchema; flow: PersonnelFlow }> {
  const response = await apiFetch('/api/workflow-personnel/assignees', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(change),
  })
  if (!response.ok) throw await apiError(response, '人员修改保存失败')
  return response.json()
}
