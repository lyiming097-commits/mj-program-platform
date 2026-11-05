<script setup lang="ts">
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js"
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  AlignLeft, ArrowLeft, ArrowRight, BadgeCheck, Building2, CalendarDays,
  Check, ClipboardList, ChevronDown, ChevronRight, CircleHelp, Code2, Copy, Database, GitFork,
  Eye, FileText, Grip, Hash, History, ImagePlus,
  LayoutGrid, ListChecks, LoaderCircle, LockKeyhole, MoreHorizontal, Paperclip, Pin,
  Plus, Radio, Save, Search, Settings2, Sparkles,
  LogOut, Play, Rocket, Star, Trash2, UserRound, Users, X,
} from '@lucide/vue'
import { createWorkflow as createWorkflowApi, currentUser as currentUserApi, listForms, listUserDirectory, listWorkflows, loadForm, loadWorkflow, logout as logoutApi, publishWorkflow as publishWorkflowApi, saveForm, saveWorkflow as saveWorkflowApi, startWorkflowRun as startWorkflowRunApi } from './api'
import DataManagement from './DataManagement.vue'
import EmployeePortal from './EmployeePortal.vue'
import { DEFAULT_WORKFLOW_CATEGORIES } from './workflow-categories'
import type { ApprovalButtonConfig, ApprovalWorkspaceTarget, AssigneeMode, AuthUser, ConditionOperator, FieldPermissionLevel, FieldType, FormField, FormSchema, PagePermissions, PageSettings, WorkflowBranch, WorkflowFieldPermission, WorkflowNode, WorkflowNodeType, WorkflowRunResult, WorkflowRunTask, WorkflowSchema } from './types'
import './workflow-runtime.css'
import './auth.css'
import { scopedStorage, setStorageUser } from './storage'
import { initializeSession, disposeSession, loginUrl } from './session'
defineProps<{ managementItems: { id: string; label: string }[] }>()
const emit = defineEmits<{ 'user-change': [AuthUser]; 'page-change': [string]; 'management-page': [string]; 'portal-view-change': [view: 'home' | 'workspace' | 'records'] }>()

type PaletteItem = { type: FieldType; label: string; icon: typeof AlignLeft }
const paletteGroups: { title: string; items: PaletteItem[] }[] = [
  { title: '基础组件', items: [
    { type: 'text', label: '单行文本', icon: AlignLeft }, { type: 'textarea', label: '多行文本', icon: FileText },
    { type: 'number', label: '数值', icon: Hash }, { type: 'rating', label: '评分', icon: Star },
    { type: 'radio', label: '单选', icon: Radio }, { type: 'checkbox', label: '复选', icon: ListChecks },
    { type: 'select', label: '下拉单选', icon: ChevronDown }, { type: 'multiSelect', label: '下拉复选', icon: ListChecks },
    { type: 'member', label: '成员', icon: UserRound }, { type: 'department', label: '部门', icon: Building2 },
    { type: 'date', label: '日期', icon: CalendarDays }, { type: 'dateRange', label: '日期区间', icon: CalendarDays },
    { type: 'image', label: '图片上传', icon: ImagePlus }, { type: 'attachment', label: '附件', icon: Paperclip },
    { type: 'description', label: '说明文字', icon: FileText },
  ] },
]

const iconMap: Record<FieldType, typeof AlignLeft> = Object.fromEntries(
  paletteGroups.flatMap((group) => group.items.map((item) => [item.type, item.icon])),
) as Record<FieldType, typeof AlignLeft>
const baseNames: Record<FieldType, string> = {
  text: '单行文本', textarea: '多行文本', number: '数值', rating: '评分', radio: '单选', checkbox: '复选',
  select: '下拉单选', multiSelect: '下拉复选', member: '成员', department: '部门', date: '日期',
  dateRange: '日期区间', image: '图片上传', attachment: '附件', description: '说明文字',
}
const fieldPermissionOptions: { value: FieldPermissionLevel; label: string }[] = [
  { value: 'editable', label: '可编辑' },
  { value: 'readonly', label: '只读' },
  { value: 'hidden', label: '隐藏' },
]

function makeId() { return `field-${Math.random().toString(36).slice(2, 9)}` }
function makeField(type: FieldType): FormField {
  const label = baseNames[type]
  const hasOptions = ['radio', 'checkbox', 'select', 'multiSelect'].includes(type)
  return {
    id: makeId(), type, label, required: false, placeholder: type === 'description' ? '' : `请输入${label}`,
    width: 'half', options: hasOptions ? ['选项一', '选项二', '选项三'] : [],
  }
}
function defaultPageSettings(): PageSettings {
  return {
    titleMode: 'default', customTitle: '', allowCopy: false, copyDataSource: 'initiator',
    previewBeforeSubmit: true, oneClickGroup: true, consultants: [], showAdminWhenNoConsultant: false,
    redirectMode: 'default', redirectUrl: '', afterApproval: 'next_dialog', refreshMemberFields: true,
  }
}
function defaultPagePermissions(): PagePermissions {
  return { accessMode: 'all', members: [], canSubmit: true, canViewOwnRecords: true, canViewAllRecords: false, canExportRecords: false }
}
function normalizeFormSchema(schema: FormSchema): FormSchema {
  schema.pageSettings = { ...defaultPageSettings(), ...(schema.pageSettings ?? {}) }
  schema.permissions = { ...defaultPagePermissions(), ...(schema.permissions ?? {}) }
  schema.pageSettings.consultants ??= []
  schema.permissions.members ??= []
  return schema
}
function fallbackForm(): FormSchema {
  return {
    id: 'sample', name: '物品申请', description: '', pageSettings: defaultPageSettings(), permissions: defaultPagePermissions(), fields: [
      { id: 'item-name', type: 'text', label: '申请物品', required: true, placeholder: '例如显示器、键盘、工牌', width: 'half', options: [] },
      { id: 'quantity', type: 'number', label: '申请数量', required: true, placeholder: '请输入数量', width: 'half', options: [], defaultValue: '1' },
      { id: 'unit-price', type: 'number', label: '预计单价', required: true, placeholder: '请输入数字', width: 'half', options: [] },
      { id: 'address', type: 'select', label: '地址', required: true, placeholder: '填写地址', width: 'half', options: ['北京', '上海', '杭州', '深圳'] },
      { id: 'total', type: 'number', label: '预计总金额', required: false, placeholder: '请输入总金额', width: 'half', options: [] },
      { id: 'scene', type: 'select', label: '使用场景', required: true, placeholder: '请选择', width: 'half', options: ['日常办公', '项目需要', '设备更换', '其他'] },
      { id: 'remark', type: 'textarea', label: '详细说明', required: false, placeholder: '请补充申请原因或其他说明', width: 'full', options: [] },
    ],
  }
}
function emptyForm(id: string, name: string): FormSchema {
  return {
    id, name, description: '', fields: [],
    pageSettings: defaultPageSettings(), permissions: defaultPagePermissions(),
  }
}

function defaultApprovalButtons(): ApprovalButtonConfig[] {
  return [
    { key: 'agree', name: '同意', enabled: true, opinionMode: 'optional', batchEnabled: true },
    { key: 'reject', name: '拒绝', enabled: true, opinionMode: 'optional', batchEnabled: true },
    { key: 'save', name: '保存', enabled: false, opinionMode: 'none', batchEnabled: false },
    { key: 'transfer', name: '转交', enabled: false, opinionMode: 'optional', batchEnabled: false },
    { key: 'countersign', name: '加签', enabled: false, opinionMode: 'optional', batchEnabled: false },
    { key: 'return', name: '退回', enabled: false, opinionMode: 'required', batchEnabled: false },
    { key: 'recall', name: '收回', enabled: false, opinionMode: 'none', batchEnabled: false },
  ]
}
function defaultFieldPermissions(fields = workflowForm.value.fields): WorkflowFieldPermission[] {
  return fields.map((field) => ({ fieldId: field.id, permission: 'editable' }))
}

function fallbackWorkflow(id = 'sample', name = '物品申请审批流程'): WorkflowSchema {
  return {
    id, name, category: '常用流程', nodes: [
      { id: 'start', type: 'start', name: '发起', formId: 'sample' },
      { id: 'manager-approval', type: 'approval', name: '主管审批', assigneeMode: 'specified', assignees: ['approver'], approvalButtons: defaultApprovalButtons(), approvalMode: 'sequential' },
      { id: 'amount-condition', type: 'condition', name: '金额条件', branches: [
        { id: 'high-amount', name: '高金额申请', fieldId: 'total', operator: 'gt', value: '1000', isDefault: false, nodes: [
          { id: 'department-approval', type: 'approval', name: '主管审批', assigneeMode: 'specified', assignees: ['approver'], approvalButtons: defaultApprovalButtons(), approvalMode: 'sequential' },
        ] },
        { id: 'normal-amount', name: '普通金额申请', isDefault: true, nodes: [] },
      ] },
      { id: 'admin-execution', type: 'executor', name: '行政执行', assigneeMode: 'specified', assignees: ['employee-a'] },
      { id: 'end', type: 'end', name: '结束' },
    ],
  }
}

const employeePortal = ref<InstanceType<typeof EmployeePortal> | null>(null)
const form = ref<FormSchema>(fallbackForm())
const forms = ref<FormSchema[]>([])
const workflow = ref<WorkflowSchema>(fallbackWorkflow())
const workflows = ref<WorkflowSchema[]>([])
const workflowListOpen = ref(false)
const formListOpen = ref(false)
const formCreateOpen = ref(false)
const newFormName = ref('')
const isCreatingForm = ref(false)
const selectedId = ref<string | null>('item-name')
const selectedWorkflowNodeId = ref<string | null>('manager-approval')
const selectedWorkflowBranchId = ref<string | null>(null)
const panelTab = ref<'components' | 'data' | 'logic'>('components')
const panelSearch = ref('')
const activeTopTab = ref('工作台')
const pageSettingsTab = ref<'base' | 'permissions'>('base')
const dragActive = ref(false)
const previewOpen = ref(false)
const previewAnswers = ref<Record<string, string | string[]>>({})
const previewWorkflowId = ref('')
const workflowRunResult = ref<WorkflowRunResult | null>(null)
const isSubmittingWorkflow = ref(false)
const workflowSavedMessage = ref('已保存')
const isSavingWorkflow = ref(false)
const isPublishingWorkflow = ref(false)
const workflowCreateOpen = ref(false)
const newWorkflowName = ref('')
const newWorkflowCategory = ref('')
const workflowCreateError = ref('')
const workflowCreateDiscardOpen = ref(false)
const isCreatingWorkflow = ref(false)
const workflowCategoryOptions = computed(() => [...new Set([
  ...DEFAULT_WORKFLOW_CATEGORIES, '常用流程',
  workflow.value.category?.trim(), workflow.value.publishedSnapshot?.category?.trim(),
  ...workflows.value.flatMap(item => [item.category?.trim(), item.publishedSnapshot?.category?.trim()]),
].filter((category): category is string => Boolean(category)))])
const workflowCategorySelection = computed<string>({
  get: () => workflow.value.category || '',
  set: category => {
    if (category !== workflow.value.category) {
      workflow.value.category = category
      workflowChanged()
    }
  },
})
const nodePicker = ref<{ scope: 'root'; index: number } | { scope: 'branch'; branchId: string; index: number } | null>(null)
type WorkflowNodeDrag =
  | { kind: 'move'; nodeId: string; scope: 'root'; branchId?: never }
  | { kind: 'move'; nodeId: string; scope: 'branch'; branchId: string }
  | { kind: 'create'; nodeType: 'approval' | 'executor' | 'condition' }
const workflowNodeDrag = ref<WorkflowNodeDrag | null>(null)
const workflowDropTarget = ref('')
const people = ref<string[]>([])
const directoryUsers = ref<AuthUser[]>([])
function personLabel(id: string) { const user = directoryUsers.value.find(item => item.username === id); return user ? `${user.displayName} (${user.username})` : id }
const currentUser = ref<AuthUser | null>(null)
const loginError = ref('')
const isSaving = ref(false)
const saveMessage = ref('已保存')
const toast = ref('')
const historyPast = ref<string[]>([])
const historyFuture = ref<string[]>([])
const lastSnapshot = ref('')
const suppressHistory = ref(false)
let toastTimer: ReturnType<typeof setTimeout> | undefined
let formRevision = 0
let workflowRevision = 0
const workflowMigrationsPending = new Set<string>()

const selectedField = computed(() => form.value.fields.find((field) => field.id === selectedId.value) ?? null)
const selectedWorkflowNode = computed(() => selectedWorkflowNodeId.value ? findWorkflowNode(selectedWorkflowNodeId.value) : null)
const selectedWorkflowBranch = computed(() => selectedWorkflowBranchId.value ? findWorkflowBranch(selectedWorkflowBranchId.value) : null)
const availableForms = computed(() => [form.value, ...forms.value.filter((item) => item.id !== form.value.id)])
const workflowForm = computed(() => {
  const formId = workflow.value.nodes.find((node) => node.type === 'start')?.formId ?? form.value.id
  return availableForms.value.find((item) => item.id === formId) ?? form.value
})
const publishedWorkflowsForForm = computed(() => workflows.value.filter((item) => item.publishedSnapshot?.formId === form.value.id))
const workflowPublishStatus = computed(() => {
  if (workflow.value.deletedAt) return '已删除'
  if (workflow.value.disabledAt) return '已停用'
  const snapshot = workflow.value.publishedSnapshot
  if (!snapshot) return '未发布'
  const current = JSON.stringify({ name: workflow.value.name, category: workflow.value.category ?? '常用流程', nodes: workflow.value.nodes, applicantFieldPermissions: workflow.value.applicantFieldPermissions ?? [] })
  const published = JSON.stringify({ name: snapshot.name, category: snapshot.category ?? '常用流程', nodes: snapshot.nodes, applicantFieldPermissions: snapshot.applicantFieldPermissions ?? [] })
  return current === published ? '已发布' : '有未发布修改'
})
const approvalTab = ref<'assignees' | 'buttons' | 'fields' | 'advanced'>('assignees')
const executorTab = ref<'assignees' | 'fields'>('assignees')
const conditionFields = computed(() => workflowForm.value.fields.filter((field) => field.type !== 'image' && field.type !== 'attachment'))
const memberFields = computed(() => workflowForm.value.fields.filter((field) => field.type === 'member'))
const workflowNodeCount = computed(() => countWorkflowActions(workflow.value.nodes))
const nodeIcons = { start: Play, approval: UserRound, executor: UserRound, condition: GitFork, end: Check }
const nodeTypeNames: Record<WorkflowNodeType, string> = { start: '发起', approval: '审批人', executor: '执行人', condition: '条件分支', end: '结束' }
const assigneeModeNames: Record<AssigneeMode, string> = { specified: '指定成员', direct_manager: '直属主管', department_manager: '部门主管', initiator: '发起人本人', form_field: '表单成员字段' }
const operatorNames: Record<ConditionOperator, string> = { eq: '等于', neq: '不等于', gt: '大于', gte: '大于等于', lt: '小于', lte: '小于等于', contains: '包含', empty: '为空', not_empty: '不为空' }
const approvalActionNames: Record<string, string> = { agree: '同意', reject: '拒绝', save: '保存', transfer: '转交', countersign: '加签', return: '退回', recall: '收回' }
const visibleGroups = computed(() => paletteGroups.map((group) => ({
  ...group,
  items: group.items.filter((item) => item.label.toLowerCase().includes(panelSearch.value.toLowerCase())),
})).filter((group) => group.items.length))
const fieldCount = computed(() => form.value.fields.length)
const componentCount = computed(() => paletteGroups.reduce((total, group) => total + group.items.length, 0))
const memberRefreshLabel = computed(() => form.value.pageSettings.memberFieldsRefreshedAt ? `上次刷新：${new Date(form.value.pageSettings.memberFieldsRefreshedAt).toLocaleString()}` : '尚未刷新')

function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T }
function formContentSignature(schema: FormSchema): string {
  const content = clone(schema)
  delete content.updatedAt
  const sortKeys = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(sortKeys)
    if (value !== null && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(([key, item]) => [key, sortKeys(item)]))
    }
    return value
  }
  return JSON.stringify(sortKeys(content)) ?? ''
}
function setToast(message: string) {
  toast.value = message
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 2400)
}
function togglePagePerson(list: string[], person: string) {
  const index = list.indexOf(person)
  if (index >= 0) list.splice(index, 1)
  else list.push(person)
  changed()
}
function refreshMemberFields() {
  form.value.pageSettings.refreshMemberFields = true
  form.value.pageSettings.memberFieldsRefreshedAt = new Date().toISOString()
  changed()
  setToast(`已刷新 ${memberFields.value.length} 个成员字段`)
}
const formNameSettingInput = ref<HTMLInputElement | null>(null)
async function editFormHeader() {
  selectedId.value = null
  await nextTick()
  formNameSettingInput.value?.focus()
}
function changed() {
  formRevision += 1
  saveMessage.value = '有未保存的更改'
}
function findWorkflowNode(id: string, nodes: WorkflowNode[] = workflow.value.nodes): WorkflowNode | null {
  for (const node of nodes) {
    if (node.id === id) return node
    for (const branch of node.branches ?? []) {
      const nested = findWorkflowNode(id, branch.nodes)
      if (nested) return nested
    }
  }
  return null
}
function countWorkflowActions(nodes: WorkflowNode[]): number {
  return nodes.reduce((total, node) => total + (node.type === 'start' || node.type === 'end' ? 0 : 1) + (node.branches ?? []).reduce((branchTotal, branch) => branchTotal + countWorkflowActions(branch.nodes), 0), 0)
}
function findWorkflowBranch(id: string): WorkflowBranch | null {
  for (const node of workflow.value.nodes) {
    for (const branch of node.branches ?? []) {
      if (branch.id === id) return branch
      const nested = findWorkflowBranchInNodes(id, branch.nodes)
      if (nested) return nested
    }
  }
  return null
}
function findWorkflowBranchInNodes(id: string, nodes: WorkflowNode[]): WorkflowBranch | null {
  for (const node of nodes) {
    for (const branch of node.branches ?? []) {
      if (branch.id === id) return branch
      const nested = findWorkflowBranchInNodes(id, branch.nodes)
      if (nested) return nested
    }
  }
  return null
}
function normalizeWorkflowConfig(schema: WorkflowSchema): WorkflowSchema {
  if (schema.id === 'sample') {
    const migrateLegacyAssignees = (nodes: WorkflowNode[]) => {
      for (const node of nodes) {
        if (node.assignees?.length === 1 && (node.assignees[0] === '陈主管' || node.assignees[0] === '王经理')) {
          node.assignees = ['approver']
          node.assigneeMode = 'specified'
          workflowMigrationsPending.add(schema.id)
        } else if (node.assignees?.length === 1 && node.assignees[0] === '钟小康') {
          node.assignees = ['employee-a']
          node.assigneeMode = 'specified'
          workflowMigrationsPending.add(schema.id)
        }
        for (const branch of node.branches ?? []) migrateLegacyAssignees(branch.nodes)
      }
    }
    migrateLegacyAssignees(schema.nodes)
  }
  schema.category ||= '常用流程'
  const startNode = schema.nodes.find((node) => node.type === 'start')
  if (startNode) startNode.formId ??= form.value.id
  const formId = startNode?.formId ?? form.value.id
  const linkedForm = availableForms.value.find((item) => item.id === formId) ?? form.value
  const applicantPermissionByField = new Map((schema.applicantFieldPermissions ?? []).map((item) => [item.fieldId, item.permission]))
  schema.applicantFieldPermissions = linkedForm.fields.map((field) => ({
    fieldId: field.id,
    permission: normalizeFieldPermission(applicantPermissionByField.get(field.id)),
  }))
  if (schema.publishedSnapshot) {
    const publishedFields = schema.publishedSnapshot.formSchema?.fields ?? linkedForm.fields
    const publishedPermissions = new Map((schema.publishedSnapshot.applicantFieldPermissions ?? []).map((item) => [item.fieldId, item.permission]))
    schema.publishedSnapshot.applicantFieldPermissions = publishedFields.map((field) => ({
      fieldId: field.id,
      permission: normalizeFieldPermission(publishedPermissions.get(field.id)),
    }))
  }
  const normalizeNodes = (nodes: WorkflowNode[]) => {
    for (const node of nodes) {
      if (node.type === 'approval' || node.type === 'executor') {
        if (node.assigneeMode && !['specified', 'direct_manager'].includes(node.assigneeMode)) {
          workflowMigrationsPending.add(schema.id)
          node.assigneeMode = 'specified'
        }
        node.assigneeMode ??= 'specified'
        node.assignees ??= []
        const permissionByField = new Map((node.fieldPermissions ?? []).map((item) => [item.fieldId, item.permission]))
        node.fieldPermissions = linkedForm.fields.map((field) => ({
          fieldId: field.id,
          permission: normalizeFieldPermission(permissionByField.get(field.id)),
        }))
      }
      if (node.type === 'approval') {
        node.approvalButtons ??= defaultApprovalButtons()
        node.approvalMode ??= 'sequential'
        const legacyJumpSettings = node as WorkflowNode & { allowTransfer?: boolean; allowCountersign?: boolean; returnTarget?: string }
        delete legacyJumpSettings.allowTransfer
        delete legacyJumpSettings.allowCountersign
        delete legacyJumpSettings.returnTarget
      }
      for (const branch of node.branches ?? []) normalizeNodes(branch.nodes)
    }
  }
  normalizeNodes(schema.nodes)
  return schema
}
function normalizeFieldPermission(value: unknown): FieldPermissionLevel {
  return value === 'readonly' || value === 'hidden' ? value : 'editable'
}
function branchSummary(branch: WorkflowBranch) {
  if (branch.isDefault) return '其他情况进入此流程'
  const field = workflowForm.value.fields.find((item) => item.id === branch.fieldId)
  const operator = branch.operator ? operatorNames[branch.operator] : '等于'
  if (branch.operator === 'empty' || branch.operator === 'not_empty') return `${field?.label ?? '表单字段'} ${operator}`
  return `${field?.label ?? '表单字段'} ${operator} ${branch.value || '未设置'}`
}
function assigneeSummary(node: WorkflowNode) {
  const mode = node.assigneeMode ?? 'specified'
  return mode === 'specified' ? (node.assignees?.map(personLabel).join('、') || '请选择成员') : assigneeModeNames[mode]
}
function selectWorkflowNode(node: WorkflowNode) {
  selectedWorkflowNodeId.value = node.id
  selectedWorkflowBranchId.value = null
  nodePicker.value = null
  if (node.type === 'approval') approvalTab.value = 'assignees'
  if (node.type === 'executor') executorTab.value = 'assignees'
}
function selectWorkflowBranch(node: WorkflowNode, branch: WorkflowBranch) {
  selectedWorkflowNodeId.value = node.id
  selectedWorkflowBranchId.value = branch.id
  nodePicker.value = null
}
function upsertWorkflowList(item: WorkflowSchema) {
  const index = workflows.value.findIndex((workflowItem) => workflowItem.id === item.id)
  if (index >= 0) workflows.value.splice(index, 1)
  workflows.value.unshift(clone(item))
}
async function switchWorkflow(item: WorkflowSchema) {
  if (item.id === workflow.value.id) return
  if (isSavingWorkflow.value) {
    setToast('工作流正在保存，请稍后再试')
    return
  }
  if (workflowSavedMessage.value === '有未保存的更改' && !window.confirm('当前工作流有未保存的更改，放弃更改并切换吗？')) return
  workflowListOpen.value = false
  try {
    workflow.value = normalizeWorkflowConfig(await loadWorkflow(item.id))
    workflowSavedMessage.value = workflowMigrationsPending.has(workflow.value.id) ? '有未保存的更改' : '已保存'
  } catch {
    workflow.value = normalizeWorkflowConfig(clone(item))
    workflowSavedMessage.value = workflowMigrationsPending.has(workflow.value.id) ? '有未保存的更改' : '本地草稿'
  }
  scopedStorage.setItem('selected-workflow-id', workflow.value.id)
  selectedWorkflowNodeId.value = workflow.value.nodes.find((node) => node.type === 'approval')?.id ?? workflow.value.nodes[1]?.id ?? null
  selectedWorkflowBranchId.value = null
  upsertWorkflowList(workflow.value)
}
function openRootNodePicker(index: number) { nodePicker.value = { scope: 'root', index } }
function openBranchNodePicker(branchId: string, index: number) { nodePicker.value = { scope: 'branch', branchId, index } }
function isRootPickerOpen(index: number) { return nodePicker.value?.scope === 'root' && nodePicker.value.index === index }
function isBranchPickerOpen(branchId: string, index: number) { return nodePicker.value?.scope === 'branch' && nodePicker.value.branchId === branchId && nodePicker.value.index === index }
function makeWorkflowNode(type: WorkflowNodeType): WorkflowNode {
  const id = `${type}-${Math.random().toString(36).slice(2, 9)}`
  if (type === 'condition') {
    const fieldId = conditionFields.value[0]?.id
    return {
      id, type, name: '条件分支', branches: [
        { id: `${id}-branch-1`, name: '条件一', fieldId, operator: 'eq', value: '', isDefault: false, nodes: [] },
        { id: `${id}-branch-else`, name: '其他情况', isDefault: true, nodes: [] },
      ],
    }
  }
  return {
    id, type, name: type === 'approval' ? '审批人' : '执行人',
    assigneeMode: 'specified', assignees: [],
    fieldPermissions: defaultFieldPermissions(),
    ...(type === 'approval' ? { approvalButtons: defaultApprovalButtons(), approvalMode: 'sequential' as const } : {}),
  }
}
function addWorkflowNode(type: 'approval' | 'executor' | 'condition') {
  if (!nodePicker.value) return
  const node = makeWorkflowNode(type)
  if (nodePicker.value.scope === 'root') {
    workflow.value.nodes.splice(nodePicker.value.index, 0, node)
  } else {
    const branch = findWorkflowBranch(nodePicker.value.branchId)
    if (!branch || type === 'condition') return
    branch.nodes.splice(nodePicker.value.index, 0, node)
  }
  selectWorkflowNode(node)
  workflowChanged()
}
function addConditionBranch(node: WorkflowNode) {
  if (!node.branches) node.branches = []
  const index = node.branches.length + 1
  const branch: WorkflowBranch = {
    id: `${node.id}-branch-${Math.random().toString(36).slice(2, 7)}`,
    name: `条件${index}`, fieldId: conditionFields.value[0]?.id, operator: 'eq', value: '', isDefault: false, nodes: [],
  }
  node.branches.push(branch)
  selectWorkflowBranch(node, branch)
  workflowChanged()
}
function setDefaultBranch(node: WorkflowNode, branch: WorkflowBranch) {
  for (const item of node.branches ?? []) {
    if (item.isDefault && item.id !== branch.id) {
      item.fieldId = conditionFields.value[0]?.id
      item.operator = 'eq'
      item.value = ''
    }
    item.isDefault = item.id === branch.id
  }
  delete branch.fieldId
  delete branch.operator
  delete branch.value
  workflowChanged()
}
function deleteConditionBranch(node: WorkflowNode, branch: WorkflowBranch) {
  if (!node.branches || node.branches.length <= 2) {
    setToast('条件分支至少保留两个出口')
    return
  }
  node.branches = node.branches.filter((item) => item.id !== branch.id)
  if (!node.branches.some((item) => item.isDefault)) node.branches[node.branches.length - 1].isDefault = true
  if (selectedWorkflowBranchId.value === branch.id) selectedWorkflowBranchId.value = null
  workflowChanged()
}
function setNodeAssigneeMode(node: WorkflowNode, mode: 'specified' | 'direct_manager') {
  node.assigneeMode = mode
  if (mode === 'direct_manager') node.assignees = []
  workflowChanged()
}
function setAssigneeAt(node: WorkflowNode, index: number, person: string) {
  if (!node.assignees) node.assignees = []
  if (!people.value.includes(person)) return false
  const duplicateIndex = node.assignees.findIndex((item, itemIndex) => item === person && itemIndex !== index)
  if (duplicateIndex >= 0) return false
  node.assignees[index] = person
  workflowChanged()
  return true
}
function setAssigneeAtFromInput(node: WorkflowNode, index: number, event: Event) {
  const input = event.target as HTMLInputElement
  if (!setAssigneeAt(node, index, input.value)) input.value = node.assignees?.[index] ?? ''
}
function addAssignee(node: WorkflowNode) {
  if (!node.assignees) node.assignees = []
  const next = people.value.find((person) => !node.assignees?.includes(person))
  if (next) node.assignees.push(next)
  workflowChanged()
}
function removeAssignee(node: WorkflowNode, index: number) {
  node.assignees?.splice(index, 1)
  workflowChanged()
}
function fieldPermission(node: WorkflowNode, fieldId: string): FieldPermissionLevel {
  return node.fieldPermissions?.find((item) => item.fieldId === fieldId)?.permission ?? 'editable'
}
function applicantFieldPermission(fieldId: string): FieldPermissionLevel {
  return workflow.value.applicantFieldPermissions?.find((item) => item.fieldId === fieldId)?.permission ?? 'editable'
}
function setApplicantFieldPermission(fieldId: string, permission: FieldPermissionLevel) {
  if (!workflow.value.applicantFieldPermissions) workflow.value.applicantFieldPermissions = []
  const current = workflow.value.applicantFieldPermissions.find((item) => item.fieldId === fieldId)
  if (current) current.permission = permission
  else workflow.value.applicantFieldPermissions.push({ fieldId, permission })
  workflowChanged()
}
function setFieldPermission(node: WorkflowNode, fieldId: string, permission: FieldPermissionLevel) {
  if (!node.fieldPermissions) node.fieldPermissions = []
  const current = node.fieldPermissions.find((item) => item.fieldId === fieldId)
  if (current) current.permission = permission
  else node.fieldPermissions.push({ fieldId, permission })
  workflowChanged()
}
function selectStartForm(node: WorkflowNode, event: Event) {
  node.formId = (event.target as HTMLSelectElement).value
  normalizeWorkflowConfig(workflow.value)
  workflowChanged()
}
function removeWorkflowNode(id: string) {
  if (id === 'start' || id === 'end') return
  const removeFrom = (nodes: WorkflowNode[]): boolean => {
    const index = nodes.findIndex((node) => node.id === id)
    if (index >= 0) { nodes.splice(index, 1); return true }
    for (const node of nodes) for (const branch of node.branches ?? []) if (removeFrom(branch.nodes)) return true
    return false
  }
  removeFrom(workflow.value.nodes)
  selectedWorkflowNodeId.value = null
  selectedWorkflowBranchId.value = null
  workflowChanged()
}
function startWorkflowNodeDrag(event: DragEvent, node: WorkflowNode, scope: 'root' | 'branch', branchId?: string) {
  if (!event.dataTransfer) return
  workflowNodeDrag.value = scope === 'root' ? { kind: 'move', nodeId: node.id, scope } : { kind: 'move', nodeId: node.id, scope, branchId: branchId! }
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', node.id)
}
function startNewWorkflowNodeDrag(event: DragEvent, nodeType: 'approval' | 'executor' | 'condition') {
  if (!event.dataTransfer) return
  workflowNodeDrag.value = { kind: 'create', nodeType }
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('text/plain', `new:${nodeType}`)
}
function finishWorkflowNodeDrag() {
  workflowNodeDrag.value = null
  workflowDropTarget.value = ''
}
function workflowDropKey(scope: 'root' | 'branch', targetIndex: number, branchId?: string) {
  return `${scope}:${branchId ?? ''}:${targetIndex}`
}
function hoverWorkflowDropTarget(event: DragEvent, scope: 'root' | 'branch', targetIndex: number, branchId?: string) {
  const source = workflowNodeDrag.value
  if (!source || (source.kind === 'move' && (source.scope !== scope || (scope === 'branch' && source.branchId !== branchId))) || (source.kind === 'create' && scope === 'branch' && source.nodeType === 'condition')) return
  event.preventDefault()
  event.stopPropagation()
  workflowDropTarget.value = workflowDropKey(scope, targetIndex, branchId)
}
function hoverWorkflowNodeTarget(event: DragEvent, targetNode: WorkflowNode, scope: 'root' | 'branch', targetIndex: number, branchId?: string) {
  const source = workflowNodeDrag.value
  if (!source || (source.kind === 'move' && (source.scope !== scope || (scope === 'branch' && source.branchId !== branchId) || source.nodeId === targetNode.id)) || (source.kind === 'create' && scope === 'branch' && source.nodeType === 'condition')) return
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const insertAfter = event.clientY > rect.top + rect.height / 2
  hoverWorkflowDropTarget(event, scope, targetIndex + (insertAfter ? 1 : 0), branchId)
}
function moveWorkflowNode(event: DragEvent, scope: 'root' | 'branch', targetIndex: number, branchId?: string) {
  event.preventDefault()
  event.stopPropagation()
  const source = workflowNodeDrag.value
  if (!source || (source.kind === 'move' && (source.scope !== scope || (scope === 'branch' && source.branchId !== branchId))) || (source.kind === 'create' && scope === 'branch' && source.nodeType === 'condition')) return
  const nodes = scope === 'root' ? workflow.value.nodes : findWorkflowBranch(branchId!)?.nodes
  if (!nodes) return
  let insertIndex = targetIndex
  let node: WorkflowNode
  if (source.kind === 'create') {
    node = makeWorkflowNode(source.nodeType)
    if (scope === 'root') insertIndex = Math.max(1, Math.min(insertIndex, nodes.length - 1))
    else insertIndex = Math.max(0, Math.min(insertIndex, nodes.length))
  } else {
    const sourceIndex = nodes.findIndex((item) => item.id === source.nodeId)
    node = nodes[sourceIndex]
    if (sourceIndex < 0 || !node) return
    nodes.splice(sourceIndex, 1)
    if (sourceIndex < insertIndex) insertIndex -= 1
    if (scope === 'root') insertIndex = Math.max(1, Math.min(insertIndex, nodes.length - 1))
    else insertIndex = Math.max(0, Math.min(insertIndex, nodes.length))
  }
  nodes.splice(insertIndex, 0, node)
  selectedWorkflowNodeId.value = node.id
  selectedWorkflowBranchId.value = null
  nodePicker.value = null
  workflowNodeDrag.value = null
  workflowDropTarget.value = ''
  workflowChanged()
}
function dropWorkflowNode(event: DragEvent, targetNode: WorkflowNode, scope: 'root' | 'branch', targetIndex: number, branchId?: string) {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const insertAfter = event.clientY > rect.top + rect.height / 2
  if (workflowNodeDrag.value?.kind === 'move' && targetNode.id === workflowNodeDrag.value.nodeId) {
    event.preventDefault()
    event.stopPropagation()
    return
  }
  moveWorkflowNode(event, scope, targetIndex + (insertAfter ? 1 : 0), branchId)
}
function workflowChanged() {
  workflowRevision += 1
  workflowSavedMessage.value = '有未保存的更改'
}
async function saveWorkflowNow(showSuccess = true): Promise<boolean> {
  if (isSavingWorkflow.value) return false
  isSavingWorkflow.value = true
  const revision = workflowRevision
  const snapshot = clone(workflow.value)
  try {
    const saved = await saveWorkflowApi(snapshot)
    const persisted = { ...snapshot, ...saved }
    if (revision === workflowRevision) Object.assign(workflow.value, saved)
    upsertWorkflowList(persisted)
    scopedStorage.setItem('selected-workflow-id', workflow.value.id)
    scopedStorage.removeItem(`workflow-draft-${workflow.value.id}`)
    if (revision === workflowRevision) workflowMigrationsPending.delete(workflow.value.id)
    workflowSavedMessage.value = revision === workflowRevision ? '已保存' : '有未保存的更改'
    if (showSuccess) setToast(revision === workflowRevision ? '工作流已保存' : '已保存当前版本，仍有未保存的更改')
    return true
  } catch (error) {
    workflowSavedMessage.value = '有未保存的更改'
    scopedStorage.setItem(`workflow-draft-${snapshot.id}`, JSON.stringify(snapshot))
    if (showSuccess) setToast(error instanceof Error ? `${error.message}，已保留本地草稿` : '工作流保存失败，已保留本地草稿')
    return false
  } finally {
    isSavingWorkflow.value = false
  }
}
async function publishWorkflowNow() {
  if (isPublishingWorkflow.value || isSavingWorkflow.value) return
  if (workflowSavedMessage.value !== '已保存') {
    setToast('请先保存流程，再发布')
    return
  }
  isPublishingWorkflow.value = true
  try {
    const published = normalizeWorkflowConfig(await publishWorkflowApi(workflow.value.id))
    workflow.value = published
    upsertWorkflowList(published)
    setToast(`流程已发布 · 第 ${published.publishedVersion ?? 1} 版${published.disabledAt ? '，当前仍为停用状态，请在工作台启用' : ''}`)
  } catch (error) {
    setToast(error instanceof Error ? error.message : '流程发布失败')
  } finally {
    isPublishingWorkflow.value = false
  }
}
function openWorkflowCreate() {
  if (!currentUser.value?.canManagePermissions || isCreatingWorkflow.value) return
  workflowListOpen.value = false
  newWorkflowName.value = ''
  newWorkflowCategory.value = ''
  workflowCreateError.value = ''
  workflowCreateDiscardOpen.value = false
  workflowCreateOpen.value = true
}
function closeWorkflowCreate() {
  if (isCreatingWorkflow.value) return
  if (newWorkflowName.value || newWorkflowCategory.value !== '') {
    workflowCreateDiscardOpen.value = true
    return
  }
  workflowCreateOpen.value = false
}
async function createNewWorkflow() {
  if (!currentUser.value?.canManagePermissions || isCreatingWorkflow.value) return
  workflowCreateError.value = ''
  const name = newWorkflowName.value.trim()
  const category = newWorkflowCategory.value.trim()
  if (!name) { workflowCreateError.value = '请填写工作流名称'; return }
  if (!category) { workflowCreateError.value = '请选择审批分类'; return }
  if (category.length > 40) { workflowCreateError.value = '审批分类最多40个字'; return }
  if (isSavingWorkflow.value) {
    workflowCreateError.value = '工作流正在保存，请稍后再试'
    return
  }
  if (workflowSavedMessage.value === '有未保存的更改' && !window.confirm('当前工作流有未保存的更改，放弃更改并创建新工作流吗？')) return
  const created = normalizeWorkflowConfig({ ...fallbackWorkflow('flow-' + Date.now().toString(36), name), category })
  isCreatingWorkflow.value = true
  try {
    let createdInDatabase = false
    try {
      workflow.value = await createWorkflowApi(created)
      createdInDatabase = true
      workflowSavedMessage.value = '已保存'
    } catch {
      workflow.value = created
      workflowSavedMessage.value = '本地草稿'
      scopedStorage.setItem('workflow-draft-' + created.id, JSON.stringify(created))
    }
    if (createdInDatabase) {
      scopedStorage.setItem('selected-workflow-id', workflow.value.id)
      scopedStorage.removeItem('workflow-draft-' + workflow.value.id)
    }
    upsertWorkflowList(workflow.value)
    selectedWorkflowNodeId.value = 'manager-approval'
    selectedWorkflowBranchId.value = null
    newWorkflowName.value = ''
    newWorkflowCategory.value = ''
    workflowCreateOpen.value = false
    setToast(workflowSavedMessage.value === '已保存' ? '工作流已创建' : '工作流已创建为本地草稿')
  } finally {
    isCreatingWorkflow.value = false
  }
}
function insertField(type: FieldType, index = form.value.fields.length) {
  const field = makeField(type)
  form.value.fields.splice(index, 0, field)
  selectedId.value = field.id
  changed()
}
function addFromPalette(event: DragEvent, type: FieldType) {
  event.dataTransfer?.setData('application/x-form-field', type)
  event.dataTransfer?.setData('text/plain', `component:${type}`)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'copy'
}
function startFieldDrag(event: DragEvent, field: FormField) {
  event.dataTransfer?.setData('application/x-existing-field', field.id)
  event.dataTransfer?.setData('text/plain', `field:${field.id}`)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}
function dropOnCanvas(event: DragEvent, index = form.value.fields.length) {
  event.preventDefault()
  dragActive.value = false
  const transferText = event.dataTransfer?.getData('text/plain') || ''
  const type = (event.dataTransfer?.getData('application/x-form-field') || transferText.replace(/^component:/, '')) as FieldType
  if (type && baseNames[type]) { insertField(type, index); return }
  const movingId = event.dataTransfer?.getData('application/x-existing-field') || transferText.replace(/^field:/, '')
  if (!movingId) return
  const from = form.value.fields.findIndex((field) => field.id === movingId)
  if (from < 0) return
  const [field] = form.value.fields.splice(from, 1)
  const target = from < index ? index - 1 : index
  form.value.fields.splice(Math.max(0, target), 0, field)
  selectedId.value = movingId
  changed()
}
function leaveCanvas(event: DragEvent) {
  const nextTarget = event.relatedTarget
  const currentTarget = event.currentTarget
  if (!(currentTarget instanceof Element) || !(nextTarget instanceof Node) || !currentTarget.contains(nextTarget)) dragActive.value = false
}
function onFieldChange() { changed() }
function removeField(id: string) {
  const index = form.value.fields.findIndex((field) => field.id === id)
  form.value.fields = form.value.fields.filter((field) => field.id !== id)
  selectedId.value = form.value.fields[Math.min(index, form.value.fields.length - 1)]?.id ?? null
  changed()
}
function duplicateField(field: FormField) {
  const copy = { ...clone(field), id: makeId(), label: `${field.label}（副本）` }
  const index = form.value.fields.findIndex((item) => item.id === field.id)
  form.value.fields.splice(index + 1, 0, copy)
  selectedId.value = copy.id
  changed()
}
function moveField(field: FormField, direction: -1 | 1) {
  const index = form.value.fields.findIndex((item) => item.id === field.id)
  const target = index + direction
  if (target < 0 || target >= form.value.fields.length) return
  ;[form.value.fields[index], form.value.fields[target]] = [form.value.fields[target], form.value.fields[index]]
  changed()
}
function undo() {
  if (!historyPast.value.length) return
  historyFuture.value.push(JSON.stringify(form.value))
  const previous = historyPast.value.pop()!
  suppressHistory.value = true
  form.value = JSON.parse(previous) as FormSchema
  lastSnapshot.value = previous
  selectedId.value = form.value.fields[0]?.id ?? null
  changed()
  requestAnimationFrame(() => { suppressHistory.value = false })
}
function redo() {
  if (!historyFuture.value.length) return
  historyPast.value.push(JSON.stringify(form.value))
  const next = historyFuture.value.pop()!
  suppressHistory.value = true
  form.value = JSON.parse(next) as FormSchema
  lastSnapshot.value = next
  selectedId.value = form.value.fields[0]?.id ?? null
  changed()
  requestAnimationFrame(() => { suppressHistory.value = false })
}
watch(form, () => {
  if (suppressHistory.value) return
  const current = JSON.stringify(form.value)
  if (lastSnapshot.value && lastSnapshot.value !== current) {
    historyPast.value.push(lastSnapshot.value)
    if (historyPast.value.length > 40) historyPast.value.shift()
    historyFuture.value = []
  }
  lastSnapshot.value = current
}, { deep: true })
async function saveNow(showSuccess = true) {
  if (isSaving.value) return
  isSaving.value = true
  const revision = formRevision
  const snapshot = clone(form.value)
  try {
    const saved = await saveForm(snapshot)
    const persisted = { ...snapshot, updatedAt: saved.updatedAt }
    scopedStorage.removeItem(`form-draft-${snapshot.id}`)
    forms.value = [persisted, ...forms.value.filter((item) => item.id !== snapshot.id)]
    form.value.updatedAt = saved.updatedAt
    saveMessage.value = revision === formRevision ? '已保存' : '有未保存的更改'
    if (showSuccess) setToast(revision === formRevision ? '表单已保存' : '已保存当前版本，仍有未保存的更改')
  } catch (error) {
    saveMessage.value = revision === formRevision ? '本地草稿' : '有未保存的更改'
    try {
      scopedStorage.setItem(`form-draft-${snapshot.id}`, JSON.stringify(snapshot))
    } catch {
      // Keep the save error visible even when local storage is unavailable.
    }
    if (showSuccess) setToast(error instanceof Error ? '已保存到本地草稿' : '保存失败')
  } finally {
    isSaving.value = false
  }
}
function confirmLeaveForm(): boolean {
  if (isSaving.value) {
    setToast('表单正在保存，请稍后再试')
    return false
  }
  return saveMessage.value !== '有未保存的更改' || window.confirm('当前表单有未保存的更改，放弃更改并继续吗？')
}
async function switchForm(item: FormSchema) {
  if (item.id === form.value.id || !confirmLeaveForm()) return
  formListOpen.value = false
  try {
    form.value = normalizeFormSchema(await loadForm(item.id))
    saveMessage.value = '已保存'
  } catch {
    form.value = normalizeFormSchema(clone(item))
    saveMessage.value = '本地草稿'
  }
  scopedStorage.setItem('active-form-id', form.value.id)
  selectedId.value = form.value.fields[0]?.id ?? null
  activeTopTab.value = '表单设计'
  historyPast.value = []
  historyFuture.value = []
  lastSnapshot.value = JSON.stringify(form.value)
}
async function createNewForm() {
  if (!currentUser.value?.canManagePermissions) return
  const name = newFormName.value.trim()
  if (!name) {
    setToast('请填写表单名称')
    return
  }
  if (!confirmLeaveForm()) return
  isCreatingForm.value = true
  const id = `form-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  try {
    const created = normalizeFormSchema(await saveForm(emptyForm(id, name)))
    forms.value = [clone(created), ...forms.value]
    form.value = created
    scopedStorage.setItem('active-form-id', created.id)
    scopedStorage.removeItem(`form-draft-${created.id}`)
    selectedId.value = null
    activeTopTab.value = '表单设计'
    historyPast.value = []
    historyFuture.value = []
    lastSnapshot.value = JSON.stringify(form.value)
    saveMessage.value = '已保存'
    formCreateOpen.value = false
    formListOpen.value = false
    newFormName.value = ''
    setToast('表单已创建')
  } catch {
    setToast('创建表单失败，请检查 Python 服务连接')
  } finally {
    isCreatingForm.value = false
  }
}
function addOption() {
  if (selectedField.value) selectedField.value.options.push(`选项${selectedField.value.options.length + 1}`)
  changed()
}
function removeOption(index: number) {
  selectedField.value?.options.splice(index, 1)
  changed()
}
function fieldDefaultValue(field: FormField): string | null {
  const value = field.defaultValue
  return value === undefined || value === null || value === '' ? null : String(value)
}
function fieldInitialValue(field: FormField): string | null {
  const value = fieldDefaultValue(field)
  return field.type === 'number' && value !== null && !Number.isFinite(Number(value)) ? null : value
}
function openPreview() {
  previewAnswers.value = Object.fromEntries(form.value.fields.map((field) => {
    const initialValue = fieldInitialValue(field)
    if (field.type === 'checkbox' || field.type === 'multiSelect') {
      return [field.id, initialValue ? initialValue.split(',').map((value) => value.trim()).filter(Boolean) : []]
    }
    return [field.id, initialValue ?? '']
  }))
  const matches = publishedWorkflowsForForm.value
  previewWorkflowId.value = matches.find((item) => item.id === workflow.value.id)?.id ?? matches[0]?.id ?? ''
  previewOpen.value = true
}
function answerHasValue(value: string | string[] | undefined): boolean {
  return Array.isArray(value) ? value.length > 0 : !!value?.trim()
}
async function submitPreview() {
  if (isSubmittingWorkflow.value) return
  const missing = form.value.fields.filter((field) => field.required && field.type !== 'description' && !answerHasValue(previewAnswers.value[field.id]))
  if (missing.length) {
    setToast(`请填写：${missing.map((field) => field.label).join('、')}`)
    return
  }
  const selectedWorkflow = publishedWorkflowsForForm.value.find((item) => item.id === previewWorkflowId.value)
  if (!selectedWorkflow) {
    setToast('该表单尚无已发布的工作流')
    return
  }
  isSubmittingWorkflow.value = true
  try {
    workflowRunResult.value = await startWorkflowRunApi(selectedWorkflow.id, {
      values: clone(previewAnswers.value),
    })
    previewOpen.value = false
  } catch (error) {
    setToast(error instanceof Error ? error.message : '流程发起失败')
  } finally {
    isSubmittingWorkflow.value = false
  }
}
function workflowTaskAssigneeText(task: WorkflowRunTask): string {
  if (task.assignees.length) return task.assignees.join('、')
  const mode = assigneeModeNames[task.assigneeMode]
  return task.assigneeMode === 'direct_manager' || task.assigneeMode === 'department_manager'
    ? `${mode}（待组织关系解析）`
    : task.assigneeMode === 'form_field' ? '表单成员字段未填写' : '尚未指定处理人'
}
function workflowTaskStatusText(status: WorkflowRunTask['status']): string {
  return status === 'pending' ? '当前待处理' : status === 'waiting' ? '等待前序节点' : '待分配处理人'
}
function previewValue(field: FormField) {
  if (field.type === 'description') {
    const quantity = Number(previewAnswers.value.quantity || '0')
    const price = Number(previewAnswers.value['unit-price'] || '0')
    return quantity && price ? `${(quantity * price).toFixed(2)} 元` : field.defaultValue || '--'
  }
  return field.defaultValue || ''
}
function exportJson() {
  const blob = new Blob([JSON.stringify(form.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${form.value.name || 'form'}.json`
  link.click()
  URL.revokeObjectURL(url)
  setToast('表单 JSON 已导出')
}
function formatType(type: FieldType) { return baseNames[type] }

async function loadAdminWorkspace() {
  const activeFormId = scopedStorage.getItem('active-form-id') ?? 'sample'
  const draftKey = `form-draft-${activeFormId}`
  let draft: FormSchema | null = null
  const storedDraft = scopedStorage.getItem(draftKey)
  if (storedDraft) {
    try {
      draft = normalizeFormSchema(JSON.parse(storedDraft) as FormSchema)
    } catch {
      scopedStorage.removeItem(draftKey)
    }
  }
  try {
    const savedForm = normalizeFormSchema(await loadForm(activeFormId))
    if (draft && formContentSignature(draft) !== formContentSignature(savedForm)) {
      form.value = draft
      saveMessage.value = '有未保存的更改'
    } else {
      form.value = savedForm
      scopedStorage.removeItem(draftKey)
      saveMessage.value = '已保存'
    }
  } catch {
    form.value = draft ?? normalizeFormSchema(activeFormId === 'sample' ? fallbackForm() : emptyForm(activeFormId, '新建表单'))
    saveMessage.value = draft ? '本地草稿' : '数据库连接失败'
  }
  scopedStorage.setItem('active-form-id', form.value.id)
  selectedId.value = form.value.fields[0]?.id ?? null
  lastSnapshot.value = JSON.stringify(form.value)
  try {
    const savedForms = await listForms()
    forms.value = [clone(form.value), ...savedForms.filter((item) => item.id !== form.value.id)]
  } catch {
    forms.value = [clone(form.value)]
  }

  const selectedWorkflowId = scopedStorage.getItem('selected-workflow-id') ?? 'sample'
  const workflowDraft = scopedStorage.getItem(`workflow-draft-${selectedWorkflowId}`)
  try {
    workflows.value = (await listWorkflows()).filter(item => !item.deletedAt).map((item) => normalizeWorkflowConfig(item))
    const selectedWorkflow = workflows.value.find((item) => item.id === selectedWorkflowId)
      ?? workflows.value.find((item) => item.id === 'sample')
      ?? workflows.value[0]
    if (!selectedWorkflow) {
      workflow.value = normalizeWorkflowConfig(fallbackWorkflow('flow-' + Date.now().toString(36), '新建审批流程'))
      workflowSavedMessage.value = '尚未创建流程'
      return
    }
    workflow.value = normalizeWorkflowConfig(clone(selectedWorkflow))
    scopedStorage.setItem('selected-workflow-id', workflow.value.id)
    workflowSavedMessage.value = workflowMigrationsPending.has(workflow.value.id) ? '有未保存的更改' : '已保存'
  } catch {
    workflow.value = normalizeWorkflowConfig(workflowDraft
      ? JSON.parse(workflowDraft) as WorkflowSchema
      : fallbackWorkflow('sample', `${form.value.name}审批流程`))
    workflowSavedMessage.value = workflowMigrationsPending.has(workflow.value.id) ? '有未保存的更改' : workflowDraft ? '本地草稿' : '数据库连接失败'
    workflows.value = [clone(workflow.value)]
  }
  if (!findWorkflowNode(selectedWorkflowNodeId.value ?? '')) {
    selectedWorkflowNodeId.value = workflow.value.nodes.find((node) => node.type === 'approval')?.id ?? null
  }
}
async function signOut() {
  if (activeTopTab.value === '工作台' && employeePortal.value?.confirmLeaveWorkspace() === false) return
  if (workspaceReturnConfirmOpen.value || workspaceReturning.value) return
  if (currentUser.value?.role === 'admin' && (isSaving.value || isSavingWorkflow.value)) {
    setToast('正在保存，请稍后退出')
    return
  }
  if (currentUser.value?.role === 'admin'
    && (saveMessage.value === '有未保存的更改' || workflowSavedMessage.value === '有未保存的更改')
    && !window.confirm('表单或流程有未保存的更改，确定退出并放弃吗？')) return
  try { await logoutApi(); window.location.assign(loginUrl()) } catch { setToast('退出失败，请重试') }
}
function confirmBeforeUnload(event: BeforeUnloadEvent) {
  if (currentUser.value?.role !== 'admin'
    || (saveMessage.value !== '有未保存的更改' && workflowSavedMessage.value !== '有未保存的更改')) return
  event.preventDefault()
  event.returnValue = ''
}
const workspaceDataView = ref<'applications' | 'records'>('applications')
let workspaceConfigurationRequest = 0
function resetHome() { ++workspaceConfigurationRequest; void nextTick(() => employeePortal.value?.resetHome()) }
const workspaceReturnConfirmOpen = ref(false)
const workspaceReturning = ref(false)
const workspaceReturnError = ref('')
const workspaceReturnContinue = ref<HTMLButtonElement | null>(null)
function closeWorkspaceReturn() { if (!workspaceReturning.value) workspaceReturnConfirmOpen.value = false }
async function returnToWorkspace() {
  if (workspaceReturning.value || activeTopTab.value === '工作台') return
  if (isSaving.value || isSavingWorkflow.value || isPublishingWorkflow.value) {
    setToast('正在保存或发布，请稍后返回')
    return
  }
  if (saveMessage.value === '有未保存的更改' || workflowSavedMessage.value === '有未保存的更改') {
    workspaceReturnError.value = ''
    workspaceReturnConfirmOpen.value = true
    await nextTick()
    workspaceReturnContinue.value?.focus()
    return
  }
  await finishWorkspaceReturn()
}
async function finishWorkspaceReturn(discard = false) {
  if (workspaceReturning.value || isSaving.value || isSavingWorkflow.value || isPublishingWorkflow.value) return
  workspaceReturning.value = true
  workspaceReturnError.value = ''
  try {
    if (discard) {
      // Read both saved versions before replacing either dirty design.
      const [savedForm, savedWorkflow] = await Promise.all([
        saveMessage.value === '有未保存的更改' ? loadForm(form.value.id) : Promise.resolve(null),
        workflowSavedMessage.value === '有未保存的更改' ? loadWorkflow(workflow.value.id) : Promise.resolve(null),
      ])
      if (savedForm) {
        form.value = normalizeFormSchema(savedForm)
        scopedStorage.removeItem(`form-draft-${form.value.id}`)
        selectedId.value = form.value.fields[0]?.id ?? null
        historyPast.value = []; historyFuture.value = []
        lastSnapshot.value = JSON.stringify(form.value)
        saveMessage.value = '已保存'
      }
      if (savedWorkflow) {
        workflow.value = normalizeWorkflowConfig(savedWorkflow)
        scopedStorage.removeItem(`workflow-draft-${workflow.value.id}`)
        workflowSavedMessage.value = workflowMigrationsPending.has(workflow.value.id) ? '有未保存的更改' : '已保存'
        upsertWorkflowList(workflow.value)
      }
    }
    ++workspaceConfigurationRequest
    workspaceReturnConfirmOpen.value = false
    activeTopTab.value = '工作台'
    await nextTick()
    workspaceReturning.value = false
    await employeePortal.value?.refreshWorkspace()
  } catch (cause) {
    workspaceReturnError.value = cause instanceof Error ? cause.message : '无法读取已保存版本，请重试'
  } finally { workspaceReturning.value = false }
}
function onWorkspaceWorkflowChanged(updated: WorkflowSchema) {
  if (updated.deletedAt) {
    workflows.value = workflows.value.filter(item => item.id !== updated.id)
    scopedStorage.removeItem(`workflow-draft-${updated.id}`)
    if (workflow.value.id === updated.id) {
      workflow.value = normalizeWorkflowConfig(clone(workflows.value[0] ?? fallbackWorkflow('flow-' + Date.now().toString(36), '新建审批流程')))
      workflowSavedMessage.value = workflows.value.length ? '已保存' : '尚未创建流程'
      scopedStorage.setItem('selected-workflow-id', workflow.value.id)
    }
  } else {
    upsertWorkflowList(updated)
    if (workflow.value.id === updated.id) workflow.value = normalizeWorkflowConfig(clone(updated))
  }
}
async function configureWorkspace(target: ApprovalWorkspaceTarget) {
  if (currentUser.value?.role !== 'admin' || !currentUser.value.canManagePermissions) return
  const request = ++workspaceConfigurationRequest
  try {
    // Fetch both targets before switching so a failed load never opens the wrong design.
    const [targetForm, targetWorkflow] = await Promise.all([
      target.formId ? loadForm(target.formId) : Promise.resolve(null),
      target.workflowId ? loadWorkflow(target.workflowId) : Promise.resolve(null),
    ])
    if (request !== workspaceConfigurationRequest || !navigatePlatformPage(target.page)) return
    workspaceDataView.value = target.page === '数据管理' && target.formId ? 'records' : 'applications'
    if (targetForm) {
      form.value = normalizeFormSchema(targetForm)
      saveMessage.value = '已保存'
      scopedStorage.setItem('active-form-id', form.value.id)
      selectedId.value = form.value.fields[0]?.id ?? null
      historyPast.value = []; historyFuture.value = []
      lastSnapshot.value = JSON.stringify(form.value)
    }
    if (targetWorkflow) {
      workflow.value = normalizeWorkflowConfig(targetWorkflow)
      workflowSavedMessage.value = workflowMigrationsPending.has(workflow.value.id) ? '有未保存的更改' : '已保存'
      scopedStorage.setItem('selected-workflow-id', workflow.value.id)
      selectedWorkflowNodeId.value = workflow.value.nodes.find(node => node.type === 'approval')?.id ?? null
      selectedWorkflowBranchId.value = null
      upsertWorkflowList(workflow.value)
    }
    if (target.create === 'workflow') openWorkflowCreate()
    if (target.create === 'form') { newFormName.value = ''; formCreateOpen.value = true }
  } catch (cause) { if (request === workspaceConfigurationRequest) employeePortal.value?.showWorkspaceError(cause instanceof Error ? cause.message : '配置页面读取失败，请重试') }
}
function navigatePlatformPage(page: string) {
  if (activeTopTab.value === '工作台' && page !== '工作台' && employeePortal.value?.confirmLeaveWorkspace() === false) return false
  if (page === 'permissions') return false
  if (workspaceReturnConfirmOpen.value || workspaceReturning.value) return false
  if ((isSaving.value || isSavingWorkflow.value) || ((saveMessage.value === '有未保存的更改' || workflowSavedMessage.value === '有未保存的更改') && !window.confirm('当前修改尚未保存，确定离开吗？'))) return false
  activeTopTab.value = page
  return true
}
function navigatePlatform(event: Event) { return navigatePlatformPage((event as CustomEvent<string>).detail) }
defineExpose({ navigatePlatformPage, signOut, resetHome, returnToWorkspace })
watch(activeTopTab, value => emit('page-change', value))
onMounted(async () => {
  window.addEventListener('beforeunload', confirmBeforeUnload)
  window.addEventListener('platform-form-designer-navigate', navigatePlatform)
  try {
    await initializeSession()
    currentUser.value = await currentUserApi()
    setStorageUser(currentUser.value.username)
    emit('user-change', currentUser.value)
    directoryUsers.value = await listUserDirectory()
    people.value = directoryUsers.value.map(user => user.username)
    if (currentUser.value.role === 'admin') await loadAdminWorkspace()
  } catch (error) {
    loginError.value = error instanceof Error ? error.message : '统一登录校验失败'
  }
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', confirmBeforeUnload)
  window.removeEventListener('platform-form-designer-navigate', navigatePlatform)
  disposeSession()
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<template>
  <main v-if="!currentUser" class="auth-screen">
    <section class="auth-panel"><h1>表单设计</h1><p role="status">{{ loginError || '正在验证统一登录…' }}</p><a v-if="loginError" :href="loginUrl()">前往统一身份中心</a></section>
  </main>
  <KeepAlive>
    <EmployeePortal v-if="currentUser && (currentUser.role !== 'admin' || activeTopTab === '工作台')" ref="employeePortal" :user="currentUser" :management-items="managementItems" @logout="signOut" @navigate="page => emit('management-page', page)" @configure="configureWorkspace" @workflow-changed="onWorkspaceWorkflowChanged" @view-change="value => emit('portal-view-change', value)" />
  </KeepAlive>
  <div v-if="currentUser?.role === 'admin' && activeTopTab !== '工作台'" class="app-shell">
    <header class="topbar">
      <button class="icon-button app-grid" aria-label="应用菜单"><Grip :size="19" /></button>
      <div class="brand-mark"><ClipboardList :size="18" /></div>
      <button class="workspace-name">流程工作台 <ChevronDown :size="14" /></button>
      <ChevronRight class="crumb-chevron" :size="15" />
      <div v-if="activeTopTab === '流程设计'" class="workflow-menu-anchor">
        <button class="form-breadcrumb" :aria-expanded="workflowListOpen" @click="workflowListOpen = !workflowListOpen">{{ workflow.name }} <ChevronDown :size="14" /></button>
        <div v-if="workflowListOpen" class="workflow-list-menu"><span>工作流</span><button v-for="item in workflows" :key="item.id" :class="{ selected: item.id === workflow.id }" @click="switchWorkflow(item)">{{ item.name }}<Check v-if="item.id === workflow.id" :size="13" /></button><button v-if="currentUser.canManagePermissions" class="workflow-list-create" @click="openWorkflowCreate"><Plus :size="14" /> 新建工作流</button></div>
      </div>
      <div v-else class="workflow-menu-anchor form-menu-anchor">
        <button class="form-breadcrumb" :aria-expanded="formListOpen" @click="formListOpen = !formListOpen">{{ form.name }} <ChevronDown :size="14" /></button>
        <div v-if="formListOpen" class="workflow-list-menu">
          <span>表单</span>
          <button v-for="item in forms" :key="item.id" :class="{ selected: item.id === form.id }" @click="switchForm(item)">{{ item.name }}<Check v-if="item.id === form.id" :size="13" /></button>
          <button v-if="currentUser.canManagePermissions" class="workflow-list-create" @click="formListOpen = false; newFormName = ''; formCreateOpen = true"><Plus :size="14" /> 新建表单</button>
        </div>
      </div>
      <div class="top-nav">
        <button v-for="(item, index) in ['工作台', '表单设计', '流程设计', '数据管理']" :key="item" :class="['top-nav-item', { active: activeTopTab === item }]" @click="activeTopTab = item">
          <ClipboardList v-if="index === 0" :size="15" /><FileText v-else-if="index === 1" :size="15" /><Users v-else-if="index === 2" :size="15" /><Database v-else :size="15" />
          <span>{{ item }}</span>
        </button>
      </div>
      <div class="top-actions">
        <span class="signed-in-user">{{ currentUser.displayName }} · {{ currentUser.department }} · 管理员</span>
        <button class="icon-button auth-logout" aria-label="退出登录" title="退出登录" @click="signOut"><LogOut :size="16" /></button>
        <button class="icon-button help-button" aria-label="帮助"><CircleHelp :size="17" /></button>
      </div>
    </header>

    <div :class="['designer-layout', { 'form-design-mode': activeTopTab === '表单设计', 'workflow-mode': activeTopTab === '流程设计', 'data-management-mode': activeTopTab === '数据管理' }]">
      <nav class="rail" aria-label="设计器工具">
        <button :class="['rail-button', { active: panelTab === 'components' }]" aria-label="组件" title="组件" @click="panelTab = 'components'"><LayoutGrid :size="20" /></button>
        <button :class="['rail-button', { active: panelTab === 'data' }]" aria-label="数据" title="数据" @click="panelTab = 'data'"><Database :size="19" /></button>
        <button :class="['rail-button', { active: panelTab === 'logic' }]" aria-label="逻辑" title="逻辑" @click="panelTab = 'logic'"><Code2 :size="19" /></button>
        <div class="rail-spacer"></div>
      </nav>

      <aside class="component-panel">
        <div class="panel-heading">
          <div>
            <h1>{{ panelTab === 'components' ? '组件' : panelTab === 'data' ? '数据源' : '表单逻辑' }}</h1>
            <p>{{ panelTab === 'components' ? `${componentCount} 个组件可用` : panelTab === 'data' ? '连接表单数据' : '配置字段规则' }}</p>
          </div>
          <button class="icon-button small-icon" aria-label="固定组件面板"><Pin :size="15" /></button>
          <button class="icon-button small-icon" aria-label="收起组件面板"><X :size="16" /></button>
        </div>
        <template v-if="panelTab === 'components'">
          <div class="panel-switch"><button class="selected">基础组件 <span class="help-dot">?</span></button><button @click="setToast('自定义组件即将支持')">自定义组件 <span class="help-dot">?</span></button></div>
          <label class="search-field"><Search :size="15" /><input v-model="panelSearch" placeholder="搜索组件" /><kbd>/</kbd></label>
          <div class="component-list">
            <section v-for="group in visibleGroups" :key="group.title" class="component-group">
              <h2>{{ group.title }} <span>{{ group.items.length }}</span></h2>
              <div class="component-grid">
                <button v-for="item in group.items" :key="item.type" class="component-chip" draggable="true" @dragstart="addFromPalette($event, item.type)" @click="insertField(item.type)">
                  <component :is="item.icon" :size="15" /> <span>{{ item.label }}</span><Plus class="chip-add" :size="12" />
                </button>
              </div>
            </section>
            <div v-if="!visibleGroups.length" class="empty-search">没有找到匹配组件</div>
          </div>
          <div class="panel-footer"><Sparkles :size="14" /><span>拖拽组件到画布，或点击添加</span></div>
        </template>
        <div v-else-if="panelTab === 'data'" class="side-empty"><Database :size="25" /><strong>暂无数据源</strong><span>连接数据源后，可将字段关联到业务数据。</span><button class="outline-button" @click="setToast('数据源配置将在后续版本开放')"><Plus :size="14" /> 添加数据源</button></div>
        <div v-else class="side-empty"><Code2 :size="25" /><strong>表单逻辑</strong><span>设置字段显隐条件与联动规则。</span><button class="outline-button" @click="setToast('规则编辑器将在后续版本开放')"><Plus :size="14" /> 新建规则</button></div>
      </aside>

      <main class="editor-area">
        <template v-if="activeTopTab === '页面设置'">
          <div class="page-settings-toolbar"><div><span>页面设置</span><strong>{{ pageSettingsTab === 'base' ? '基础设置' : '权限设置' }}</strong></div><div class="page-settings-actions"><span class="save-state"><span class="status-dot"></span>{{ isSaving ? '保存中' : saveMessage }}</span><button class="save-button" :disabled="isSaving" @click="saveNow()"><Save :size="15" /> 保存设置</button></div></div>
          <div class="page-settings-viewport">
            <section v-if="pageSettingsTab === 'base'" class="page-settings-content">
              <header class="settings-section-heading"><h2>常用设置</h2><p>配置表单页面的标题、提交行为和完成后的跳转方式。</p></header>
              <div class="page-setting-block">
                <div class="page-setting-label"><strong>数据标题</strong><span>设置提交记录的标题显示方式</span></div>
                <div class="page-setting-control">
                  <label class="radio-option"><input v-model="form.pageSettings.titleMode" type="radio" value="default" @change="changed" />默认标题</label>
                  <label class="radio-option"><input v-model="form.pageSettings.titleMode" type="radio" value="custom" @change="changed" />自定义</label>
                  <input v-if="form.pageSettings.titleMode === 'custom'" v-model="form.pageSettings.customTitle" class="setting-input title-template-input" placeholder="例如：{{申请人}}的{{页面名称}}" @input="changed" />
                  <div v-else class="title-example"><span>规则：<b>发起人</b> 发起的 <b>{{ form.name }}</b></span><small>示例：张三发起的{{ form.name }}</small></div>
                </div>
              </div>
              <div class="page-setting-block">
                <div class="page-setting-label"><strong>页面操作</strong><span>控制填写人可执行的操作</span></div>
                <div class="page-setting-control horizontal-controls">
                  <label class="checkbox-option"><input v-model="form.pageSettings.allowCopy" type="checkbox" @change="changed" />允许复制流程</label>
                  <select v-model="form.pageSettings.copyDataSource" class="setting-input compact-select" :disabled="!form.pageSettings.allowCopy" @change="changed"><option value="initiator">发起时的数据</option><option value="latest">最新提交数据</option></select>
                  <label class="checkbox-option"><input v-model="form.pageSettings.previewBeforeSubmit" type="checkbox" @change="changed" />提交时预览流程</label>
                  <label class="checkbox-option"><input v-model="form.pageSettings.oneClickGroup" type="checkbox" @change="changed" />一键拉群</label>
                </div>
              </div>
              <div class="page-setting-block">
                <div class="page-setting-label"><strong>设置咨询人员</strong><span>为填写人提供页面咨询联系人</span></div>
                <div class="page-setting-control consultant-control"><div class="consultant-check-list"><label v-for="person in people" :key="person" class="person-option"><input type="checkbox" :checked="form.pageSettings.consultants.includes(person)" @change="togglePagePerson(form.pageSettings.consultants, person)" /><span class="person-avatar">{{ personLabel(person).slice(0, 1) }}</span>{{ personLabel(person) }}</label></div><label class="checkbox-option"><input v-model="form.pageSettings.showAdminWhenNoConsultant" type="checkbox" @change="changed" />咨询人员为空时默认显示应用管理员</label></div>
              </div>
              <div class="page-setting-block">
                <div class="page-setting-label"><strong>页面提交后跳转的页面</strong><span>选择提交成功后打开的位置</span></div>
                <div class="page-setting-control"><div class="radio-list"><label class="radio-option"><input v-model="form.pageSettings.redirectMode" type="radio" value="default" @change="changed" />默认页面</label><label class="radio-option"><input v-model="form.pageSettings.redirectMode" type="radio" value="internal" @change="changed" />应用内页面</label><label class="radio-option"><input v-model="form.pageSettings.redirectMode" type="radio" value="external" @change="changed" />外部链接</label></div><input v-if="form.pageSettings.redirectMode === 'external'" v-model="form.pageSettings.redirectUrl" class="setting-input redirect-url-input" type="url" placeholder="https://example.com" @input="changed" /></div>
              </div>
              <div class="page-setting-block">
                <div class="page-setting-label"><strong>审批动作完成后的跳转</strong><span>选择处理完审批后的页面行为</span></div>
                <div class="page-setting-control radio-list"><label class="radio-option"><input v-model="form.pageSettings.afterApproval" type="radio" value="next_dialog" @change="changed" />展示“下一条”选择窗口</label><label class="radio-option"><input v-model="form.pageSettings.afterApproval" type="radio" value="next_item" @change="changed" />跳转至下一条</label><label class="radio-option"><input v-model="form.pageSettings.afterApproval" type="radio" value="stay" @change="changed" />停留在当前数据详情页</label></div>
              </div>
              <div class="page-setting-block member-refresh-block">
                <div class="page-setting-label"><strong>成员字段：格式刷新</strong><span>{{ memberRefreshLabel }}</span></div>
                <div class="page-setting-control"><button class="outline-button" @click="refreshMemberFields"><History :size="14" /> 刷新成员字段</button></div>
              </div>
            </section>
            <section v-else class="page-settings-content permissions-content">
              <header class="settings-section-heading"><h2>权限设置</h2><p>控制谁可以访问、提交表单和查看提交记录。</p></header>
              <div class="permission-card">
                <div class="permission-card-heading"><div><strong>页面访问范围</strong><span>设置哪些成员可以打开此页面</span></div><span class="permission-state">{{ form.permissions.accessMode === 'all' ? '所有成员' : `${form.permissions.members.length} 位成员` }}</span></div>
                <div class="permission-choice-list"><label class="radio-option"><input v-model="form.permissions.accessMode" type="radio" value="all" @change="changed" />所有应用成员可访问</label><label class="radio-option"><input v-model="form.permissions.accessMode" type="radio" value="members" @change="changed" />仅指定成员可访问</label></div>
                <div v-if="form.permissions.accessMode === 'members'" class="permission-members"><label v-for="person in people" :key="person" class="person-option"><input type="checkbox" :checked="form.permissions.members.includes(person)" @change="togglePagePerson(form.permissions.members, person)" /><span class="person-avatar">{{ personLabel(person).slice(0, 1) }}</span>{{ personLabel(person) }}</label></div>
              </div>
              <div class="permission-card">
                <div class="permission-card-heading"><div><strong>页面操作权限</strong><span>设置访问者能够执行的操作</span></div></div>
                <div class="permission-toggle-list">
                  <div class="permission-toggle-row"><div><strong>提交表单</strong><span>允许成员创建并提交新的表单记录</span></div><button :class="['switch', { on: form.permissions.canSubmit }]" role="switch" :aria-checked="form.permissions.canSubmit" aria-label="允许提交表单" @click="form.permissions.canSubmit = !form.permissions.canSubmit; changed()"><i></i></button></div>
                  <div class="permission-toggle-row"><div><strong>查看自己的记录</strong><span>提交人可查看自己创建的记录</span></div><button :class="['switch', { on: form.permissions.canViewOwnRecords }]" role="switch" :aria-checked="form.permissions.canViewOwnRecords" aria-label="允许查看自己的记录" @click="form.permissions.canViewOwnRecords = !form.permissions.canViewOwnRecords; changed()"><i></i></button></div>
                  <div class="permission-toggle-row"><div><strong>查看全部记录</strong><span>允许成员查看页面的全部提交记录</span></div><button :class="['switch', { on: form.permissions.canViewAllRecords }]" role="switch" :aria-checked="form.permissions.canViewAllRecords" aria-label="允许查看全部记录" @click="form.permissions.canViewAllRecords = !form.permissions.canViewAllRecords; changed()"><i></i></button></div>
                  <div class="permission-toggle-row"><div><strong>导出记录</strong><span>允许将有权查看的记录导出</span></div><button :class="['switch', { on: form.permissions.canExportRecords }]" role="switch" :aria-checked="form.permissions.canExportRecords" aria-label="允许导出记录" @click="form.permissions.canExportRecords = !form.permissions.canExportRecords; changed()"><i></i></button></div>
                </div>
              </div>
              <div class="inspector-tip"><LockKeyhole :size="15" /><span>权限设置会随表单保存。访问成员和提交权限由后端校验；数据管理入口由应用管理员权限控制。</span></div>
            </section>
          </div>
          <div class="editor-statusbar"><span><span class="status-dot green"></span> 页面设置</span><span>{{ pageSettingsTab === 'base' ? '基础设置' : '权限设置' }}</span><span class="statusbar-spacer"></span><span>{{ saveMessage }}</span></div>
        </template>
        <template v-else-if="activeTopTab === '数据管理'">
          <DataManagement :form="form" :initial-view="workspaceDataView" />
        </template>
        <template v-else-if="activeTopTab === '流程设计'">
          <div class="workflow-toolbar">
            <div class="workflow-toolbar-summary">
              <div class="workflow-toolbar-title">
                <div class="workflow-title-icon"><GitFork :size="17" /></div>
                <div class="workflow-title-copy"><span>当前工作流</span><input v-model="workflow.name" class="workflow-name-input" aria-label="工作流名称" :title="workflow.name" @input="workflowChanged" /></div>
              </div>
              <div class="workflow-category-editor"><span>分类</span><select v-model="workflowCategorySelection" aria-label="工作流分类" title="选择流程分类，保存并发布后生效"><option value="" disabled>请选择分类</option><option v-for="category in workflowCategoryOptions" :key="category" :value="category">{{ category }}</option></select></div>
            </div>
            <div class="workflow-toolbar-footer">
              <div class="workflow-toolbar-state" role="status" aria-live="polite" aria-atomic="true">
                <span :class="['save-state', { saving: isSavingWorkflow, dirty: workflowSavedMessage === '有未保存的更改' }]"><span class="status-dot"></span>{{ isSavingWorkflow ? '保存中…' : workflowSavedMessage }}</span>
                <span :class="['workflow-publish-status', { published: workflowPublishStatus === '已发布' }]">{{ workflowPublishStatus }}</span>
              </div>
              <div class="workflow-toolbar-actions" role="group" aria-label="流程操作">
                <button v-if="currentUser.canManagePermissions" type="button" class="preview-button" :disabled="isSavingWorkflow || isPublishingWorkflow" @click="openWorkflowCreate"><Plus :size="16" /><span>新建工作流</span></button>
                <button type="button" class="save-button" :disabled="isSavingWorkflow || isPublishingWorkflow" :aria-busy="isSavingWorkflow" @click="saveWorkflowNow()"><LoaderCircle v-if="isSavingWorkflow" :size="16" class="workflow-button-spinner" /><Save v-else :size="16" /><span>{{ isSavingWorkflow ? '保存中…' : '保存流程' }}</span></button>
                <button type="button" class="publish-button" :disabled="isSavingWorkflow || isPublishingWorkflow" :aria-busy="isPublishingWorkflow" @click="publishWorkflowNow"><LoaderCircle v-if="isPublishingWorkflow" :size="16" class="workflow-button-spinner" /><Rocket v-else :size="16" /><span>{{ isPublishingWorkflow ? '发布中…' : workflow.publishedSnapshot ? '重新发布' : '发布流程' }}</span></button>
              </div>
            </div>
          </div>
          <div class="workflow-viewport" @click.self="nodePicker = null">
            <div class="workflow-canvas">
              <button class="workflow-start" :class="{ selected: selectedWorkflowNodeId === 'start' }" @click="selectWorkflowNode(workflow.nodes[0])"><Play :size="15" fill="currentColor" /> 发起 <ChevronRight :size="14" /></button>
                <div :class="['workflow-connector', { 'workflow-drop-active': workflowDropTarget === workflowDropKey('root', 1) }]" @dragover="hoverWorkflowDropTarget($event, 'root', 1)" @drop="moveWorkflowNode($event, 'root', 1)">
                <span class="flow-line"></span><button class="flow-add-button" aria-label="在发起后添加节点" @click.stop="isRootPickerOpen(1) ? nodePicker = null : openRootNodePicker(1)"><Plus :size="15" /></button>
                  <span class="workflow-drop-placeholder">放置到此处</span>
                  <div v-if="isRootPickerOpen(1)" class="workflow-picker" @click.stop><strong>添加流程节点</strong><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'approval')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('approval')"><UserRound :size="16" /> 审批人</button><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'executor')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('executor')"><UserRound :size="16" /> 执行人</button><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'condition')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('condition')"><GitFork :size="16" /> 条件分支</button></div>
              </div>
              <template v-for="(node, index) in workflow.nodes.slice(1, -1)" :key="node.id">
                <article v-if="node.type !== 'condition'" :class="['workflow-node-card', { selected: selectedWorkflowNodeId === node.id, 'drag-source': workflowNodeDrag?.kind === 'move' && workflowNodeDrag.nodeId === node.id }]" draggable="true" @dragstart.stop="startWorkflowNodeDrag($event, node, 'root')" @dragend="finishWorkflowNodeDrag" @dragover="hoverWorkflowNodeTarget($event, node, 'root', index + 1)" @drop="dropWorkflowNode($event, node, 'root', index + 1)" @click="selectWorkflowNode(node)">
                  <div class="workflow-node-head"><Grip :size="13" class="workflow-node-grip" /><div :class="['workflow-node-icon', node.type]"><component :is="nodeIcons[node.type]" :size="16" /></div><div><input v-model="node.name" class="workflow-node-title-input" :aria-label="`${nodeTypeNames[node.type]}节点名称`" draggable="false" @click.stop="selectWorkflowNode(node)" @input="workflowChanged" /><span>{{ nodeTypeNames[node.type] }}</span></div><button class="icon-button small-icon" aria-label="删除节点" title="删除节点" @click.stop="removeWorkflowNode(node.id)"><Trash2 :size="14" /></button></div>
                  <div class="workflow-assignee-summary"><UserRound :size="13" /><span>{{ assigneeSummary(node) }}</span><ChevronRight :size="14" /></div>
                </article>
                <section v-else :class="['condition-stage', { selected: selectedWorkflowNodeId === node.id, 'drag-source': workflowNodeDrag?.kind === 'move' && workflowNodeDrag.nodeId === node.id }]" draggable="true" @dragstart.stop="startWorkflowNodeDrag($event, node, 'root')" @dragend="finishWorkflowNodeDrag" @dragover="hoverWorkflowNodeTarget($event, node, 'root', index + 1)" @drop="dropWorkflowNode($event, node, 'root', index + 1)">
                  <div class="condition-stage-heading" @click="selectWorkflowNode(node)"><span class="condition-stage-icon"><GitFork :size="16" /></span><span><input v-model="node.name" class="workflow-condition-title-input" aria-label="条件分支节点名称" draggable="false" @click.stop="selectWorkflowNode(node)" @input="workflowChanged" /><small>按表单条件选择后续审批路径</small></span><button class="icon-button small-icon" aria-label="删除分支节点" @click.stop="removeWorkflowNode(node.id)"><Trash2 :size="14" /></button></div>
                  <div class="branch-columns" :style="{ '--branch-count': node.branches?.length || 2, '--branch-inset': `${50 / (node.branches?.length || 2)}%` }">
                    <div v-for="(branch, branchIndex) in node.branches" :key="branch.id" :class="['workflow-branch', { active: selectedWorkflowBranchId === branch.id }]" @click="selectWorkflowBranch(node, branch)">
                      <div class="branch-heading"><span class="branch-order">{{ branch.isDefault ? '默认' : `条件 ${branchIndex + 1}` }}</span><strong>{{ branch.name }}</strong><button class="icon-button small-icon" aria-label="编辑条件" @click.stop="selectWorkflowBranch(node, branch)"><Settings2 :size="13" /></button></div>
                      <div class="branch-rule" @click.stop="selectWorkflowBranch(node, branch)">{{ branchSummary(branch) }}</div>
                      <div class="branch-node-list">
                        <div v-if="branch.nodes.length" :class="['branch-node-add', { 'workflow-drop-active': workflowDropTarget === workflowDropKey('branch', 0, branch.id) }]" @dragover="hoverWorkflowDropTarget($event, 'branch', 0, branch.id)" @drop="moveWorkflowNode($event, 'branch', 0, branch.id)"><span class="flow-line"></span><button class="flow-add-button" aria-label="在分支开始处添加节点" @click.stop="isBranchPickerOpen(branch.id, 0) ? nodePicker = null : openBranchNodePicker(branch.id, 0)"><Plus :size="14" /></button><span class="workflow-drop-placeholder">放置到此处</span><div v-if="isBranchPickerOpen(branch.id, 0)" class="workflow-picker branch-picker" @click.stop><strong>添加节点</strong><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'approval')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('approval')"><UserRound :size="15" /> 审批人</button><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'executor')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('executor')"><UserRound :size="15" /> 执行人</button></div></div>
                        <template v-for="(child, childIndex) in branch.nodes" :key="child.id">
                          <article :class="['workflow-node-card', 'branch-node-card', { selected: selectedWorkflowNodeId === child.id, 'drag-source': workflowNodeDrag?.kind === 'move' && workflowNodeDrag.nodeId === child.id }]" draggable="true" @dragstart.stop="startWorkflowNodeDrag($event, child, 'branch', branch.id)" @dragend="finishWorkflowNodeDrag" @dragover="hoverWorkflowNodeTarget($event, child, 'branch', childIndex, branch.id)" @drop="dropWorkflowNode($event, child, 'branch', childIndex, branch.id)" @click.stop="selectWorkflowNode(child)">
                            <div class="workflow-node-head"><Grip :size="12" class="workflow-node-grip" /><div :class="['workflow-node-icon', child.type]"><component :is="nodeIcons[child.type]" :size="15" /></div><div><input v-model="child.name" class="workflow-node-title-input" :aria-label="`${nodeTypeNames[child.type]}节点名称`" draggable="false" @click.stop="selectWorkflowNode(child)" @input="workflowChanged" /><span>{{ nodeTypeNames[child.type] }}</span></div><button class="icon-button small-icon" aria-label="删除节点" @click.stop="removeWorkflowNode(child.id)"><Trash2 :size="13" /></button></div>
                            <div class="workflow-assignee-summary"><UserRound :size="12" /><span>{{ assigneeSummary(child) }}</span></div>
                          </article>
                          <div :class="['branch-node-add', { 'workflow-drop-active': workflowDropTarget === workflowDropKey('branch', childIndex + 1, branch.id) }]" @dragover="hoverWorkflowDropTarget($event, 'branch', childIndex + 1, branch.id)" @drop="moveWorkflowNode($event, 'branch', childIndex + 1, branch.id)"><span class="flow-line"></span><button class="flow-add-button" aria-label="添加审批或执行节点" @click.stop="isBranchPickerOpen(branch.id, childIndex + 1) ? nodePicker = null : openBranchNodePicker(branch.id, childIndex + 1)"><Plus :size="14" /></button><span class="workflow-drop-placeholder">放置到此处</span><div v-if="isBranchPickerOpen(branch.id, childIndex + 1)" class="workflow-picker branch-picker" @click.stop><strong>添加节点</strong><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'approval')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('approval')"><UserRound :size="15" /> 审批人</button><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'executor')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('executor')"><UserRound :size="15" /> 执行人</button></div></div>
                        </template>
                        <div v-if="!branch.nodes.length" :class="['branch-empty', { 'workflow-drop-active': workflowDropTarget === workflowDropKey('branch', 0, branch.id) }]" @dragover="hoverWorkflowDropTarget($event, 'branch', 0, branch.id)" @drop="moveWorkflowNode($event, 'branch', 0, branch.id)"><button class="flow-add-button" aria-label="添加审批或执行节点" @click.stop="isBranchPickerOpen(branch.id, 0) ? nodePicker = null : openBranchNodePicker(branch.id, 0)"><Plus :size="14" /></button><span>添加审批或执行节点</span><span class="workflow-drop-placeholder">放置到此处</span><div v-if="isBranchPickerOpen(branch.id, 0)" class="workflow-picker branch-picker" @click.stop><strong>添加节点</strong><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'approval')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('approval')"><UserRound :size="15" /> 审批人</button><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'executor')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('executor')"><UserRound :size="15" /> 执行人</button></div></div>
                      </div>
                    </div>
                  </div>
                  <div class="branch-merge-connector" aria-hidden="true"><span class="flow-line"></span></div>
                </section>
                <div :class="['workflow-connector', { 'workflow-drop-active': workflowDropTarget === workflowDropKey('root', index + 2) }]" @dragover="hoverWorkflowDropTarget($event, 'root', index + 2)" @drop="moveWorkflowNode($event, 'root', index + 2)">
                  <span class="flow-line"></span><button class="flow-add-button" :aria-label="`在${node.name}后添加节点`" @click.stop="isRootPickerOpen(index + 2) ? nodePicker = null : openRootNodePicker(index + 2)"><Plus :size="15" /></button>
                  <span class="workflow-drop-placeholder">放置到此处</span>
                  <div v-if="isRootPickerOpen(index + 2)" class="workflow-picker" @click.stop><strong>添加流程节点</strong><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'approval')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('approval')"><UserRound :size="16" /> 审批人</button><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'executor')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('executor')"><UserRound :size="16" /> 执行人</button><button draggable="true" @dragstart.stop="startNewWorkflowNodeDrag($event, 'condition')" @dragend="finishWorkflowNodeDrag" @click="addWorkflowNode('condition')"><GitFork :size="16" /> 条件分支</button></div>
                </div>
              </template>
              <button class="workflow-end" :class="{ selected: selectedWorkflowNodeId === 'end' }" @click="selectWorkflowNode(workflow.nodes[workflow.nodes.length - 1])"><Check :size="15" /> 结束</button>
            </div>
          </div>
          <div class="editor-statusbar"><span><span class="status-dot green"></span> 流程设计</span><span>{{ workflowNodeCount }} 个流程节点</span><span class="statusbar-spacer"></span><span>{{ workflowSavedMessage }}</span></div>
        </template>
        <template v-else>
        <div class="editor-toolbar">
          <div class="toolbar-left"><span class="crumb-muted">设计器</span><ChevronRight :size="14" /><span class="crumb-current">表单画布</span></div>
          <div class="toolbar-right"><span :class="['save-state', { saving: isSaving }]" ><span class="status-dot"></span>{{ isSaving ? '保存中' : saveMessage }}</span><button class="preview-button" @click="openPreview"><Eye :size="15" /> 预览</button><button class="save-button" :disabled="isSaving" @click="saveNow()"><Save :size="15" /> 保存</button><button class="more-button" aria-label="更多操作" @click="exportJson"><MoreHorizontal :size="18" /></button></div>
        </div>

        <div :class="['canvas-viewport', { 'drag-active': dragActive }]" @dragenter.prevent="dragActive = true" @dragleave="leaveCanvas" @dragover.prevent @drop="dropOnCanvas($event)">
          <div class="canvas-page" style="--zoom: 1" @click.self="selectedId = null">
            <div class="canvas-page-head">
              <div class="form-tag"><span class="tag-dot"></span> 表单</div>
              <div class="canvas-header-actions"><button type="button" class="form-header-edit-button" @click.stop="editFormHeader"><Settings2 :size="14" />编辑名称</button><button class="canvas-menu" aria-label="表单操作" @click="exportJson"><MoreHorizontal :size="17" /></button></div>
            </div>
            <div class="form-heading" @click.stop="selectedId = null"><input v-model="form.name" class="form-title-input" aria-label="表单名称" placeholder="输入表单名称" maxlength="80" @focus="selectedId = null" @input="changed" /><span class="title-required">*</span><span class="title-pencil"><Settings2 :size="14" /></span></div>
            <div class="canvas-divider"></div>
            <div class="form-grid">
              <template v-for="(field, index) in form.fields" :key="field.id">
                <article :class="['form-field', field.width, { selected: selectedId === field.id }]" draggable="true" @dragstart="startFieldDrag($event, field)" @click.stop="selectedId = field.id" @dragover.prevent @drop.stop="dropOnCanvas($event, index)">
                  <div v-if="selectedId === field.id" class="selection-tools"><span><Grip :size="14" /> {{ formatType(field.type) }}</span><div><button aria-label="上移字段" title="上移" @click.stop="moveField(field, -1)"><ArrowLeft :size="13" class="move-up-icon" /></button><button aria-label="下移字段" title="下移" @click.stop="moveField(field, 1)"><ArrowRight :size="13" class="move-down-icon" /></button><button aria-label="复制字段" title="复制" @click.stop="duplicateField(field)"><Copy :size="13" /></button><button aria-label="删除字段" title="删除" @click.stop="removeField(field.id)"><Trash2 :size="13" /></button></div></div>
                  <label class="field-label">{{ field.label }} <span v-if="field.required" class="required-mark">*</span></label>
                  <div v-if="field.type === 'description'" class="description-value">{{ field.defaultValue || '--' }}</div>
                  <div v-else-if="field.type === 'textarea'" class="preview-control textarea-control">{{ field.placeholder || '请输入内容' }}<span class="field-count">0 / 500</span></div>
                  <div v-else-if="field.type === 'radio' || field.type === 'checkbox'" class="choice-preview"><span v-for="option in field.options.slice(0, 3)" :key="option"><i :class="field.type"></i>{{ option }}</span></div>
                  <div v-else-if="field.type === 'rating'" class="rating-preview"><Star v-for="n in 5" :key="n" :size="17" /></div>
                  <div v-else-if="field.type === 'image' || field.type === 'attachment'" class="upload-preview"><component :is="iconMap[field.type]" :size="16" /> {{ field.type === 'image' ? '点击或拖拽上传图片' : '点击上传附件' }}</div>
                  <div v-else-if="field.type === 'dateRange'" class="preview-control"><span>{{ field.placeholder || '开始日期' }}</span><span class="range-separator">至</span><span>结束日期</span><CalendarDays :size="15" /></div>
                  <div v-else class="preview-control"><span :class="{ placeholder: fieldInitialValue(field) === null }">{{ fieldInitialValue(field) ?? field.placeholder ?? '请输入内容' }}</span><ChevronDown v-if="field.type === 'select' || field.type === 'multiSelect' || field.type === 'member' || field.type === 'department'" :size="15" class="control-arrow" /><CalendarDays v-else-if="field.type === 'date'" :size="15" class="control-arrow" /></div>
                  <div v-if="selectedId === field.id" class="field-hint">拖拽可调整顺序 <span>{{ field.width === 'half' ? '半行宽度' : '整行宽度' }}</span></div>
                </article>
              </template>
              <div class="canvas-drop-end" @dragover.prevent @drop.stop="dropOnCanvas($event)"><span><Plus :size="14" /> 拖拽组件到此处添加</span></div>
            </div>
            <button class="add-field-button" @click="panelTab = 'components'; setToast('从左侧选择组件添加到表单')"><Plus :size="15" /> 添加字段</button>
            <div class="canvas-bottom-note"><LockKeyhole :size="12" /> 表单数据仅对有权限的成员可见</div>
          </div>
        </div>
        <div class="editor-statusbar"><span><span class="status-dot green"></span> 设计模式</span><span>{{ fieldCount }} 个字段</span><span class="statusbar-spacer"></span></div>
        </template>
      </main>

      <aside class="inspector-panel">
        <template v-if="activeTopTab === '流程设计'">
          <div class="workflow-inspector-heading"><div class="workflow-inspector-icon"><component :is="selectedWorkflowBranch ? GitFork : selectedWorkflowNode ? nodeIcons[selectedWorkflowNode.type] : GitFork" :size="17" /></div><div><strong>{{ selectedWorkflowBranch?.name || selectedWorkflowNode?.name || '工作流设置' }}</strong><span>{{ selectedWorkflowBranch ? '条件出口' : selectedWorkflowNode ? nodeTypeNames[selectedWorkflowNode.type] : '流程属性' }}</span></div></div>
          <div v-if="selectedWorkflowBranch && selectedWorkflowNode?.type === 'condition'" class="inspector-content workflow-inspector-content">
            <div class="setting-section"><label class="setting-label">出口名称 <span class="required-mark">*</span></label><input v-model="selectedWorkflowBranch.name" class="setting-input" placeholder="例如：高金额申请" @input="workflowChanged" /></div>
            <div class="toggle-row"><div><strong>设为默认出口</strong><span>其他条件不满足时进入此分支</span></div><button :class="['switch', { on: selectedWorkflowBranch.isDefault }]" role="switch" :aria-checked="selectedWorkflowBranch.isDefault" aria-label="设为默认出口" @click="!selectedWorkflowBranch.isDefault && setDefaultBranch(selectedWorkflowNode, selectedWorkflowBranch)"><i></i></button></div>
            <template v-if="!selectedWorkflowBranch.isDefault">
              <div class="setting-section"><label class="setting-label">判断字段 <span class="required-mark">*</span></label><select v-model="selectedWorkflowBranch.fieldId" class="setting-input" @change="workflowChanged"><option value="" disabled>选择表单字段</option><option v-for="field in conditionFields" :key="field.id" :value="field.id">{{ field.label }}</option></select></div>
              <div class="setting-section"><label class="setting-label">判断规则</label><select v-model="selectedWorkflowBranch.operator" class="setting-input" @change="workflowChanged"><option v-for="(label, operator) in operatorNames" :key="operator" :value="operator">{{ label }}</option></select></div>
              <div v-if="selectedWorkflowBranch.operator !== 'empty' && selectedWorkflowBranch.operator !== 'not_empty'" class="setting-section"><label class="setting-label">比较值</label><input v-model="selectedWorkflowBranch.value" class="setting-input" placeholder="输入条件值" @input="workflowChanged" /></div>
              <div class="condition-summary-box"><GitFork :size="14" /><span>{{ branchSummary(selectedWorkflowBranch) }}</span></div>
            </template>
            <button class="danger-action" @click="deleteConditionBranch(selectedWorkflowNode, selectedWorkflowBranch)"><Trash2 :size="14" /> 删除此出口</button>
          </div>
          <div v-else-if="selectedWorkflowNode?.type === 'start'" class="inspector-content workflow-inspector-content">
            <h3 class="approval-section-title">发起设置</h3>
            <div class="setting-section">
              <label class="setting-label">选择发起表单 <span class="required-mark">*</span></label>
              <select class="setting-input" aria-label="选择工作流发起表单" :value="selectedWorkflowNode.formId ?? form.id" @change="selectStartForm(selectedWorkflowNode, $event)">
                <option v-for="item in availableForms" :key="item.id" :value="item.id">{{ item.name }}</option>
              </select>
              <span class="setting-caption">流程条件和审批字段权限将使用此表单的字段。</span>
            </div>
            <div class="condition-summary-box"><FileText :size="14" /><span>当前关联：{{ workflowForm.name }} · {{ workflowForm.fields.length }} 个字段</span></div>
            <div class="setting-section role-fields-section">
              <div class="field-permission-title-row"><h3>字段权限 <CircleHelp :size="13" title="设置申请人可编辑、只读或隐藏的表单字段" /></h3></div>
              <div v-if="workflowForm.fields.length" class="field-permission-table role-field-permission-table field-permission-matrix">
                <div class="field-permission-header"><span>组件名称</span><span>可编辑</span><span>只读</span><span>隐藏</span></div>
                <div v-for="field in workflowForm.fields" :key="field.id" class="field-permission-row"><span class="permission-field-name">{{ field.label }}<i v-if="field.required">*</i></span><label v-for="option in fieldPermissionOptions" :key="option.value" class="field-permission-radio"><input type="radio" :name="`applicant-${field.id}`" :value="option.value" :checked="applicantFieldPermission(field.id) === option.value" :aria-label="`${field.label}对申请人${option.label}`" @change="setApplicantFieldPermission(field.id, option.value)" /></label></div>
              </div>
              <div v-else class="condition-summary-box">关联表单尚未添加字段</div>
            </div>
          </div>
          <div v-else-if="selectedWorkflowNode?.type === 'condition'" class="inspector-content workflow-inspector-content">
            <div class="setting-section"><label class="setting-label">分支节点名称</label><input v-model="selectedWorkflowNode.name" class="setting-input" @input="workflowChanged" /></div>
            <div class="setting-section"><label class="setting-label">条件出口 <span class="option-count">{{ selectedWorkflowNode.branches?.length ?? 0 }}</span></label><button v-for="(branch, index) in selectedWorkflowNode.branches" :key="branch.id" class="branch-summary-row" @click="selectWorkflowBranch(selectedWorkflowNode, branch)"><span class="branch-summary-order">{{ branch.isDefault ? '默认' : `条件 ${index + 1}` }}</span><span><strong>{{ branch.name }}</strong><small>{{ branchSummary(branch) }}</small></span><ChevronRight :size="15" /></button><button class="add-option" @click="addConditionBranch(selectedWorkflowNode)"><Plus :size="14" /> 添加条件出口</button></div>
            <div class="inspector-tip"><GitFork :size="15" /><span>条件按顺序进行判断。默认出口作为兜底路径，且每个分支至少保留两个出口。</span></div>
            <button class="danger-action" @click="removeWorkflowNode(selectedWorkflowNode.id)"><Trash2 :size="14" /> 删除条件分支节点</button>
          </div>
          <div v-else-if="selectedWorkflowNode?.type === 'approval'" class="approval-config-panel">
            <div class="approval-config-tabs" role="tablist" aria-label="审批节点配置">
              <button :class="{ active: approvalTab === 'assignees' }" @click="approvalTab = 'assignees'">审批人</button>
              <button :class="{ active: approvalTab === 'buttons' }" @click="approvalTab = 'buttons'">审批按钮</button>
              <button :class="{ active: approvalTab === 'fields' }" @click="approvalTab = 'fields'">设置字段权限</button>
              <button :class="{ active: approvalTab === 'advanced' }" @click="approvalTab = 'advanced'">高级设置</button>
            </div>
            <div class="inspector-content approval-config-content">
              <template v-if="approvalTab === 'assignees'">
                <h3 class="approval-section-title">审批人设置</h3>
                <div class="setting-section"><label class="setting-label">节点名称</label><input v-model="selectedWorkflowNode.name" class="setting-input" @input="workflowChanged" /></div>
                <div class="setting-section"><label class="setting-label">审批人来源 <span class="required-mark">*</span></label><select class="setting-input" :value="selectedWorkflowNode.assigneeMode ?? 'specified'" @change="setNodeAssigneeMode(selectedWorkflowNode, ($event.target as HTMLSelectElement).value as 'specified' | 'direct_manager')"><option value="direct_manager">直属主管</option><option value="specified">指定成员</option></select></div>
                <div v-if="selectedWorkflowNode.assigneeMode === 'specified'" class="setting-section"><label class="setting-label">依次审批成员 <span class="required-mark">*</span></label><div class="sequential-assignee-list"><div v-for="(person, index) in selectedWorkflowNode.assignees" :key="`${selectedWorkflowNode.id}-assignee-${index}`" class="sequential-assignee-row"><span class="sequential-assignee-order">{{ index + 1 }}</span><select class="setting-input" :value="person" @change="setAssigneeAtFromInput(selectedWorkflowNode, index, $event)"><option v-for="candidate in people" :key="candidate" :value="candidate">{{ personLabel(candidate) }}</option></select><button class="icon-button small-icon" aria-label="移除审批人" title="移除审批人" @click="removeAssignee(selectedWorkflowNode, index)"><X :size="14" /></button></div><datalist :id="`approval-people-${selectedWorkflowNode.id}`"><option v-for="candidate in people" :key="candidate" :value="candidate" /></datalist><button class="add-option" :disabled="(selectedWorkflowNode.assignees?.length ?? 0) >= people.length" @click="addAssignee(selectedWorkflowNode)"><Plus :size="14" /> 添加审批人</button></div><span class="setting-caption">可输入关键词搜索或展开候选成员，按列表顺序依次审批</span></div>
                <div v-else class="condition-summary-box"><Users :size="14" /><span>由“{{ workflow.category || '常用流程' }}”分类设置的主管审批；多人时按配置顺序依次处理。管理员可在“发起审批 → 更多”中选中流程，点击“新增”后的“设置主管”。</span></div>
              </template>
              <template v-else-if="approvalTab === 'buttons'">
                <h3 class="approval-section-title">操作按钮</h3>
                <div class="approval-button-table">
                  <div class="approval-button-header"><span>操作按钮</span><span>显示名称</span><span>审批意见</span><span>批量</span><span>启用</span></div>
                  <div v-for="button in selectedWorkflowNode.approvalButtons" :key="button.key" class="approval-button-row">
                    <span class="approval-action-name">{{ approvalActionNames[button.key] || button.key }}</span>
                    <input v-model="button.name" class="button-name-input" :aria-label="`${approvalActionNames[button.key]}显示名称`" @input="workflowChanged" />
                    <select v-model="button.opinionMode" class="opinion-select" :aria-label="`${button.name}审批意见要求`" @change="workflowChanged"><option value="none">不需要</option><option value="optional">非必填</option><option value="required">必填</option></select>
                    <label class="batch-cell"><input v-model="button.batchEnabled" type="checkbox" :aria-label="`${button.name}允许批量审批`" @change="workflowChanged" /></label>
                    <button :class="['switch', { on: button.enabled }]" role="switch" :aria-checked="button.enabled" :aria-label="`启用${button.name}`" @click="button.enabled = !button.enabled; workflowChanged()"><i></i></button>
                  </div>
                </div>
                <p class="approval-hint">停用的按钮不会显示在审批任务中。</p>
              </template>
              <template v-else-if="approvalTab === 'fields'">
                <div class="field-permission-title-row"><h3>字段权限 <CircleHelp :size="13" title="设置审批人可编辑、只读或隐藏的表单字段" /></h3></div>
                <div class="field-permission-table role-field-permission-table field-permission-matrix"><div class="field-permission-header"><span>组件名称</span><span>可编辑</span><span>只读</span><span>隐藏</span></div><div v-for="field in workflowForm.fields" :key="field.id" class="field-permission-row"><span class="permission-field-name">{{ field.label }}<i v-if="field.required">*</i></span><label v-for="option in fieldPermissionOptions" :key="option.value" class="field-permission-radio"><input type="radio" :name="`approval-${selectedWorkflowNode.id}-${field.id}`" :value="option.value" :checked="fieldPermission(selectedWorkflowNode, field.id) === option.value" :aria-label="`${field.label}${option.label}`" @change="setFieldPermission(selectedWorkflowNode, field.id, option.value)" /></label></div></div>
                <div class="inspector-tip"><LockKeyhole :size="15" /><span>隐藏的字段在当前审批节点不会展示；只读字段可查看但不能修改。</span></div>
              </template>
              <template v-else>
                <h3 class="approval-section-title">高级设置</h3>
                <div class="setting-section"><label class="setting-label">多人审批方式</label><select v-model="selectedWorkflowNode.approvalMode" class="setting-input" @change="workflowChanged"><option value="sequential">依次审批</option><option value="all">会签：所有人通过</option><option value="any">或签：一人通过</option></select><span class="setting-caption">选择此节点有多个审批人时的处理方式</span></div>
                <div class="inspector-tip"><Settings2 :size="15" /><span>这些设置只影响当前审批节点。</span></div>
              </template>
              <button v-if="approvalTab === 'assignees'" class="danger-action" @click="removeWorkflowNode(selectedWorkflowNode.id)"><Trash2 :size="14" /> 删除审批节点</button>
            </div>
          </div>
          <div v-else-if="selectedWorkflowNode?.type === 'executor'" class="approval-config-panel">
            <div class="approval-config-tabs executor-config-tabs" role="tablist" aria-label="执行节点配置">
              <button :class="{ active: executorTab === 'assignees' }" @click="executorTab = 'assignees'">执行人</button>
              <button :class="{ active: executorTab === 'fields' }" @click="executorTab = 'fields'">设置字段权限</button>
            </div>
            <div class="inspector-content approval-config-content workflow-inspector-content">
              <template v-if="executorTab === 'assignees'">
                <h3 class="approval-section-title">执行人设置</h3>
                <div class="setting-section"><label class="setting-label">节点名称 <span class="required-mark">*</span></label><input v-model="selectedWorkflowNode.name" class="setting-input" @input="workflowChanged" /></div>
                <div class="setting-section"><label class="setting-label">执行人来源 <span class="required-mark">*</span></label><select class="setting-input" :value="selectedWorkflowNode.assigneeMode ?? 'specified'" @change="setNodeAssigneeMode(selectedWorkflowNode, ($event.target as HTMLSelectElement).value as 'specified' | 'direct_manager')"><option value="direct_manager">直属主管</option><option value="specified">指定成员</option></select></div>
                <div v-if="selectedWorkflowNode.assigneeMode === 'specified'" class="setting-section"><label class="setting-label">依次执行成员 <span class="required-mark">*</span></label><div class="sequential-assignee-list"><div v-for="(person, index) in selectedWorkflowNode.assignees" :key="`${selectedWorkflowNode.id}-assignee-${index}`" class="sequential-assignee-row"><span class="sequential-assignee-order">{{ index + 1 }}</span><select class="setting-input" :value="person" @change="setAssigneeAtFromInput(selectedWorkflowNode, index, $event)"><option v-for="candidate in people" :key="candidate" :value="candidate">{{ personLabel(candidate) }}</option></select><button class="icon-button small-icon" aria-label="移除执行人" title="移除执行人" @click="removeAssignee(selectedWorkflowNode, index)"><X :size="14" /></button></div><datalist :id="`executor-people-${selectedWorkflowNode.id}`"><option v-for="candidate in people" :key="candidate" :value="candidate" /></datalist><button class="add-option" :disabled="(selectedWorkflowNode.assignees?.length ?? 0) >= people.length" @click="addAssignee(selectedWorkflowNode)"><Plus :size="14" /> 添加执行人</button></div><span class="setting-caption">可输入关键词搜索或展开候选成员，按列表顺序依次执行</span></div>
                <div v-else class="condition-summary-box"><Users :size="14" /><span>成员任务交给本部门主管，主管任务交给总经理；部门未设置主管时直接交给总经理。</span></div>
                <div class="inspector-tip"><BadgeCheck :size="15" /><span>按成员列表顺序依次执行，所有执行人完成后进入下一节点。</span></div>
                <button class="danger-action" @click="removeWorkflowNode(selectedWorkflowNode.id)"><Trash2 :size="14" /> 删除节点</button>
              </template>
              <template v-else>
                <h3 class="approval-section-title">执行人字段权限</h3>
                <div v-if="workflowForm.fields.length" class="field-permission-table role-field-permission-table field-permission-matrix"><div class="field-permission-header"><span>组件名称</span><span>可编辑</span><span>只读</span><span>隐藏</span></div><div v-for="field in workflowForm.fields" :key="field.id" class="field-permission-row"><span class="permission-field-name">{{ field.label }}<i v-if="field.required">*</i></span><label v-for="option in fieldPermissionOptions" :key="option.value" class="field-permission-radio"><input type="radio" :name="`executor-${selectedWorkflowNode.id}-${field.id}`" :value="option.value" :checked="fieldPermission(selectedWorkflowNode, field.id) === option.value" :aria-label="`${field.label}对执行人${option.label}`" @change="setFieldPermission(selectedWorkflowNode, field.id, option.value)" /></label></div></div>
                <div v-else class="condition-summary-box">关联表单尚未添加字段</div>
                <div class="inspector-tip"><LockKeyhole :size="15" /><span>隐藏的字段在当前执行节点不会展示；只读字段可查看但不能修改。</span></div>
              </template>
            </div>
          </div>
          <div v-else class="inspector-content workflow-inspector-content"><div class="workflow-fixed-node"><div class="large-form-icon"><component :is="selectedWorkflowNode ? nodeIcons[selectedWorkflowNode.type] : GitFork" :size="18" /></div><strong>{{ selectedWorkflowNode ? selectedWorkflowNode.name : workflow.name }}</strong><span>{{ selectedWorkflowNode?.type === 'end' ? '流程在此节点结束' : '选择画布中的节点配置流程' }}</span></div><div class="inspector-tip"><GitFork :size="15" /><span>流程条件使用当前表单字段进行判断。</span></div></div>
        </template>
        <template v-else>
        <template v-if="selectedField">
          <div class="inspector-heading"><div class="inspector-icon"><component :is="iconMap[selectedField.type]" :size="16" /></div><div><strong>{{ selectedField.label }}</strong><span>{{ formatType(selectedField.type) }}</span></div><button class="icon-button small-icon" aria-label="更多字段设置" @click="setToast('字段快捷操作已在画布中提供')"><MoreHorizontal :size="17" /></button></div>
          <div class="inspector-content">
            <div class="setting-section"><label class="setting-label">字段名称 <span class="required-mark">*</span></label><input v-model="selectedField.label" class="setting-input" @input="onFieldChange" /></div>
            <div v-if="selectedField.type !== 'description'" class="setting-section"><label class="setting-label">提示文字</label><input v-model="selectedField.placeholder" class="setting-input" placeholder="请输入提示文字" @input="onFieldChange" /></div>
            <div v-if="['radio', 'checkbox', 'select', 'multiSelect'].includes(selectedField.type)" class="setting-section"><label class="setting-label">选项 <span class="option-count">{{ selectedField.options.length }}</span></label><div class="option-list"><div v-for="(option, index) in selectedField.options" :key="`${selectedField.id}-${index}`" class="option-row"><Grip :size="13" class="option-grip" /><input v-model="selectedField.options[index]" class="setting-input" @input="onFieldChange" /><button class="icon-button option-remove" aria-label="删除选项" @click="removeOption(index)"><X :size="14" /></button></div></div><button class="add-option" @click="addOption"><Plus :size="14" /> 添加选项</button></div>
            <div class="setting-section"><label class="setting-label">字段宽度</label><div class="segmented-control"><button :class="{ active: selectedField.width === 'half' }" @click="selectedField.width = 'half'; onFieldChange()"><span class="width-symbol half-width"></span>半行</button><button :class="{ active: selectedField.width === 'full' }" @click="selectedField.width = 'full'; onFieldChange()"><span class="width-symbol full-width"></span>整行</button></div></div>
            <div class="setting-divider"></div>
            <div class="toggle-row"><div><strong>必填</strong><span>提交前必须填写此字段</span></div><button :class="['switch', { on: selectedField.required }]" role="switch" :aria-checked="selectedField.required" aria-label="必填" @click="selectedField.required = !selectedField.required; onFieldChange()"><i></i></button></div>
            <div class="toggle-row"><div><strong>默认值</strong><span>为填写人预设初始内容</span></div><button :class="['switch', { on: !!selectedField.defaultValue }]" role="switch" :aria-checked="!!selectedField.defaultValue" aria-label="默认值" @click="selectedField.defaultValue = selectedField.defaultValue ? '' : selectedField.type === 'number' ? '0' : '默认内容'; onFieldChange()"><i></i></button></div>
            <div v-if="selectedField.defaultValue !== undefined && selectedField.type !== 'description'" class="setting-section default-value-section"><input v-model="selectedField.defaultValue" :type="selectedField.type === 'number' ? 'number' : 'text'" class="setting-input" placeholder="输入默认值" @input="onFieldChange" /></div>
            <button class="danger-action" @click="removeField(selectedField.id)"><Trash2 :size="14" /> 删除字段</button>
          </div>
        </template>
        <template v-else>
          <div class="inspector-heading"><div class="inspector-icon"><FileText :size="16" /></div><div><strong>表单名称</strong><span>修改后点击保存</span></div></div>
          <section class="inspector-content form-header-settings" aria-label="编辑表单名称">
            <div class="setting-section"><label class="setting-label" for="form-name-setting">表单名称 <span class="required-mark">*</span></label><input id="form-name-setting" ref="formNameSettingInput" v-model="form.name" class="setting-input" aria-label="编辑表单名称" maxlength="80" placeholder="输入表单名称" @input="changed" /></div>
            <button type="button" class="save-button" :disabled="isSaving" @click="saveNow()"><Save :size="14" />{{ isSaving ? '保存中…' : '保存名称' }}</button>
            <p class="form-header-settings-hint">画布与此处同步更新。保存后，重新发布流程可更新申请页面。</p>
          </section>
        </template>
        </template>
      </aside>
    </div>

    <div v-if="workspaceReturnConfirmOpen" class="modal-backdrop" v-backdrop-dismiss="closeWorkspaceReturn" @keydown.esc.stop="closeWorkspaceReturn">
      <section class="workflow-create-dialog" role="alertdialog" aria-modal="true" aria-label="是否放弃修改" @click.stop>
        <header><div><strong>是否放弃修改</strong><p>表单或流程有未保存的修改，确认放弃后返回更多页面。</p></div></header>
        <p v-if="workspaceReturnError" class="workflow-create-error" role="alert">{{ workspaceReturnError }}</p>
        <footer><button ref="workspaceReturnContinue" class="save-button" :disabled="workspaceReturning" @click="closeWorkspaceReturn">继续编辑</button><button class="workflow-discard-button" :disabled="workspaceReturning" @click="finishWorkspaceReturn(true)">{{ workspaceReturning ? '正在返回…' : '确认放弃' }}</button></footer>
      </section>
    </div>
    <div v-if="workflowCreateOpen" class="modal-backdrop" v-backdrop-dismiss="closeWorkflowCreate">
      <section class="workflow-create-dialog" :role="workflowCreateDiscardOpen ? 'alertdialog' : 'dialog'" aria-modal="true" :aria-label="workflowCreateDiscardOpen ? '是否放弃修改' : '新建工作流'" @click.stop>
        <template v-if="workflowCreateDiscardOpen">
          <header><div><strong>是否放弃修改</strong><span>放弃后将清除本次填写的名称和分类。</span></div></header>
          <footer><button class="save-button" @click="workflowCreateDiscardOpen = false">继续编辑</button><button class="workflow-discard-button" @click="workflowCreateOpen = false; workflowCreateDiscardOpen = false">确认放弃</button></footer>
        </template>
        <template v-else>
          <header><div class="workflow-title-icon"><GitFork :size="17" /></div><div><strong>新建工作流</strong><span>选择审批分类后，继续配置表单和审批流程</span></div><button class="icon-button" aria-label="关闭" :disabled="isCreatingWorkflow" @click="closeWorkflowCreate"><X :size="18" /></button></header>
          <form id="workflow-create-form" @submit.prevent="createNewWorkflow">
            <label class="setting-label" for="new-workflow-name">工作流名称 <span class="required-mark">*</span></label>
            <input id="new-workflow-name" v-model="newWorkflowName" class="setting-input" placeholder="例如：物品申请审批流程" maxlength="80" :readonly="isCreatingWorkflow" @input="workflowCreateError = ''" />
            <label class="setting-label" for="new-workflow-category">审批分类 <span class="required-mark">*</span></label>
            <select id="new-workflow-category" v-model="newWorkflowCategory" class="setting-input" :disabled="isCreatingWorkflow" @change="workflowCreateError = ''">
              <option value="" disabled>请选择审批分类</option>
              <option v-for="category in workflowCategoryOptions" :key="category" :value="category">{{ category }}</option>
            </select>
            <p class="workflow-create-help">发布后，审批会显示在首页对应分类中。</p>
            <p v-if="workflowCreateError" class="workflow-create-error" role="alert">{{ workflowCreateError }}</p>
          </form>
          <footer><button class="preview-button" :disabled="isCreatingWorkflow" @click="closeWorkflowCreate">取消</button><button class="save-button" type="submit" form="workflow-create-form" :disabled="isCreatingWorkflow"><Plus :size="14" />{{ isCreatingWorkflow ? '创建中…' : '创建' }}</button></footer>
        </template>
      </section>
    </div>
    <div v-if="formCreateOpen" class="modal-backdrop" v-backdrop-dismiss="() => { formCreateOpen = false }">
      <section class="workflow-create-dialog" role="dialog" aria-modal="true" aria-label="新建表单">
        <header><div class="workflow-title-icon"><FileText :size="17" /></div><div><strong>新建表单</strong></div><button class="icon-button" aria-label="关闭" @click="formCreateOpen = false"><X :size="18" /></button></header>
        <label class="setting-label" for="new-form-name">表单名称 <span class="required-mark">*</span></label>
        <input id="new-form-name" v-model="newFormName" class="setting-input" placeholder="输入表单名称" maxlength="80" @keydown.enter="createNewForm" />
        <footer><button class="preview-button" @click="formCreateOpen = false">取消</button><button class="save-button" :disabled="isCreatingForm" @click="createNewForm"><Plus :size="14" /> 创建</button></footer>
      </section>
    </div>
    <div v-if="previewOpen" class="modal-backdrop" v-backdrop-dismiss="() => { previewOpen = false }">
      <section class="preview-modal" role="dialog" aria-modal="true" :aria-label="`${form.name}预览`">
        <header class="preview-header"><div><Eye :size="17" /><strong>表单预览</strong><span>填写人视角</span></div><button class="icon-button" aria-label="关闭预览" @click="previewOpen = false"><X :size="19" /></button></header>
        <div class="preview-body">
          <div class="preview-form-card">
            <div class="preview-form-title">{{ form.name }}</div>
            <label v-if="publishedWorkflowsForForm.length > 1" class="run-workflow-picker"><span>发起流程</span><select v-model="previewWorkflowId" class="setting-input"><option v-for="item in publishedWorkflowsForForm" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
            <div class="preview-form-grid">
              <div v-for="field in form.fields" :key="field.id" :class="['live-field', field.width]">
                <label>{{ field.label }} <span v-if="field.required" class="required-mark">*</span></label>
                <div v-if="field.type === 'description'" class="live-description">{{ previewValue(field) }}</div>
                <textarea v-else-if="field.type === 'textarea'" v-model="previewAnswers[field.id]" :placeholder="field.placeholder" rows="3"></textarea>
                <div v-else-if="field.type === 'radio' || field.type === 'checkbox'" class="live-options">
                  <label v-for="option in field.options" :key="option"><input v-model="previewAnswers[field.id]" :type="field.type === 'radio' ? 'radio' : 'checkbox'" :name="field.id" :value="option" /> {{ option }}</label>
                </div>
                <div v-else-if="field.type === 'rating'" class="rating-preview"><Star v-for="n in 5" :key="n" :size="19" /></div>
                <div v-else-if="field.type === 'image' || field.type === 'attachment'" class="upload-preview live-upload"><component :is="iconMap[field.type]" :size="18" /> 点击上传</div>
                <div v-else-if="field.type === 'dateRange'" class="live-date-range"><input type="date" /><span>至</span><input type="date" /></div>
                <div v-else-if="field.type === 'select' || field.type === 'multiSelect'" class="live-select">
                  <select v-model="previewAnswers[field.id]" :multiple="field.type === 'multiSelect'"><option v-if="field.type === 'select'" value="" disabled>{{ field.placeholder || '请选择' }}</option><option v-for="option in field.options" :key="option" :value="option">{{ option }}</option></select>
                  <ChevronDown :size="15" />
                </div>
                <div v-else-if="field.type === 'member' || field.type === 'department'" class="live-select"><input v-model="previewAnswers[field.id]" :placeholder="field.placeholder" /><Users :size="15" /></div>
                <div v-else>
                  <div class="live-input-wrap">
                    <input v-model="previewAnswers[field.id]" :type="field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'" :step="field.type === 'number' ? 'any' : undefined" :placeholder="field.placeholder" />
                  </div>
                </div>
              </div>
            </div>
            <button class="submit-button" :disabled="isSubmittingWorkflow" @click="submitPreview">{{ isSubmittingWorkflow ? '发起中…' : '提交并发起' }}</button>
          </div>
        </div>
      </section>
    </div>
    <div v-if="workflowRunResult" class="modal-backdrop" v-backdrop-dismiss="() => { workflowRunResult = null }">
      <section class="workflow-create-dialog workflow-run-dialog" role="dialog" aria-modal="true" aria-label="流程发起结果">
        <header><div class="workflow-title-icon"><Check :size="17" /></div><div><strong>流程已发起</strong><span>{{ workflowRunResult.workflowName }} · 第 {{ workflowRunResult.workflowVersion }} 版</span></div><button class="icon-button" aria-label="关闭" @click="workflowRunResult = null"><X :size="18" /></button></header>
        <div class="workflow-run-meta"><span>申请人 <strong>{{ workflowRunResult.applicant }}</strong></span><span>申请单 <strong>{{ workflowRunResult.title }}</strong></span></div>
        <section v-if="workflowRunResult.matchedBranches.length" class="workflow-run-section"><strong>条件分支</strong><div v-for="branch in workflowRunResult.matchedBranches" :key="branch.nodeId" class="workflow-run-branch"><GitFork :size="14" /><span>{{ branch.conditionName }}</span><ChevronRight :size="13" /><b>{{ branch.branchName }}</b></div></section>
        <section class="workflow-run-section"><strong>审批与执行任务</strong><div v-if="!workflowRunResult.tasks.length" class="workflow-run-empty">此流程没有需要处理的审批或执行任务</div><div v-for="task in workflowRunResult.tasks" :key="task.id" :class="['workflow-run-task', task.status]"><span class="workflow-run-task-icon"><component :is="nodeIcons[task.nodeType]" :size="14" /></span><span class="workflow-run-task-copy"><b>{{ task.nodeName }}</b><small>{{ workflowTaskAssigneeText(task) }}<template v-if="task.branchPath.length"> · {{ task.branchPath.join(' / ') }}</template></small></span><span class="workflow-run-task-status">{{ workflowTaskStatusText(task.status) }}</span></div></section>
        <footer><button class="save-button" @click="workflowRunResult = null">完成</button></footer>
      </section>
    </div>
    <Transition name="toast"><div v-if="toast" class="toast-message"><Check :size="16" />{{ toast }}</div></Transition>
  </div>
</template>

<style>
.editor-toolbar{grid-template-columns:minmax(0,1fr) auto}
.toolbar-right{grid-column:2}
</style>
