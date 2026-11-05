<script setup lang="ts">
import { PlatformDetailDrawer } from "@platform-ui"
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js"
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, BadgeCheck, Check, ChevronRight, Clock3, FilePenLine, FileText, GitFork, Inbox, RefreshCw, Send, UserRound, X } from '@lucide/vue'
import { actOnTask, listMyWorkflowRuns, listTaskHistory, listTaskInbox, listUserDirectory, listWorkflows, loadApprovalRecord, loadForm, recallWorkflowRun } from './api'
import type { ApprovalWorkspaceTarget, AuthUser, FormField, FormSchema, FormValues, WorkflowRunResult, WorkflowSchema, WorkflowTaskInboxItem } from './types'
import WorkflowCatalog from './WorkflowCatalog.vue'
import StartApproval from './StartApproval.vue'
import ApprovalStatus from './ApprovalStatus.vue'
import ApprovalWorkspace from './ApprovalWorkspace.vue'
import './employee-portal.css'
import './approval-home.css'

defineProps<{ user: AuthUser; managementItems: { id: string; label: string }[] }>()
const emit = defineEmits<{ logout: []; navigate: [page: string]; configure: [target: ApprovalWorkspaceTarget]; workflowChanged: [workflow: WorkflowSchema]; viewChange: [view: 'home' | 'workspace' | 'records'] }>()
type PublishedForm = { workflow: WorkflowSchema; form: FormSchema }
type HistoryEntry = { runId: string; workflowName: string; title: string; applicant: string; runStatus: string; nodeName: string; action: string; comment: string; createdAt: string }
type RecordTab = 'pending' | 'returned' | 'mine' | 'history'
const activeTab = ref<RecordTab | null>('pending')
const recordSection = ref<HTMLElement | null>(null)
const statusOpen = ref(false)
const workspaceOpen = ref(false)
watch([workspaceOpen, statusOpen], ([workspace, records]) => emit('viewChange', workspace ? 'workspace' : records ? 'records' : 'home'), { immediate: true })
const workspacePage = ref<InstanceType<typeof ApprovalWorkspace> | null>(null)
const statusPage = ref<InstanceType<typeof ApprovalStatus> | null>(null)
const publishedForms = ref<PublishedForm[]>([])
const inbox = ref<WorkflowTaskInboxItem[]>([])
const history = ref<HistoryEntry[]>([])
const myApplications = ref<WorkflowRunResult[]>([])
const directory = ref<AuthUser[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const startDialog = ref<PublishedForm | null>(null)
const submittedRun = ref<WorkflowRunResult | null>(null)
const submissionModal = ref<HTMLDialogElement | null>(null)
watch(submittedRun, async run => {
  if (run) {
    await nextTick()
    submissionModal.value?.showModal()
  }
})
function closeSubmission() {
  submissionModal.value?.close()
  submittedRun.value = null
}
const selectedTask = ref<WorkflowTaskInboxItem | null>(null)
const selectedApplication = ref<WorkflowRunResult | null>(null)
const recallPanelOpen = ref(false)
const recallComment = ref('')
const recallBusy = ref(false)
const recallError = ref('')
const taskValues = ref<FormValues>({})
const taskComment = ref('')
const targetUsername = ref('')
const actionBusy = ref(false)
const rejectPanelOpen = ref(false)
const rejectBehavior = ref<'' | 'return' | 'end'>('')
let noticeTimer: ReturnType<typeof setTimeout> | undefined

function cloneData<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

const returnedApplications = computed(() => myApplications.value.filter(run => run.status === 'returned'))
const statCards = computed(() => [
  { key: 'pending' as const, label: '待我处理', count: inbox.value.length, icon: Inbox, color: 'blue' },
  { key: 'returned' as const, label: '已退回', count: returnedApplications.value.length, icon: FilePenLine, color: 'amber' },
  { key: 'mine' as const, label: '我发起的', count: myApplications.value.length, icon: Send, color: 'green' },
  { key: 'history' as const, label: '我已处理', count: history.value.length, icon: BadgeCheck, color: 'slate' },
])
const recordTitle = computed(() => statCards.value.find(item => item.key === activeTab.value)?.label ?? '')
const visibleApplications = computed(() => activeTab.value === 'returned' ? returnedApplications.value : myApplications.value)
async function showRecords(tab: RecordTab) {
  activeTab.value = tab
  await nextTick()
  recordSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
async function openStatusDetail(id: string) {
  try { openApplication(await loadApprovalRecord(id)) }
  catch (cause) { const message = cause instanceof Error ? cause.message : '无法读取审批详情'; if (workspaceOpen.value) workspacePage.value?.showError(message); else statusPage.value?.showError(message) }
}
function openApplication(run: WorkflowRunResult) {
  selectedApplication.value = run
  recallPanelOpen.value = false
  recallComment.value = ''
  recallError.value = ''
}
function closeApplication() {
  if (!recallBusy.value) selectedApplication.value = null
}
async function confirmRecall() {
  const run = selectedApplication.value
  if (!run?.canRecall || recallBusy.value) return
  recallBusy.value = true
  recallError.value = ''
  try {
    const result = await recallWorkflowRun(run.id, recallComment.value)
    selectedApplication.value = {
      ...run, status: result.runStatus, canRecall: false, recall: result.recall,
      tasks: run.tasks.map(task => ['pending', 'waiting', 'unassigned'].includes(task.status) ? { ...task, status: 'cancelled' as const } : task),
    }
    recallPanelOpen.value = false
    toast('申请已撤回，未完成的待办已取消')
    try { selectedApplication.value = await loadApprovalRecord(run.id) }
    catch { recallError.value = '申请已撤回，详情刷新失败，请稍后重新打开' }
    await refresh()
    await statusPage.value?.refresh()
    await workspacePage.value?.refresh()
  } catch (cause) {
    recallError.value = cause instanceof Error ? cause.message : '撤回申请失败，请重试'
    // An approver may have finished while this drawer was open.
    try {
      selectedApplication.value = await loadApprovalRecord(run.id)
      if (!selectedApplication.value.canRecall) recallPanelOpen.value = false
      await refresh()
      await statusPage.value?.refresh()
      await workspacePage.value?.refresh()
    } catch { /* Preserve the confirmation and reason if the network is unavailable. */ }
  } finally { recallBusy.value = false }
}
async function openStatusTask(id: string) {
  try {
    const tasks = await listTaskInbox()
    const task = tasks.find(item => item.runId === id)
    if (!task) { await statusPage.value?.refresh(); await workspacePage.value?.refresh(); const view = workspaceOpen.value ? workspacePage.value : statusPage.value; view?.showError('当前审批已更新，请刷新后查看'); return }
    openTask(task)
  } catch (cause) { const view = workspaceOpen.value ? workspacePage.value : statusPage.value; view?.showError(cause instanceof Error ? cause.message : '无法读取待办') }
}
function confirmLeaveWorkspace() { return !workspaceOpen.value || workspacePage.value?.canLeave() !== false }
function resetHome() { if (!confirmLeaveWorkspace()) return; activeTab.value = 'pending'; statusOpen.value = false; workspaceOpen.value = false; void refresh() }
function showWorkspaceError(message: string) { workspacePage.value?.showError(message) }
async function refreshWorkspace() { await Promise.all([refresh(), workspacePage.value?.refresh()]) }
defineExpose({ resetHome, showWorkspaceError, refreshWorkspace, confirmLeaveWorkspace })
function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
const taskPermissions = computed(() => new Map((selectedTask.value?.task.fieldPermissions ?? []).map((item) => [item.fieldId, item.permission])))
const currentTaskAction = ref('')
const taskCommentRequired = computed(() => selectedTask.value?.actions.find((item) => item.key === currentTaskAction.value)?.opinionMode === 'required')
const transferActionAvailable = computed(() => selectedTask.value?.actions.some((item) => item.key === 'transfer' || item.key === 'countersign') ?? false)

function toast(message: string) {
  notice.value = message
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { notice.value = '' }, 2600)
}

async function refresh() {
  loading.value = true
  error.value = ''
  const [workflowResult, inboxResult, historyResult, directoryResult, applicationsResult] = await Promise.allSettled([
    listWorkflows(), listTaskInbox(), listTaskHistory(), listUserDirectory(), listMyWorkflowRuns(),
  ])
  if (workflowResult.status === 'fulfilled') {
    publishedForms.value = (await Promise.all(workflowResult.value.filter((item) => item.publishedSnapshot && !item.disabledAt && !item.deletedAt).map(async (workflow) => {
      try {
        const form = workflow.publishedSnapshot!.formSchema ?? await loadForm(workflow.publishedSnapshot!.formId)
        return { workflow, form }
      } catch { return null }
    }))).filter((item): item is PublishedForm => item !== null)
  } else error.value = workflowResult.reason instanceof Error ? workflowResult.reason.message : '无法读取已发布表单'
  if (inboxResult.status === 'fulfilled') inbox.value = inboxResult.value
  else if (!error.value) error.value = inboxResult.reason instanceof Error ? inboxResult.reason.message : '无法读取待办'
  if (historyResult.status === 'fulfilled') history.value = historyResult.value
  if (directoryResult.status === 'fulfilled') directory.value = directoryResult.value
  if (applicationsResult.status === 'fulfilled') myApplications.value = applicationsResult.value
  else if (!error.value) error.value = applicationsResult.reason instanceof Error ? applicationsResult.reason.message : '无法读取我的申请记录'
  loading.value = false
}

function openStart(item: PublishedForm) {
  startDialog.value = item
}
function onSubmitted(run: WorkflowRunResult) {
  submittedRun.value = run
  startDialog.value = null
  void refresh()
  void workspacePage.value?.refresh()
}

function openTask(item: WorkflowTaskInboxItem) {
  selectedTask.value = item
  taskValues.value = cloneData(item.values)
  taskComment.value = ''
  targetUsername.value = ''
  currentTaskAction.value = ''
  rejectPanelOpen.value = false
  rejectBehavior.value = ''
}

function taskFieldEditable(field: FormField) {
  return taskPermissions.value.get(field.id) === 'editable'
}

function formatAction(action: string) {
  const names: Record<string, string> = { agree: '同意', reject: '拒绝', save: '保存', transfer: '转交', countersign: '加签', return: '退回', recall: '撤回', complete: '完成' }
  return names[action] ?? action
}

async function handleTaskAction(action: string, confirmReject = false) {
  if (!selectedTask.value || actionBusy.value) return
  currentTaskAction.value = action
  if (action === 'reject') {
    rejectPanelOpen.value = true
    if (!confirmReject) return
    if (!rejectBehavior.value) { toast('请选择拒绝后处理方式'); return }
  } else rejectPanelOpen.value = false
  if (taskCommentRequired.value && !taskComment.value.trim()) { toast(`请填写${formatAction(action)}意见`); return }
  if ((action === 'transfer' || action === 'countersign') && !targetUsername.value) { toast('请选择要处理的成员'); return }
  actionBusy.value = true
  try {
    await actOnTask(selectedTask.value.runId, selectedTask.value.task.id, {
      action,
      comment: taskComment.value,
      values: cloneData(taskValues.value),
      targetUsername: action === 'transfer' || action === 'countersign' ? targetUsername.value : undefined,
      rejectBehavior: action === 'reject' ? rejectBehavior.value || undefined : undefined,
    })
    selectedTask.value = null
    toast(action === 'save' ? '审批内容已保存' : `已${formatAction(action)}`)
    await refresh()
    await statusPage.value?.refresh()
    await workspacePage.value?.refresh()
  } catch (cause) {
    toast(cause instanceof Error ? cause.message : '处理失败')
  } finally { actionBusy.value = false }
}

function taskAssigneeNames(task: WorkflowTaskInboxItem['task']) {
  if (task.status === 'pending' && (task.executionMode === 'sequential' || (task.nodeType === 'approval' && (task.approvalMode ?? 'sequential') === 'sequential'))) {
    const index = task.activeAssigneeIndex ?? 0
    const name = task.assigneeNames[index] ?? task.assignees[index]
    return name ? `${name}（第 ${index + 1}/${task.assignees.length} 位）` : ''
  }
  return task.assigneeNames.join('、') || task.assignees.join('、')
}

function runStatusText(status: string) {
  return ({ pending: '处理中', pending_assignment: '待分配', completed: '已完成', rejected: '已拒绝', returned: '已退回', recalled: '已撤回' } as Record<string, string>)[status] ?? status
}

function applicationCurrentStep(run: WorkflowRunResult) {
  if (run.status === 'completed') return '流程已完成'
  if (run.status === 'rejected') return '申请已拒绝'
  if (run.status === 'returned') return '申请已退回'
  if (run.status === 'recalled') return '申请已撤回'
  const active = run.tasks.find((task) => task.status === 'pending' || task.status === 'unassigned')
  if (active) return active.status === 'unassigned' ? `${active.nodeName} · 待分配` : `当前节点：${active.nodeName}`
  const waiting = run.tasks.find((task) => task.status === 'waiting')
  return waiting ? `等待：${waiting.nodeName}` : '流程处理中'
}

function taskStatusText(status: string) {
  return ({ pending: '处理中', waiting: '等待前序', unassigned: '待分配', completed: '已完成', rejected: '已拒绝', returned: '已退回', recalled: '已撤回', cancelled: '已取消' } as Record<string, string>)[status] ?? status
}

function displayValue(value: unknown) {
  if (Array.isArray(value)) return value.length ? value.map(String).join('、') : '--'
  return value === undefined || value === null || value === '' ? '--' : String(value)
}

onMounted(() => { void refresh() })
function closeTask() {
  if (actionBusy.value) return
  if ((taskComment.value || targetUsername.value || JSON.stringify(taskValues.value) !== JSON.stringify(selectedTask.value?.values || {})) && !window.confirm('当前处理内容尚未提交，确定关闭吗？')) return
  selectedTask.value = null
}
</script>

<template>
  <div class="employee-app approval-app">
    <ApprovalWorkspace v-if="workspaceOpen" ref="workspacePage" :user="user" :items="publishedForms" :directory="directory" @submitted="onSubmitted" @back="activeTab = 'pending'; workspaceOpen = false; refresh()" @start="openStart" @detail="openStatusDetail" @handle="openStatusTask" @configure="target => emit('configure', target)" @changed="item => { emit('workflowChanged', item); refresh() }" />
    <ApprovalStatus v-else-if="statusOpen" ref="statusPage" :user="user" @back="activeTab = 'pending'; statusOpen = false; refresh()" @detail="openStatusDetail" @handle="openStatusTask" @configure="emit('navigate', '流程设计')" />
    <main v-else class="employee-main approval-home">
      <header class="approval-page-header">
        <div><h1>审批首页</h1><p>处理待办并发起新的审批</p></div>
        <div class="approval-page-actions">
          <button class="approval-refresh" :disabled="loading" aria-label="刷新审批首页" title="刷新" @click="refresh"><RefreshCw :size="16" /></button>
        </div>
      </header>
      <div v-if="error" class="employee-error" role="alert">{{ error }}</div>
      <section class="approval-stat-grid" aria-label="我的审批统计" :aria-busy="loading">
        <button v-for="card in statCards" :key="card.key" :class="['approval-stat-card', { selected: activeTab === card.key }]" :aria-label="card.label + '，' + card.count + ' 条'" :aria-pressed="activeTab === card.key" @click="showRecords(card.key)">
          <span :class="['approval-stat-icon', card.color]"><component :is="card.icon" :size="21" /></span>
          <span class="approval-stat-copy"><strong>{{ loading ? '—' : card.count }}</strong><span>{{ card.label }}</span></span>
          <ArrowRight :size="17" />
        </button>
      </section>
      <section v-if="activeTab" ref="recordSection" class="approval-record-panel" :aria-label="recordTitle">
        <header class="approval-section-heading"><div><h2>{{ recordTitle }}</h2><p>查看和处理对应的审批记录</p></div><button class="approval-text-button" @click="statusOpen = true">更多<ChevronRight :size="14" /></button></header>
        <div v-if="activeTab === 'pending'">
          <div v-if="inbox.length" class="inbox-list">
            <button v-for="item in inbox" :key="`${item.runId}-${item.task.id}`" class="inbox-row" @click="openTask(item)">
              <span :class="['inbox-type-icon', item.task.nodeType]"><UserRound v-if="item.task.nodeType === 'approval'" :size="17" /><BadgeCheck v-else :size="17" /></span>
              <span class="inbox-copy"><b>{{ item.title }}</b><small>{{ item.applicant }} · {{ item.workflowName }} · {{ item.task.nodeName }}</small></span>
              <span class="inbox-side"><b>{{ taskAssigneeNames(item.task) }}</b><small>{{ formatDate(item.createdAt) }}</small></span><ChevronRight :size="16" />
            </button>
          </div>
          <div v-else class="approval-empty" role="status">{{ loading ? '正在加载…' : '暂无待处理的审批' }}</div>
        </div>
        <div v-else-if="activeTab === 'history'">
          <div v-if="history.length" class="history-list"><article v-for="(item, index) in history" :key="`${item.runId}-${item.nodeName}-${index}`" class="history-row"><span class="history-icon"><Clock3 :size="17" /></span><span class="history-copy"><b>{{ item.title }}</b><small>{{ item.applicant }} · {{ item.workflowName }} · {{ item.nodeName }} · {{ formatDate(item.createdAt) }}</small></span><span class="history-action">{{ formatAction(item.action) }}</span></article></div>
          <div v-else class="approval-empty" role="status">{{ loading ? '正在加载…' : '暂无已处理的审批' }}</div>
        </div>
        <div v-else>
          <div v-if="visibleApplications.length" class="application-list"><button v-for="run in visibleApplications" :key="run.id" class="application-row" @click="openApplication(run)"><span class="application-icon"><FileText :size="17" /></span><span class="application-copy"><b>{{ run.title }}</b><small>{{ run.workflowName }} · {{ formatDate(run.createdAt) }}</small></span><span class="application-side"><b :class="['application-status', run.status]">{{ runStatusText(run.status) }}</b></span><ChevronRight :size="16" /></button></div>
          <div v-else class="approval-empty" role="status">{{ loading ? '正在加载…' : activeTab === 'returned' ? '暂无退回的审批' : '暂无发起的审批' }}</div>
        </div>
      </section>
      <div class="approval-catalog-anchor"><WorkflowCatalog :items="publishedForms" :loading="loading" @start="openStart" @more="workspaceOpen = true" /></div>

    </main>

    <StartApproval v-if="startDialog" :workflow="startDialog.workflow" :form="startDialog.form" :user="user" :directory="directory" @close="startDialog = null" @submitted="onSubmitted" />

    <PlatformDetailDrawer v-if="selectedTask" :open="Boolean(selectedTask)" :suspended="actionBusy" @close="closeTask">
      <section class="employee-dialog task-dialog" role="dialog" aria-modal="true" :aria-label="selectedTask.task.nodeName">
        <header><span :class="['employee-dialog-icon', selectedTask.task.nodeType]"><UserRound v-if="selectedTask.task.nodeType === 'approval'" :size="17" /><BadgeCheck v-else :size="17" /></span><span class="employee-dialog-heading"><b>{{ selectedTask.task.nodeName }}</b><small>{{ selectedTask.workflowName }} · {{ selectedTask.task.nodeType === 'approval' ? '审批任务' : '执行任务' }}</small></span><button class="employee-close" aria-label="关闭" @click="closeTask"><X :size="18" /></button></header>
        <div class="task-context"><span>申请事项 <b>{{ selectedTask.title }}</b></span><span>发起人 <b>{{ selectedTask.applicant }}</b></span><span>申请时间 <b>{{ new Date(selectedTask.createdAt).toLocaleString() }}</b></span><span v-if="selectedTask.task.branchPath.length">命中分支 <b>{{ selectedTask.task.branchPath.join(' / ') }}</b></span></div>
        <div class="employee-dialog-body">
          <div class="task-assignee-line"><span>处理人</span><b>{{ taskAssigneeNames(selectedTask.task) }}</b></div>
          <div class="employee-form-grid task-fields">
            <div v-for="field in selectedTask.form.fields" :key="field.id" :class="['employee-form-field', field.width]">
              <label>{{ field.label }}<i v-if="field.required">*</i><small v-if="!taskFieldEditable(field)">只读</small></label>
              <p v-if="field.type === 'description'" class="employee-description">{{ taskValues[field.id] ?? field.defaultValue ?? '--' }}</p>
              <textarea v-else-if="field.type === 'textarea'" v-model="taskValues[field.id] as string" :readonly="!taskFieldEditable(field)" :placeholder="field.placeholder" rows="3"></textarea>
              <div v-else-if="field.type === 'radio' || field.type === 'checkbox'" class="employee-choice-list"><label v-for="option in field.options" :key="option"><input v-model="taskValues[field.id]" :disabled="!taskFieldEditable(field)" :type="field.type === 'radio' ? 'radio' : 'checkbox'" :name="`${selectedTask.task.id}-${field.id}`" :value="option" />{{ option }}</label></div>
              <select v-else-if="field.type === 'select' || field.type === 'multiSelect'" v-model="taskValues[field.id]" :disabled="!taskFieldEditable(field)" :multiple="field.type === 'multiSelect'"><option v-if="field.type === 'select'" value="" disabled>{{ field.placeholder || '请选择' }}</option><option v-for="option in field.options" :key="option" :value="option">{{ option }}</option></select>
              <div v-else class="employee-input-wrap"><input v-model="taskValues[field.id] as string" :readonly="!taskFieldEditable(field)" :type="field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'" :step="field.type === 'number' ? 'any' : undefined" :placeholder="field.placeholder" /></div>
            </div>
          </div>
          <label class="employee-comment-label">处理意见<textarea v-model="taskComment" rows="2" placeholder="填写审批或执行备注"></textarea></label>
          <div v-if="rejectPanelOpen" class="employee-reject-panel" role="group" aria-label="拒绝后处理">
            <b>拒绝后处理</b>
            <label><input v-model="rejectBehavior" type="radio" value="return" name="reject-behavior" :disabled="actionBusy" />退回发起人</label>
            <label><input v-model="rejectBehavior" type="radio" value="end" name="reject-behavior" :disabled="actionBusy" />结束流程</label>
            <div><button class="employee-secondary-button" :disabled="actionBusy" @click="rejectPanelOpen = false; rejectBehavior = ''; currentTaskAction = ''">取消拒绝</button><button class="employee-action-button" :disabled="actionBusy || !rejectBehavior" @click="handleTaskAction('reject', true)">{{ actionBusy ? '处理中…' : '确认拒绝' }}</button></div>
          </div>
          <label v-if="transferActionAvailable" class="employee-comment-label">转交/加签成员<select v-model="targetUsername"><option value="">选择成员</option><option v-for="person in directory.filter((item) => item.username !== user.username)" :key="person.username" :value="person.username">{{ person.displayName }} · {{ person.department }}</option></select></label>
        </div>
        <footer><button class="employee-secondary-button" :disabled="actionBusy" @click="closeTask">关闭</button><button v-for="action in selectedTask.actions" :key="action.key" :class="['employee-action-button', { primary: action.key === 'agree' || action.key === 'complete' }]" :disabled="actionBusy" @click="handleTaskAction(action.key)">{{ actionBusy && currentTaskAction === action.key ? '处理中…' : action.name }}</button></footer>
      </section>
    </PlatformDetailDrawer>

    <PlatformDetailDrawer v-if="selectedApplication" :open="Boolean(selectedApplication)" :suspended="recallBusy" @close="closeApplication">
      <section class="employee-dialog application-dialog" role="dialog" aria-modal="true" :aria-label="`${selectedApplication.title}流程详情`">
        <header><span class="employee-dialog-icon"><GitFork :size="17" /></span><span class="employee-dialog-heading"><b>{{ selectedApplication.title }}</b><small>{{ selectedApplication.workflowName }} · 第 {{ selectedApplication.workflowVersion }} 版</small></span><button class="employee-close" aria-label="关闭" :disabled="recallBusy" @click="closeApplication"><X :size="18" /></button></header>
        <div class="application-context"><span>申请人 <b>{{ selectedApplication.applicant }}</b></span><span>提交时间 <b>{{ new Date(selectedApplication.createdAt).toLocaleString() }}</b></span><span>流程状态 <b>{{ runStatusText(selectedApplication.status) }}</b></span></div>
        <div class="employee-dialog-body application-detail-body">
          <div class="application-current"><span>当前进度</span><b>{{ applicationCurrentStep(selectedApplication) }}</b></div>
          <div v-if="recallError" class="employee-error" role="alert">{{ recallError }}</div>
          <section v-if="recallPanelOpen" class="application-recall-panel" aria-label="撤回确认">
            <h3>确认撤回这条申请？</h3>
            <p>撤回后，未完成的审批和执行待办将取消，申请内容及已有处理记录会保留。</p>
            <label class="employee-comment-label">撤回原因（选填）<textarea v-model="recallComment" maxlength="2000" rows="2" :disabled="recallBusy" placeholder="填写撤回原因"></textarea></label>
          </section>
          <section v-if="selectedApplication.recall" class="application-recall-record" aria-label="撤回记录">
            <h3>撤回记录</h3>
            <p>{{ selectedApplication.recall.displayName }} · 已撤回 · {{ formatDate(selectedApplication.recall.createdAt) }}</p>
            <p v-if="selectedApplication.recall.comment">{{ selectedApplication.recall.comment }}</p>
          </section>
          <section v-if="selectedApplication.matchedBranches.length" class="application-detail-section">
            <h3>条件分支</h3>
            <div v-for="branch in selectedApplication.matchedBranches" :key="branch.nodeId" class="submission-branch"><GitFork :size="14" /><span>{{ branch.conditionName }}</span><ChevronRight :size="13" /><b>{{ branch.branchName }}</b></div>
          </section>
          <section class="application-detail-section">
            <h3>申请内容</h3>
            <div v-if="selectedApplication.formSchema?.fields.length" class="employee-form-grid application-values">
              <div v-for="field in selectedApplication.formSchema.fields" :key="field.id" :class="['employee-form-field', field.width]">
                <label>{{ field.label }}</label><p class="application-value">{{ displayValue(selectedApplication.values?.[field.id] ?? field.defaultValue) }}</p>
              </div>
            </div>
            <div v-else class="application-no-fields">没有可显示的表单内容</div>
          </section>
          <section class="application-detail-section">
            <h3>流程记录</h3>
            <ol v-if="selectedApplication.tasks.length" class="application-timeline">
              <li v-for="task in selectedApplication.tasks" :key="task.id" :class="['application-timeline-item', task.status]">
                <span class="application-timeline-marker"><UserRound v-if="task.nodeType === 'approval'" :size="14" /><BadgeCheck v-else :size="14" /></span>
                <div class="application-timeline-content">
                  <div class="application-timeline-heading"><b>{{ task.nodeName }}</b><span :class="['application-status', task.status]">{{ taskStatusText(task.status) }}</span></div>
                  <small>{{ task.nodeType === 'approval' ? '审批' : '执行' }} · {{ task.assigneeNames.join('、') || '未分配' }}<template v-if="task.branchPath.length"> · {{ task.branchPath.join(' / ') }}</template></small>
                  <div v-if="task.decisions?.length" class="application-decisions">
                    <div v-for="(decision, index) in task.decisions" :key="`${decision.username}-${index}`" class="application-decision"><span><b>{{ decision.displayName }}</b> · {{ formatAction(decision.action) }}<template v-if="decision.action === 'reject' && decision.rejectBehavior"> · {{ decision.rejectBehavior === 'return' ? '退回发起人' : '结束流程' }}</template><small>{{ new Date(decision.createdAt).toLocaleString() }}</small></span><p v-if="decision.comment">{{ decision.comment }}</p></div>
                  </div>
                </div>
              </li>
            </ol>
            <div v-else class="application-no-fields">此流程没有审批或执行节点</div>
          </section>
        </div>
        <footer>
          <template v-if="selectedApplication.canRecall">
            <button v-if="!recallPanelOpen" class="employee-action-button application-recall-button" @click="recallPanelOpen = true; recallError = ''">撤回申请</button>
            <template v-else>
              <button class="employee-secondary-button" :disabled="recallBusy" @click="recallPanelOpen = false">取消撤回</button>
              <button class="employee-action-button application-recall-button" :disabled="recallBusy" @click="confirmRecall">{{ recallBusy ? '撤回中…' : '确认撤回' }}</button>
            </template>
          </template>
          <button class="employee-primary-button" :disabled="recallBusy" @click="closeApplication">关闭</button>
        </footer>
      </section>
    </PlatformDetailDrawer>

    <Teleport to="body">
      <dialog v-if="submittedRun" ref="submissionModal" v-backdrop-dismiss="closeSubmission" class="submission-modal-shell" aria-labelledby="submission-modal-title" @cancel.prevent="closeSubmission">
        <section class="submission-modal" @click.stop>
          <header><h2 id="submission-modal-title">提交成功</h2><button class="submission-close" aria-label="关闭" @click="closeSubmission"><X :size="20" /></button></header>
          <div class="submission-modal-body">
            <h3>审批流程</h3>
            <div class="submission-timeline-scroll" tabindex="0" aria-label="审批流程节点">
              <ol class="submission-timeline">
                <li><span class="submission-avatar"><UserRound :size="26" /></span><div><b>{{ submittedRun.applicant }}</b><small>提交申请</small></div></li>
                <li v-for="task in submittedRun.tasks" :key="task.id">
                  <span class="submission-avatar"><UserRound v-if="task.nodeType === 'approval'" :size="26" /><BadgeCheck v-else :size="26" /></span>
                  <div><b>{{ task.assigneeNames.join('、') || '待分配' }}</b><small>{{ task.nodeName }}</small><span class="submission-node-status">{{ taskStatusText(task.status) }}</span></div>
                </li>
              </ol>
              <p v-if="!submittedRun.tasks.length" class="submission-empty">{{ submittedRun.status === 'completed' ? '无需审批，流程已完成' : '申请已提交，请在申请详情中查看后续进度' }}</p>
            </div>
          </div>
          <footer><span role="status"><Check :size="15" />流程已提交</span><button @click="closeSubmission">确定</button></footer>
        </section>
      </dialog>
    </Teleport>

    <Transition name="employee-notice"><div v-if="notice" class="employee-toast">{{ notice }}</div></Transition>
  </div>
</template>
