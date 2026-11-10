export type FieldType =
  | 'text'
  | 'textarea'
  | 'number'
  | 'rating'
  | 'radio'
  | 'checkbox'
  | 'select'
  | 'multiSelect'
  | 'member'
  | 'department'
  | 'date'
  | 'dateRange'
  | 'image'
  | 'attachment'
  | 'description'

export interface FormField {
  id: string
  type: FieldType
  label: string
  required: boolean
  placeholder: string
  width: 'full' | 'half'
  options: string[]
  defaultValue?: string
  max?: number
}

export interface PageSettings {
  titleMode: 'default' | 'custom'
  customTitle: string
  allowCopy: boolean
  copyDataSource: 'initiator' | 'latest'
  previewBeforeSubmit: boolean
  oneClickGroup: boolean
  consultants: string[]
  showAdminWhenNoConsultant: boolean
  redirectMode: 'default' | 'internal' | 'external'
  redirectUrl: string
  afterApproval: 'next_dialog' | 'next_item' | 'stay'
  refreshMemberFields: boolean
  memberFieldsRefreshedAt?: string
}

export interface PagePermissions {
  accessMode: 'all' | 'members'
  members: string[]
  canSubmit: boolean
  canViewOwnRecords: boolean
  canViewAllRecords: boolean
  canExportRecords: boolean
}

export interface FormSchema {
  id: string
  name: string
  description: string
  fields: FormField[]
  pageSettings: PageSettings
  permissions: PagePermissions
  updatedAt?: string
}

export interface FormRecord {
  id: string
  formId: string
  title: string
  applicant: string
  values: FormValues
  createdAt: string
  updatedAt: string
  deletedAt?: string | null
}

export type FormValue = string | number | string[]
export type FormValues = Record<string, FormValue>

export interface UploadedFileInfo {
  id: string
  name: string
  size: number
  contentType: string
  isImage: boolean
}

export type WorkflowNodeType = 'start' | 'approval' | 'executor' | 'cc' | 'condition' | 'end'
export type AddableWorkflowNodeType = Exclude<WorkflowNodeType, 'start' | 'end'>
export type AssigneeMode = 'specified' | 'direct_manager' | 'department_manager' | 'initiator' | 'form_field'
export type ConditionOperator = 'eq' | 'neq' | 'gt' | 'gte' | 'lt' | 'lte' | 'contains' | 'empty' | 'not_empty'
export type ApprovalOpinionMode = 'none' | 'optional' | 'required'
export type FieldPermissionLevel = 'editable' | 'readonly' | 'hidden'

export interface ApprovalButtonConfig {
  key: string
  name: string
  enabled: boolean
  opinionMode: ApprovalOpinionMode
  batchEnabled: boolean
}

export interface WorkflowFieldPermission {
  fieldId: string
  permission: FieldPermissionLevel
}

export interface WorkflowBranch {
  id: string
  name: string
  fieldId?: string
  operator?: ConditionOperator
  value?: string
  isDefault: boolean
  nodes: WorkflowNode[]
}

export interface WorkflowNode {
  id: string
  type: WorkflowNodeType
  name: string
  formId?: string
  assigneeMode?: AssigneeMode
  assignees?: string[]
  assigneeFieldId?: string
  approvalButtons?: ApprovalButtonConfig[]
  fieldPermissions?: WorkflowFieldPermission[]
  approvalMode?: 'sequential' | 'all' | 'any'
  branches?: WorkflowBranch[]
}

export interface WorkflowSchema {
  draftSavedAt?: string
  disabledAt?: string | null
  deletedAt?: string | null
  id: string
  name: string
  category?: string
  nodes: WorkflowNode[]
  applicantFieldPermissions?: WorkflowFieldPermission[]
  publishedAt?: string | null
  publishedVersion?: number
  publishedSnapshot?: {
    name: string
    category?: string
    formId: string
    formSchema?: FormSchema
    version: number
    nodes: WorkflowNode[]
    applicantFieldPermissions?: WorkflowFieldPermission[]
  } | null
  updatedAt?: string
}

export interface WorkflowRunTask {
  id: string
  nodeId: string
  nodeName: string
  nodeType: 'approval' | 'executor' | 'cc'
  assigneeMode: AssigneeMode
  assignees: string[]
  assigneeNames: string[]
  branchPath: string[]
  status: 'pending' | 'waiting' | 'unassigned' | 'completed' | 'rejected' | 'returned' | 'recalled' | 'cancelled'
  approvalMode?: 'sequential' | 'all' | 'any'
  executionMode?: 'sequential'
  approvalButtons?: ApprovalButtonConfig[]
  fieldPermissions?: WorkflowFieldPermission[]
  assigneeProgress?: Record<string, string>
  activeAssigneeIndex?: number
  decisions?: Array<{ username: string; displayName: string; action: string; comment: string; createdAt: string; rejectBehavior?: 'return' | 'end' }>
}

export interface WorkflowPreview {
  version: number
  incomplete: boolean
  steps: { name: string; type: WorkflowRunTask['nodeType']; assigneeNames: string[] }[]
}

export interface WorkflowRunResult {
  id: string
  workflowId: string
  workflowName: string
  workflowVersion: number
  formId: string
  submissionId: string
  title: string
  applicant: string
  applicantUsername?: string
  canRecall?: boolean
  recall?: { username: string; displayName: string; actorUserId: string; actorName: string; comment: string; createdAt: string }
  status: 'pending' | 'pending_assignment' | 'completed' | 'rejected' | 'returned' | 'recalled'
  matchedBranches: Array<{
    nodeId: string
    conditionName: string
    branchId: string
    branchName: string
  }>
  tasks: WorkflowRunTask[]
  createdAt: string
  updatedAt?: string
  values?: FormValues
  formSchema?: FormSchema
}

export interface AuthUser {
  username: string
  displayName: string
  role: 'admin' | 'general_manager' | 'manager' | 'employee'
  department: string
  managerUsername?: string | null
  canManagePermissions?: boolean
  canDesign?: boolean
  canDesignGlobally?: boolean
  managedCategories?: string[]
}

export interface WorkflowTaskInboxItem {
  runId: string
  workflowId: string
  workflowName: string
  workflowVersion: number
  submissionId: string
  title: string
  applicant: string
  createdAt: string
  matchedBranches: WorkflowRunResult['matchedBranches']
  task: WorkflowRunTask
  form: Pick<FormSchema, 'id' | 'name' | 'fields'>
  values: FormValues
  actions: Array<{ key: string; name: string; enabled: boolean; opinionMode: ApprovalOpinionMode; batchEnabled?: boolean }>
}


export type ApprovalRecordScope = 'pending' | 'mine' | 'processed' | 'copied'
export type ApprovalSection = ApprovalRecordScope | 'workspace' | 'settings'
export type ApprovalPortalView = 'home' | 'workspace' | 'records' | 'settings'

export interface ApprovalRecord {
  id: string
  title: string
  workflowId: string
  workflowName: string
  category: string
  status: string
  stage: string
  applicant: string
  currentNode: string
  currentHandlers: string[]
  createdAt: string
  taskArrivedAt?: string | null
  mine: boolean
  delegated?: boolean
  participating: boolean
  processed: boolean
  copied?: boolean
  approving: boolean
  executing: boolean
  canHandle: boolean
}
export interface ApprovalCreated { form: FormSchema; workflow: WorkflowSchema }
export interface CategorySupervisorConfig {
  items: Array<{ category: string; supervisorUserIds: string[] }>
  revision: string
}
export interface WorkflowCategoryDefinition { key: string; name: string; deletedAt?: string | null }
export interface WorkflowCategorySettings {
  items: Array<WorkflowCategoryDefinition & { administratorUserIds: string[]; supervisorUserIds: string[] }>
  revision: string
}
export interface PersonnelTemplateHit {
  workflowId: string
  workflowName: string
  nodeId: string
  nodeName: string
  category: string
  categoryKey: string
  updatedAt: string
  locatable: boolean
  publishedVersion: number | null
  draft: boolean
  replaceable: boolean
  supervisor: boolean
}
export interface PersonnelImpact {
  people: { id: string; name: string; active: boolean }[]
  person: PersonnelImpact['people'][number] | null
  templates: PersonnelTemplateHit[]
  runs: { id: string; title: string; workflowName: string; category: string; tasks: { id: string; name: string; status: string }[] }[]
  flows: PersonnelFlow[]
}
export interface PersonnelFlow {
  id: string
  name: string
  category: string
  updatedAt: string
  publishedVersion: number | null
  nodes: WorkflowNode[]
}
export interface SupervisorDirectory {
  orgRevision: number
  departments: Array<{ id: string; name: string; children?: SupervisorDirectory['departments'] }>
  employees: Array<{
    userId: string; name: string; pinyinInitials?: string
    departments: Array<{ deptId: string; name?: string; pinyinInitials?: string; departmentPathText?: string }>
  }>
}
export interface ApprovalWorkspaceTarget {
  nodeId?: string
  page: '表单设计' | '流程设计' | '数据管理'
  formId?: string
  workflowId?: string
  newCategory?: string
}
