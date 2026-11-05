<script setup lang="ts">
import { PlatformDetailDrawer } from '@platform-ui'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { ArrowDownToLine, ArrowLeft, ArrowUpDown, Check, ChevronDown, ChevronLeft, ChevronRight, Columns3, FilePenLine, FileText, FolderOpen, GitFork, PanelLeftClose, Plus, RefreshCw, RotateCcw, Search, Settings2, Table2, Trash2, X } from '@lucide/vue'
import StartApproval from './StartApproval.vue'
import CategorySupervisorSettings from './CategorySupervisorSettings.vue'
import { changeWorkflowStatus, listApprovalRecords, listFormRecords, listForms, listWorkflows } from './api'
import type { ApprovalRecord, ApprovalWorkspaceTarget, AuthUser, FormRecord, FormSchema, WorkflowSchema, WorkflowRunResult } from './types'
import { DEFAULT_WORKFLOW_CATEGORIES, workflowCategory } from './workflow-categories'
import './approval-workspace.css'

type WorkflowAction = 'disable' | 'enable' | 'delete' | 'restore'
type PublishedItem = { workflow: WorkflowSchema; form: FormSchema }
type Entry = { key: string; kind: 'workflow' | 'form'; name: string; formId: string; workflowId?: string; category: string; published: boolean; disabled: boolean; deleted: boolean; startItem?: PublishedItem }
type Row = { id: string; title: string; applicant: string; category: string; stage: string; createdAt: string; canHandle: boolean; approval: boolean }
const props = defineProps<{ user: AuthUser; items: PublishedItem[]; directory: AuthUser[] }>()
const emit = defineEmits<{ back: []; submitted: [run: WorkflowRunResult]; detail: [id: string]; handle: [id: string]; configure: [target: ApprovalWorkspaceTarget]; changed: [workflow: WorkflowSchema] }>()
const isAdmin = computed(() => props.user.canManagePermissions === true)
const workflows = ref<WorkflowSchema[]>([]), forms = ref<FormSchema[]>([]), records = ref<ApprovalRecord[]>([])
const formRecords = ref<FormRecord[]>([])
const selected = ref(''), navigationSearch = ref(''), search = ref('')
const emptyFilters = () => ({ title: '', applicant: '', category: '', stage: '', createdAt: '', id: '' })
const columnFilters = ref(emptyFilters())
const workspaceView = ref<'submit' | 'data'>('submit')
const applicationForm = ref<InstanceType<typeof StartApproval> | null>(null)
function canLeave() { return applicationForm.value?.canLeave() !== false }
function selectEntry(key: string) { if (key !== selected.value && canLeave()) selected.value = key }
function backHome() { if (canLeave()) emit('back') }
function submitted(run: WorkflowRunResult) { workspaceView.value = 'data'; emit('submitted', run); void refresh() }
const loading = ref(false), formLoading = ref(false), error = ref(''), notice = ref('')
const collapsed = ref(false), columnsOpen = ref(false)
const expandedCategories = ref<string[]>([])
const supervisorCategory = ref('')
const recycledWorkflows = ref<WorkflowSchema[]>([])
const recycleMode = computed(() => isAdmin.value && selected.value === 'recycle')
const statusBusy = ref(false), statusError = ref('')
const statusTarget = ref<{ id: string; name: string; action: WorkflowAction } | null>(null)
const actionNames = { disable: '停用', enable: '启用', delete: '移入回收站', restore: '恢复' }
const statusTitle = computed(() => statusTarget.value ? statusTarget.value.action === 'delete' ? '删除审批流程' : actionNames[statusTarget.value.action] + '审批流程' : '')
const categoryNavigationId = useId()
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
    const formId = workflow.nodes.find(node => node.type === 'start')?.formId || workflow.publishedSnapshot?.formId || ''
    if (formId) bound.add(formId)
    const startItem = !workflow.disabledAt && !workflow.deletedAt ? props.items.find(item => item.workflow.id === workflow.id) : undefined
    return { key: 'workflow:' + workflow.id, kind: 'workflow', name: workflow.name, formId, workflowId: workflow.id, category: (isAdmin.value ? workflow.category?.trim() : '') || workflowCategory(workflow), published: Boolean(workflow.publishedSnapshot), disabled: Boolean(workflow.disabledAt), deleted: Boolean(workflow.deletedAt), startItem }
  })
  if (isAdmin.value) for (const form of forms.value) {
    if (!bound.has(form.id)) result.push({ key: 'form:' + form.id, kind: 'form', name: form.name, formId: form.id, category: '独立表单', published: false, disabled: false, deleted: false })
  }
  return result
})
const categoryGroups = computed(() => {
  const query = navigationSearch.value.trim().toLowerCase()
  const workflowEntries = entries.value.filter(entry => entry.kind === 'workflow' && !entry.deleted)
  const categories = [...new Set<string>([...DEFAULT_WORKFLOW_CATEGORIES, ...workflowEntries.map(entry => entry.category)])]
  const groups = categories.map(category => ({
    key: 'category:' + category, name: category, kind: 'workflow' as Entry['kind'],
    entries: workflowEntries.filter(entry => entry.category === category && (!query || category.toLowerCase().includes(query) || entry.name.toLowerCase().includes(query))),
  }))
  const standalone = entries.value.filter(entry => entry.kind === 'form')
  if (standalone.length) groups.push({ key: 'standalone-forms', name: '独立表单', kind: 'form', entries: standalone.filter(entry => !query || entry.name.toLowerCase().includes(query) || '独立表单'.includes(query)) })
  return groups.filter(group => !query || group.name.toLowerCase().includes(query) || group.entries.length > 0)
})
function categoryExpanded(key: string) { return Boolean(navigationSearch.value.trim()) || expandedCategories.value.includes(key) }
function toggleCategory(key: string) {
  if (navigationSearch.value.trim()) return
  expandedCategories.value = expandedCategories.value.includes(key) ? expandedCategories.value.filter(value => value !== key) : [...expandedCategories.value, key]
}
const current = computed(() => entries.value.find(entry => entry.key === selected.value))
const title = computed(() => recycleMode.value ? '流程回收站' : current.value?.name || '页面管理')
const currentRows = computed<Row[]>(() => {
  if (!current.value) return []
  if (current.value.kind === 'form') return formRecords.value.map(record => ({ ...record, category: '独立表单', stage: '', canHandle: false, approval: false }))
  return records.value.filter(record => record.workflowId === current.value?.workflowId)
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
  return recycledWorkflows.value.filter(workflow => !query || [workflow.name, workflow.category || workflowCategory(workflow)].some(value => value.toLowerCase().includes(query)))
    .sort((left, right) => String(right.deletedAt || '').localeCompare(String(left.deletedAt || '')))
})
const recycleRows = computed(() => recycleFiltered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const pageCount = computed(() => Math.max(1, Math.ceil((recycleMode.value ? recycleFiltered.value.length : filtered.value.length) / pageSize.value)))
const rows = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const allSelected = computed(() => rows.value.length > 0 && rows.value.every(row => selectedIds.value.includes(row.id)))
const busy = computed(() => loading.value || formLoading.value || statusBusy.value)
let formRequest = 0, noticeTimer: ReturnType<typeof setTimeout> | undefined
async function refresh() {
  if (loading.value) return
  loading.value = true; error.value = ''
  try {
    const [summaries, formList, workflowList, recycleList] = await Promise.all([listApprovalRecords(), isAdmin.value ? listForms() : Promise.resolve([]), listWorkflows(), isAdmin.value ? listWorkflows(true) : Promise.resolve([])])
    records.value = isAdmin.value ? summaries : summaries.filter(record => record.mine); forms.value = formList; workflows.value = workflowList; recycledWorkflows.value = recycleList
    if (!recycleMode.value && !entries.value.some(entry => entry.key === selected.value)) selected.value = entries.value.find(entry => !entry.deleted)?.key || ''
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
function configure(page: ApprovalWorkspaceTarget['page'], create?: ApprovalWorkspaceTarget['create']) {
  if (!isAdmin.value || !canLeave()) return
  emit('configure', { page, formId: create ? undefined : current.value?.formId || undefined, workflowId: create ? undefined : current.value?.workflowId, create })
}
function requestStatus(action: WorkflowAction, workflow?: WorkflowSchema) {
  if (!isAdmin.value || busy.value || !canLeave()) return
  const target = workflow || [...workflows.value, ...recycledWorkflows.value].find(item => item.id === current.value?.workflowId)
  if (!target || (action === 'restore' ? !target.deletedAt : target.deletedAt)) return
  statusError.value = ''
  statusTarget.value = { id: target.id, name: target.name, action }
}
function closeStatus() { if (!statusBusy.value) { statusTarget.value = null; statusError.value = '' } }
async function confirmStatus() {
  const target = statusTarget.value
  if (!target || !isAdmin.value || statusBusy.value) return
  statusBusy.value = true; statusError.value = ''
  try {
    const updated = await changeWorkflowStatus(target.id, target.action)
    workflows.value = workflows.value.filter(item => item.id !== updated.id)
    recycledWorkflows.value = recycledWorkflows.value.filter(item => item.id !== updated.id)
    if (updated.deletedAt) recycledWorkflows.value.unshift(updated)
    else workflows.value.unshift(updated)
    statusTarget.value = null
    if (target.action === 'delete') selected.value = 'recycle'
    if (target.action === 'restore') selected.value = 'workflow:' + updated.id
    notice.value = `流程“${target.name}”已${actionNames[target.action]}`
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
  const lines = [['实例标题', '提交人', '流程分类', '流程状态', '创建时间', '实例ID'], ...data.map(row => [row.title, row.applicant, row.category, statuses[row.stage] || '—', date(row.createdAt), row.id])]
  const url = URL.createObjectURL(new Blob(['\uFEFF' + lines.map(line => line.map(escape).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = title.value.replace(/[<>:"/\\|?*]/g, '_') + '-审批记录.csv'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  notice.value = `已导出 ${data.length} 条记录`; if (noticeTimer) clearTimeout(noticeTimer); noticeTimer = setTimeout(() => { notice.value = '' }, 2400)
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
watch(selected, () => { search.value = ''; clearFilters(); workspaceView.value = current.value?.startItem ? 'submit' : 'data'; selectedIds.value = []; error.value = ''; formRecords.value = []; ++formRequest; formLoading.value = false; if (current.value?.kind === 'form') void refreshForm(current.value.formId) })
watch(() => current.value && !current.value.deleted ? current.value.kind === 'form' ? 'standalone-forms' : 'category:' + current.value.category : '', key => { if (key && !expandedCategories.value.includes(key)) expandedCategories.value.push(key) }, { immediate: true })
watch([selected, search, columnFilters, pageSize], () => { page.value = 1; selectedIds.value = [] }, { deep: true })
watch(pageCount, count => { page.value = Math.min(page.value, count) })
onMounted(() => { void refresh(); document.addEventListener('pointerdown', closeMenus); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { ++formRequest; if (noticeTimer) clearTimeout(noticeTimer); document.removeEventListener('pointerdown', closeMenus); document.removeEventListener('keydown', onKey) })
defineExpose({ refresh, showError, canLeave })
</script>

<template>
  <main class="approval-workspace" aria-label="审批页面管理">
    <header class="aw-topbar">
      <button class="aw-text-button" @click="backHome"><ArrowLeft :size="15" />返回审批首页</button>
      <button class="aw-text-button aw-nav-toggle" :aria-expanded="!collapsed" @click="collapsed = !collapsed"><PanelLeftClose :size="15" />{{ collapsed ? '展开导航' : '收起导航' }}</button>
    </header>
    <div :class="['aw-layout', { collapsed }]">
      <aside v-show="!collapsed" class="aw-sidebar" aria-label="审批页面导航">
        <div class="aw-sidebar-tools"><label><Search :size="15" /><input v-model="navigationSearch" aria-label="搜索流程或表单" placeholder="搜索流程或表单" /></label><button v-if="isAdmin" class="aw-primary aw-plus" aria-label="新建审批" title="新建审批" @click="configure('流程设计', 'workflow')"><Plus :size="20" /></button></div>
        <button v-if="isAdmin" :class="['aw-recycle-link', { active: recycleMode || current?.deleted }]" :aria-current="recycleMode ? 'page' : undefined" @click="selectEntry('recycle')"><Trash2 :size="15" /><span>流程回收站</span><small>{{ recycledWorkflows.length }}</small></button>
        <nav class="aw-page-list" aria-label="流程分类">
          <div class="aw-category-heading">流程分类</div>
          <section v-for="(group, index) in categoryGroups" :key="group.key" class="aw-category-group" :data-category="group.name">
            <div class="aw-category-row">
            <button class="aw-category-toggle" :class="{ active: current && (group.kind === 'form' ? current.kind === 'form' : current.kind === 'workflow' && current.category === group.name) }" :aria-expanded="categoryExpanded(group.key)" :aria-controls="categoryNavigationId + '-group-' + index" :title="group.name" @click="toggleCategory(group.key)">
              <FolderOpen v-if="group.kind === 'workflow'" :size="15" /><FileText v-else :size="15" /><span>{{ group.name }}</span><small>{{ group.entries.length }}</small><ChevronDown :size="13" :class="{ rotated: !categoryExpanded(group.key) }" />
            </button>
            <button v-if="isAdmin && group.kind === 'workflow'" type="button" class="aw-category-supervisor" :aria-label="'设置' + group.name + '主管'" :title="'设置' + group.name + '分类主管'" @click="supervisorCategory = group.name"><Settings2 :size="14" /><span>主管</span></button>
            </div>
            <div v-show="categoryExpanded(group.key)" :id="categoryNavigationId + '-group-' + index" class="aw-category-entries">
              <button v-for="entry in group.entries" :key="entry.key" :data-page-key="entry.key" :class="['aw-workflow-entry', { active: selected === entry.key }]" :aria-current="selected === entry.key ? 'page' : undefined" :title="entry.name + ' · ' + entry.category" @click="selectEntry(entry.key)"><GitFork v-if="entry.kind === 'workflow'" :size="14" /><FileText v-else :size="14" /><span>{{ entry.name }}</span><small v-if="entry.deleted" class="aw-retired-label">已删除</small><small v-else-if="entry.disabled" class="aw-retired-label">已停用</small><small v-else-if="!entry.published">草稿</small></button>
              <p v-if="!group.entries.length" class="aw-category-empty">{{ loading ? '正在加载…' : '该分类暂无可用审批流程' }}</p>
            </div>
          </section>
          <p v-if="!categoryGroups.length" class="aw-navigation-empty">没有匹配的分类或流程</p>
        </nav>
      </aside>
      <section class="aw-content">
        <header class="aw-page-heading">
          <div><h1>{{ title }}</h1><span v-if="current" :class="['aw-publish-state', { published: current.published && !current.disabled && !current.deleted, disabled: current.disabled, deleted: current.deleted }]">{{ current.deleted ? '回收站' : current.disabled ? '已停用' : current.published ? '已发布' : '草稿' }}</span></div>
          <div class="aw-page-actions">
            <button v-if="isAdmin && current?.deleted" class="aw-text-button" @click="selectEntry('recycle')"><ArrowLeft :size="15" />返回回收站</button>
            <button v-if="isAdmin && current?.formId && !current.deleted" class="aw-text-button" @click="configure('数据管理')"><Table2 :size="15" />数据管理</button>
            <button v-if="isAdmin && current && !current.deleted && (current.formId || current.workflowId)" class="aw-primary" @click="configure(current.formId ? '表单设计' : '流程设计')"><FilePenLine :size="15" />{{ current.workflowId ? '编辑流程表单' : '编辑表单' }}</button>
            <button v-if="isAdmin && current?.workflowId && current.deleted" class="aw-primary" :disabled="busy" @click="requestStatus('restore')"><RotateCcw :size="15" />恢复流程</button>
            <template v-if="isAdmin && current?.workflowId && !current.deleted"><button :class="current.disabled ? 'aw-button' : 'aw-button aw-danger'" :disabled="busy || (current.disabled && !current.published)" @click="requestStatus(current.disabled ? 'enable' : 'disable')">{{ current.disabled ? '启用流程' : '停用流程' }}</button><button class="aw-button aw-danger" :disabled="busy" @click="requestStatus('delete')"><Trash2 :size="15" />删除流程</button></template>
          </div>
        </header>
        <p v-if="current?.disabled || current?.deleted" class="aw-lifecycle-hint">{{ current.deleted ? '此流程已移入回收站，可查询历史记录或恢复流程。' : '此流程已停用，不能发起新申请。' }}已有审批可继续处理。</p>
        <p v-if="error" class="aw-error" role="alert">{{ error }}<button :disabled="loading" @click="refresh">重试</button></p>
        <p v-if="notice" class="aw-notice" role="status"><Check :size="15" />{{ notice }}</p>
        <section v-if="recycleMode" class="aw-records aw-recycle-records" aria-label="流程回收站列表" :aria-busy="busy">
          <div class="aw-viewbar"><span class="active"><Trash2 :size="15" />已删除流程</span></div>
          <p class="aw-recycle-description">删除的流程在此保留，可查看历史记录或恢复到原分类。</p>
          <div class="aw-toolbar"><label class="aw-search"><Search :size="14" /><input v-model="search" aria-label="搜索回收站流程" placeholder="搜索流程名称或分类" /></label><button class="aw-text-button" aria-label="刷新流程回收站" :disabled="busy" @click="refresh"><RefreshCw :size="16" />刷新</button></div>
          <div class="aw-table-scroll">
            <table class="aw-table aw-recycle-table"><thead><tr><th>流程名称</th><th>流程分类</th><th>删除前状态</th><th>删除时间</th><th>操作</th></tr></thead><tbody>
              <tr v-for="workflow in recycleRows" :key="workflow.id" :data-recycled-workflow="workflow.id">
                <td><button class="aw-record-link" @click="selectEntry('workflow:' + workflow.id)">{{ workflow.name }}</button></td><td>{{ workflow.category || workflowCategory(workflow) }}</td><td><span :class="['aw-status', { pending_assignment: workflow.disabledAt, completed: !workflow.disabledAt && workflow.publishedSnapshot }]">{{ workflow.disabledAt ? '已停用' : workflow.publishedSnapshot ? '已发布' : '草稿' }}</span></td><td>{{ date(workflow.deletedAt || '') }}</td>
                <td><div class="aw-row-actions"><button class="aw-record-link" @click="selectEntry('workflow:' + workflow.id)">查看记录</button><button class="aw-record-link" :aria-label="'恢复流程' + workflow.name" :disabled="busy" @click="requestStatus('restore', workflow)"><RotateCcw :size="13" />恢复</button></div></td>
              </tr>
              <tr v-if="!recycleRows.length"><td colspan="5" class="aw-empty"><Trash2 :size="28" /><strong>{{ busy ? '正在加载流程…' : error ? '回收站加载失败' : search ? '没有匹配的已删除流程' : '回收站为空' }}</strong><span v-if="!busy && !error && !search">删除的审批流程会显示在这里</span></td></tr>
            </tbody></table>
          </div>
          <footer class="aw-pagination"><span>总计：{{ recycleFiltered.length }}</span><div><button aria-label="回收站上一页" :disabled="page <= 1" @click="page--"><ChevronLeft :size="14" />上一页</button><strong>{{ page }}</strong><button aria-label="回收站下一页" :disabled="page >= pageCount" @click="page++">下一页<ChevronRight :size="14" /></button><span>共 {{ pageCount }} 页</span><select v-model.number="pageSize" aria-label="回收站每页条数"><option :value="10">每页10条</option><option :value="20">每页20条</option><option :value="50">每页50条</option></select></div></footer>
        </section>
        <section v-else class="aw-records" aria-label="当前页面记录" :aria-busy="busy">
          <div class="aw-viewbar" role="tablist" aria-label="流程内容">
            <button v-if="current?.startItem" role="tab" :aria-selected="workspaceView === 'submit'" :class="{ active: workspaceView === 'submit' }" @click="workspaceView = 'submit'"><FileText :size="15" />表单提交</button>
            <button role="tab" :aria-selected="workspaceView === 'data' || !current?.startItem" :class="{ active: workspaceView === 'data' || !current?.startItem }" @click="workspaceView = 'data'"><Table2 :size="15" />{{ current?.kind === 'form' ? '表单数据' : '全部数据' }}</button>
            <span v-if="current" class="aw-category-label">{{ current.category }}</span>
          </div>
          <StartApproval v-if="current?.startItem" v-show="workspaceView === 'submit'" :key="current.startItem.workflow.id + ':' + current.startItem.workflow.publishedVersion" ref="applicationForm" inline :workflow="current.startItem.workflow" :form="current.startItem.form" :user="user" :directory="directory" @submitted="submitted" />
          <template v-if="workspaceView === 'data' || !current?.startItem">
          <div class="aw-toolbar"><div><button v-if="isAdmin" class="aw-text-button" :disabled="!filtered.length" @click="exportRows"><ArrowDownToLine :size="15" />导出{{ selectedIds.length ? '（' + selectedIds.length + '）' : '' }}</button><span v-if="selectedIds.length" class="aw-selected-count">已选 {{ selectedIds.length }} 条<button aria-label="取消选择" @click="selectedIds = []"><X :size="13" /></button></span></div><div class="aw-table-tools"><button v-if="hasFilters" class="aw-text-button" @click="clearFilters">清空筛选</button><div ref="columnAnchor" class="aw-column-anchor"><button class="aw-text-button" :aria-expanded="columnsOpen" @click="columnsOpen = !columnsOpen"><Columns3 :size="15" />显示列</button><div v-if="columnsOpen" class="aw-column-menu" aria-label="显示列设置"><label v-for="column in optionalColumns" :key="column.key"><input type="checkbox" :checked="visibleColumns.includes(column.key)" @change="toggleColumn(column.key)" />{{ column.name }}</label></div></div><button class="aw-text-button" aria-label="刷新页面记录" :disabled="busy" @click="refresh"><RefreshCw :size="16" /></button></div></div>
          <div class="aw-table-scroll" @pointerdown="dragStart" @pointermove="dragMove" @pointerup="dragEnd" @pointercancel="dragEnd" @pointerleave="event => { if (drag && !drag.active) dragEnd(event) }" @click.capture="captureClick">
            <table class="aw-table"><thead><tr><th class="aw-check"><input type="checkbox" aria-label="选择本页记录" :checked="allSelected" :disabled="!rows.length" @change="selectPage" /></th><th><button @click="sort('title')">实例标题<ArrowUpDown :size="12" /></button></th><th><button @click="sort('applicant')">提交人<ArrowUpDown :size="12" /></button></th><th v-if="visibleColumns.includes('category')">流程分类</th><th v-if="visibleColumns.includes('stage')">流程状态</th><th v-if="visibleColumns.includes('createdAt')"><button @click="sort('createdAt')">创建时间<ArrowUpDown :size="12" /></button></th><th v-if="visibleColumns.includes('id')">实例ID</th><th>操作</th></tr>
            <tr class="aw-column-filters"><th></th><th><input v-model="columnFilters.title" aria-label="筛选实例标题" placeholder="筛选标题" /></th><th><input v-model="columnFilters.applicant" aria-label="筛选提交人" placeholder="筛选提交人" /></th><th v-if="visibleColumns.includes('category')"><input v-model="columnFilters.category" aria-label="筛选流程分类" placeholder="筛选分类" /></th><th v-if="visibleColumns.includes('stage')"><select v-model="columnFilters.stage" aria-label="筛选流程状态"><option value="">全部状态</option><option v-for="(name, key) in statuses" :key="key" :value="key">{{ name }}</option></select></th><th v-if="visibleColumns.includes('createdAt')"><input v-model="columnFilters.createdAt" type="date" aria-label="筛选创建日期" /></th><th v-if="visibleColumns.includes('id')"><input v-model="columnFilters.id" aria-label="筛选实例ID" placeholder="筛选实例ID" /></th><th></th></tr>
            </thead><tbody><tr v-for="row in rows" :key="row.id" :data-workspace-record="row.id" :class="{ selected: selectedIds.includes(row.id) }"><td class="aw-check"><input type="checkbox" :aria-label="'选择记录' + row.title" :checked="selectedIds.includes(row.id)" @change="selectRow(row.id)" /></td><td><button v-if="row.approval" class="aw-record-link" @click="emit('detail', row.id)">{{ row.title }}</button><span v-else>{{ row.title }}</span></td><td>{{ row.applicant }}</td><td v-if="visibleColumns.includes('category')">{{ row.category }}</td><td v-if="visibleColumns.includes('stage')"><span :class="['aw-status', row.stage]">{{ statuses[row.stage] || '—' }}</span></td><td v-if="visibleColumns.includes('createdAt')">{{ date(row.createdAt) }}</td><td v-if="visibleColumns.includes('id')" class="aw-instance-id" :title="row.id">{{ row.id }}</td><td><div class="aw-row-actions"><button v-if="row.approval" class="aw-record-link" @click="emit('detail', row.id)">查看</button><button v-if="row.canHandle" class="aw-record-link" @click="emit('handle', row.id)">去处理</button><button v-if="!row.approval && isAdmin" class="aw-record-link" @click="configure('数据管理')">数据管理</button></div></td></tr><tr v-if="!rows.length"><td :colspan="4 + visibleColumns.length" class="aw-empty"><FileText :size="28" /><strong>{{ busy ? '正在加载记录…' : error ? '记录加载失败' : !current ? '暂无可查看的流程' : hasFilters ? '没有符合条件的记录' : '暂无提交记录' }}</strong><span v-if="!busy && !error && current?.startItem">点击“表单提交”填写审批申请</span><span v-else-if="!busy && !error && current && !current.published && !current.disabled && !current.deleted">管理员配置并发布流程后，成员即可发起审批</span></td></tr></tbody></table>
          </div>
          <footer class="aw-pagination"><span>总计：{{ filtered.length }}</span><div><button aria-label="工作台上一页" :disabled="page <= 1" @click="page--"><ChevronLeft :size="14" />上一页</button><strong>{{ page }}</strong><button aria-label="工作台下一页" :disabled="page >= pageCount" @click="page++">下一页<ChevronRight :size="14" /></button><span>共 {{ pageCount }} 页</span><select v-model.number="pageSize" aria-label="工作台每页条数"><option :value="10">每页10条</option><option :value="20">每页20条</option><option :value="50">每页50条</option></select></div></footer>
          </template>
        </section>
      </section>
    </div>
    <PlatformDetailDrawer v-if="statusTarget" :open="Boolean(statusTarget)" :suspended="statusBusy" @close="closeStatus">
      <section class="employee-dialog aw-lifecycle-dialog" role="dialog" aria-modal="true" :aria-label="statusTitle" @click.stop>
        <header><span class="employee-dialog-heading"><b>{{ statusTitle }}</b><small>{{ statusTarget.name }}</small></span><button class="employee-close" aria-label="关闭流程操作" :disabled="statusBusy" @click="closeStatus"><X :size="18" /></button></header>
        <div class="employee-dialog-body">
          <p v-if="statusTarget.action === 'delete'">删除后，该流程将移入回收站，从流程分类和发起审批中隐藏。流程配置、表单和历史记录会保留，已发起的审批可继续处理；管理员可在回收站恢复。</p>
          <p v-else-if="statusTarget.action === 'disable'">停用后，成员不能发起新的申请。已有记录和正在处理的审批会保留；管理员可编辑流程，完成后重新启用。</p>
          <p v-else-if="statusTarget.action === 'restore'">恢复后，流程将返回原分类，并保留删除前的发布或停用状态。历史记录和正在处理的审批仍与此流程关联。</p>
          <p v-else>启用后，成员可按最新已发布版本发起申请。未发布的编辑不会生效。</p>
          <p v-if="statusError" class="aw-error" role="alert">{{ statusError }}</p>
        </div>
        <footer><button class="aw-button" :disabled="statusBusy" @click="closeStatus">取消</button><button :class="['enable', 'restore'].includes(statusTarget.action) ? 'aw-primary' : 'aw-button aw-danger-solid'" :disabled="statusBusy" @click="confirmStatus">{{ statusBusy ? '处理中…' : statusTarget.action === 'delete' ? '确认删除' : '确认' + actionNames[statusTarget.action] }}</button></footer>
      </section>
    </PlatformDetailDrawer>
    <CategorySupervisorSettings v-if="isAdmin && supervisorCategory" :key="supervisorCategory" :category="supervisorCategory" @close="supervisorCategory = ''" />
  </main>
</template>
