<script setup lang="ts">
import ResizableDetailDrawer from './ResizableDetailDrawer.vue'
import CenteredApprovalDialog from './CenteredApprovalDialog.vue'
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import { ArrowDownToLine, ArrowLeft, ArrowUpDown, Check, ChevronDown, ChevronLeft, ChevronRight, Columns3, FileText, GitFork, Pencil, Plus, RefreshCw, RotateCcw, Search, ShieldCheck, Table2, Trash2, UsersRound, X } from '@lucide/vue'
import CategorySupervisorSettings from './CategorySupervisorSettings.vue'
import WorkflowPersonnel from './WorkflowPersonnel.vue'
import PermissionSettings from './PermissionSettings.vue'
import { changeWorkflowCategoryStatus, changeWorkflowStatus, listApprovalRecords, listFormRecords, listForms, listWorkflowAudit, listWorkflows, renameWorkflow } from './api'
import type { ApprovalRecord, ApprovalWorkspaceTarget, AuthUser, FormRecord, FormSchema, WorkflowCategoryDefinition, WorkflowNode, WorkflowSchema } from './types'
import { categoryLabel, DEFAULT_WORKFLOW_CATEGORIES, recycledCategories, refreshWorkflowCategories, updateWorkflowCategory, workflowCategory, workflowCategoryDefinitions } from './workflow-categories'
import './approval-workspace.css'
import './oa-workspace.css'

type WorkflowAction = 'disable' | 'enable' | 'delete' | 'restore'
type PublishedItem = { workflow: WorkflowSchema; form: FormSchema }
type Entry = { key: string; kind: 'workflow' | 'form'; name: string; formId: string; workflowId?: string; category: string; published: boolean; disabled: boolean; deleted: boolean; startItem?: PublishedItem }
type FlowStatus = 'enabled' | 'draft' | 'disabled'
const flowStatuses = { enabled: '启用', draft: '草稿', disabled: '停用' }
type Row = { id: string; title: string; applicant: string; category: string; stage: string; createdAt: string; canHandle: boolean; approval: boolean }
const props = defineProps<{ user: AuthUser; items: PublishedItem[]; directory: AuthUser[]; settingsMode?: boolean }>()
const emit = defineEmits<{ start: [item: PublishedItem]; detail: [id: string]; handle: [id: string]; configure: [target: ApprovalWorkspaceTarget]; changed: [workflow: WorkflowSchema] }>()
const isAdmin = computed(() => props.user.canManagePermissions === true)
const managedCategories = computed(() => new Set(props.user.managedCategories ?? []))
const canManage = computed(() => isAdmin.value || managedCategories.value.size > 0)
function canManageCategory(key: string) { return isAdmin.value || managedCategories.value.has(key) }
function canManageWorkflow(workflow: WorkflowSchema) {
  return canManageCategory(workflow.category || '常用流程') && (!workflow.publishedSnapshot || canManageCategory(workflowCategory(workflow)))
}
const workflows = ref<WorkflowSchema[]>([]), forms = ref<FormSchema[]>([]), records = ref<ApprovalRecord[]>([])
const formRecords = ref<FormRecord[]>([])
const selected = ref(''), navigationSearch = ref(''), search = ref('')
const emptyFilters = () => ({ title: '', applicant: '', category: '', stage: '', createdAt: '', id: '' })
const columnFilters = ref(emptyFilters())
function selectEntry(key: string) { selected.value = key }
const loading = ref(false), formLoading = ref(false), error = ref(''), notice = ref('')
const columnsOpen = ref(false)
const managing = ref(false)
const selectedCategory = ref('全部流程')
const collapsedCategories = ref<string[]>([])
const toolsPanel = ref<'audit' | ''>('')
const settingsTab = ref<'permissions' | 'people'>('permissions')
const permissionsPage = ref<InstanceType<typeof PermissionSettings> | null>(null)
const personnelPanel = ref<InstanceType<typeof WorkflowPersonnel> | null>(null)
const auditRecords = ref<Awaited<ReturnType<typeof listWorkflowAudit>>>([])
const auditLoading = ref(false), auditError = ref('')
const auditLabels: Record<string, string> = {
  create_approval: '新建流程', create_workflow: '新建流程', put_workflow: '保存流程', publish_workflow: '发布流程',
  disable_workflow: '停用流程', enable_workflow: '启用流程', delete_workflow: '删除流程', restore_workflow: '恢复流程',
  'category_supervisors.save': '设置分类主管',
  'workflow_category.save': '保存流程设置', 'workflow_personnel.replace': '替换审批草稿节点人员',
  'workflow_category.delete': '删除分组', 'workflow_category.restore': '恢复分组', rename_workflow: '修改流程名称',
  'workflow_personnel.update': '更新审批节点人员',
}
const settingsCategory = ref<string | null>(null)
const settingsApprovalCount = computed(() => workflows.value.filter(workflow => !workflow.deletedAt &&
  workflowCategory(workflow) === settingsCategory.value).length)
const recycledWorkflows = ref<WorkflowSchema[]>([])
const recycleMode = computed(() => isAdmin.value && selected.value === 'recycle')
const statusBusy = ref(false), statusError = ref('')
const categoryBusy = ref(false)
const renameTarget = ref<{ id: string; name: string; updatedAt: string } | null>(null)
const renameBusy = ref(false), renameError = ref('')
const renameInput = 'oa-flow-name'
const statusTarget = ref<{ id: string; name: string; action: WorkflowAction } | null>(null)
const centeredStatus = computed(() => statusTarget.value?.action === 'delete' || statusTarget.value?.action === 'disable')
const actionNames = { disable: '停用', enable: '启用', delete: '移入回收站', restore: '恢复' }
const statusTitle = computed(() => statusTarget.value ? statusTarget.value.action === 'delete' ? '删除审批流程' : actionNames[statusTarget.value.action] + '审批流程' : '')
const columnAnchor = ref<HTMLElement | null>(null)
const selectedIds = ref<string[]>([]), page = ref(1), pageSize = ref(20)
const sortBy = ref<'title' | 'applicant' | 'createdAt'>('createdAt'), direction = ref<'asc' | 'desc'>('desc')
const visibleColumns = ref(['category', 'stage', 'createdAt', 'id'])
const optionalColumns = [{ key: 'category', name: '流程分类' }, { key: 'stage', name: '流程状态' }, { key: 'createdAt', name: '创建时间' }, { key: 'id', name: '实例ID' }]
const statuses: Record<string, string> = { approving: '待审批', executing: '执行中', pending_assignment: '待分配', returned: '已退回', completed: '已完成', rejected: '已拒绝', recalled: '已撤回' }
const entries = computed<Entry[]>(() => {
  const available = [...workflows.value, ...recycledWorkflows.value]
  const bound = new Set<string>()
  const result: Entry[] = available.map(workflow => {
    const published = workflow.publishedSnapshot
    const formId = workflow.nodes.find(node => node.type === 'start')?.formId || published?.formId || ''
    if (formId) bound.add(formId)
    if (published?.formId) bound.add(published.formId)
    const startItem = !workflow.disabledAt && !workflow.deletedAt ? props.items.find(item => item.workflow.id === workflow.id) : undefined
    const name = published
      ? published.formSchema?.name || published.name || startItem?.form.name || workflow.name
      : forms.value.find(form => form.id === formId)?.name || workflow.name
    return { key: 'workflow:' + workflow.id, kind: 'workflow', name, formId, workflowId: workflow.id, category: workflowCategory(workflow), published: Boolean(published), disabled: Boolean(workflow.disabledAt), deleted: Boolean(workflow.deletedAt), startItem }
  })
  if (isAdmin.value) for (const form of forms.value) {
    if (!bound.has(form.id)) result.push({ key: 'form:' + form.id, kind: 'form', name: form.name, formId: form.id, category: '独立表单', published: false, disabled: false, deleted: false })
  }
  return result
})
const categoryGroups = computed(() => {
  const query = navigationSearch.value.trim().toLowerCase()
  const workflowEntries = entries.value.filter(entry => entry.kind === 'workflow' && !entry.deleted &&
    (managing.value ? Boolean(entry.workflowId && workflowById.value.get(entry.workflowId) && canManageWorkflow(workflowById.value.get(entry.workflowId)!)) : entry.startItem))
  const categories = [...new Set<string>([...DEFAULT_WORKFLOW_CATEGORIES, ...workflowCategoryDefinitions.value.map(item => item.key), ...workflowEntries.map(entry => entry.category)])]
    .filter(category => !recycledCategories.value.has(category) && (!managing.value || canManageCategory(category)))
  const groups = categories.map(category => ({
    key: category, name: categoryLabel(category), kind: 'workflow' as Entry['kind'],
    entries: workflowEntries.filter(entry => entry.category === category && (!query || categoryLabel(category).toLowerCase().includes(query) || entry.name.toLowerCase().includes(query))),
  }))
  const standalone = managing.value ? entries.value.filter(entry => entry.kind === 'form') : []
  if (standalone.length) groups.push({ key: '独立表单', name: '独立表单', kind: 'form', entries: standalone.filter(entry => !query || entry.name.toLowerCase().includes(query) || '独立表单'.includes(query)) })
  return managing.value ? groups : groups.filter(group => !query || group.name.toLowerCase().includes(query) || group.entries.length > 0)
})
function firstManagedCategory() { return categoryGroups.value.find(group => group.kind === 'workflow')?.key || categoryGroups.value[0]?.key || '' }
function selectCategory(key: string) {
  if (!closeRename()) return
  selectedCategory.value = key
}
function toggleManagement() {
  if (!closeRename()) return
  managing.value = !managing.value
  navigationSearch.value = ''
  selectedCategory.value = managing.value ? firstManagedCategory() : '全部流程'
}
watch(categoryGroups, groups => {
  if (managing.value && !groups.some(group => group.key === selectedCategory.value)) selectedCategory.value = firstManagedCategory()
})
const shownGroups = computed(() => categoryGroups.value.filter(group => selectedCategory.value === '全部流程'
  ? !managing.value && group.entries.length > 0 : group.key === selectedCategory.value))
function flowStatus(entry: Entry): FlowStatus { return entry.disabled ? 'disabled' : entry.published ? 'enabled' : 'draft' }
function statusSections(groupEntries: Entry[]) {
  return managing.value
    ? (Object.keys(flowStatuses) as FlowStatus[]).map(key => ({ key, name: flowStatuses[key], entries: groupEntries.filter(entry => flowStatus(entry) === key) }))
    : [{ key: 'browse', name: '', entries: groupEntries }]
}
function categoryExpanded(key: string) { return Boolean(navigationSearch.value.trim()) || !collapsedCategories.value.includes(key) }
function toggleCategory(key: string) {
  if (navigationSearch.value.trim()) return
  collapsedCategories.value = collapsedCategories.value.includes(key) ? collapsedCategories.value.filter(value => value !== key) : [...collapsedCategories.value, key]
}
const workflowById = computed(() => new Map(workflows.value.map(workflow => [workflow.id, workflow])))
const directoryById = computed(() => new Map(props.directory.map(person => [person.username, person.displayName])))
function personName(id: string) { return directoryById.value.get(id) || id }
const personnelReferences = computed(() => {
  const references = new Map<string, { key: string; workflowId: string; workflowName: string; nodeName: string; person: string }>()
  function visit(workflow: WorkflowSchema, nodes: WorkflowNode[]) {
    for (const node of nodes) {
      for (const person of node.assignees ?? []) {
        const key = [workflow.id, node.id, person].join(':')
        references.set(key, { key, workflowId: workflow.id, workflowName: workflow.name, nodeName: node.name, person })
      }
      for (const branch of node.branches ?? []) visit(workflow, branch.nodes)
    }
  }
  for (const workflow of workflows.value) {
    visit(workflow, workflow.nodes)
    if (workflow.publishedSnapshot) visit(workflow, workflow.publishedSnapshot.nodes)
  }
  return [...references.values()]
})
const flaggedWorkflows = computed(() => new Set(personnelReferences.value.filter(item => props.directory.length && !directoryById.value.has(item.person)).map(item => item.workflowId)))
function hasDraft(entry: Entry) {
  const workflow = entry.workflowId && workflowById.value.get(entry.workflowId)
  if (!workflow || !workflow.publishedSnapshot) return false
  const snapshot = workflow.publishedSnapshot
  const linkedForm = forms.value.find(form => form.id === entry.formId)
  return Boolean(workflow.draftSavedAt || (linkedForm?.updatedAt && snapshot.formSchema?.updatedAt &&
    linkedForm.updatedAt !== snapshot.formSchema.updatedAt))
    || workflow.name !== snapshot.name || (workflow.category || '常用流程') !== (snapshot.category || '常用流程')
    || JSON.stringify(workflow.nodes) !== JSON.stringify(snapshot.nodes)
    || JSON.stringify(workflow.applicantFieldPermissions ?? []) !== JSON.stringify(snapshot.applicantFieldPermissions ?? [])
}
async function openAudit() {
  toolsPanel.value = 'audit'
  auditLoading.value = true; auditError.value = ''
  try { auditRecords.value = await listWorkflowAudit() }
  catch (cause) { auditError.value = cause instanceof Error ? cause.message : '无法读取流程操作记录' }
  finally { auditLoading.value = false }
}
const current = computed(() => entries.value.find(entry => entry.key === selected.value))
const title = computed(() => recycleMode.value ? '流程回收站' : current.value?.name || '页面管理')
const recordTitleLabel = computed(() => current.value?.kind === 'form' ? '实例标题' : '标题')
const currentRows = computed<Row[]>(() => {
  const entry = current.value
  if (!entry) return []
  if (entry.kind === 'form') return formRecords.value.map(record => ({ ...record, category: '独立表单', stage: '', canHandle: false, approval: false }))
  return records.value.filter(record => record.workflowId === entry.workflowId)
    .map(record => ({ ...record, approval: true }))
})
const hasFilters = computed(() => Object.values(columnFilters.value).some(value => value.trim()))
function localDate(value: string) {
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-') : ''
}
function clearFilters() { columnFilters.value = emptyFilters() }
const filtered = computed(() => {
  const filters = columnFilters.value
  const contains = (value: string, query: string) => value.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  return currentRows.value.filter(record => contains(record.title, filters.title)
    && contains(record.applicant, filters.applicant) && contains(record.category, filters.category)
    && (!filters.stage || record.stage === filters.stage)
    && (!filters.createdAt || localDate(record.createdAt) === filters.createdAt)
    && contains(record.id, filters.id))
    .sort((left, right) => left[sortBy.value].localeCompare(right[sortBy.value], 'zh-CN', { numeric: true }) * (direction.value === 'asc' ? 1 : -1))
})
const recycleFiltered = computed(() => {
  const query = search.value.trim().toLowerCase()
  const approvals = recycledWorkflows.value.map(workflow => ({
    kind: 'approval' as const, key: 'approval:' + workflow.id, workflow,
    name: entries.value.find(entry => entry.workflowId === workflow.id)?.name || workflow.name,
    category: categoryLabel(workflowCategory(workflow)), deletedAt: workflow.deletedAt || '',
  }))
  const categories = [...recycledCategories.value].map(([categoryKey, deletedAt]) => ({
    kind: 'category' as const, key: 'category:' + categoryKey, categoryKey,
    name: categoryLabel(categoryKey), category: '流程分类', deletedAt,
  }))
  return [...categories, ...approvals]
    .filter(row => !query || [row.name, row.category].some(value => value.toLowerCase().includes(query)))
    .sort((left, right) => right.deletedAt.localeCompare(left.deletedAt))
})
const recycleRows = computed(() => recycleFiltered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const pageCount = computed(() => Math.max(1, Math.ceil((recycleMode.value ? recycleFiltered.value.length : filtered.value.length) / pageSize.value)))
const rows = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const allSelected = computed(() => rows.value.length > 0 && rows.value.every(row => selectedIds.value.includes(row.id)))
const busy = computed(() => loading.value || formLoading.value || statusBusy.value || renameBusy.value || categoryBusy.value)
let formRequest = 0, noticeTimer: ReturnType<typeof setTimeout> | undefined
function showNotice(message: string) {
  notice.value = message
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { notice.value = '' }, 2400)
}
async function refresh() {
  if (loading.value) return
  loading.value = true; error.value = ''
  try {
    void refreshWorkflowCategories().catch(() => {})
    const [summaries, formList, workflowList, recycleList] = await Promise.all([listApprovalRecords(), canManage.value ? listForms() : Promise.resolve([]), listWorkflows(), isAdmin.value ? listWorkflows(true) : Promise.resolve([])])
    records.value = isAdmin.value ? summaries : summaries.filter(record => record.mine); forms.value = formList; workflows.value = workflowList; recycledWorkflows.value = recycleList
    if (!recycleMode.value && selected.value && !entries.value.some(entry => entry.key === selected.value)) selected.value = ''
    if (current.value?.kind === 'form') await refreshForm(current.value.formId)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '页面加载失败，请重试' }
  finally { loading.value = false }
}
async function refreshForm(id: string) {
  const request = ++formRequest
  formLoading.value = true
  try { const data = await listFormRecords(id); if (request === formRequest) formRecords.value = data }
  catch (cause) { if (request === formRequest) error.value = cause instanceof Error ? cause.message : '表单记录读取失败' }
  finally { if (request === formRequest) formLoading.value = false }
}
function configure(page: ApprovalWorkspaceTarget['page'], entry = current.value) {
  if (!canManage.value) return
  selected.value = ''
  emit('configure', { page, formId: entry?.formId || undefined, workflowId: entry?.workflowId })
}
function editEntry(entry: Entry) { configure(entry.formId ? '表单设计' : '流程设计', entry) }
function openEntry(entry: Entry) {
  if (managing.value) editEntry(entry)
  else if (entry.startItem) emit('start', entry.startItem)
}
function onPersonnelChanged(workflow: WorkflowSchema) {
  emit('changed', workflow)
  void refresh()
}
function onCategorySaved(item: WorkflowCategoryDefinition) {
  settingsCategory.value = null
  updateWorkflowCategory(item)
  selectedCategory.value = item.key
  navigationSearch.value = ''
  collapsedCategories.value = collapsedCategories.value.filter(key => key !== item.key)
}
function onCategoryDeleted(item: WorkflowCategoryDefinition) {
  updateWorkflowCategory(item)
  settingsCategory.value = null
  showNotice(`「${item.name}」已移入回收站。`)
}
async function restoreCategory(category: string) {
  if (categoryBusy.value) return
  categoryBusy.value = true
  error.value = ''
  try {
    const item = await changeWorkflowCategoryStatus(category, 'restore')
    updateWorkflowCategory(item)
    showNotice(`「${item.name}」已恢复。`)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '恢复分组失败' }
  finally { categoryBusy.value = false }
}
function openApprovalCreate(category: string) {
  if (canManageCategory(category)) emit('configure', { page: '表单设计', newCategory: category })
}
function closeRename() {
  if (renameBusy.value) return false
  renameTarget.value = null
  renameError.value = ''
  return true
}
async function openRename(entry: Entry) {
  const workflow = entry.workflowId && workflowById.value.get(entry.workflowId)
  if (!workflow || !canManageWorkflow(workflow) || !closeRename()) return
  renameTarget.value = { id: workflow.id, name: entry.name, updatedAt: workflow.updatedAt || '' }
  await nextTick()
  const input = document.getElementById(renameInput) as HTMLInputElement | null
  input?.focus()
  input?.select()
}
async function saveRename() {
  const target = renameTarget.value
  if (!target?.name.trim() || renameBusy.value) return
  renameBusy.value = true
  renameError.value = ''
  try {
    const saved = await renameWorkflow(target.id, target.name.trim(), target.updatedAt)
    workflows.value = workflows.value.map(workflow => workflow.id === saved.workflow.id ? saved.workflow : workflow)
    forms.value = [...forms.value.filter(form => !saved.forms.some(item => item.id === form.id)), ...saved.forms]
    renameTarget.value = null
    showNotice('流程名称已保存。')
    emit('changed', saved.workflow)
  } catch (cause) { renameError.value = cause instanceof Error ? cause.message : '流程名称保存失败' }
  finally { renameBusy.value = false }
}
function requestStatus(action: WorkflowAction, workflow?: WorkflowSchema) {
  if (!canManage.value || busy.value) return
  const target = workflow || [...workflows.value, ...recycledWorkflows.value].find(item => item.id === current.value?.workflowId)
  if (!target || !canManageWorkflow(target) || (action === 'restore' ? !isAdmin.value || !target.deletedAt : target.deletedAt)) return
  statusError.value = ''
  statusTarget.value = { id: target.id, name: target.name, action }
}
function closeStatus() { if (!statusBusy.value) { statusTarget.value = null; statusError.value = '' } }
async function confirmStatus() {
  const target = statusTarget.value
  if (!target || !canManage.value || statusBusy.value) return
  statusBusy.value = true; statusError.value = ''
  try {
    const updated = await changeWorkflowStatus(target.id, target.action)
    workflows.value = workflows.value.filter(item => item.id !== updated.id)
    recycledWorkflows.value = recycledWorkflows.value.filter(item => item.id !== updated.id)
    if (updated.deletedAt) recycledWorkflows.value.unshift(updated)
    else workflows.value.unshift(updated)
    statusTarget.value = null
    if (target.action === 'delete' && current.value?.workflowId === target.id) selected.value = ''
    showNotice(`流程“${target.name}”已${actionNames[target.action]}`)
    emit('changed', updated)
  } catch (cause) { statusError.value = cause instanceof Error ? cause.message : '操作失败，请重试' }
  finally { statusBusy.value = false }
}
function showError(message: string) { error.value = message }
function sort(key: typeof sortBy.value) { direction.value = sortBy.value === key && direction.value === 'asc' ? 'desc' : 'asc'; sortBy.value = key }
function selectRow(id: string) { selectedIds.value = selectedIds.value.includes(id) ? selectedIds.value.filter(value => value !== id) : [...selectedIds.value, id] }
function selectPage() { const ids = rows.value.map(row => row.id); selectedIds.value = allSelected.value ? selectedIds.value.filter(id => !ids.includes(id)) : [...new Set([...selectedIds.value, ...ids])] }
function toggleColumn(key: string) { if (key in columnFilters.value) columnFilters.value[key as keyof ReturnType<typeof emptyFilters>] = ''; visibleColumns.value = visibleColumns.value.includes(key) ? visibleColumns.value.filter(value => value !== key) : [...visibleColumns.value, key] }
function date(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
function exportRows() {
  const data = selectedIds.value.length ? filtered.value.filter(row => selectedIds.value.includes(row.id)) : filtered.value
  const escape = (value: string) => '"' + (/^[=+\-@\t\r\n]/.test(value) ? "'" + value : value).replaceAll('"', '""') + '"'
  const lines = [[recordTitleLabel.value, '提交人', '流程分类', '流程状态', '创建时间', '实例ID'], ...data.map(row => [row.title, row.applicant, row.category, statuses[row.stage] || '—', date(row.createdAt), row.id])]
  const url = URL.createObjectURL(new Blob(['\uFEFF' + lines.map(line => line.map(escape).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = title.value.replace(/[<>:"/\\|?*]/g, '_') + '-审批记录.csv'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  showNotice(`已导出 ${data.length} 条记录`)
}
function closeMenus(event: PointerEvent) { if (event.target instanceof Node && !columnAnchor.value?.contains(event.target)) columnsOpen.value = false }
function onKey(event: KeyboardEvent) { if (event.key === 'Escape') { columnsOpen.value = false; closeStatus() } }
// Desktop drag scroll skips controls and suppresses clicks only after a real drag.
let drag: { id: number; x: number; scroll: number; active: boolean } | null = null, suppressClickUntil = 0
function dragStart(event: PointerEvent) {
  const target = event.target as HTMLElement, container = event.currentTarget as HTMLElement
  if (event.pointerType !== 'mouse' || event.button !== 0 || target.closest('button,input,select,a,label,[contenteditable]') || container.scrollWidth <= container.clientWidth) return
  drag = { id: event.pointerId, x: event.clientX, scroll: container.scrollLeft, active: false }
}
function dragMove(event: PointerEvent) {
  if (!drag || drag.id !== event.pointerId) return
  const container = event.currentTarget as HTMLElement, offset = event.clientX - drag.x
  if (!drag.active && Math.abs(offset) < 6) return
  if (!drag.active) { drag.active = true; container.setPointerCapture(event.pointerId); container.classList.add('dragging') }
  event.preventDefault(); container.scrollLeft = drag.scroll - offset
}
function dragEnd(event: PointerEvent) {
  if (!drag || drag.id !== event.pointerId) return
  const container = event.currentTarget as HTMLElement
  if (drag.active) { suppressClickUntil = Date.now() + 200; if (container.hasPointerCapture(event.pointerId)) container.releasePointerCapture(event.pointerId) }
  drag = null; container.classList.remove('dragging')
}
function captureClick(event: MouseEvent) { if (Date.now() < suppressClickUntil) { event.preventDefault(); event.stopPropagation() } }
watch(selected, () => { search.value = ''; clearFilters(); selectedIds.value = []; error.value = ''; formRecords.value = []; ++formRequest; formLoading.value = false; if (current.value?.kind === 'form') void refreshForm(current.value.formId) })
watch([selected, search, columnFilters, pageSize], () => { page.value = 1; selectedIds.value = [] }, { deep: true })
watch(pageCount, count => { page.value = Math.min(page.value, count) })
onActivated(() => { void refresh(); document.addEventListener('pointerdown', closeMenus); document.addEventListener('keydown', onKey) })
onDeactivated(() => { document.removeEventListener('pointerdown', closeMenus); document.removeEventListener('keydown', onKey) })
onBeforeUnmount(() => { ++formRequest; if (noticeTimer) clearTimeout(noticeTimer) })
function canLeave() {
  return closeRename() && personnelPanel.value?.canLeave() !== false && permissionsPage.value?.canLeave() !== false
}
function selectSettingsTab(next: typeof settingsTab.value) {
  if (next !== settingsTab.value && canLeave()) settingsTab.value = next
}
defineExpose({ refresh, showError, canLeave })
</script>

<template>
  <main class="approval-workspace" :aria-label="settingsMode ? '审批设置' : '审批页面管理'">
    <div v-if="settingsMode" class="oa-center oa-settings-center">
      <template v-if="isAdmin">
        <nav class="oa-settings-tabs" aria-label="设置分类">
          <button type="button" class="aw-button" :aria-pressed="settingsTab === 'permissions'" @click="selectSettingsTab('permissions')"><ShieldCheck :size="16" />权限设置</button>
          <button type="button" class="aw-button" :aria-pressed="settingsTab === 'people'" @click="selectSettingsTab('people')"><UsersRound :size="16" />人员排查</button>
        </nav>
        <PermissionSettings v-if="settingsTab === 'permissions'" ref="permissionsPage" />
        <WorkflowPersonnel v-else ref="personnelPanel" @changed="onPersonnelChanged" />
      </template>
      <p v-else class="oa-settings-restricted">权限设置和人员排查由审批应用的总管理员管理。</p>
    </div>
    <div v-else class="oa-center">
      <div class="oa-toolbar">
        <label class="aw-search oa-search"><Search :size="16" /><input v-model="navigationSearch" aria-label="搜索审批流程" placeholder="请输入审批名称" /></label>
        <div class="oa-actions">
          <button v-if="canManage" type="button" :class="managing ? 'aw-primary' : 'aw-button'" :aria-pressed="managing" @click="toggleManagement">{{ managing ? '完成管理' : '管理审批表单' }}</button>
        </div>
      </div>
      <div class="oa-groupbar">
        <nav class="oa-category-tabs" aria-label="流程分类">
          <button v-if="!managing" type="button" :aria-pressed="selectedCategory === '全部流程'" @click="selectCategory('全部流程')">全部流程</button>
          <button v-for="group in categoryGroups" :key="group.key" type="button" :aria-pressed="selectedCategory === group.key" @click="selectCategory(group.key)">{{ group.name }}</button>
        </nav>
        <div v-if="managing && isAdmin" class="oa-actions oa-group-tools">
          <button type="button" class="aw-record-link" :disabled="!shownGroups.some(group => group.kind === 'workflow')" @click="settingsCategory = selectedCategory">分组管理</button>
          <button type="button" class="aw-record-link" @click="selectEntry('recycle')">回收站</button>
          <button type="button" class="aw-record-link" @click="openAudit">操作记录</button>
          <button type="button" class="aw-primary" @click="settingsCategory = ''"><Plus :size="15" />新建分组</button>
        </div>
      </div>
      <p v-if="error" class="aw-error" role="alert">{{ error }}<button :disabled="loading" @click="refresh">重试</button></p>
      <div class="oa-groups" :class="{ 'oa-groups-managing': managing }">
        <section v-for="group in shownGroups" :key="group.key" class="oa-group">
          <header>
            <div>
              <h2>{{ group.name }}</h2>
              <p v-if="managing" class="oa-group-count">{{ group.entries.length }} 项流程</p>
            </div>
            <button v-if="managing && group.kind === 'workflow'" type="button" class="aw-button" @click="openApprovalCreate(group.key)"><Plus :size="14" />新建流程</button>
            <button v-if="!managing" type="button" class="aw-text-button oa-collapse" :aria-label="(categoryExpanded(group.key) ? '收起' : '展开') + group.name" :aria-expanded="categoryExpanded(group.key)" :disabled="Boolean(navigationSearch.trim())" @click="toggleCategory(group.key)"><ChevronDown :size="15" /></button>
          </header>
          <component :is="managing ? 'details' : 'div'" v-for="section in statusSections(group.entries)" :key="section.key" :open="managing ? true : undefined" :class="{ 'oa-status-section': managing }">
            <summary v-if="managing" class="oa-status-summary">
              <span class="oa-status-dot" :class="section.key" aria-hidden="true"></span>
              <strong>{{ section.name }}</strong><span class="oa-status-count">{{ section.entries.length }}</span><ChevronDown :size="15" />
            </summary>
            <div v-show="managing || categoryExpanded(group.key)" class="oa-card-grid">
              <article v-for="entry in section.entries" :key="entry.key" class="oa-card">
                <form v-if="renameTarget && renameTarget.id === entry.workflowId" class="oa-rename-form" @submit.prevent="saveRename" @keydown.esc.stop.prevent="closeRename">
                  <input :id="renameInput" v-model="renameTarget.name" aria-label="流程名称" maxlength="80" required :disabled="renameBusy" />
                  <div class="oa-actions">
                    <button type="button" class="aw-record-link" :disabled="renameBusy" @click="closeRename">取消</button>
                    <button type="submit" class="aw-record-link" :disabled="renameBusy || !renameTarget.name.trim()">保存</button>
                  </div>
                  <p v-if="renameError" class="aw-error" role="alert">{{ renameError }}</p>
                </form>
                <div v-else class="oa-card-title-row">
                  <button type="button" class="oa-card-open" @click="openEntry(entry)"><span class="oa-card-icon"><component :is="entry.kind === 'workflow' ? FileText : Table2" :size="19" /></span><b>{{ entry.name }}</b></button>
                  <button v-if="managing && entry.workflowId" type="button" class="aw-text-button oa-rename-button" :aria-label="'修改流程名称 ' + entry.name" title="修改流程名称" :disabled="busy" @click="openRename(entry)"><Pencil :size="15" /></button>
                </div>
              <template v-if="managing">
                <div class="oa-card-status">
                  <span :class="['aw-publish-state', 'oa-flow-' + flowStatus(entry), { published: entry.published && !entry.disabled, disabled: entry.disabled }]">{{ flowStatuses[flowStatus(entry)] }}</span>
                  <small v-if="entry.workflowId && workflowById.get(entry.workflowId)?.publishedVersion">v{{ workflowById.get(entry.workflowId)?.publishedVersion }}</small>
                  <small v-if="hasDraft(entry)" class="oa-draft">有草稿</small>
                  <small v-if="entry.workflowId && flaggedWorkflows.has(entry.workflowId)" class="oa-warning">成员不在目录</small>
                </div>
                <div class="oa-card-actions">
                  <button type="button" class="aw-record-link" @click="editEntry(entry)">编辑</button>
                  <button v-if="isAdmin" type="button" class="aw-record-link" @click="selectEntry(entry.key)">记录</button>
                  <template v-if="entry.workflowId">
                    <button v-if="entry.published" type="button" class="aw-record-link" :disabled="busy" @click="requestStatus(entry.disabled ? 'enable' : 'disable', workflowById.get(entry.workflowId))">{{ entry.disabled ? '启用' : '停用' }}</button>
                    <button type="button" class="aw-record-link oa-delete" :disabled="busy" @click="requestStatus('delete', workflowById.get(entry.workflowId))">删除</button>
                  </template>
                </div>
              </template>
              </article>
              <p v-if="!section.entries.length" class="oa-empty">{{ loading ? '正在加载流程…' : managing ? '暂无' + section.name + '流程' : '暂无审批' }}</p>
            </div>
          </component>
        </section>
        <p v-if="!shownGroups.length" class="oa-empty">{{ loading ? '正在加载审批…' : '暂无匹配的审批' }}</p>
      </div>
    </div>
    <ResizableDetailDrawer v-if="toolsPanel === 'audit'" :open="true" @close="toolsPanel = ''">
      <section class="employee-dialog oa-tool-panel" aria-label="流程操作记录" @click.stop>
        <header><span class="employee-dialog-heading"><b>操作记录</b></span><button class="employee-close" aria-label="关闭管理工具" @click="toolsPanel = ''"><X :size="18" /></button></header>
        <div class="employee-dialog-body">
          <p v-if="auditLoading">正在加载操作记录…</p>
          <p v-else-if="auditError" class="aw-error" role="alert">{{ auditError }}<button @click="openAudit">重试</button></p>
          <p v-else-if="!auditRecords.length" class="oa-empty">暂无流程操作记录</p>
          <div v-for="event in auditRecords" :key="event.id" class="oa-tool-row"><span><b>{{ auditLabels[event.action] }}</b><small>{{ personName(event.actorId) }}<template v-if="event.actorId !== event.effectiveUserId"> · 代理 {{ personName(event.effectiveUserId) }}</template></small></span><time :datetime="event.createdAt">{{ date(event.createdAt) }}</time></div>
        </div>
      </section>
    </ResizableDetailDrawer>
    <ResizableDetailDrawer v-if="selected" :open="true" @close="selectEntry('')">
      <section class="aw-content" :class="{ 'aw-recycle-content': recycleMode }">
        <header class="aw-page-heading">
          <div><h1>{{ title }}</h1><span v-if="current" :class="['aw-publish-state', { published: current.published && !current.disabled && !current.deleted, disabled: current.disabled, deleted: current.deleted }]">{{ current.deleted ? '回收站' : current.disabled ? '已停用' : current.published ? '已发布' : '草稿' }}</span></div>
          <div class="aw-page-actions">
            <button class="aw-text-button" aria-label="关闭详情" @click="selectEntry('')"><X :size="17" /></button>
            <button v-if="isAdmin && current?.deleted" class="aw-text-button" @click="selectEntry('recycle')"><ArrowLeft :size="15" />返回回收站</button>
            <button v-if="isAdmin && current?.workflowId && current.deleted" class="aw-primary" :disabled="busy" @click="requestStatus('restore')"><RotateCcw :size="15" />恢复流程</button>
          </div>
        </header>
        <p v-if="current?.disabled || current?.deleted" class="aw-lifecycle-hint">{{ current.deleted ? '此流程已移入回收站，可查询历史记录或恢复流程。' : '此流程已停用，不能发起新申请。' }}已有审批可继续处理。</p>
        <p v-if="error" class="aw-error" role="alert">{{ error }}<button :disabled="loading" @click="refresh">重试</button></p>
        <section v-if="recycleMode" class="aw-records aw-recycle-records" aria-label="流程回收站列表" :aria-busy="busy">
          <div class="aw-viewbar"><span class="active"><Trash2 :size="15" />已删除流程</span></div>
          <p class="aw-recycle-description">删除的流程和分组可从这里恢复。</p>
          <div class="aw-toolbar"><label class="aw-search"><Search :size="14" /><input v-model="search" aria-label="搜索回收站流程" placeholder="搜索流程名称或分类" /></label><button class="aw-text-button" aria-label="刷新流程回收站" :disabled="busy" @click="refresh"><RefreshCw :size="16" />刷新</button></div>
          <div class="aw-table-scroll" tabindex="0" role="region" aria-label="回收站表格"
            @pointerdown="dragStart" @pointermove="dragMove" @pointerup="dragEnd" @pointercancel="dragEnd"
            @pointerleave="event => { if (drag && !drag.active) dragEnd(event) }" @click.capture="captureClick">
            <table class="aw-table aw-recycle-table"><thead><tr><th>流程名称</th><th>流程分类</th><th>删除前状态</th><th>删除时间</th><th>操作</th></tr></thead><tbody>
              <tr v-for="row in recycleRows" :key="row.key" :data-recycled-workflow="row.kind === 'approval' ? row.workflow.id : undefined">
                <template v-if="row.kind === 'category'">
                  <td>{{ row.name }}</td><td>{{ row.category }}</td><td><span class="aw-status">分组</span></td><td>{{ date(row.deletedAt) }}</td>
                  <td><div class="aw-row-actions"><button class="aw-record-link" :aria-label="'恢复分组' + row.name" :disabled="busy" @click="restoreCategory(row.categoryKey)"><RotateCcw :size="13" />恢复</button></div></td>
                </template>
                <template v-else>
                  <td><button class="aw-record-link" @click="selectEntry('workflow:' + row.workflow.id)">{{ row.name }}</button></td><td>{{ row.category }}</td><td><span :class="['aw-status', { pending_assignment: row.workflow.disabledAt, completed: !row.workflow.disabledAt && row.workflow.publishedSnapshot }]">{{ row.workflow.disabledAt ? '已停用' : row.workflow.publishedSnapshot ? '已发布' : '草稿' }}</span></td><td>{{ date(row.deletedAt) }}</td>
                  <td><div class="aw-row-actions"><button class="aw-record-link" @click="selectEntry('workflow:' + row.workflow.id)">查看记录</button><button class="aw-record-link" :aria-label="'恢复流程' + row.name" :disabled="busy" @click="requestStatus('restore', row.workflow)"><RotateCcw :size="13" />恢复</button></div></td>
                </template>
              </tr>
              <tr v-if="!recycleRows.length"><td colspan="5" class="aw-empty"><Trash2 :size="28" /><strong>{{ busy ? '正在加载流程…' : error ? '回收站加载失败' : search ? '没有匹配的已删除流程' : '回收站为空' }}</strong><span v-if="!busy && !error && !search">删除的审批流程会显示在这里</span></td></tr>
            </tbody></table>
          </div>
          <footer class="aw-pagination"><span>总计：{{ recycleFiltered.length }}</span><div><button aria-label="回收站上一页" :disabled="page <= 1" @click="page--"><ChevronLeft :size="14" />上一页</button><strong>{{ page }}</strong><button aria-label="回收站下一页" :disabled="page >= pageCount" @click="page++">下一页<ChevronRight :size="14" /></button><span>共 {{ pageCount }} 页</span><select v-model.number="pageSize" aria-label="回收站每页条数"><option :value="10">每页10条</option><option :value="20">每页20条</option><option :value="50">每页50条</option></select></div></footer>
        </section>
        <section v-else class="aw-records" aria-label="全部数据" :aria-busy="busy">
          <div class="aw-viewbar">
            <span class="active"><Table2 :size="15" />全部数据</span>
            <span v-if="current" class="aw-category-label">{{ categoryLabel(current.category) }}</span>
          </div>
          <div class="aw-toolbar"><div><button v-if="isAdmin" class="aw-text-button" :disabled="!filtered.length" @click="exportRows"><ArrowDownToLine :size="15" />导出{{ selectedIds.length ? '（' + selectedIds.length + '）' : '' }}</button><span v-if="selectedIds.length" class="aw-selected-count">已选 {{ selectedIds.length }} 条<button aria-label="取消选择" @click="selectedIds = []"><X :size="13" /></button></span></div><div class="aw-table-tools"><button v-if="hasFilters" class="aw-text-button" @click="clearFilters">清空筛选</button><div ref="columnAnchor" class="aw-column-anchor"><button class="aw-text-button" :aria-expanded="columnsOpen" @click="columnsOpen = !columnsOpen"><Columns3 :size="15" />显示列</button><div v-if="columnsOpen" class="aw-column-menu" aria-label="显示列设置"><label v-for="column in optionalColumns" :key="column.key"><input type="checkbox" :checked="visibleColumns.includes(column.key)" @change="toggleColumn(column.key)" />{{ column.name }}</label></div></div><button class="aw-text-button" aria-label="刷新页面记录" :disabled="busy" @click="refresh"><RefreshCw :size="16" /></button></div></div>
          <div class="aw-table-scroll" @pointerdown="dragStart" @pointermove="dragMove" @pointerup="dragEnd" @pointercancel="dragEnd" @pointerleave="event => { if (drag && !drag.active) dragEnd(event) }" @click.capture="captureClick">
            <table class="aw-table"><thead><tr><th class="aw-check"><input type="checkbox" aria-label="选择本页记录" :checked="allSelected" :disabled="!rows.length" @change="selectPage" /></th><th><button @click="sort('title')">{{ recordTitleLabel }}<ArrowUpDown :size="12" /></button></th><th><button @click="sort('applicant')">提交人<ArrowUpDown :size="12" /></button></th><th v-if="visibleColumns.includes('category')">流程分类</th><th v-if="visibleColumns.includes('stage')">流程状态</th><th v-if="visibleColumns.includes('createdAt')"><button @click="sort('createdAt')">创建时间<ArrowUpDown :size="12" /></button></th><th v-if="visibleColumns.includes('id')">实例ID</th><th>操作</th></tr>
            <tr class="aw-column-filters"><th></th><th><input v-model="columnFilters.title" :aria-label="'筛选' + recordTitleLabel" placeholder="筛选标题" /></th><th><input v-model="columnFilters.applicant" aria-label="筛选提交人" placeholder="筛选提交人" /></th><th v-if="visibleColumns.includes('category')"><input v-model="columnFilters.category" aria-label="筛选流程分类" placeholder="筛选分类" /></th><th v-if="visibleColumns.includes('stage')"><select v-model="columnFilters.stage" aria-label="筛选流程状态"><option value="">全部状态</option><option v-for="(name, key) in statuses" :key="key" :value="key">{{ name }}</option></select></th><th v-if="visibleColumns.includes('createdAt')"><input v-model="columnFilters.createdAt" type="date" aria-label="筛选创建日期" /></th><th v-if="visibleColumns.includes('id')"><input v-model="columnFilters.id" aria-label="筛选实例ID" placeholder="筛选实例ID" /></th><th></th></tr>
            </thead><tbody><tr v-for="row in rows" :key="row.id" :data-workspace-record="row.id" :class="{ selected: selectedIds.includes(row.id) }"><td class="aw-check"><input type="checkbox" :aria-label="'选择记录' + row.title" :checked="selectedIds.includes(row.id)" @change="selectRow(row.id)" /></td><td><button v-if="row.approval" class="aw-record-link" @click="emit('detail', row.id)">{{ row.title }}</button><span v-else>{{ row.title }}</span></td><td>{{ row.applicant }}</td><td v-if="visibleColumns.includes('category')">{{ row.category }}</td><td v-if="visibleColumns.includes('stage')"><span :class="['aw-status', row.stage]">{{ statuses[row.stage] || '—' }}</span></td><td v-if="visibleColumns.includes('createdAt')">{{ date(row.createdAt) }}</td><td v-if="visibleColumns.includes('id')" class="aw-instance-id" :title="row.id">{{ row.id }}</td><td><div class="aw-row-actions"><button v-if="row.approval" class="aw-record-link" @click="emit('detail', row.id)">查看</button><button v-if="row.canHandle" class="aw-record-link" @click="emit('handle', row.id)">去处理</button></div></td></tr><tr v-if="!rows.length"><td :colspan="4 + visibleColumns.length" class="aw-empty"><FileText :size="28" /><strong>{{ busy ? '正在加载记录…' : error ? '记录加载失败' : !current ? '暂无可查看的流程' : hasFilters ? '没有符合条件的记录' : '暂无提交记录' }}</strong><span v-if="!busy && !error && current && !current.published && !current.disabled && !current.deleted">管理员配置并发布流程后，成员即可发起审批</span></td></tr></tbody></table>
          </div>
          <footer class="aw-pagination"><span>总计：{{ filtered.length }}</span><div><button aria-label="工作台上一页" :disabled="page <= 1" @click="page--"><ChevronLeft :size="14" />上一页</button><strong>{{ page }}</strong><button aria-label="工作台下一页" :disabled="page >= pageCount" @click="page++">下一页<ChevronRight :size="14" /></button><span>共 {{ pageCount }} 页</span><select v-model.number="pageSize" aria-label="工作台每页条数"><option :value="10">每页10条</option><option :value="20">每页20条</option><option :value="50">每页50条</option></select></div></footer>
        </section>
      </section>
    </ResizableDetailDrawer>
    <component :is="centeredStatus ? CenteredApprovalDialog : ResizableDetailDrawer" v-if="statusTarget"
      v-bind="centeredStatus ? { label: statusTitle } : { open: true }" :suspended="statusBusy" @close="closeStatus">
      <section class="employee-dialog aw-lifecycle-dialog" :role="centeredStatus ? undefined : 'dialog'"
        :aria-modal="centeredStatus ? undefined : true" :aria-label="centeredStatus ? undefined : statusTitle" @click.stop>
        <header><span class="employee-dialog-heading"><b>{{ statusTitle }}</b><small>{{ statusTarget.name }}</small></span><button class="employee-close" aria-label="关闭流程操作" :disabled="statusBusy" @click="closeStatus"><X :size="18" /></button></header>
        <div class="employee-dialog-body">
          <p v-if="statusTarget.action === 'delete'">删除后，该流程将移入回收站，从流程分类和发起审批中隐藏。流程配置、表单和历史记录会保留，已发起的审批可继续处理；管理员可在回收站恢复。</p>
          <p v-else-if="statusTarget.action === 'disable'">停用后，成员不能发起新的申请。已有记录和正在处理的审批会保留；管理员可编辑流程，完成后重新启用。</p>
          <p v-else-if="statusTarget.action === 'restore'">恢复后，流程将返回原分类，并保留删除前的发布或停用状态。历史记录和正在处理的审批仍与此流程关联。</p>
          <p v-else>启用后，成员可按最新已发布版本发起申请。未发布的编辑不会生效。</p>
          <p v-if="statusError" class="aw-error" role="alert">{{ statusError }}</p>
        </div>
        <footer><button class="aw-button" :autofocus="centeredStatus" :disabled="statusBusy" @click="closeStatus">取消</button><button :class="centeredStatus ? 'aw-button aw-danger-solid' : 'aw-primary'" :disabled="statusBusy" @click="confirmStatus">{{ statusBusy ? '处理中…' : statusTarget.action === 'delete' ? '确认删除' : '确认' + actionNames[statusTarget.action] }}</button></footer>
      </section>
    </component>
    <CategorySupervisorSettings v-if="isAdmin && settingsCategory !== null" :key="settingsCategory" :category="settingsCategory" :approval-count="settingsApprovalCount" @close="settingsCategory = null" @saved="onCategorySaved" @deleted="onCategoryDeleted" />
    <Teleport to="body">
      <p v-if="notice" class="toast-message oa-workspace-toast" role="status"><Check :size="15" />{{ notice }}</p>
    </Teleport>
  </main>
</template>

<style scoped>
.oa-settings-center { max-width: 1120px; }
.oa-settings-center .oa-settings-tabs { margin-bottom: 12px; }
.oa-settings-restricted { padding: 22px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; color: #677b92; }
.oa-workspace-toast { z-index: 200; height: auto; min-height: 37px; max-width: calc(100vw - 32px); margin: 0; padding-block: 6px; white-space: normal; overflow-wrap: anywhere; }
.oa-workspace-toast svg { flex: none; }
</style>
